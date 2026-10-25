# ==========================================
# MY EXPERT CRYPTO BOT - MTF VOLUME PROFILE & PoC (V17.3)
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
    return "MY EXPERT CRYPTO BOT V17.3 Active!"

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
        f"💎 *صفقة قناص نخبويّة - توافق الفريمات الأربعة مع PoC* 💎\n\n"
        f"🔹 العملة: `{symbol}`\n"
        f"⚖️ الاتجاه: `🟢 LONG`\n"
        f"💵 سعر الدخول: `{entry_price}`\n"
        f"⭐️ درجة الجودة: `{details.get('score')}/100`\n\n"
        f"🟥 وقف الخسارة (SL): `{details.get('stop_loss')}`\n"
        f"🟩 الهدف الأول (TP1): `{rm.get('take_profit_1')}`\n"
        f"🟩 الهدف الثاني (TP2): `{rm.get('take_profit_2')}`\n"
        f"🎯 الهدف الرئيسي (TP3 - R:R 1:2.5): `{rm.get('take_profit_3')}`\n\n"
        f"ℹ️ *التفاصيل الهيكلية:* {details.get('smc_note')}"
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
        if quote_volume < 3000000:
            return

        ohlcv_15m = bingx_call("fetch_ohlcv", symbol, timeframe="15m", limit=30)
        ohlcv_1h = bingx_call("fetch_ohlcv", symbol, timeframe="1h", limit=30)
        ohlcv_4h = bingx_call("fetch_ohlcv", symbol, timeframe="4h", limit=30)
        ohlcv_1d = bingx_call("fetch_ohlcv", symbol, timeframe="1d", limit=25)

        if not (ohlcv_15m and ohlcv_1h and ohlcv_4h and ohlcv_1d):
            return

        direction, entry_price, details = engine.analyze_market_structure(
            ohlcv_15m=ohlcv_15m, ohlcv_1h=ohlcv_1h, ohlcv_4h=ohlcv_4h, ohlcv_1d=ohlcv_1d
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
        "💎 *تم تشغيل بوت قناص الفريمات الأربعة (V17.3)*\n"
        "يمكنك إرسال اسم أي عملة هنا (مثل SKAI أو ARB) للتحليل الفوري!"
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

def check_telegram_updates():
    offset = 0
    engine = StrategyEngine(capital=BOT_CAPITAL_USD, risk_per_trade=RISK_PER_TRADE)
    
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates?offset={offset}&timeout=30"
            response = requests.get(url, timeout=35)
            if response.status_code != 200:
                time.sleep(5)
                continue
            
            data = response.json()
            for result in data.get("result", []):
                offset = result["update_id"] + 1
                message = result.get("message", {})
                text = message.get("text", "").strip().upper()
                chat_id = message.get("chat", {}).get("id")
                
                if not text or str(chat_id) != str(TELEGRAM_CHAT_ID):
                    continue
                
                if text.startswith("/"):
                    continue
                
                base_coin = text.replace("/USDT", "").replace("USDT", "").strip()
                send_telegram_message(f"🔍 جاري البحث عن عملة `{base_coin}` وفحصها...")
                
                # البحث الذكي في الأسواق المتاحة بالمنصة عن الرمز المطابق
                all_symbols = get_all_usdt_symbols()
                target_symbol = None
                for s in all_symbols:
                    if s.split('/')[0].upper() == base_coin:
                        target_symbol = s
                        break
                
                if not target_symbol:
                    # محاولة احتياطية مباشرة
                    target_symbol = f"{base_coin}/USDT:USDT"

                ohlcv_15m = bingx_call("fetch_ohlcv", target_symbol, timeframe="15m", limit=30)
                ohlcv_1h = bingx_call("fetch_ohlcv", target_symbol, timeframe="1h", limit=30)
                ohlcv_4h = bingx_call("fetch_ohlcv", target_symbol, timeframe="4h", limit=30)
                ohlcv_1d = bingx_call("fetch_ohlcv", target_symbol, timeframe="1d", limit=25)
                
                if not (ohlcv_15m and ohlcv_1h and ohlcv_4h and ohlcv_1d):
                    send_telegram_message(f"❌ تعذر جلب بيانات الفريمات لعملة `{base_coin}`. تأكد أن الرمز مدرج في عقود Swap بنجاح.")
                    continue
                
                direction, entry_price, details = engine.analyze_market_structure(
                    ohlcv_15m=ohlcv_15m, ohlcv_1h=ohlcv_1h, ohlcv_4h=ohlcv_4h, ohlcv_1d=ohlcv_1d
                )
                
                current_price = float(ohlcv_15m[-1, 4])
                
                if direction == "LONG":
                    rm = details.get("risk_management", {})
                    reply_msg = (
                        f"✅ **العملة جاهزة للونج حالياً!**\n\n"
                        f"🔹 العملة: `{target_symbol}`\n"
                        f"💵 السعر الحالي: `{current_price}`\n"
                        f"⭐️ تقييم الفرصة: `{details.get('score')}/100`\n\n"
                        f"🟥 وقف الخسارة: `{details.get('stop_loss')}`\n"
                        f"🟩 الهدف الأول: `{rm.get('take_profit_1')}`\n"
                        f"🎯 الهدف الرئيسي: `{rm.get('take_profit_3')}`\n\n"
                        f"ℹ️ {details.get('smc_note')}"
                    )
                else:
                    reason = details.get("reason", "الشروط غير مكتملة")
                    reply_msg = (
                        f"⏳ **العملة غير جاهزة للونج بالكامل حالياً**\n\n"
                        f"🔹 العملة: `{target_symbol}`\n"
                        f"💵 السعر الحالي: `{current_price}`\n"
                        f"⚠️ **السبب الفني:** `{reason}`\n\n"
                        f"💡 **نصيحة قناص:** انتظر اختراق مقاومة قريبة أو تكون فوليوم إيجابي على فريم 15 دقيقة للدخول بأمان."
                    )
                
                send_telegram_message(reply_msg)
                
        except Exception as e:
            logger.error(f"Telegram listener error: {e}")
            time.sleep(10)

scanner_thread = threading.Thread(target=background_scanner, daemon=True, name="mtf-poc-scanner")
scanner_thread.start()

telegram_listener_thread = threading.Thread(target=check_telegram_updates, daemon=True, name="telegram-listener")
telegram_listener_thread.start()

if __name__ == "__main__":
    port = int(os.environ.com.get("PORT", "5000") if hasattr(os.environ, "com") else os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=False)
