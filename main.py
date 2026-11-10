# ============================================================
# main.py — Bot V90.0 (MultiMarket Scanner & Webhook)
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
PRIORITY_SYMBOLS = ["BTC/USDT:USDT", "ETH/USDT:USDT", "XAU/USDT:USDT", "SOL/USDT:USDT"]

bingx = ccxt.bingx({"enableRateLimit": True, "timeout": 20000, "options": {"defaultType": "swap"}})
engine = StrategyEngine()

db_lock = threading.RLock()
exchange_lock = threading.RLock()
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


def fetch_last_price(symbol):
    try:
        t = ex_call(bingx.fetch_ticker, symbol)
        p = float(t.get("last") or t.get("close") or 0)
        return p if p > 0 else None
    except Exception:
        return None


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
    if not resolved or not candles15 or len(candles15) < 65:
        if manual:
            tg_send(f"❌ العملة أو الأصل <code>{symbol_raw}</code> <b>لا تصلح للتداول</b> لعدم كفاية البيانات.", chat_id)
        return False, None

    _, candles5 = fetch_ohlcv(resolved, "5m", 40)
    scan_stats["scanned_pairs"] += 1
    direction, price, signal = engine.analyze_market_structure(candles5, candles15)

    if direction in ("LONG", "SHORT"):
        d = decimals_for(price)
        tps = signal.get("take_profits", [0, 0, 0])
        dir_text = "🟢 <b>يصلح (صفقة لونغ LONG)</b>" if direction == "LONG" else "🔴 <b>يصلح (صفقة شورت SHORT)</b>"
        
        msg = (
            f"🚨 <b>تقرير التحليل الفني المؤكد</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🪙 الأصل: <code>{resolved}</code>\n"
            f"📌 الحالة: {dir_text}\n"
            f"⭐ التقييم: <code>{signal.get('score', 0)}/100</code>\n"
            f"🎯 الدخول: <code>{format_num(signal.get('entry', 0), d)}</code>\n"
            f"🛑 الستوب: <code>{format_num(signal.get('stop_loss', 0), d)}</code>\n"
            f"🥇 TP1: <code>{format_num(tps[0], d)}</code>\n"
            f"🥈 TP2: <code>{format_num(tps[1], d)}</code>\n"
            f"🥉 TP3: <code>{format_num(tps[2], d)}</code>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📝 السبب: {signal.get('reason', '')}"
        )
        tg_send(msg, chat_id)
        return True, signal

    if manual:
        msg = (
            f"📊 <b>تحليل الأصل: {symbol_raw}</b>\n"
            f"❌ <b>لا تصلح للتداول حالياً (Neutral)</b>\n"
            f"📝 السبب: {signal.get('reason', 'الشروط الفنية والسيولة لم تكتمل بعد.')}"
        )
        tg_send(msg, chat_id)
    return False, signal


HELP_TEXT = ("🤖 <b>مرحباً بك في بوت التحليل المتقدم V90.0</b>\n\n"
             "• أرسل أي رمز (مثل <code>XAU</code> أو <code>SOL</code> أو <code>BTC</code>) لمعرفة إن كان <b>يصلح أم لا</b> واتجاه الصفقة بدقة.")


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
        else:
            if not base_of(parts[0]):
                tg_send("❌ رمز غير صالح. مثال: <code>XAU</code> أو <code>SOL</code>", chat_id)
            else:
                analyze_symbol(parts[0], chat_id=chat_id, manual=True)
    except Exception as e:
        logger.exception(f"handle_update error: {e}")


@app.route("/")
def index():
    return jsonify({"status": "running", "version": "V90.0-Pro", "stats": scan_stats})


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
    logger.info("Bot V90.0 bootstrapped successfully.")


bootstrap()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), threaded=True)
