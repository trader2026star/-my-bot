# ==========================================
# MY EXPERT CRYPTO BOT - VOLUME PROFILE & PoC ENGINE (V16.0)
# Main Bot Controller
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
SIGNAL_COOLDOWN_SECONDS = max(60, int(os.environ.get("SIGNAL_COOLDOWN_SECONDS", "3600")))
API_MIN_INTERVAL_SECONDS = max(0.25, float(os.environ.get("API_MIN_INTERVAL_SECONDS", "0.35")))
SYMBOL_PAUSE_SECONDS = max(0.05, float(os.environ.get("SYMBOL_PAUSE_SECONDS", "0.10")))
MAX_API_RETRIES = max(0, min(3, int(os.environ.get("MAX_API_RETRIES", "2"))))

BOT_CAPITAL_USD = max(1.0, float(os.environ.get("BOT_CAPITAL_USD", "1000")))
RISK_PER_TRADE = min(0.05, max(0.001, float(os.environ.get("RISK_PER_TRADE", "0.01"))))

signal_history = {}
scan_stats = {"scanned_pairs": 0, "signals_sent": 0}

history_lock = threading.Lock()
api_lock = threading.Lock()
_last_api_request = 0.0

bingx = ccxt.bingx({"enableRateLimit": True, "timeout": 20000, "options": {"defaultType": "swap"}})

@app.route("/")
def home():
    return "MY EXPERT CRYPTO BOT V16.0 (Volume Profile & PoC Strategy) Active!"

@app.route("/health")
def health():
    return jsonify({"status": "healthy", "stats": scan_stats}), 200

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown", "disable_web_page_preview": True},
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
                if any(x in symbol.upper() for x in ["TEST", "UP/", "DOWN/", "BULL", "BEAR"]):
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
        f"💎 *إشارة نخبويّة - استراتيجية ملف الحجم و PoC* 💎\n\n"
        f"🔹 العملة: `{symbol}`\n"
        f"⚖️ الاتجاه: `🟢 LONG`\n"
        f"💵 سعر الدخول: `{entry_price}`\n"
        f"⭐️ درجة الجودة الممتازة: `{details.get('score')}/100`\n\n"
        f"🟥 وقف الخسارة (SL): `{details.get('stop_loss')}`\n"
        f"🟩 الهدف الأول (TP1): `{rm.get('take_profit_1')}`\n"
        f"🟩 الهدف الثاني (TP2): `{rm.get('take_profit_2')}`\n"
        f"🎯 الهدف الرئيسي (TP3 - R:R 1:2.5): `{rm.get('take_profit_3')}`\n\n"
        f"ℹ️ *تفاصيل المستويات:* {details.get('smc_note')}"
    )
    return send_telegram_message(message)

def process_symbol(symbol, engine):
    try:
        now = time.time()
        with history_lock:
            if now - signal_history.get(symbol, 0) < SIGNAL_COOLDOWN_SECONDS:
                return

        ticker = bingx_call("fetch_ticker", symbol)
        if not ticker:
            return

        quote_volume = float(ticker.get("quoteVolume") or ticker.get("baseVolume") or 0)
        if quote_volume < 3000000: # تصفية السيولة العالية لضمان قوة العملات المحددة
            return

        # جلب بيانات الشموع اللازمة لحساب ملف الحجم (Volume Profile)
        ohlcv_15m = bingx_call("fetch_ohlcv", symbol, timeframe="15m", limit=50)
        ohlcv_1h = bingx_call("fetch_ohlcv", symbol, timeframe="1h", limit=50)

        if not (ohlcv_15m and ohlcv_1h):
            return

        direction, entry_price, details = engine.analyze_market_structure(
            ohlcv_15m=ohlcv_15m, ohlcv_1h=ohlcv_1h
        )
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
        "💎 *تم تشغيل بوت استراتيجية ملف الحجم و PoC (V16.0)*\n"
        "البوت يراقب السوق الآن ويرسل الصفقات عند ارتداد السعر من نقطة التحكم بدقة عالية."
    )
    engine = StrategyEngine(capital=BOT_CAPITAL_USD, risk_per_trade=RISK_PER_TRADE)

    while True:
        try:
            symbols = get_all_usdt_symbols()
            if not symbols:
                time.sleep(30)
                continue

            for symbol in symbols:
                process_symbol(symbol, engine)
                time.sleep(SYMBOL_PAUSE_SECONDS)

            time.sleep(60)
        except Exception as exc:
            logger.error(f"Scanner Loop Error: {exc}")
            time.sleep(30)

scanner_thread = threading.Thread(target=background_scanner, daemon=True, name="volume-profile-scanner")
scanner_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
