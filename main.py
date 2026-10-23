# ============================================================
# MY EXPERT CRYPTO BOT - MAIN V18.0 (OPTIMIZED & SECURE)
# BingX Futures + Telegram + Render; compatible with analysis.py V18.0
# ============================================================
import os
import time
import threading
import logging
import requests
import ccxt
from flask import Flask, jsonify
from analysis import StrategyEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("MainBot")
app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
SIGNAL_COOLDOWN_SECONDS = max(60, int(os.environ.get("SIGNAL_COOLDOWN_SECONDS", "3600")))
API_MIN_INTERVAL_SECONDS = max(0.40, float(os.environ.get("API_MIN_INTERVAL_SECONDS", "0.50"))) # زيادة الفاصل لحماية الـ API
SYMBOL_PAUSE_SECONDS = max(0.15, float(os.environ.get("SYMBOL_PAUSE_SECONDS", "0.25"))) # مهلة أمان بين العملات لتفادي خطأ 100410
MAX_API_RETRIES = max(0, min(3, int(os.environ.get("MAX_API_RETRIES", "2"))))
BOT_CAPITAL_USD = max(1.0, float(os.environ.get("BOT_CAPITAL_USD", "1000")))
RISK_PER_TRADE = min(0.02, max(0.001, float(os.environ.get("RISK_PER_TRADE", "0.01"))))
MIN_QUOTE_VOLUME_USD = max(5000000.0, float(os.environ.get("MIN_QUOTE_VOLUME_USD", "5000000"))) # رفع الحد الأدنى للسيولة لمنع العملات الوهمية

signal_history = {}
scan_stats = {"scanned_pairs": 0, "signals_sent": 0, "api_errors": 0}
history_lock = threading.Lock()
api_lock = threading.Lock()
_last_api_request = 0.0
bingx = ccxt.bingx({"enableRateLimit": True, "timeout": 20000, "options": {"defaultType": "swap"}})


@app.route("/")
def home():
    return "MY EXPERT CRYPTO BOT V18.0 (ICT/SMC LONG+SHORT - Anti-Fake & Optimized) Active!"


@app.route("/health")
def health():
    return jsonify({"status": "healthy", "version": "18.0", "stats": dict(scan_stats)}), 200


def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram credentials missing; message not sent.")
        return False
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message,
                  "parse_mode": "Markdown", "disable_web_page_preview": True},
            timeout=15
        )
        if response.status_code != 200:
            logger.error("Telegram HTTP %s: %s", response.status_code, response.text[:300])
        return response.status_code == 200
    except Exception as exc:
        logger.error("Telegram error: %s", exc)
        return False


def bingx_call(method_name, *args, **kwargs):
    global _last_api_request
    method = getattr(bingx, method_name)
    for attempt in range(MAX_API_RETRIES + 1):
        with api_lock:
            wait_for = max(0.0, API_MIN_INTERVAL_SECONDS - (time.monotonic() - _last_api_request))
            if wait_for:
                time.sleep(wait_for)
            _last_api_request = time.monotonic()
        try:
            return method(*args, **kwargs)
        except Exception as exc:
            logger.warning("BingX %s attempt %s failed: %s", method_name, attempt + 1, exc)
            if attempt >= MAX_API_RETRIES:
                with history_lock:
                    scan_stats["api_errors"] += 1
                return None
            time.sleep(1.2 * (attempt + 1))
    return None


def get_all_usdt_symbols():
    markets = bingx_call("load_markets")
    if not markets:
        return []
    symbols = []
    for symbol, market in markets.items():
        if not (
            market.get("linear") and market.get("quote") == "USDT"
            and market.get("active", True) and market.get("swap")
            and "/USDT:USDT" in symbol
        ):
            continue
        base = symbol.split("/")[0].upper()
        sym_upper = symbol.upper()
        
        # فلترة قاطعة وصارمة لاستبعاد العملات الوهمية، التجريبية، والرموز الهامشية
        if any(x in base for x in ("TEST", "DEMO", "FAKE", "USD2")) or any(x in sym_upper for x in ("UP/", "DOWN/", "BULL", "BEAR", "1000000")):
            continue
        if len(base) > 9:
            continue
        symbols.append(symbol)
    return sorted(set(symbols))


def _format_signal(symbol, direction, entry_price, details):
    rm = details.get("risk_management", {})
    is_long = direction == "LONG"
    arrow = "🟢 LONG" if is_long else "🔴 SHORT"
    fvg = details.get("fvg") or {}
    ob = details.get("order_block") or {}
    lines = [
        "💎 *MY EXPERT CRYPTO BOT — ICT/SMC V18.0*",
        "",
        f"🔹 العملة: `{symbol}`",
        f"⚖️ الاتجاه: `{arrow}`",
        f"💵 سعر الإغلاق المرجعي: `{entry_price}`",
        f"⭐️ تقييم الأدلة: `{details.get('score', 0)}/100`",
        f"🛑 وقف الخسارة: `{details.get('stop_loss')}`",
        f"🎯 TP1: `{rm.get('take_profit_1')}`",
        f"🎯 TP2: `{rm.get('take_profit_2')}`",
        f"🏁 TP3: `{rm.get('take_profit_3')}` (R:R 1:2.5)",
        f"📊 حجم 15M: `{details.get('volume_ratio', 0)}x`",
        f"💧 سحب سيولة: `{'YES' if details.get('liquidity_sweep') else 'NO'}`",
        f"🧱 FVG: `{fvg.get('type', 'غير موجود')}`",
        f"🏛️ Order Block: `{ob.get('type', 'غير موجود')}`",
        f"₿ اتجاه BTC: `{details.get('btc_bias', 'UNAVAILABLE')}`",
        "",
        f"ℹ️ {details.get('smc_note', '')}",
        "",
        "⚠️ إشارة تحليلية وليست ضمانًا للربح. تحقق من مواصفات العقد والرسوم قبل التنفيذ."
    ]
    return "\n".join(lines)


def notify_trade_executed(symbol, direction, entry_price, details):
    return send_telegram_message(_format_signal(symbol, direction, entry_price, details))


def process_symbol(symbol, engine):
    now = time.time()
    with history_lock:
        if now - signal_history.get(symbol, 0) < SIGNAL_COOLDOWN_SECONDS:
            return
    try:
        # 1. فحص التيستر وحجم التداول الحقيقي أولاً لمنع العملات الوهمية
        ticker = bingx_call("fetch_ticker", symbol)
        if not ticker:
            return
        quote_volume = ticker.get("quoteVolume")
        if quote_volume is None:
            base_volume = float(ticker.get("baseVolume") or 0)
            last = float(ticker.get("last") or 0)
            quote_volume = base_volume * last
        
        # استبعاد العملات التي تقل سيولتها عن الحد الأدنى الصارم (5 مليون $)
        if float(quote_volume or 0) < MIN_QUOTE_VOLUME_USD:
            return

        # 2. جلب الشموع فقط للعملات الحقيقية التي اجتازت شرط السيولة
        data = {}
        for tf, limit in (("15m", 50), ("1h", 50), ("4h", 50), ("1d", 40)):
            candles = bingx_call("fetch_ohlcv", symbol, timeframe=tf, limit=limit)
            if not candles or len(candles) < 25:
                return
            data[tf] = candles

        btc_data = bingx_call("fetch_ohlcv", "BTC/USDT:USDT", timeframe="1h", limit=50)
        direction, entry_price, details = engine.analyze_market_structure(
            ohlcv_15m=data["15m"],
            ohlcv_1h=data["1h"],
            ohlcv_4h=data["4h"],
            ohlcv_1d=data["1d"],
            ohlcv_btc_1h=btc_data
        )
        with history_lock:
            scan_stats["scanned_pairs"] += 1
        if direction not in ("LONG", "SHORT"):
            return
        sent = notify_trade_executed(symbol, direction, entry_price, details)
        if sent:
            with history_lock:
                scan_stats["signals_sent"] += 1
                signal_history[symbol] = time.time()
    except Exception:
        logger.exception("Error processing %s", symbol)


def background_scanner():
    time.sleep(5)
    send_telegram_message(
        "🚀 *تم تشغيل MY EXPERT CRYPTO BOT V18.0 بنجاح*\n"
        "تم تفعيل الفلترة الصارمة للسيولة (5 مليون $+$) ومنع العملات الوهمية وحماية خوادم الـ API."
    )
    engine = StrategyEngine(capital=BOT_CAPITAL_USD, risk_per_trade=RISK_PER_TRADE)
    while True:
        try:
            symbols = get_all_usdt_symbols()
            if not symbols:
                logger.warning("No eligible BingX USDT perpetual symbols found.")
                time.sleep(30)
                continue
            logger.info("Starting clean scan of %s validated symbols", len(symbols))
            for symbol in symbols:
                process_symbol(symbol, engine)
                time.sleep(SYMBOL_PAUSE_SECONDS)
            time.sleep(120) # فترة استراحة أطول بين الدورات لراحة الخوادم وتففريغ الـ Rate Limit
        except Exception:
            logger.exception("Scanner loop error")
            time.sleep(30)


scanner_thread = threading.Thread(target=background_scanner, daemon=True, name="mtf-scanner")
scanner_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
