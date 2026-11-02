# ============================================================
# main.py — Main Controller V75.3 (Interactive Scan with Live Reports)
# Signal-only bot | SQLite persistence | Long only | Interactive commands
# ============================================================
import os
import time
import threading
import logging
import sqlite3
import requests
from datetime import datetime, timezone

import ccxt
from flask import Flask, jsonify, request

from analysis import StrategyEngine, is_signal_expired

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("MainBot")
app = Flask(__name__)

# ---------- Config ----------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
BOT_CAPITAL_USD = max(1.0, float(os.environ.get("BOT_CAPITAL_USD", "10000")))
RISK_PER_TRADE = min(0.02, max(0.001, float(os.environ.get("RISK_PER_TRADE", "0.01"))))
MAX_SCAN_SYMBOLS = max(5, min(150, int(os.environ.get("MAX_SCAN_SYMBOLS", "40"))))
SCAN_INTERVAL_SECONDS = max(120, int(os.environ.get("SCAN_INTERVAL_SECONDS", "300")))
SIGNAL_COOLDOWN_SECONDS = max(300, int(os.environ.get("SIGNAL_COOLDOWN_SECONDS", "3600")))
SIGNAL_EXPIRY_SECONDS = 900
MAX_ACTIVE_POSITIONS = max(1, int(os.environ.get("MAX_ACTIVE_POSITIONS", "10")))
MAX_DAILY_SIGNALS = max(1, int(os.environ.get("MAX_DAILY_SIGNALS", "30")))
DB_PATH = os.environ.get("DB_PATH", "bot_state.db")

PRIORITY_SYMBOLS = [
    "BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT",
    "BNB/USDT:USDT", "XRP/USDT:USDT", "ADA/USDT:USDT",
    "DOGE/USDT:USDT", "AVAX/USDT:USDT", "LINK/USDT:USDT",
]

# ---------- Exchange ----------
bingx = ccxt.bingx({
    "enableRateLimit": True,
    "timeout": 20000,
    "options": {"defaultType": "swap"},
    "apiKey": os.environ.get("BINGX_API_KEY", "").strip(),
    "secret": os.environ.get("BINGX_SECRET_KEY", "").strip(),
})

engine = StrategyEngine(capital=BOT_CAPITAL_USD, risk_per_trade=RISK_PER_TRADE)

# ---------- Locks ----------
db_lock = threading.Lock()
signal_lock = threading.Lock()

# ---------- Stats ----------
scan_stats = {"scanned_pairs": 0, "signals_sent": 0, "errors": 0}


# ============================================================
# Database layer
# ============================================================
def db_init():
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                symbol TEXT PRIMARY KEY,
                signal_id TEXT,
                direction TEXT,
                entry REAL,
                stop_loss REAL,
                tp1 REAL, tp2 REAL, tp3 REAL,
                tp1_done INTEGER DEFAULT 0,
                tp2_done INTEGER DEFAULT 0,
                tp3_done INTEGER DEFAULT 0,
                breakeven_done INTEGER DEFAULT 0,
                created_at REAL,
                expires_at REAL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS signal_history (
                signal_id TEXT PRIMARY KEY,
                symbol TEXT,
                direction TEXT,
                entry REAL,
                stop_loss REAL,
                score INTEGER,
                created_at REAL,
                sent INTEGER DEFAULT 0
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS daily_counter (
                day TEXT PRIMARY KEY,
                count INTEGER DEFAULT 0
            )
        """)
        conn.commit()
    finally:
        conn.close()


def _db():
    return sqlite3.connect(DB_PATH, timeout=10)


def db_save_position(symbol, pos):
    with db_lock:
        conn = _db()
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT OR REPLACE INTO positions
                (symbol, signal_id, direction, entry, stop_loss,
                 tp1, tp2, tp3, tp1_done, tp2_done, tp3_done,
                 breakeven_done, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                symbol, pos.get("signal_id"), pos.get("direction"),
                pos.get("entry"), pos.get("stop_loss"),
                pos.get("tp1"), pos.get("tp2"), pos.get("tp3"),
                int(pos.get("tp1_done", 0)), int(pos.get("tp2_done", 0)),
                int(pos.get("tp3_done", 0)), int(pos.get("breakeven_done", 0)),
                pos.get("created_at"), pos.get("expires_at"),
            ))
            conn.commit()
        finally:
            conn.close()


def db_daily_count_today():
    today = datetime.now(timezone.utc).date().isoformat()
    with db_lock:
        conn = _db()
        try:
            cur = conn.cursor()
            cur.execute("SELECT count FROM daily_counter WHERE day = ?", (today,))
            row = cur.fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()


def db_daily_increment():
    today = datetime.now(timezone.utc).date().isoformat()
    with db_lock:
        conn = _db()
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO daily_counter (day, count) VALUES (?, 1)
                ON CONFLICT(day) DO UPDATE SET count = count + 1
            """, (today,))
            conn.commit()
        finally:
            conn.close()


def db_last_signal_time(symbol):
    with db_lock:
        conn = _db()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT created_at FROM signal_history
                WHERE symbol = ? ORDER BY created_at DESC LIMIT 1
            """, (symbol,))
            row = cur.fetchone()
            return float(row[0]) if row else 0.0
        finally:
            conn.close()


# ============================================================
# Telegram
# ============================================================
def tg_send(message, chat_id=None):
    target = chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not target:
        return False
    url = "https://api.telegram.org/bot{}/sendMessage".format(TELEGRAM_BOT_TOKEN)
    payload = {
        "chat_id": target,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    for attempt in range(2):
        try:
            r = requests.post(url, json=payload, timeout=15)
            if r.status_code == 200:
                return True
            if r.status_code == 429:
                retry = 5
                try:
                    retry = r.json().get("parameters", {}).get("retry_after", 5)
                except Exception:
                    pass
                time.sleep(min(int(retry), 30))
                continue
            logger.warning("Telegram non-200: %s %s", r.status_code, r.text[:200])
            return False
        except Exception as exc:
            logger.error("Telegram send error: %s", exc)
            time.sleep(2)
    return False


def tg_escape(text):
    return (str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))


# ============================================================
# Exchange helpers
# ============================================================
def normalize_symbol(raw):
    s = str(raw).strip().upper().replace(" ", "")
    s = s.replace("_", "").replace("-", "/")
    if ":" in s:
        s = s.split(":")[0]
    if "/" not in s:
        if s.endswith("USDT"):
            s = s[:-4] + "/USDT"
        else:
            s += "/USDT"
    return s


def fetch_ohlcv(symbol_raw, timeframe, limit=100):
    base = normalize_symbol(symbol_raw).split("/")[0]
    candidates = [base + "/USDT:USDT", base + "/USDT"]
    last_err = None
    for symbol in candidates:
        try:
            bars = bingx.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            if bars and len(bars) > 10:
                return symbol, bars
        except ccxt.BadSymbol:
            continue
        except ccxt.NetworkError as exc:
            last_err = exc
            time.sleep(1)
            continue
        except Exception as exc:
            last_err = exc
            time.sleep(0.5)
            continue
    if last_err:
        logger.debug("fetch_ohlcv failed for %s: %s", symbol_raw, last_err)
    return None, None


def get_scan_universe():
    try:
        markets = bingx.load_markets()
        by_priority = [s for s in PRIORITY_SYMBOLS if s in markets]
        candidates = [
            s for s, m in markets.items()
            if m.get("swap") and m.get("active", True)
            and m.get("quote") == "USDT" and m.get("settle") == "USDT"
            and m.get("base") and m["base"] not in (
                "USDC", "BUSD", "TUSD", "FDUSD", "DAI"
            )
        ]
        ordered = []
        seen = set()
        for s in by_priority + candidates:
            if s not in seen:
                seen.add(s)
                ordered.append(s)
        return ordered[:MAX_SCAN_SYMBOLS]
    except Exception as exc:
        logger.warning("get_scan_universe failed: %s", exc)
        return PRIORITY_SYMBOLS[:5]


# ============================================================
# Signal logic
# ============================================================
def can_send_signal(symbol):
    now = time.time()
    with signal_lock:
        if now - db_last_signal_time(symbol) < SIGNAL_COOLDOWN_SECONDS:
            return False
        with db_lock:
            conn = _db()
            try:
                cur = conn.cursor()
                cur.execute("SELECT 1 FROM positions WHERE symbol = ?", (symbol,))
                if cur.fetchone() is not None:
                    return False
                cur.execute("SELECT COUNT(*) FROM positions")
                if int(cur.fetchone()[0]) >= MAX_ACTIVE_POSITIONS:
                    return False
            finally:
                conn.close()
        if db_daily_count_today() >= MAX_DAILY_SIGNALS:
            return False
        return True


def register_signal(symbol, signal):
    tps = list(signal.get("take_profits", [])) + [0, 0, 0]
    pos = {
        "signal_id": signal["signal_id"],
        "direction": signal["direction"],
        "entry": signal["entry"],
        "stop_loss": signal["stop_loss"],
        "tp1": tps[0], "tp2": tps[1], "tp3": tps[2],
        "tp1_done": 0, "tp2_done": 0, "tp3_done": 0, "breakeven_done": 0,
        "created_at": time.time(),
        "expires_at": time.time() + SIGNAL_EXPIRY_SECONDS,
    }
    db_save_position(symbol, pos)
    db_daily_increment()


def format_num(value, decimals):
    try:
        v = float(value)
        if v <= 0:
            return "N/A"
        return "{:.{}f}".format(v, decimals)
    except Exception:
        return "N/A"


def build_report(symbol, signal, current_price):
    price = float(current_price or signal.get("entry") or 0)
    decimals = 8 if price < 0.1 else (6 if price < 1 else (4 if price < 100 else 2))
    tps = signal.get("take_profits", [])
    tp1 = tps[0] if len(tps) > 0 else 0
    tp2 = tps[1] if len(tps) > 1 else 0
    tp3 = tps[2] if len(tps) > 2 else 0

    valid = signal.get("direction") == "LONG" and signal.get("score", 0) >= 70
    status = "🟢 LONG (جاهزة للدخول)" if valid else "🟡 تحت المراقبة"

    lines = [
        "🏛️ <b>MY EXPERT CRYPTO BOT V75.3</b>",
        "━━━━━━━━━━━━━━━━━━",
        "🪙 العملة: <code>{}</code>".format(tg_escape(symbol)),
        "📌 الحالة: {}".format(status),
        "⭐ التقييم: <code>{}/100</code>".format(signal.get("score", 0)),
        "💵 السعر الحالي: <code>{}</code>".format(format_num(price, decimals)),
    ]
    if valid:
        lines.extend([
            "🎯 سعر الدخول: <code>{}</code>".format(format_num(signal.get("entry", 0), decimals)),
            "🥇 TP1: <code>{}</code>".format(format_num(tp1, decimals)),
            "🥈 TP2: <code>{}</code>".format(format_num(tp2, decimals)),
            "🥉 TP3: <code>{}</code>".format(format_num(tp3, decimals)),
            "🛑 الستوب: <code>{}</code>".format(format_num(signal.get("stop_loss", 0), decimals)),
        ])
    lines.extend([
        "📊 RSI: <code>{}</code>".format(round(signal.get("rsi", 50), 2)),
        "━━━━━━━━━━━━━━━━━━",
        "📝 السبب: {}".format(tg_escape(signal.get("reason", ""))),
    ])
    return "\n".join(lines)


# ============================================================
# Analyze a symbol
# ============================================================
def analyze_symbol(symbol_raw, chat_id=None, send_no_signal=False):
    resolved, candles15 = fetch_ohlcv(symbol_raw, "15m", 110)
    if not resolved or not candles15 or len(candles15) < 65:
        if send_no_signal:
            tg_send("❌ لا تتوفر بيانات كافية لـ <code>{}</code>".format(tg_escape(symbol_raw)), chat_id)
        return False, None

    _, candles5 = fetch_ohlcv(resolved, "5m", 40)
    scan_stats["scanned_pairs"] += 1

    direction, price, signal = engine.analyze_market_structure(
        ohlcv_5m=candles5, ohlcv_15m=candles15, asset_type="crypto"
    )

    valid = bool(signal.get("direction") == "LONG" and signal.get("score", 0) >= 70)

    if valid and not is_signal_expired(signal):
        report = build_report(resolved, signal, price)
        if tg_send(report, chat_id):
            register_signal(resolved, signal)
            scan_stats["signals_sent"] += 1
            return True, signal
    elif send_no_signal:
        report = build_report(resolved, signal, price)
        tg_send(report, chat_id)
        return False, signal

    return False, signal


# ============================================================
# Background Scanner & Flask / Webhook Server
# ============================================================
def background_scanner():
    db_init()
    logger.info("Background scanner started.")
    while True:
        try:
            symbols = get_scan_universe()
            logger.info("Scanning %d symbols...", len(symbols))
            for sym in symbols:
                try:
                    analyze_symbol(sym)
                    time.sleep(1.5)
                except Exception as exc:
                    scan_stats["errors"] += 1
                    logger.debug("Error scanning %s: %s", sym, exc)
            time.sleep(SCAN_INTERVAL_SECONDS)
        except Exception as exc:
            logger.error("Scanner loop error: %s", exc)
            time.sleep(30)


@app.route("/")
def index():
    return jsonify({
        "status": "running",
        "bot_version": "V75.3",
        "stats": scan_stats,
    })


@app.route("/health")
def health():
    return "OK", 200


@app.route(f"/{TELEGRAM_BOT_TOKEN}", methods=["POST"])
def telegram_webhook():
    try:
        data = request.get_json(force=True)
        message = data.get("message") or data.get("edited_message")
        if not message:
            return "OK", 200

        chat_id = message.get("chat", {}).get("id")
        text = message.get("text", "").strip()

        if not chat_id or not text:
            return "OK", 200

        text_upper = text.upper()

        if text_upper.startswith("/START") or text_upper.startswith("/HELP"):
            tg_send(
                "🤖 <b>مرحباً بك في بوت التداول الفني (V75.3)</b>\n\n"
                "الأوامر المتاحة:\n"
                "• <code>/scan</code> - لفحص السوق وعرض تقييمات العملات الفورية.\n"
                "• اكتب اسم العملة مباشرة (مثل <code>BTC</code> أو <code>THETA</code>) لتحليلها وفحصها فوراً.",
                chat_id
            )
        elif text_upper.startswith("/SCAN"):
            tg_send("🔍 جاري فحص السوق وعرض تقييمات العملات...", chat_id)
            symbols = get_scan_universe()[:10]  # فحص 10 عملات مع إرسال تقرير لكل منها لترى التقييمات
            found = 0
            for sym in symbols:
                try:
                    is_valid, _ = analyze_symbol(sym, chat_id=chat_id, send_no_signal=True)
                    if is_valid:
                        found += 1
                    time.sleep(1)
                except Exception:
                    pass
            tg_send(f"✅ انتهى الفحص. تم العثور على {found} صفقة مطابقة لشرط الدخول (Score >= 70).", chat_id)
        else:
            clean_symbol = text.split()[0]
            tg_send(f"🔍 جاري تحليل العملة <code>{tg_escape(clean_symbol)}</code>...", chat_id)
            analyze_symbol(clean_symbol, chat_id=chat_id, send_no_signal=True)

    except Exception as exc:
        logger.error("Webhook error: %s", exc)
    return "OK", 200


if __name__ == "__main__":
    db_init()
    t = threading.Thread(target=background_scanner, daemon=True)
    t.start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
