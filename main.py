# ============================================================
# main.py — Bot V7.7 (Optimized Scanner & Telegram Notifier)
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("MainBot")
app = Flask(__name__)

# ---------- Config ----------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
BOT_CAPITAL_USD = max(1.0, float(os.environ.get("BOT_CAPITAL_USD", "10000")))
RISK_PER_TRADE = min(0.02, max(0.001, float(os.environ.get("RISK_PER_TRADE", "0.01"))))
MAX_SCAN_SYMBOLS = max(5, min(150, int(os.environ.get("MAX_SCAN_SYMBOLS", "60"))))
SCAN_INTERVAL_SECONDS = max(60, int(os.environ.get("SCAN_INTERVAL_SECONDS", "180")))
SIGNAL_COOLDOWN_SECONDS = max(180, int(os.environ.get("SIGNAL_COOLDOWN_SECONDS", "1800")))
SIGNAL_EXPIRY_SECONDS = 900
MAX_ACTIVE_POSITIONS = max(1, int(os.environ.get("MAX_ACTIVE_POSITIONS", "12")))
MAX_DAILY_SIGNALS = max(1, int(os.environ.get("MAX_DAILY_SIGNALS", "40")))
DB_PATH = os.environ.get("DB_PATH", "bot_state.db")
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL", "").strip().rstrip("/")

PRIORITY_SYMBOLS = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "BNB/USDT:USDT", "XRP/USDT:USDT", "ADA/USDT:USDT", "DOGE/USDT:USDT", "AVAX/USDT:USDT", "LINK/USDT:USDT", "PEPE/USDT:USDT", "NEAR/USDT:USDT", "RENDER/USDT:USDT"]

bingx = ccxt.bingx({"enableRateLimit": True, "timeout": 20000, "options": {"defaultType": "swap"}})
engine = StrategyEngine(capital=BOT_CAPITAL_USD, risk_per_trade=RISK_PER_TRADE)

db_lock = threading.Lock()
signal_lock = threading.Lock()
scan_stats = {"scanned_pairs": 0, "signals_sent": 0, "errors": 0}
_all_markets_cache = []
_markets_cache_time = 0

# ================= Database =================
def db_init():
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS positions (symbol TEXT PRIMARY KEY, signal_id TEXT, direction TEXT, entry REAL, stop_loss REAL, tp1 REAL, tp2 REAL, tp3 REAL, tp1_done INTEGER DEFAULT 0, tp2_done INTEGER DEFAULT 0, tp3_done INTEGER DEFAULT 0, breakeven_done INTEGER DEFAULT 0, created_at REAL, expires_at REAL)")
        cur.execute("CREATE TABLE IF NOT EXISTS signal_history (signal_id TEXT PRIMARY KEY, symbol TEXT, direction TEXT, entry REAL, stop_loss REAL, score INTEGER, created_at REAL, sent INTEGER DEFAULT 0)")
        cur.execute("CREATE TABLE IF NOT EXISTS daily_counter (day TEXT PRIMARY KEY, count INTEGER DEFAULT 0)")
        cur.execute("CREATE TABLE IF NOT EXISTS bot_state (key TEXT PRIMARY KEY, value TEXT)")
        conn.commit()
    finally: conn.close()

def _db(): return sqlite3.connect(DB_PATH, timeout=10)

def db_save_position(symbol, pos):
    with db_lock:
        conn = _db()
        try:
            conn.execute("INSERT OR REPLACE INTO positions (symbol, signal_id, direction, entry, stop_loss, tp1, tp2, tp3, tp1_done, tp2_done, tp3_done, breakeven_done, created_at, expires_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (symbol, pos.get("signal_id"), pos.get("direction"), pos.get("entry"), pos.get("stop_loss"), pos.get("tp1"), pos.get("tp2"), pos.get("tp3"), int(pos.get("tp1_done",0)), int(pos.get("tp2_done",0)), int(pos.get("tp3_done",0)), int(pos.get("breakeven_done",0)), pos.get("created_at"), pos.get("expires_at")))
            conn.commit()
        finally: conn.close()

def db_daily_count_today():
    today = datetime.now(timezone.utc).date().isoformat()
    with db_lock:
        conn = _db()
        try:
            cur = conn.cursor()
            cur.execute("SELECT count FROM daily_counter WHERE day = ?", (today,))
            row = cur.fetchone()
            return int(row[0]) if row else 0
        finally: conn.close()

def db_daily_increment():
    today = datetime.now(timezone.utc).date().isoformat()
    with db_lock:
        conn = _db()
        try:
            conn.execute("INSERT INTO daily_counter (day, count) VALUES (?, 1) ON CONFLICT(day) DO UPDATE SET count = count + 1", (today,))
            conn.commit()
        finally: conn.close()

def db_last_signal_time(symbol):
    with db_lock:
        conn = _db()
        try:
            cur = conn.cursor()
            cur.execute("SELECT created_at FROM signal_history WHERE symbol = ? ORDER BY created_at DESC LIMIT 1", (symbol,))
            row = cur.fetchone()
            return float(row[0]) if row else 0.0
        finally: conn.close()

# ================= Telegram & Helpers =================
def tg_send(message, chat_id=None):
    target = chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not target: return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": target, "text": message, "parse_mode": "HTML", "disable_web_page_preview": True}, timeout=15)
        return r.status_code == 200
    except Exception as e:
        logger.error(f"Telegram send error: {e}")
        return False

def tg_escape(text): return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def register_telegram_webhook():
    if not TELEGRAM_BOT_TOKEN or not RENDER_EXTERNAL_URL:
        logger.warning("TELEGRAM_BOT_TOKEN or RENDER_EXTERNAL_URL missing. Webhook not set.")
        return
    webhook_url = f"{RENDER_EXTERNAL_URL}/{TELEGRAM_BOT_TOKEN}"
    try:
        r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook", json={"url": webhook_url, "drop_pending_updates": True}, timeout=15)
        logger.info(f"Webhook registration: {r.json()}")
    except Exception as e:
        logger.error(f"Webhook registration failed: {e}")

def normalize_symbol(raw):
    s = str(raw).strip().upper().replace(" ", "").replace("_", "").replace("-", "/")
    if ":" in s: s = s.split(":")[0]
    if "/" not in s: s = s[:-4] + "/USDT" if s.endswith("USDT") else s + "/USDT"
    return s

def fetch_ohlcv(symbol_raw, timeframe, limit=100):
    base = normalize_symbol(symbol_raw).split("/")[0]
    for symbol in [f"{base}/USDT:USDT", f"{base}/USDT"]:
        try:
            bars = bingx.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            if bars and len(bars) > 10: return symbol, bars
        except: time.sleep(0.3)
    return None, None

# ================= Scan Universe (Top Gainers & Rotation) =================
def get_scan_universe():
    global _all_markets_cache, _markets_cache_time
    try:
        if not _all_markets_cache or time.time() - _markets_cache_time > 1800:
            markets = bingx.load_markets()
            valid_symbols = [
                s for s, m in markets.items()
                if m.get("swap") and m.get("active", True)
                and m.get("quote") == "USDT" and m.get("settle") == "USDT"
                and m.get("base") and m["base"] not in ("USDC", "BUSD", "TUSD", "FDUSD", "DAI")
            ]
            _all_markets_cache = valid_symbols
            _markets_cache_time = time.time()
            logger.info(f"Loaded {len(_all_markets_cache)} total markets.")

        total = len(_all_markets_cache)
        if total == 0: return PRIORITY_SYMBOLS[:5]

        fixed_priority = [s for s in PRIORITY_SYMBOLS if s in _all_markets_cache]
        remaining = [s for s in _all_markets_cache if s not in fixed_priority]
        
        with db_lock:
            conn = _db()
            try:
                cur = conn.cursor()
                cur.execute("SELECT value FROM bot_state WHERE key = 'scan_index'")
                row = cur.fetchone()
                current_index = int(row[0]) if row else 0
            finally: conn.close()

        if current_index >= len(remaining):
            current_index = 0

        needed_dynamic = MAX_SCAN_SYMBOLS - len(fixed_priority)
        end_index = min(current_index + needed_dynamic, len(remaining))
        dynamic_batch = remaining[current_index:end_index]

        if len(dynamic_batch) < needed_dynamic:
            needed_more = needed_dynamic - len(dynamic_batch)
            dynamic_batch += remaining[:needed_more]
            new_index = needed_more
        else:
            new_index = end_index

        with db_lock:
            conn = _db()
            try:
                conn.execute("INSERT OR REPLACE INTO bot_state (key, value) VALUES ('scan_index', ?)", (str(new_index),))
                conn.commit()
            finally: conn.close()

        final_list = fixed_priority + dynamic_batch
        return final_list[:MAX_SCAN_SYMBOLS]

    except Exception as exc:
        logger.warning(f"get_scan_universe failed: {exc}")
        return PRIORITY_SYMBOLS[:5]

# ================= Logic =================
def can_send_signal(symbol):
    with signal_lock:
        if time.time() - db_last_signal_time(symbol) < SIGNAL_COOLDOWN_SECONDS: return False
        with db_lock:
            conn = _db()
            try:
                cur = conn.cursor()
                cur.execute("SELECT 1 FROM positions WHERE symbol = ?", (symbol,))
                if cur.fetchone(): return False
                cur.execute("SELECT COUNT(*) FROM positions")
                if int(cur.fetchone()[0]) >= MAX_ACTIVE_POSITIONS: return False
            finally: conn.close()
        return db_daily_count_today() < MAX_DAILY_SIGNALS

def register_signal(symbol, signal):
    tps = list(signal.get("take_profits", [])) + [0, 0, 0]
    pos = {"signal_id": signal["signal_id"], "direction": signal["direction"], "entry": signal["entry"], "stop_loss": signal["stop_loss"], "tp1": tps[0], "tp2": tps[1], "tp3": tps[2], "tp1_done": 0, "tp2_done": 0, "tp3_done": 0, "breakeven_done": 0, "created_at": time.time(), "expires_at": time.time() + SIGNAL_EXPIRY_SECONDS}
    db_save_position(symbol, pos)
    db_daily_increment()

def format_num(v, d):
    try: return f"{float(v):.{d}f}" if float(v) > 0 else "N/A"
    except: return "N/A"

def build_report(symbol, signal, current_price):
    price = float(current_price or signal.get("entry") or 0)
    d = 8 if price < 0.1 else (6 if price < 1 else (4 if price < 100 else 2))
    tps = signal.get("take_profits", [0, 0, 0])
    lines = [
        f"🚨 <b>صفقة لونغ (LONG) مؤكدة للعملات الصاعدة!</b>",
        f"🏛️ <b>EXPERT BOT V7.7 (MOMENTUM & SMC)</b>",
        f"━━━━━━━━━━━━━━━━━━",
        f"🪙 العملة: <code>{tg_escape(symbol)}</code>",
        f"⭐ التقييم: <code>{signal.get('score', 0)}/100</code>",
        f"💵 السعر الحالي: <code>{format_num(price, d)}</code>",
        f"🎯 سعر الدخول: <code>{format_num(signal.get('entry', 0), d)}</code>",
        f"🥇 TP1: <code>{format_num(tps[0] if len(tps)>0 else 0, d)}</code>",
        f"🥈 TP2: <code>{format_num(tps[1] if len(tps)>1 else 0, d)}</code>",
        f"🥉 TP3: <code>{format_num(tps[2] if len(tps)>2 else 0, d)}</code>",
        f"🛑 وقف الخسارة: <code>{format_num(signal.get('stop_loss', 0), d)}</code>",
        f"📊 RSI: <code>{round(signal.get('rsi', 50), 2)}</code>",
        f"━━━━━━━━━━━━━━━━━━",
        f"📝 السبب: {tg_escape(signal.get('reason', ''))}"
    ]
    return "\n".join(lines)

def analyze_symbol(symbol_raw, chat_id=None, force_report=False):
    resolved, candles15 = fetch_ohlcv(symbol_raw, "15m", 110)
    if not resolved or len(candles15) < 65:
        if force_report: tg_send(f"❌ لا تتوفر بيانات كافية لـ <code>{tg_escape(symbol_raw)}</code>", chat_id)
        return False, None
    _, candles5 = fetch_ohlcv(resolved, "5m", 40)
    scan_stats["scanned_pairs"] += 1
    direction, price, signal = engine.analyze_market_structure(candles5, candles15)
    valid = bool(signal.get("direction") == "LONG" and signal.get("score", 0) >= 65)
    
    if valid and not is_signal_expired(signal) and (can_send_signal(resolved) or force_report):
        if tg_send(build_report(resolved, signal, price), chat_id or TELEGRAM_CHAT_ID):
            register_signal(resolved, signal)
            scan_stats["signals_sent"] += 1
            return True, signal
    elif force_report:
        lines = [
            f"🏛️ <b>تحليل عملة {tg_escape(resolved)}</b>",
            f"⭐ التقييم: {signal.get('score', 0)}/100 (تحت المراقبة)",
            f"💵 السعر: {format_num(price, 4)}",
            f"📝 السبب: {tg_escape(signal.get('reason', ''))}"
        ]
        tg_send("\n".join(lines), chat_id)
    return False, signal

# ================= Background Scanner =================
def background_scanner():
    logger.info("Background scanner started with Momentum Focus.")
    while True:
        try:
            symbols = get_scan_universe()
            logger.info(f"Scanning {len(symbols)} symbols...")
            for sym in symbols:
                try:
                    analyze_symbol(sym)
                    time.sleep(1.0)
                except Exception as e:
                    scan_stats["errors"] += 1
                    logger.debug(f"Error scanning {sym}: {e}")
            time.sleep(SCAN_INTERVAL_SECONDS)
        except Exception as e:
            logger.error(f"Scanner loop error: {e}")
            time.sleep(30)

# ================= Flask Routes & Webhook =================
@app.route("/")
def index(): return jsonify({"status": "running", "version": "V7.7", "stats": scan_stats})

@app.route("/health")
def health(): return "OK", 200

@app.route(f"/{TELEGRAM_BOT_TOKEN}", methods=["POST"])
def telegram_webhook():
    try:
        data = request.get_json(force=True)
        message = data.get("message") or data.get("edited_message")
        if not message: return "OK", 200
        chat_id = message.get("chat", {}).get("id")
        text = message.get("text", "").strip()
        if not chat_id or not text: return "OK", 200

        text_upper = text.upper()
        if text_upper.startswith("/START") or text_upper.startswith("/HELP"):
            tg_send("🤖 <b>مرحباً بك في البوت النسخة الاحترافية (V7.7)</b>\n\n• مخصص لاصطياد العملات الصاعدة والزخم القوي.\n• يرسل التنبيهات تلقائياً عند توافر شروط الدخول الناجحة.\n• استخدم <code>/scan</code> للبحث الفوري، أو أرسل رمز العملة (مثل <code>SOL</code>) لتحليلها فوراً.", chat_id)
        elif text_upper.startswith("/SCAN"):
            found = 0
            for sym in get_scan_universe():
                try:
                    is_valid, _ = analyze_symbol(sym, chat_id=chat_id, force_report=False)
                    if is_valid: found += 1
                    time.sleep(0.2)
                except: pass
            if found == 0: tg_send("🔍 تم فحص السوق ولم يتم رصد صفقات جديدة مطابقة للشروط حالياً. البوت مستمر في المراقبة!", chat_id)
        else:
            analyze_symbol(text.split()[0], chat_id=chat_id, force_report=True)
    except Exception as e:
        logger.error(f"Webhook error: {e}")
    return "OK", 200

if __name__ == "__main__":
    db_init()
    register_telegram_webhook()
    threading.Thread(target=background_scanner, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), threaded=True)
