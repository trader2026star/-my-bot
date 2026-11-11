# ============================================================
# main.py — Bot V95.0 (Telegram Webhook & Scanner)
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
PRIORITY_SYMBOLS = ["BTC/USDT:USDT", "ETH/USDT:USDT", "XAU/USDT:USDT", "SOL/USDT:USDT", "BNB/USDT:USDT"]

bingx = ccxt.bingx({"enableRateLimit": True, "timeout": 20000, "options": {"defaultType": "swap"}})
engine = StrategyEngine()

db_lock = threading.RLock()
exchange_lock = threading.RLock()
scan_lock = threading.Lock()
scan_stats = {"scanned_pairs": 0, "signals_sent": 0, "errors": 0}
_seen_updates = deque(maxlen=500)
_seen_lock = threading.Lock()


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
    resolved, candles15 = fetch_ohlcv(symbol_raw, "15m", 110)
    if not resolved or not candles15 or len(candles15) < 50:
        if manual:
            tg_send(f"❌ الأصل <code>{symbol_raw}</code> <b>لا يملك بيانات كافية</b> أو لا يصلح للتداول.", chat_id)
        return False, None

    _, candles5 = fetch_ohlcv(resolved, "5m", 40)
    scan_stats["scanned_pairs"] += 1
    direction, price, signal = engine.analyze_market_structure(candles5, candles15)

    if direction in ("LONG", "SHORT"):
        d = decimals_for(price)
        tps = signal.get("take_profits", [0, 0, 0])
        details = signal.get("details", {})
        
        dir_text = "🟢 <b>صفقة قناصة (LONG - شراء مؤسسي)</b>" if direction == "LONG" else "🔴 <b>صفقة قناصة (SHORT - بيع مؤسسي)</b>"
        
        msg = (
            f"⚡ <b>Smart Flow Sniper V5.5</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🪙 العملة: <code>{resolved}</code>\n"
            f"📌 الاتجاه: {dir_text}\n"
            f"⭐ التقييم: <code>{signal.get('score', 0)}/100</code>\n"
            f"💵 سعر الدخول: <code>{format_num(signal.get('entry', 0), d)}</code>\n"
            f"🥇 TP1: <code>{format_num(tps[0], d)}</code>\n"
            f"🥈 TP2: <code>{format_num(tps[1], d)}</code>\n"
            f"🥉 TP3: <code>{format_num(tps[2], d)}</code>\n"
            f"🛑 وقف الخسارة: <code>{format_num(signal.get('stop_loss', 0), d)}</code>\n"
            f"🌊 دفتر الأوامر L2 OBI: <code>{details.get('obi', '52%')}</code>\n"
            f"📊 تدفق الدلتا CVD: <code>{details.get('cvd', 'BULLISH_FLOW')}</code>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📝 السبب: {signal.get('reason', '')}"
        )
        tg_send(msg, chat_id)
        return True, signal

    if manual:
        msg = (
            f"📊 <b>تحليل الأصل: {symbol_raw}</b>\n"
            f"❌ <b>لا تصلح للتداول حالياً (Neutral)</b>\n"
            f"📝 السبب: {signal.get('reason', 'الشروط المؤسسية لم تكتمل بعد.')}"
        )
        tg_send(msg, chat_id)
    return False, signal


def run_full_scan(chat_id):
    if not scan_lock.acquire(blocking=False):
        tg_send("⏳ يوجد فحص قيد التشغيل حالياً.", chat_id)
        return
    try:
        tg_send("🔍 بدأ فحص القناصة المؤسسي للأصول...", chat_id)
        found = 0
        for sym in PRIORITY_SYMBOLS:
            scan_stats["scanned_pairs"] += 1
            ok, _ = analyze_symbol(sym, chat_id=chat_id, manual=False)
            if ok:
                found += 1
            time.sleep(1.0)
        tg_send(f"✅ انتهى الفحص. تم رصد {found} فرصة قناصة مطابقة.", chat_id)
    except Exception as e:
        logger.error(f"Scan error: {e}")
    finally:
        scan_lock.release()


HELP_TEXT = ("🤖 <b>مرحباً بك في بوت Smart Flow Sniper V95.0</b>\n\n"
             "• أرسل أي رمز مثل <code>XAU</code> أو <code>SOL</code> أو <code>BTC</code> لفحصه ومعرفة إن كان <b>يصلح للتداول المؤسسي أم لا</b>.\n"
             "• أرسل <code>/scan</code> للفحص الشامل.")


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
                tg_send("❌ رمز غير صالح. مثال: <code>XAU</code> أو <code>SOL</code>", chat_id)
            else:
                analyze_symbol(parts[0], chat_id=chat_id, manual=True)
    except Exception as e:
        logger.exception(f"handle_update error: {e}")


@app.route("/")
def index():
    return jsonify({"status": "running", "version": "V95.0-SmartFlow", "stats": scan_stats})


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
    logger.info("Bot V95.0 Smart Flow bootstrapped successfully.")


bootstrap()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), threaded=True)
