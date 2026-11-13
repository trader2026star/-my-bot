# ============================================================
# main.py — Bot V120.0 (Swing Accumulation Format)
# ============================================================
import os
import re
import time
import threading
import logging
import sqlite3
from collections import deque
from datetime import datetime, timezone

import ccxt
import requests
from flask import Flask, jsonify, request

from analysis import StrategyEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("MainBot")
app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
ALLOWED_CHAT_IDS = {c.strip() for c in os.environ.get("ALLOWED_CHAT_IDS", "").split(",") if c.strip()}
if TELEGRAM_CHAT_ID:
    ALLOWED_CHAT_IDS.add(TELEGRAM_CHAT_ID)

DB_PATH = os.environ.get("DB_PATH", "/tmp/bot_state.db")

bingx = ccxt.bingx({"enableRateLimit": True, "timeout": 20000, "options": {"defaultType": "swap"}})
engine = StrategyEngine()

db_lock = threading.RLock()
exchange_lock = threading.RLock()
scan_lock = threading.Lock()
scan_stats = {"scanned_pairs": 0, "signals_sent": 0, "errors": 0}
_seen_updates = deque(maxlen=500)
_seen_lock = threading.Lock()

_all_markets_cache = []
_markets_cache_time = 0
_sent_signals_cache = {}


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
    try:
        db_query("CREATE TABLE IF NOT EXISTS bot_state (key TEXT PRIMARY KEY, value TEXT)")
    except Exception:
        pass


def ex_call(fn, *args, **kwargs):
    with exchange_lock:
        return fn(*args, **kwargs)


def get_full_market_universe():
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
        return _all_markets_cache if _all_markets_cache else ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"]
    except Exception:
        return ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"]


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
        except Exception:
            pass
    return None, None


def tg_send(message, chat_id=None):
    target = chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not target:
        return False
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": target, "text": message, "parse_mode": "HTML"},
            timeout=15
        )
        return True
    except Exception:
        return False


def decimals_for(price):
    return 8 if price < 0.1 else (6 if price < 1 else (4 if price < 100 else 2))


def format_num(v, d):
    try:
        return f"{float(v):.{d}f}" if float(v) > 0 else "N/A"
    except Exception:
        return "N/A"


def analyze_symbol(symbol_raw, chat_id=None, manual=False):
    resolved, candles_daily = fetch_ohlcv(symbol_raw, "1d", 60)
    if not resolved or not candles_daily or len(candles_daily) < 30:
        if manual:
            tg_send(f"❌ الأصل <code>{symbol_raw}</code> غير متوفر أو بياناته غير كافية.", chat_id)
        return False, None

    _, candles4h = fetch_ohlcv(resolved, "4h", 50)
    _, candles1h = fetch_ohlcv(resolved, "1h", 40)

    scan_stats["scanned_pairs"] += 1
    direction, price, signal = engine.analyze_market_structure(candles_daily, candles4h, candles1h)

    if direction == "LONG":
        sym_name = resolved.split("/")[0]
        full_sym_name = sym_name + "$"

        if not manual:
            last_sent = _sent_signals_cache.get(sym_name, 0)
            if time.time() - last_sent < 14400:
                return False, signal
            _sent_signals_cache[sym_name] = time.time()

        d = decimals_for(price)
        tps = signal.get("take_profits", [0, 0, 0])

        msg = (
            f"🚀 <b>فرصة شراء جديدة قد تشاهد هذه الأشهر ارتفاع مذهل</b>\n\n"
            f"🟢 <b>صفقة: Futures – USDT Perpetual</b>\n"
            f"💎 <b>العملة: {full_sym_name}</b>\n"
            f"⚡ <b>الرافعة المالية: 20x</b>\n\n"
            f"📍 <b>سعر الدخول:</b> <code>{format_num(signal.get('entry_low', 0), d)}$</code>\n\n"
            f"🎯 <b>الأهداف:</b>\n"
            f"🥇 <code>{format_num(tps[0], d)}$</code>\n"
            f"🥈 <code>{format_num(tps[1], d)}$</code>\n"
            f"🥉 <code>{format_num(tps[2], d)}$</code>\n\n"
            f"🔴 <b>وقف الخسارة:</b> <code>{format_num(signal.get('stop_loss', 0), d)}$</code>\n\n"
            f"⚠️ <b>التزم بإدارة رأس المال ولا تذاطر بأكثر مما تستطيع تحمله.</b>"
        )
        scan_stats["signals_sent"] += 1
        tg_send(msg, chat_id)
        return True, signal

    if manual:
        msg = (
            f"📊 <b>تحليل الأصل: {symbol_raw}</b>\n"
            f"⏳ <b>العملة لم تصل لمنطقة التجميع المناسبة بعد، انتظر الإشارة المكتملة.</b>"
        )
        tg_send(msg, chat_id)
    return False, signal


def run_full_scan(chat_id=None):
    if not scan_lock.acquire(blocking=False):
        if chat_id:
            tg_send("⏳ يوجد فحص شامل قيد التشغيل حالياً.", chat_id)
        return
    try:
        if chat_id:
            tg_send("🔍 جاري مسح السوق وبحث فرص التجميع والسوينغ...", chat_id)
        symbols = get_full_market_universe()
        found = 0
        for sym in symbols[:50]:
            ok, _ = analyze_symbol(sym, chat_id=chat_id, manual=False)
            if ok:
                found += 1
            time.sleep(0.2)
        if chat_id:
            tg_send(f"✅ انتهى مسح السوق. تم رصد {found} فرصة تجميع سوينغ ناشطة.", chat_id)
    except Exception as e:
        logger.error(f"Full Scan error: {e}")
    finally:
        scan_lock.release()


def background_auto_scheduler():
    time.sleep(15)
    while True:
        try:
            if TELEGRAM_CHAT_ID:
                run_full_scan(chat_id=None)
        except Exception as e:
            logger.error(f"Background scheduler error: {e}")
        time.sleep(14400)


HELP_TEXT = (
    "🤖 <b>بوت تداول السوينغ والتجميع (نسخة V120.0)</b>\n\n"
    "• أرسل رمز العملة مثل <code>BARD</code> أو <code>BTC</code> لفحصها.\n"
    "• أرسل <code>/scan</code> لمسح السوق وبحث فرص الصعود."
)


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
            threading.Thread(target=run_full_scan, args=(chat_id,), daemon=True).start()
        else:
            if not base_of(parts[0]):
                tg_send("❌ رمز غير صالح. مثال: <code>BARD</code> أو <code>BTC</code>", chat_id)
            else:
                analyze_symbol(parts[0], chat_id=chat_id, manual=True)
    except Exception as e:
        logger.exception(f"handle_update error: {e}")


@app.route("/")
def index():
    return jsonify({"status": "running", "version": "V120.0-SwingAccumulation", "stats": scan_stats})


@app.route("/health")
def health():
    return "OK", 200


@app.route("/tg-webhook", methods=["POST"])
def telegram_webhook():
    data = request.get_json(silent=True) or {}
    uid = data.get("update_id")
    with _seen_lock:
        if uid is not None and uid in _seen_updates:
            return "OK", 200
        _seen_updates.append(uid)
    threading.Thread(target=handle_update, args=(data,), daemon=True).start()
    return "OK", 200


def bootstrap():
    db_init()
    logger.info("Bot V120.0 Swing Accumulation bootstrapped successfully.")
    threading.Thread(target=background_auto_scheduler, daemon=True).start()


bootstrap()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), threaded=True)
