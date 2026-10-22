# ==========================================
# MY EXPERT CRYPTO BOT - CRT + TBS MAIN ENGINE (V13.0)
# Features: Clean Market Filtering & High Probability CRT + TBS Signals
# ==========================================
import os
import time
import threading
import logging
import requests
import ccxt
from flask import Flask, jsonify
from analysis import StrategyEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("MainBot")

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
SIGNAL_COOLDOWN_SECONDS = max(60, int(os.environ.get("SIGNAL_COOLDOWN_SECONDS", "1800")))
API_MIN_INTERVAL_SECONDS = max(0.25, float(os.environ.get("API_MIN_INTERVAL_SECONDS", "0.35")))
SYMBOL_PAUSE_SECONDS = max(0.05, float(os.environ.get("SYMBOL_PAUSE_SECONDS", "0.10")))
MAX_API_RETRIES = max(0, min(3, int(os.environ.get("MAX_API_RETRIES", "2"))))

BOT_CAPITAL_USD = max(1.0, float(os.environ.get("BOT_CAPITAL_USD", "1000")))
RISK_PER_TRADE = min(0.05, max(0.001, float(os.environ.get("RISK_PER_TRADE", "0.01"))))
DEBUG_MODE = os.environ.get("DEBUG_MODE", "false").lower() == "true"

signal_history = {}
active_trades = {}
scan_stats = {
    "scanned_pairs": 0,
    "fetch_failures": 0,
    "signals_sent": 0
}

history_lock = threading.Lock()
api_lock = threading.Lock()
_last_api_request = 0.0

bingx = ccxt.bingx({
    "enableRateLimit": True,
    "timeout": 20000,
    "options": {"defaultType": "swap"}
})

@app.route("/")
def home():
    return f"MY EXPERT CRYPTO BOT V13.0 (CRT + TBS High Probability Engine) Active!"

@app.route("/health")
def health():
    return jsonify({"status": "healthy", "stats": scan_stats}), 200


def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True
            },
            timeout=15
        )
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Telegram error: {e}")
        return False


def bingx_call(method_name, *args, **kwargs):
    global _last_api_request
    method = getattr(bingx, method_name)
    for attempt in range(MAX_API_RETRIES + 1):
        with api_lock:
            now = time.monotonic()
            wait_for = max(0.0, API_MIN_INTERVAL_SECONDS - (now - _last_api_request))
            if wait_for > 0:
                time.sleep(wait_for)
            _last_api_request = time.monotonic()
        try:
            return method(*args, **kwargs)
        except Exception:
            if attempt >= MAX_API_RETRIES:
                return None
            time.sleep(1.0)
    return None


def get_all_usdt_symbols():
    try:
        markets = bingx_call("load_markets")
        if not markets:
            return []
        symbols = []
        for symbol, market in markets.items():
            if (
                market.get("linear", False)
                and market.get("quote") == "USDT"
                and market.get("active", True)
                and "/USDT:USDT" in symbol
                and market.get("swap", True)
            ):
                base_asset = symbol.split('/')[0].upper()
                sym_upper = symbol.upper()
                if any(x in sym_upper for x in ["TEST", "UP/", "DOWN/", "BULL", "BEAR", "USD2"]):
                    continue
                if len(base_asset) > 9:
                    continue
                symbols.append(symbol)
        return sorted(set(symbols))
    except Exception as e:
        logger.error(f"Error loading markets: {e}")
        return []


def notify_trade_executed(symbol, direction, entry_price, details):
    rm = details.get("risk_management", {})
    message = (
        f"🎯 *إشارة CRT + TBS عالية الدقة (High Probability)* 🎯\n\n"
        f"🔹 العملة: `{symbol}`\n"
        f"⚖️ الاتجاه: `🟢 LONG (شراء - Turtle Soup)`\n"
        f"💵 سعر الدخول: `{entry_price}`\n"
        f"📍 القاع المرجعي (CRT Low): `{details.get('neckline')}`\n"
        f"⭐️ درجة التقييم الصارمة: `{details.get('score')}/100`\n\n"
        f"🟥 وقف الخسارة (SL): `{details.get('stop_loss')}`\n"
        f"🟩 الهدف الأول (TP1): `{rm.get('take_profit_1')}`\n"
        f"🟩 الهدف الثاني (TP2): `{rm.get('take_profit_2')}`\n"
        f"🎯 الهدف الرئيسي (CRT High): `{rm.get('take_profit_3')}`\n\n"
        f"ℹ️ *ملاحظة الاستراتيجية:* {details.get('smc_note')}"
    )
    return send_telegram_message(message)


def process_symbol(symbol, engine, btc_ohlcv_1h):
    try:
        now = time.time()
        with history_lock:
            if now - signal_history.get(symbol, 0) < SIGNAL_COOLDOWN_SECONDS:
                return

        ticker = bingx_call("fetch_ticker", symbol)
        if not ticker:
            return

        quote_volume = float(ticker.get("quoteVolume") or ticker.get("baseVolume") or 0)
        if quote_volume < 800000: # تصفية سيولة عالية جداً لضمان جودة الصفقات
            return

        ohlcv_15m = bingx_call("fetch_ohlcv", symbol, timeframe="15m", limit=45)
        if not ohlcv_15m:
            return

        direction, entry_price, details = engine.analyze_market_structure(ohlcv_15m)
        scan_stats["scanned_pairs"] += 1

        if direction == "NEUTRAL":
            return

        sent = notify_trade_executed(symbol, direction, entry_price, details)
        if sent:
            scan_stats["signals_sent"] += 1
            with history_lock:
                signal_history[symbol] = time.time()

    except Exception as exc:
        logger.error(f"Error processing {symbol}: {exc}")


def background_scanner():
    time.sleep(5)
    send_telegram_message(
        "🚀 *تم تشغيل محرك CRT + TBS الصارم (V13.0)*\n"
        "الاستراتيجية تعمل الآن بفلترة صفقات القمة فقط (High Probability Setups)."
    )
    engine = StrategyEngine(capital=BOT_CAPITAL_USD, risk_per_trade=RISK_PER_TRADE)

    while True:
        try:
            symbols = get_all_usdt_symbols()
            if not symbols:
                time.sleep(30)
                continue

            btc_ohlcv = bingx_call("fetch_ohlcv", "BTC/USDT:USDT", timeframe="1h", limit=25)

            for symbol in symbols:
                process_symbol(symbol, engine, btc_ohlcv)
                time.sleep(SYMBOL_PAUSE_SECONDS)

            time.sleep(60)
        except Exception as exc:
            logger.error(f"Scanner Loop Error: {exc}")
            time.sleep(30)


scanner_thread = threading.Thread(target=background_scanner, daemon=True, name="crt-scanner")
scanner_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
