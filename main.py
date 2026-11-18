# ============================================================
# main.py — Bot V124.1 Elite Multi-Market (With ADX & MACD Filters)
# Crypto + Stocks/ETFs + Forex + Metals | LONG + SHORT
# Signal-only. Telegram/BingX/Yahoo connectivity preserved.
# ============================================================

import os
import time
import threading
import logging
import sqlite3
from collections import deque
import ccxt
import requests
import pandas as pd
import yfinance as yf
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
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "").strip().rstrip("/")
if not WEBHOOK_URL:
    WEBHOOK_URL = os.environ.get("RENDER_EXTERNAL_URL", "").strip().rstrip("/")

bingx = ccxt.bingx({
    "enableRateLimit": True,
    "timeout": 15000,
    "options": {"defaultType": "swap"},
})

engine = StrategyEngine(capital=10000.0, risk_per_trade=0.01, min_score=72)

db_lock = threading.RLock()
exchange_lock = threading.RLock()
scan_lock = threading.Lock()
scan_stats = {"scanned_pairs": 0, "signals_sent": 0, "errors": 0}
_seen_updates = deque(maxlen=500)
_seen_lock = threading.Lock()
_all_markets_cache = []
_markets_cache_time = 0
_sent_signals_cache = {}
SIGNAL_COOLDOWN_SECONDS = 14400

US_STOCKS_AND_ETFS = [
    "SOXS", "SOXL", "SPY", "QQQ", "TQQQ", "SQQQ",
    "NVDA", "TSLA", "AAPL", "MSFT", "AMZN", "META", "AMD"
]
FOREX_AND_METALS = ["XAUUSD=X", "EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X"]


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
            return rows[0] if rows and one else (None if one else rows)
        finally:
            conn.close()


def db_init():
    try:
        db_query("CREATE TABLE IF NOT EXISTS bot_state (key TEXT PRIMARY KEY, value TEXT)")
    except Exception as exc:
        logger.error("DB init error: %s", exc)


def ex_call(fn, *args, **kwargs):
    with exchange_lock:
        return fn(*args, **kwargs)


def get_full_market_universe():
    global _all_markets_cache, _markets_cache_time
    try:
        if not _all_markets_cache or time.time() - _markets_cache_time > 1800:
            markets = ex_call(bingx.load_markets, True)
            crypto = []
            for symbol, market in markets.items():
                if not market.get("swap") or not market.get("active", True):
                    continue
                if market.get("quote") == "USDT" and market.get("settle") == "USDT":
                    crypto.append(symbol)
            _all_markets_cache = sorted(set(crypto + US_STOCKS_AND_ETFS + FOREX_AND_METALS))
            _markets_cache_time = time.time()
        return _all_markets_cache or ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOXS", "XAUUSD=X"]
    except Exception as exc:
        logger.error("Market universe error: %s", exc)
        return ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOXS", "XAUUSD=X"]


def clean_symbol_input(raw):
    s = str(raw).strip().upper().replace(" ", "")
    return s if len(s) >= 2 else None


def _yf_interval(timeframe):
    return {"1d": ("6mo", "1d"), "4h": ("60d", "1h"), "1h": ("30d", "1h"), "15m": ("30d", "15m")}.get(timeframe)


def _fetch_yfinance_ohlcv(ticker, timeframe):
    try:
        cfg = _yf_interval(timeframe)
        if not cfg:
            return None
        period, interval = cfg
        df = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=False, threads=False)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        if timeframe == "4h":
            df = df.resample("4h").agg({"Open":"first","High":"max","Low":"min","Close":"last","Volume":"sum"}).dropna()
        df = df.dropna().tail(180)
        bars = []
        for idx, row in df.iterrows():
            try:
                ts = int(pd.Timestamp(idx).timestamp() * 1000)
                vol = float(row.get("Volume", 1000) or 1000)
                if vol <= 0: vol = 1000.0
                bars.append([ts, float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"]), vol])
            except Exception:
                continue
        return bars if len(bars) > 10 else None
    except Exception as exc:
        logger.debug("yfinance fetch failed for %s %s: %s", ticker, timeframe, exc)
        return None


def fetch_ohlcv(symbol_raw, timeframe, limit=100):
    try:
        sym = clean_symbol_input(symbol_raw)
        if not sym:
            return None, None, "unknown"
        aliases = {"XAU":"XAUUSD=X", "XAUUSD":"XAUUSD=X", "GOLD":"XAUUSD=X",
                   "EURUSD":"EURUSD=X", "GBPUSD":"GBPUSD=X", "USDJPY":"USDJPY=X", "AUDUSD":"AUDUSD=X"}
        if sym in aliases or sym.endswith("=X"):
            ticker = aliases.get(sym, sym)
            bars = _fetch_yfinance_ohlcv(ticker, timeframe)
            if bars: return ticker.replace("=X", ""), bars, "forex"
        if sym in US_STOCKS_AND_ETFS:
            bars = _fetch_yfinance_ohlcv(sym, timeframe)
            if bars: return sym, bars, "stock"

        base = sym.split(":")[0].split("/")[0]
        if base.endswith("USDT") and len(base) > 4:
            base = base[:-4]
        for c_sym in (f"{base}/USDT:USDT", f"{base}/USDT"):
            try:
                bars = ex_call(bingx.fetch_ohlcv, c_sym, timeframe=timeframe, limit=limit)
                if bars and len(bars) > 10:
                    return c_sym, bars, "crypto"
            except Exception as exc:
                logger.debug("BingX OHLCV %s %s: %s", c_sym, timeframe, exc)
            time.sleep(0.04)
        bars = _fetch_yfinance_ohlcv(sym, timeframe)
        if bars: return sym, bars, "stock"
    except Exception as exc:
        logger.debug("Safe fetch_ohlcv warning for %s: %s", symbol_raw, exc)
    return None, None, "unknown"


def tg_send(message, chat_id=None):
    target = chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not target:
        return False
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": target, "text": message, "parse_mode":"HTML", "disable_web_page_preview":True},
            timeout=15,
        )
        if not response.ok:
            logger.error("Telegram send failed: %s %s", response.status_code, response.text[:300])
        return response.ok
    except Exception as exc:
        logger.error("Telegram send error: %s", exc)
        return False


def configure_webhook():
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("Telegram token missing; webhook not configured.")
        return
    if not WEBHOOK_URL:
        logger.warning("WEBHOOK_URL/RENDER_EXTERNAL_URL missing; keeping existing Telegram webhook state.")
        return
    try:
        url = f"{WEBHOOK_URL}/tg-webhook"
        r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook", json={"url":url, "drop_pending_updates":False}, timeout=15)
        logger.info("Telegram webhook setup: %s", r.text[:500])
    except Exception as exc:
        logger.error("Webhook setup error: %s", exc)


def decimals_for(price):
    try:
        price = float(price)
        if price < 0.0001: return 10
        if price < 0.01: return 8
        if price < 0.1: return 7
        if price < 1: return 6
        if price < 100: return 4
        return 2
    except Exception:
        return 4


def format_num(value, decimals):
    try:
        value = float(value)
        return "N/A" if value <= 0 else f"{value:.{decimals}f}"
    except Exception:
        return "N/A"


def analyze_symbol(symbol_raw, chat_id=None, manual=False):
    try:
        resolved, daily, asset_type = fetch_ohlcv(symbol_raw, "1d", 100)
        if not resolved or not daily or len(daily) < 55:
            if manual: tg_send(f"❌ الأصل <code>{symbol_raw}</code> غير متوفر أو بياناته اليومية غير كافية.", chat_id)
            return False, None
        _, h4, _ = fetch_ohlcv(symbol_raw, "4h", 100)
        _, h1, _ = fetch_ohlcv(symbol_raw, "1h", 100)
        _, m15, _ = fetch_ohlcv(symbol_raw, "15m", 120)
        if len(h4 or []) < 40 or len(h1 or []) < 35:
            if manual: tg_send(f"❌ <code>{resolved}</code> بيانات 4H/1H غير كافية.", chat_id)
            return False, None

        scan_stats["scanned_pairs"] += 1
        direction, price, signal = engine.analyze_market_structure(daily, h4, h1, asset_type=asset_type, ohlcv_15m=m15)
        market_tag = {"crypto":"🪙 Crypto", "stock":"📈 Stocks / ETFs", "forex":"💱 Forex / Metals"}.get(asset_type, "📊 Market")

        if direction in ("LONG", "SHORT"):
            key = resolved.split("/")[0]
            if not manual and time.time() - _sent_signals_cache.get(key, 0) < SIGNAL_COOLDOWN_SECONDS:
                return False, signal
            _sent_signals_cache[key] = time.time()
            d = decimals_for(price)
            tps = list(signal.get("take_profits", []))
            while len(tps) < 3: tps.append(0)
            details = signal.get("details", {}) or {}
            _, momentum_msg = engine.check_momentum_at_tp1(h1)
            emoji = "🟢" if direction == "LONG" else "🔴"
            side = "شراء LONG" if direction == "LONG" else "بيع SHORT"
            msg = (
                "🚀 <b>MY EXPERT MULTI-MARKET BOT V124.1 (ADX+MACD)</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"🏷️ <b>السوق:</b> {market_tag}\n"
                f"{emoji} <b>{side} — توقيت دخول مؤكد (ترند وزخم)</b>\n\n"
                f"💎 <b>الأصل:</b> <code>{resolved}</code>\n"
                f"⭐ <b>التقييم:</b> <code>{signal.get('score',0)}/100</code> ({details.get('quality','B+')})\n\n"
                f"📍 <b>منطقة الدخول:</b> <code>{format_num(signal.get('entry_low'),d)} — {format_num(signal.get('entry_high'),d)}</code>\n\n"
                "🎯 <b>الأهداف:</b>\n"
                f"🥇 TP1: <code>{format_num(tps[0],d)}</code>\n"
                f"🥈 TP2: <code>{format_num(tps[1],d)}</code>\n"
                f"🥉 TP3: <code>{format_num(tps[2],d)}</code>\n\n"
                f"🛑 <b>وقف الخسارة:</b> <code>{format_num(signal.get('stop_loss'),d)}</code>\n"
                f"📊 <b>RSI:</b> <code>{float(signal.get('rsi',50)):.1f}</code>\n"
                f"📍 <b>موقع النطاق:</b> <code>{float(details.get('position_in_range',0))*100:.1f}%</code>\n"
                f"📐 <b>الامتداد:</b> <code>{float(details.get('extension_atr',0)):.2f} ATR</code>\n"
                f"⚖️ <b>المخاطرة:</b> <code>{float(details.get('risk_pct',0)):.2f}%</code>\n\n"
                f"🧠 <b>السبب:</b> {signal.get('reason','')}\n\n"
                f"🎯 <b>متابعة الزخم:</b>\n{momentum_msg}\n\n"
                "⚠️ <b>إشارة تحليلية فقط — لا يتم تنفيذ أوامر تلقائيًا.</b>"
            )
            sent = tg_send(msg, chat_id)
            if sent: scan_stats["signals_sent"] += 1
            return True, signal

        if manual:
            reason = signal.get("reason", "الشروط غير مكتملة") if signal else "الشروط غير مكتملة"
            tg_send(
                f"📊 <b>تحليل:</b> <code>{symbol_raw}</code>\n🏷️ <b>السوق:</b> {market_tag}\n━━━━━━━━━━━━━━━━━━\n"
                "⚪ <b>لا توجد صفقة LONG/SHORT مكتملة حاليًا.</b>\n"
                f"🔎 <b>السبب:</b> {reason}", chat_id)
        return False, signal
    except Exception as exc:
        scan_stats["errors"] += 1
        logger.exception("Analyze %s error: %s", symbol_raw, exc)
        if manual: tg_send(f"❌ حدث خطأ مؤقت أثناء تحليل <code>{symbol_raw}</code>.", chat_id)
        return False, None


def run_full_scan(chat_id=None):
    if not scan_lock.acquire(blocking=False):
        if chat_id: tg_send("⏳ يوجد فحص شامل قيد التشغيل حاليًا.", chat_id)
        return
    try:
        if chat_id: tg_send("🔍 <b>جارٍ فحص Crypto + Stocks/ETFs + Forex/Metals (مع فلاتر الاتجاه والزخم)...</b>", chat_id)
        symbols = get_full_market_universe()
        found = 0
        for sym in symbols:
            try:
                ok, _ = analyze_symbol(sym, chat_id=None, manual=False)
                if ok: found += 1
            except Exception as exc:
                scan_stats["errors"] += 1
                logger.debug("Scan skip %s: %s", sym, exc)
            time.sleep(0.12)
        if chat_id:
            tg_send(f"✅ <b>انتهى الفحص.</b>\n\n🔎 الأصول المفحوصة: <code>{len(symbols)}</code>\n🟢 الفرص: <code>{found}</code>", chat_id)
    except Exception as exc:
        scan_stats["errors"] += 1
        logger.exception("Full scan error: %s", exc)
        if chat_id: tg_send("❌ حدث خطأ أثناء الفحص الشامل.", chat_id)
    finally:
        scan_lock.release()


def background_auto_scheduler():
    time.sleep(20)
    while True:
        try:
            if TELEGRAM_CHAT_ID:
                run_full_scan()
        except Exception as exc:
            logger.exception("Scheduler error: %s", exc)
        time.sleep(14400)


HELP_TEXT = (
    "🤖 <b>MY EXPERT MULTI-MARKET BOT V124.1</b>\n━━━━━━━━━━━━━━━━━━\n\n"
    "🧭 <b>الأسواق:</b> Crypto + Stocks/ETFs + Forex/Metals\n"
    "🟢 LONG و 🔴 SHORT (مدعوم بفلتر ADX & MACD)\n"
    "📌 أرسل BTC أو SOXS أو XAUUSD أو أي رمز مدعوم\n"
    "🔍 أرسل <code>/scan</code> للفحص الشامل.\n"
    "⚠️ إشارات تحليلية فقط — لا تنفيذ تلقائي."
)


def handle_update(data):
    try:
        message = data.get("message") or data.get("edited_message")
        if not message: return
        chat_id = message.get("chat", {}).get("id")
        text = (message.get("text") or "").strip()
        if not chat_id or not text: return
        if ALLOWED_CHAT_IDS and str(chat_id) not in ALLOWED_CHAT_IDS: return
        parts = text.split()
        cmd = parts[0].split("@")[0].lower()
        if cmd in ("/start", "/help"):
            tg_send(HELP_TEXT, chat_id)
        elif cmd == "/scan":
            threading.Thread(target=run_full_scan, args=(chat_id,), daemon=True).start()
        else:
            analyze_symbol(parts[0], chat_id=chat_id, manual=True)
    except Exception:
        logger.exception("handle_update error")


@app.route("/")
def index():
    return jsonify({"status":"running", "version":"V124.1-Elite-ADX", "stats":scan_stats})


@app.route("/health")
def health():
    return "OK", 200


@app.route("/tg-webhook", methods=["POST"])
def telegram_webhook():
    data = request.get_json(silent=True) or {}
    uid = data.get("update_id")
    with _seen_lock:
        if uid is not None and uid in _seen_updates: return "OK", 200
        if uid is not None: _seen_updates.append(uid)
    threading.Thread(target=handle_update, args=(data,), daemon=True).start()
    return "OK", 200


def bootstrap():
    db_init()
    logger.info("Bot V124.1 bootstrapped: LONG+SHORT, ADX+MACD filters, multi-market.")
    threading.Thread(target=configure_webhook, daemon=True).start()
    threading.Thread(target=background_auto_scheduler, daemon=True).start()


bootstrap()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), threaded=True)
