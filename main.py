# ============================================================ #
# main.py — Bot V123.8 (Crypto + Forex + Metals + US Stocks)   #
# ============================================================ #

import os
import re
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("MainBot")
app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
ALLOWED_CHAT_IDS = {
    c.strip()
    for c in os.environ.get("ALLOWED_CHAT_IDS", "").split(",")
    if c.strip()
}
if TELEGRAM_CHAT_ID:
    ALLOWED_CHAT_IDS.add(TELEGRAM_CHAT_ID)
DB_PATH = os.environ.get("DB_PATH", "/tmp/bot_state.db")

bingx = ccxt.bingx(
    {
        "enableRateLimit": True,
        "timeout": 15000,
        "options": {
            "defaultType": "swap",
        },
    }
)

engine = StrategyEngine(
    capital=10000.0,
    risk_per_trade=0.01,
    min_score=72,
)

db_lock = threading.RLock()
exchange_lock = threading.RLock()
scan_lock = threading.Lock()
scan_stats = {
    "scanned_pairs": 0,
    "signals_sent": 0,
    "errors": 0,
}
_seen_updates = deque(maxlen=500)
_seen_lock = threading.Lock()
_all_markets_cache = []
_markets_cache_time = 0
_sent_signals_cache = {}

SIGNAL_COOLDOWN_SECONDS = 14400

# قائمة الأسهم والصناديق المتداولة (ETFs) الأمريكية الأساسية للفحص الشامل
US_STOCKS_AND_ETFS = [
    "SOXS", "SOXL", "SPY", "QQQ", "TQQQ", "SQQQ",
    "NVDA", "TSLA", "AAPL", "MSFT", "AMZN", "META", "AMD"
]

# قائمة الفوركس والمعادن
FOREX_AND_METALS = [
    "XAUUSD=X",  # الذهب الفوري
    "EURUSD=X",  # اليورو دولار
    "GBPUSD=X",  # الباوند دولار
    "USDJPY=X",  # الدولار ين
    "AUDUSD=X",  # الأسترالي دولار
]


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
        db_query(
            """
            CREATE TABLE IF NOT EXISTS bot_state (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
    except Exception as exc:
        logger.error("DB init error: %s", exc)


def ex_call(fn, *args, **kwargs):
    with exchange_lock:
        return fn(*args, **kwargs)


def get_full_market_universe():
    global _all_markets_cache
    global _markets_cache_time
    try:
        if not _all_markets_cache or (time.time() - _markets_cache_time > 1800):
            markets = ex_call(bingx.load_markets, True)
            crypto_universe = []
            for symbol, market in markets.items():
                if not market.get("swap", False):
                    continue
                if not market.get("active", True):
                    continue
                if market.get("quote") != "USDT":
                    continue
                if market.get("settle") != "USDT":
                    continue
                crypto_universe.append(symbol)

            # دمج العملات الرقمية + الأسهم الأمريكية وصناديق ETF + الفوركس والذهب
            combined = sorted(set(crypto_universe + US_STOCKS_AND_ETFS + FOREX_AND_METALS))
            _all_markets_cache = combined
            _markets_cache_time = time.time()

        if _all_markets_cache:
            return _all_markets_cache
        return ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOXS", "XAUUSD=X"]
    except Exception as exc:
        logger.error("Market universe error: %s", exc)
        return ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOXS", "XAUUSD=X"]


def clean_symbol_input(raw):
    s = str(raw).strip().upper().replace(" ", "")
    return s if len(s) >= 2 else None


def _fetch_yfinance_ohlcv(ticker, timeframe):
    """جلب بيانات الأسهم الأمريكية والفوركس عبر Yahoo Finance وتحويلها لصيغة OHLCV القياسية"""
    try:
        if timeframe == "1d":
            df = yf.download(ticker, period="6mo", interval="1d", progress=False, auto_adjust=False)
        elif timeframe == "4h":
            # Yahoo يدعم 1h ونجمعه تلقائياً إلى 4h بدقة
            df_1h = yf.download(ticker, period="60d", interval="1h", progress=False, auto_adjust=False)
            if df_1h is None or df_1h.empty:
                return None
            if isinstance(df_1h.columns, pd.MultiIndex):
                df_1h.columns = df_1h.columns.get_level_values(0)
            df = df_1h.resample("4h").agg({
                "Open": "first",
                "High": "max",
                "Low": "min",
                "Close": "last",
                "Volume": "sum"
            }).dropna()
        else:  # 1h
            df = yf.download(ticker, period="30d", interval="1h", progress=False, auto_adjust=False)

        if df is None or df.empty:
            return None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df.dropna().tail(100)
        bars = []
        for idx, row in df.iterrows():
            ts = int(idx.timestamp() * 1000)
            vol = float(row["Volume"]) if "Volume" in row and not pd.isna(row["Volume"]) else 1000.0
            if vol <= 0:
                vol = 1000.0  # للعملات الفوركس التي قد يكون حجمها 0 في بعض التحديثات
            bars.append([
                ts,
                float(row["Open"]),
                float(row["High"]),
                float(row["Low"]),
                float(row["Close"]),
                vol
            ])
        return bars if len(bars) > 10 else None
    except Exception as exc:
        logger.debug("yfinance fetch failed for %s %s: %s", ticker, timeframe, exc)
        return None


def fetch_ohlcv(symbol_raw, timeframe, limit=100):
    """جلب ذكي: يبحث أولاً في العملات الرقمية عبر BingX، وإذا لم يجد يبحث في الأسهم والفوركس"""
    sym = clean_symbol_input(symbol_raw)
    if not sym:
        return None, None, "unknown"

    # 1. التحقق إذا كان رمز فوركس مباشر أو معدن
    forex_aliases = {
        "XAU": "XAUUSD=X",
        "XAUUSD": "XAUUSD=X",
        "GOLD": "XAUUSD=X",
        "EURUSD": "EURUSD=X",
        "EUR/USD": "EURUSD=X",
        "GBPUSD": "GBPUSD=X",
        "GBP/USD": "GBPUSD=X",
        "USDJPY": "USDJPY=X",
        "USD/JPY": "USDJPY=X",
        "AUDUSD": "AUDUSD=X",
        "AUD/USD": "AUDUSD=X",
    }
    if sym in forex_aliases or sym.endswith("=X"):
        yf_ticker = forex_aliases.get(sym, sym)
        bars = _fetch_yfinance_ohlcv(yf_ticker, timeframe)
        if bars:
            return yf_ticker.replace("=X", ""), bars, "forex"

    # 2. التحقق إذا كان سهم أمريكي معروف أو ETF صريح
    if sym in US_STOCKS_AND_ETFS:
        bars = _fetch_yfinance_ohlcv(sym, timeframe)
        if bars:
            return sym, bars, "stock"

    # 3. محاولة البحث في العملات الرقمية عبر BingX
    base = sym.split(":")[0].split("/")[0]
    if base.endswith("USDT") and len(base) > 4:
        base = base[:-4]

    crypto_candidates = [f"{base}/USDT:USDT", f"{base}/USDT"]
    for c_sym in crypto_candidates:
        try:
            bars = ex_call(
                bingx.fetch_ohlcv,
                c_sym,
                timeframe=timeframe,
                limit=limit,
            )
            if bars and len(bars) > 10:
                return c_sym, bars, "crypto"
        except Exception:
            pass
        time.sleep(0.05)

    # 4. إذا لم يوجد في الكريبتو، نحاول كسهم أمريكي أو ETF (مثل SOXS, NIO, PLTR, etc.)
    bars = _fetch_yfinance_ohlcv(sym, timeframe)
    if bars:
        return sym, bars, "stock"

    return None, None, "unknown"


def tg_send(message, chat_id=None):
    target = chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not target:
        return False
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": target,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        return response.ok
    except Exception as exc:
        logger.error("Telegram send error: %s", exc)
        return False


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
        if value <= 0: return "N/A"
        return f"{value:.{decimals}f}"
    except Exception:
        return "N/A"


def analyze_symbol(symbol_raw, chat_id=None, manual=False):
    try:
        resolved, candles_daily, asset_type = fetch_ohlcv(symbol_raw, "1d", 80)
        if not resolved or not candles_daily or len(candles_daily) < 40:
            if manual:
                tg_send(f"❌ الأصل <code>{symbol_raw}</code> غير متوفر أو بياناته اليومية غير كافية.", chat_id)
            return False, None

        _, candles4h, _ = fetch_ohlcv(symbol_raw, "4h", 60)
        if not candles4h or len(candles4h) < 35:
            if manual:
                tg_send(f"❌ <code>{resolved}</code>\nبيانات 4H غير كافية.", chat_id)
            return False, None

        _, candles1h, _ = fetch_ohlcv(symbol_raw, "1h", 60)
        if not candles1h or len(candles1h) < 30:
            if manual:
                tg_send(f"❌ <code>{resolved}</code>\nبيانات 1H غير كافية.", chat_id)
            return False, None

        scan_stats["scanned_pairs"] += 1

        direction, price, signal = engine.analyze_market_structure(
            candles_daily, candles4h, candles1h, asset_type=asset_type
        )

        market_labels = {
            "crypto": "🪙 عملات رقمية (Crypto)",
            "stock": "📈 أسهم أمريكية / ETF",
            "forex": "💱 فوركس / معادن",
        }
        market_tag = market_labels.get(asset_type, "📊 سوق مالي")

        if direction == "LONG":
            sym_key = resolved.split("/")[0]
            if not manual:
                last_sent = _sent_signals_cache.get(sym_key, 0)
                if time.time() - last_sent < SIGNAL_COOLDOWN_SECONDS:
                    return False, signal

            _sent_signals_cache[sym_key] = time.time()
            d = decimals_for(price)
            entry_low = signal.get("entry_low", 0)
            entry_high = signal.get("entry_high", 0)
            stop_loss = signal.get("stop_loss", 0)
            tps = signal.get("take_profits", [])
            while len(tps) < 3:
                tps.append(0)

            score = int(signal.get("score", 0))
            rsi = float(signal.get("rsi", 50))
            details = signal.get("details", {}) or {}
            quality = details.get("quality", "B")
            position_in_range = float(details.get("position_in_range", 0))
            roc_5bar = float(details.get("roc_5bar", 0))

            _, momentum_msg = engine.check_momentum_at_tp1(candles1h)

            msg = (
                "🚀 <b>MY EXPERT MULTI-MARKET BOT V123.8</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"🏷️ <b>التصنيف:</b> {market_tag}\n"
                "🟢 <b>LONG — Early Accumulation (تجميع مبكر Fibo)</b>\n\n"
                f"💎 <b>الأصل/الرمز:</b> <code>{resolved}</code>\n"
                f"⭐ <b>التقييم:</b> <code>{score}/100</code> ({quality})\n\n"
                "📍 <b>منطقة الدخول المبكر:</b>\n"
                f"<code>{format_num(entry_low, d)} — {format_num(entry_high, d)}</code>\n\n"
                "🎯 <b>الأهداف:</b>\n"
                f"🥇 TP1: <code>{format_num(tps[0], d)}</code>\n"
                f"🥈 TP2: <code>{format_num(tps[1], d)}</code>\n"
                f"🥉 TP3: <code>{format_num(tps[2], d)}</code>\n\n"
                "🔴 <b>وقف الخسارة:</b>\n"
                f"<code>{format_num(stop_loss, d)}</code>\n\n"
                f"📊 <b>RSI 1H:</b> <code>{rsi:.1f}</code>\n"
                f"📍 <b>موقع السعر بالنطاق:</b> <code>{position_in_range * 100:.1f}%</code>\n"
                f"📈 <b>معدل التغير:</b> <code>{roc_5bar:+.2f}%</code>\n\n"
                f"🎯 <b>متابعة الزخم عند الهدف الأول (TP1):</b>\n{momentum_msg}\n\n"
                "⚠️ <b>إشارة تحليلية فقط.</b>"
            )
            sent = tg_send(msg, chat_id)
            if sent:
                scan_stats["signals_sent"] += 1
            return True, signal

        if manual:
            reason = signal.get("reason", "الشروط غير مكتملة") if signal else "الشروط غير مكتملة"
            msg = (
                f"📊 <b>تحليل الأصل:</b> <code>{resolved}</code>\n"
                f"🏷️ <b>السوق:</b> {market_tag}\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "⚪ <b>لا توجد صفقة LONG مكتملة حالياً.</b>\n"
                f"🔎 <b>السبب:</b>\n{reason}"
            )
            tg_send(msg, chat_id)
            return False, signal

    except Exception as exc:
        scan_stats["errors"] += 1
        logger.exception("analyze_symbol error: %s", exc)
        if manual:
            tg_send(f"❌ حدث خطأ أثناء تحليل <code>{symbol_raw}</code>.", chat_id)
        return False, None


def run_full_scan(chat_id=None):
    if not scan_lock.acquire(blocking=False):
        if chat_id:
            tg_send("⏳ يوجد فحص شامل قيد التشغيل حاليًا.", chat_id)
        return
    try:
        if chat_id:
            tg_send(
                "🔍 <b>جارٍ مسح جميع الأسواق (العملات الرقمية + الأسهم الأمريكية ETFs + الفوركس والذهب)...</b>",
                chat_id,
            )
        symbols = get_full_market_universe()
        found = 0
        for sym in symbols:
            try:
                ok, _ = analyze_symbol(sym, chat_id=None, manual=False)
                if ok:
                    found += 1
            except Exception:
                pass
            time.sleep(0.15)

        if chat_id:
            tg_send(
                "✅ <b>انتهى الفحص الشامل لجميع الأسواق بنجاح.</b>\n\n"
                f"🔎 الأصول المفحوصة (عملات + أسهم + فوركس): <code>{len(symbols)}</code>\n"
                f"🟢 الفرص المكتشفة: <code>{found}</code>",
                chat_id,
            )
    except Exception as exc:
        scan_stats["errors"] += 1
        logger.exception("Full Scan error: %s", exc)
    finally:
        scan_lock.release()


def background_auto_scheduler():
    time.sleep(20)
    while True:
        try:
            if TELEGRAM_CHAT_ID:
                run_full_scan(chat_id=None)
        except Exception as exc:
            logger.exception("Background scheduler error: %s", exc)
        time.sleep(14400)


HELP_TEXT = (
    "🤖 <b>MY EXPERT MULTI-MARKET BOT V123.8</b>\n"
    "━━━━━━━━━━━━━━━━━━\n\n"
    "🧭 <b>الأسواق المدعومة بالكامل:</b>\n"
    "• 🪙 العملات الرقمية (BTC, ETH, SOL...)\n"
    "• 📈 الأسهم وصناديق الـ ETF الأمريكية (SOXS, SPY, NVDA, TSLA...)\n"
    "• 💱 الفوركس والمعادن (XAUUSD, EURUSD, GBPUSD...)\n\n"
    "📌 أرسل رمز أي سهم أو عملة أو زوج مباشرة مثل:\n"
    "<code>SOXS</code>\n"
    "<code>BTC</code>\n"
    "<code>XAUUSD</code>\n\n"
    "🔍 <code>/scan</code> لفحص جميع الأسواق دفعة واحدة."
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
            analyze_symbol(parts[0], chat_id=chat_id, manual=True)
    except Exception as exc:
        logger.exception("handle_update error: %s", exc)


@app.route("/")
def index():
    return jsonify(
        {
            "status": "running",
            "version": "V123.8",
            "markets": "Crypto + US Stocks/ETFs + Forex + Metals",
            "stats": scan_stats,
        }
    )


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
        if uid is not None:
            _seen_updates.append(uid)
    threading.Thread(target=handle_update, args=(data,), daemon=True).start()
    return "OK", 200


def bootstrap():
    db_init()
    logger.info("Bot V123.8 bootstrapped (Crypto + Stocks/ETFs + Forex + Gold).")
    threading.Thread(target=background_auto_scheduler, daemon=True).start()


bootstrap()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), threaded=True)
