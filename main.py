# ============================================================
# main.py — Bot V85.0 (MultiMarket Scanner, Tracker & Webhook)
# Crypto + Gold + Forex (BingX Swaps) - LONG & SHORT Support
# ============================================================
import os
import re
import time
import hashlib
import threading
import logging
import sqlite3
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import ccxt
import requests
from flask import Flask, jsonify, request

from analysis import StrategyEngine, is_signal_expired, validate_signal

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("MainBot")
app = Flask(__name__)


# ---------- Config ----------
def _env_float(name, default):
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return float(default)


def _env_int(name, default):
    try:
        return int(float(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return int(default)


TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
ALLOWED_CHAT_IDS = {c.strip() for c in os.environ.get("ALLOWED_CHAT_IDS", "").split(",") if c.strip()}
if TELEGRAM_CHAT_ID:
    ALLOWED_CHAT_IDS.add(TELEGRAM_CHAT_ID)

BOT_CAPITAL_USD = max(1.0, _env_float("BOT_CAPITAL_USD", 10000))
RISK_PER_TRADE = min(0.02, max(0.001, _env_float("RISK_PER_TRADE", 0.01)))
MAX_SCAN_SYMBOLS = max(5, min(150, _env_int("MAX_SCAN_SYMBOLS", 60)))
SCAN_INTERVAL_SECONDS = max(60, _env_int("SCAN_INTERVAL_SECONDS", 180))
SIGNAL_COOLDOWN_SECONDS = max(180, _env_int("SIGNAL_COOLDOWN_SECONDS", 1800))
MAX_ACTIVE_POSITIONS = max(1, _env_int("MAX_ACTIVE_POSITIONS", 8))
MAX_DAILY_SIGNALS = max(1, _env_int("MAX_DAILY_SIGNALS", 15))
POSITION_MAX_HOURS = max(1, _env_int("POSITION_MAX_HOURS", 24))
TRACK_INTERVAL_SECONDS = max(30, _env_int("TRACK_INTERVAL_SECONDS", 60))
KEEPALIVE_INTERVAL_SECONDS = max(120, _env_int("KEEPALIVE_INTERVAL_SECONDS", 600))
WEBHOOK_CHECK_INTERVAL_SECONDS = max(300, _env_int("WEBHOOK_CHECK_INTERVAL_SECONDS", 1800))
STALE_SECONDS = max(600, _env_int("STALE_SECONDS", 1200))
DB_PATH = os.environ.get("DB_PATH", "bot_state.db")
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL", "").strip().rstrip("/")

WEBHOOK_PATH = "/tg-webhook"
WEBHOOK_URL = f"{RENDER_EXTERNAL_URL}{WEBHOOK_PATH}" if RENDER_EXTERNAL_URL else ""
WEBHOOK_SECRET = hashlib.sha256(TELEGRAM_BOT_TOKEN.encode()).hexdigest()[:32] if TELEGRAM_BOT_TOKEN else ""

PRIORITY_SYMBOLS = ["BTC/USDT:USDT", "ETH/USDT:USDT", "XAU/USDT:USDT", "SOL/USDT:USDT",
                    "EUR/USDT:USDT", "GBP/USDT:USDT", "BNB/USDT:USDT", "XRP/USDT:USDT"]

bingx = ccxt.bingx({"enableRateLimit": True, "timeout": 20000, "options": {"defaultType": "swap"}})
engine = StrategyEngine(capital=BOT_CAPITAL_USD, risk_per_trade=RISK_PER_TRADE)

db_lock = threading.RLock()
signal_lock = threading.Lock()
exchange_lock = threading.RLock()
scan_lock = threading.Lock()
worker_lock = threading.Lock()
boot_lock = threading.Lock()
executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="tg")

scan_stats = {"scanned_pairs": 0, "signals_sent": 0, "errors": 0, "closed": 0}
heartbeat = {"scanner": time.time(), "tracker": time.time()}
thread_gen = {"scanner": 0, "tracker": 0}
threads = {}
_all_markets_cache = []
_markets_cache_time = 0
_seen_updates = deque(maxlen=500)
_seen_lock = threading.Lock()
_started = False


# ================= Database =================
def _db():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def db_query(sql, params=(), one=False):
    with db_lock:
        conn = _db()
        try:
            cur = conn.execute(sql, params)
            rows = cur.fetchall()
            conn.commit()
            if one:
                return rows[0] if rows else None
            return rows
        finally:
            conn.close()


def db_init():
    folder = os.path.dirname(os.path.abspath(DB_PATH))
    os.makedirs(folder, exist_ok=True)
    try:
        db_query("PRAGMA journal_mode=WAL")
    except Exception:
        pass
    db_query("CREATE TABLE IF NOT EXISTS positions (symbol TEXT PRIMARY KEY, signal_id TEXT, direction TEXT, entry REAL, stop_loss REAL, tp1 REAL, tp2 REAL, tp3 REAL, tp1_done INTEGER DEFAULT 0, tp2_done INTEGER DEFAULT 0, tp3_done INTEGER DEFAULT 0, breakeven_done INTEGER DEFAULT 0, created_at REAL, expires_at REAL, initial_stop REAL, realized_r REAL DEFAULT 0, last_checked REAL, score INTEGER DEFAULT 0)")
    db_query("CREATE TABLE IF NOT EXISTS signal_history (signal_id TEXT PRIMARY KEY, symbol TEXT, direction TEXT, entry REAL, stop_loss REAL, score INTEGER, created_at REAL, sent INTEGER DEFAULT 0)")
    db_query("CREATE TABLE IF NOT EXISTS daily_counter (day TEXT PRIMARY KEY, count INTEGER DEFAULT 0)")
    db_query("CREATE TABLE IF NOT EXISTS bot_state (key TEXT PRIMARY KEY, value TEXT)")
    db_query("CREATE TABLE IF NOT EXISTS trade_results (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, signal_id TEXT, entry REAL, exit_price REAL, r_multiple REAL, outcome TEXT, score INTEGER, opened_at REAL, closed_at REAL)")


def db_get_state(key, default=None):
    row = db_query("SELECT value FROM bot_state WHERE key = ?", (key,), one=True)
    return row["value"] if row else default


def db_set_state(key, value):
    db_query("INSERT OR REPLACE INTO bot_state (key, value) VALUES (?, ?)", (key, str(value)))


def _today():
    return datetime.now(timezone.utc).date().isoformat()


def db_daily_count_today():
    row = db_query("SELECT count FROM daily_counter WHERE day = ?", (_today(),), one=True)
    return int(row["count"]) if row else 0


def db_daily_increment():
    db_query("INSERT INTO daily_counter (day, count) VALUES (?, 1) ON CONFLICT(day) DO UPDATE SET count = count + 1", (_today(),))


def db_last_signal_time(symbol):
    row = db_query("SELECT created_at FROM signal_history WHERE symbol = ? ORDER BY created_at DESC LIMIT 1", (symbol,), one=True)
    return float(row["created_at"]) if row else 0.0


# ================= Exchange Helpers =================
def ex_call(fn, *args, retries=3, **kwargs):
    delay = 1.0
    last_exc = None
    for _ in range(retries):
        try:
            with exchange_lock:
                return fn(*args, **kwargs)
        except (ccxt.BadSymbol, ccxt.BadRequest, ccxt.AuthenticationError):
            raise
        except ccxt.NetworkError as e:
            last_exc = e
            time.sleep(delay)
            delay *= 2
    raise last_exc


_SYM_RE = re.compile(r"^[A-Z0-9]{2,20}$")


def base_of(raw):
    s = str(raw).strip().upper().replace(" ", "").replace("_", "").replace("-", "/")
    s = s.split(":")[0]
    if "/" in s:
        s = s.split("/")[0]
    elif s.endswith("USDT") and len(s) > 4:
        s = s[:-4]
    if s in ("USDT", "USDC", "BUSD") or not _SYM_RE.match(s):
        return None
    return s


def fetch_ohlcv(symbol_raw, timeframe, limit=100):
    base = base_of(symbol_raw)
    if not base:
        return None, None
    for symbol in (f"{base}/USDT:USDT", f"{base}/USDT"):
        try:
            bars = ex_call(bingx.fetch_ohlcv, symbol, timeframe=timeframe, limit=limit)
            if bars and len(bars) > 10:
                return symbol, bars
        except Exception as e:
            logger.debug(f"fetch_ohlcv {symbol} {timeframe} failed: {e}")
    return None, None


def fetch_last_price(symbol):
    try:
        t = ex_call(bingx.fetch_ticker, symbol)
        p = float(t.get("last") or t.get("close") or 0)
        return p if p > 0 else None
    except Exception as e:
        logger.debug(f"fetch_last_price {symbol} failed: {e}")
        return None


# ================= Telegram =================
def tg_escape(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _tg_post(url, target, text, parse_mode):
    payload = {"chat_id": target, "text": text, "disable_web_page_preview": True}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    for attempt in range(3):
        try:
            r = requests.post(url, json=payload, timeout=15)
            if r.status_code == 200:
                return True
            if r.status_code == 429:
                time.sleep(3)
                continue
            if r.status_code >= 500:
                time.sleep(2 * (attempt + 1))
                continue
            return False
        except requests.RequestException:
            time.sleep(2 * (attempt + 1))
    return False


def tg_send(message, chat_id=None, parse_mode="HTML"):
    target = chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not target:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    message = str(message)
    chunks = [message[i:i + 4000] for i in range(0, len(message), 4000)] or [""]
    ok = True
    for chunk in chunks:
        ok = _tg_post(url, target, chunk, parse_mode) and ok
    return ok


def register_telegram_webhook(drop_pending=False):
    if not TELEGRAM_BOT_TOKEN or not WEBHOOK_URL:
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook",
            json={"url": WEBHOOK_URL, "secret_token": WEBHOOK_SECRET,
                  "allowed_updates": ["message", "edited_message"],
                  "max_connections": 4, "drop_pending_updates": drop_pending},
            timeout=15)
        return r.status_code == 200
    except Exception:
        return False


def webhook_is_healthy():
    try:
        r = requests.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getWebhookInfo", timeout=15)
        info = r.json().get("result", {})
        return info.get("url") == WEBHOOK_URL
    except Exception:
        return True


# ================= Scan Universe =================
def get_scan_universe():
    global _all_markets_cache, _markets_cache_time
    try:
        if not _all_markets_cache or time.time() - _markets_cache_time > 1800:
            markets = ex_call(bingx.load_markets, True)
            _all_markets_cache = [
                s for s, m in markets.items()
                if m.get("swap") and m.get("active", True)
                and m.get("quote") == "USDT" and m.get("settle") == "USDT"
            ]
            _markets_cache_time = time.time()

        if not _all_markets_cache:
            return PRIORITY_SYMBOLS[:5]

        fixed = [s for s in PRIORITY_SYMBOLS if s in _all_markets_cache]
        remaining = [s for s in _all_markets_cache if s not in set(fixed)]
        needed = max(0, MAX_SCAN_SYMBOLS - len(fixed))
        batch = []
        if remaining and needed:
            idx = int(db_get_state("scan_index", 0)) % len(remaining)
            count = min(needed, len(remaining))
            batch = [remaining[(idx + i) % len(remaining)] for i in range(count)]
            db_set_state("scan_index", (idx + count) % len(remaining))
        return (fixed + batch)[:MAX_SCAN_SYMBOLS]
    except Exception:
        return PRIORITY_SYMBOLS[:5]


# ================= Signal Gating & Positions =================
def can_send_signal(symbol):
    if time.time() - db_last_signal_time(symbol) < SIGNAL_COOLDOWN_SECONDS:
        return False
    if db_query("SELECT 1 FROM positions WHERE symbol = ?", (symbol,), one=True):
        return False
    if int(db_query("SELECT COUNT(*) AS n FROM positions", one=True)["n"]) >= MAX_ACTIVE_POSITIONS:
        return False
    return db_daily_count_today() < MAX_DAILY_SIGNALS


def reserve_signal(symbol, signal, entry_eff):
    with signal_lock:
        if not can_send_signal(symbol):
            return False
        tps = (list(signal.get("take_profits", [])) + [0, 0, 0])[:3]
        now = time.time()
        db_query(
            "INSERT OR REPLACE INTO positions (symbol, signal_id, direction, entry, stop_loss, tp1, tp2, tp3, tp1_done, tp2_done, tp3_done, breakeven_done, created_at, expires_at, initial_stop, realized_r, last_checked, score) VALUES (?,?,?,?,?,?,?,?,0,0,0,0,?,?,?,0,?,?)",
            (symbol, signal["signal_id"], signal["direction"], entry_eff, signal["stop_loss"],
             tps[0], tps[1], tps[2], now, now + POSITION_MAX_HOURS * 3600,
             signal["stop_loss"], now, int(signal.get("score", 0))))
        db_query(
            "INSERT OR REPLACE INTO signal_history (signal_id, symbol, direction, entry, stop_loss, score, created_at, sent) VALUES (?,?,?,?,?,?,?,0)",
            (signal["signal_id"], symbol, signal["direction"], entry_eff, signal["stop_loss"],
             int(signal.get("score", 0)), now))
        db_daily_increment()
        return True


def confirm_signal_sent(signal_id):
    db_query("UPDATE signal_history SET sent = 1 WHERE signal_id = ?", (signal_id,))


def release_signal(symbol, signal_id):
    db_query("DELETE FROM positions WHERE symbol = ? AND signal_id = ?", (symbol, signal_id))
    db_query("DELETE FROM signal_history WHERE signal_id = ?", (signal_id,))
    db_query("UPDATE daily_counter SET count = MAX(0, count - 1) WHERE day = ?", (_today(),))


# ================= Formatting Reports =================
def decimals_for(price):
    return 8 if price < 0.1 else (6 if price < 1 else (4 if price < 100 else 2))


def format_num(v, d):
    try:
        return f"{float(v):.{d}f}" if float(v) > 0 else "N/A"
    except Exception:
        return "N/A"


def build_report(symbol, signal, live_price, manual=False):
    price = float(live_price or signal.get("entry") or 0)
    d = decimals_for(price)
    tps = (list(signal.get("take_profits", [])) + [0, 0, 0])[:3]
    direction = signal.get("direction", "LONG")
    
    emoji_dir = "🟢 صفقـة لونـغ (LONG)" if direction == "LONG" else "🔴 صفقـة شـورت (SHORT)"
    title = f"📊 تحليل شامل (يصلح للتداول)" if manual else f"🚨 <b>{emoji_dir} مؤكدة</b>"
    
    lines = [
        title,
        "🏛️ <b>EXPERT BOT V85.0 (SMC + ICT ANALYZER)</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"🪙 الأصل: <code>{tg_escape(symbol)}</code>",
        f"⭐ التقييم: <code>{signal.get('score', 0)}/100</code>",
        f"💵 السعر اللحظي: <code>{format_num(price, d)}</code>",
        f"🎯 سعر الدخول: <code>{format_num(signal.get('entry', 0), d)}</code>",
        f"🥇 TP1: <code>{format_num(tps[0], d)}</code>",
        f"🥈 TP2: <code>{format_num(tps[1], d)}</code>",
        f"🥉 TP3: <code>{format_num(tps[2], d)}</code>",
        f"🛑 وقف الخسارة: <code>{format_num(signal.get('stop_loss', 0), d)}</code>",
        "━━━━━━━━━━━━━━━━━━",
        f"📝 السبب الفني: {tg_escape(signal.get('reason', ''))}",
        "✅ التحليل دقيق ومطابق للشروط الهيكلية.",
    ]
    return "\n".join(lines)


# ================= Analysis Execution =================
def analyze_symbol(symbol_raw, chat_id=None, manual=False):
    resolved, candles15 = fetch_ohlcv(symbol_raw, "15m", 110)
    if not resolved or not candles15 or len(candles15) < 65:
        if manual:
            tg_send(f"❌ لا تتوفر بيانات كافية لـ <code>{tg_escape(symbol_raw)}</code> (لا تصلح)", chat_id)
        return False, None
    if not manual and not can_send_signal(resolved):
        return False, None

    _, candles5 = fetch_ohlcv(resolved, "5m", 40)
    scan_stats["scanned_pairs"] += 1
    direction, price, signal = engine.analyze_market_structure(candles5, candles15)

    if direction in ("LONG", "SHORT"):
        live = fetch_last_price(resolved)
        if manual:
            tg_send(build_report(resolved, signal, live, manual=True), chat_id)
            return True, signal
        if reserve_signal(resolved, signal, live or price):
            if tg_send(build_report(resolved, signal, live or price), TELEGRAM_CHAT_ID):
                confirm_signal_sent(signal["signal_id"])
                scan_stats["signals_sent"] += 1
                return True, signal
            release_signal(resolved, signal["signal_id"])
        return False, signal

    if manual:
        lines = [
            f"🏛️ <b>تحليل {tg_escape(resolved)}</b>",
            f"❌ <b>لا تصلح للتداول حالياً (Neutral)</b>",
            f"⭐ التقييم: {signal.get('score', 0)}/100",
            f"📝 السبب: {tg_escape(signal.get('reason', 'شروط السيولة والهيكل غير متوفرة'))}",
        ]
        tg_send("\n".join(lines), chat_id)
    return False, signal


# ================= Background Scanner & Tracker =================
def sleep_with_heartbeat(seconds, name, gen):
    end = time.time() + seconds
    while time.time() < end and thread_gen[name] == gen:
        heartbeat[name] = time.time()
        time.sleep(min(5, max(0.1, end - time.time())))


def scan_once(blocking=True, stop_check=None):
    if not scan_lock.acquire(blocking=blocking):
        return None
    try:
        found = 0
        for sym in get_scan_universe():
            if stop_check and stop_check():
                break
            heartbeat["scanner"] = time.time()
            try:
                ok, _ = analyze_symbol(sym)
                if ok:
                    found += 1
            except Exception as e:
                scan_stats["errors"] += 1
            time.sleep(0.5)
        return found
    finally:
        scan_lock.release()


def scanner_loop(gen):
    while thread_gen["scanner"] == gen:
        try:
            heartbeat["scanner"] = time.time()
            scan_once(stop_check=lambda: thread_gen["scanner"] != gen)
        except Exception:
            sleep_with_heartbeat(30, "scanner", gen)
        sleep_with_heartbeat(SCAN_INTERVAL_SECONDS, "scanner", gen)


def tracker_loop(gen):
    while thread_gen["tracker"] == gen:
        try:
            for pos in db_query("SELECT * FROM positions"):
                if thread_gen["tracker"] != gen:
                    break
                heartbeat["tracker"] = time.time()
                time.sleep(0.3)
        except Exception:
            pass
        sleep_with_heartbeat(TRACK_INTERVAL_SECONDS, "tracker", gen)


def start_worker(name, target):
    with worker_lock:
        thread_gen[name] += 1
        gen = thread_gen[name]
        heartbeat[name] = time.time()
        t = threading.Thread(target=target, args=(gen,), daemon=True, name=f"{name}-{gen}")
        threads[name] = t
        t.start()


def keepalive_loop():
    while True:
        time.sleep(300)
        try:
            if RENDER_EXTERNAL_URL:
                requests.get(f"{RENDER_EXTERNAL_URL}/health", timeout=20)
        except Exception:
            pass


# ================= Telegram Updates =================
HELP_TEXT = ("🤖 <b>مرحباً بك في البوت V85.0 (SMC + ICT Pro)</b>\n\n"
             "• يحدد صفقات <b>LONG</b> و <b>SHORT</b> تلقائياً.\n"
             "• أرسل أي رمز مثل <code>XAU</code> أو <code>BTC</code> لتحليله ومعرفة إن كان <b>يصلح أم لا</b>.\n"
             "• <code>/scan</code> فحص السوق فوراً.")


def handle_update(data):
    try:
        message = data.get("message") or data.get("edited_message")
        if not message:
            return
        chat_id = message.get("chat", {}).get("id")
        text = (message.get("text") or "").strip()
        if not chat_id or not text:
            return
        if str(chat_id) not in ALLOWED_CHAT_IDS:
            return

        parts = text.split()
        cmd = parts[0].split("@")[0].lower()
        if cmd in ("/start", "/help"):
            tg_send(HELP_TEXT, chat_id)
        elif cmd == "/scan":
            tg_send("🔍 بدأ الفحص الفني الذكي...", chat_id)
            found = scan_once(blocking=False)
            if found is None:
                tg_send("⏳ فحص آخر يعمل حالياً.", chat_id)
            else:
                tg_send(f"✅ انتهى الفحص: تم رصد {found} فرصة.", chat_id)
        elif cmd.startswith("/"):
            tg_send(HELP_TEXT, chat_id)
        else:
            if not base_of(parts[0]):
                tg_send("❌ رمز غير صالح. مثال: <code>XAU</code> أو <code>SOL</code>", chat_id)
            else:
                analyze_symbol(parts[0], chat_id=chat_id, manual=True)
    except Exception as e:
        logger.exception(f"handle_update error: {e}")


# ================= Flask Routes =================
@app.route("/")
def index():
    return jsonify({"status": "running", "version": "V85.0-SMC-Pro", "stats": scan_stats})


@app.route("/health")
def health():
    return "OK", 200


@app.route(WEBHOOK_PATH, methods=["POST"])
def telegram_webhook():
    if not TELEGRAM_BOT_TOKEN or request.headers.get("X-Telegram-Bot-Api-Secret-Token", "") != WEBHOOK_SECRET:
        return "forbidden", 403
    data = request.get_json(silent=True) or {}
    uid = data.get("update_id")
    with _seen_lock:
        if uid is not None and uid in _seen_updates:
            return "OK", 200
        _seen_updates.append(uid)
    executor.submit(handle_update, data)
    return "OK", 200


def bootstrap():
    global _started
    with boot_lock:
        if _started:
            return
        _started = True
    db_init()
    register_telegram_webhook(drop_pending=True)
    start_worker("scanner", scanner_loop)
    start_worker("tracker", tracker_loop)
    threading.Thread(target=keepalive_loop, daemon=True, name="keepalive").start()


bootstrap()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), threaded=True)
