# ==========================================
# MY EXPERT CRYPTO BOT - Main Controller (SMC Edition)
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

BOT_CAPITAL_USD = max(1.0, float(os.environ.get("BOT_CAPITAL_USD", "10000")))
RISK_PER_TRADE = min(0.05, max(0.001, float(os.environ.get("RISK_PER_TRADE", "0.01"))))

signal_history = {}
scan_stats = {"scanned_pairs": 0, "signals_sent": 0}

history_lock = threading.Lock()
api_lock = threading.Lock()
_last_api_request = 0.0

bingx = ccxt.bingx({"enableRateLimit": True, "timeout": 20000, "options": {"defaultType": "swap"}})

@app.route("/")
def home():
    return "MY EXPERT CRYPTO BOT (SMC Edition) Active!"

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
                if len(base_asset) > 12:
                    continue
                symbols.append(symbol)
        return sorted(set(symbols))
    except Exception as e:
        logger.error(f"Error loading markets: {e}")
        return []

def background_scanner():
    time.sleep(5)
    send_telegram_message(
        "🏛️ *تم تشغيل بوت الصفقات المؤسسية (نسخة SMC & Order Blocks)*\n"
        "البوت يراقَب مناطق السيولة، الـ Order Blocks، وفجوات القيمة العادلة (FVG) بدقة!"
    )
    engine = StrategyEngine(capital=BOT_CAPITAL_USD, risk_per_trade=RISK_PER_TRADE)

    while True:
        try:
            symbols = get_all_usdt_symbols()
            if not symbols:
                time.sleep(30)
                continue

            btc_ohlcv_1d = bingx_call("fetch_ohlcv", "BTC/USDT:USDT", timeframe="1d", limit=25)

            for symbol in symbols:
                if symbol == "BTC/USDT:USDT":
                    continue
                
                now = time.time()
                with history_lock:
                    if now - signal_history.get(symbol, 0) < SIGNAL_COOLDOWN_SECONDS:
                        continue

                ticker = bingx_call("fetch_ticker", symbol)
                if not ticker:
                    continue

                quote_volume = float(ticker.get("quoteVolume") or ticker.get("baseVolume") or 0)
                if quote_volume < 4000000:
                    continue

                ohlcv_15m = bingx_call("fetch_ohlcv", symbol, timeframe="15m", limit=30)
                ohlcv_1h = bingx_call("fetch_ohlcv", symbol, timeframe="1h", limit=30)
                ohlcv_4h = bingx_call("fetch_ohlcv", symbol, timeframe="4h", limit=30)
                ohlcv_1d = bingx_call("fetch_ohlcv", symbol, timeframe="1d", limit=25)

                if not (ohlcv_15m and ohlcv_1h and ohlcv_4h and ohlcv_1d):
                    continue

                direction, entry_price, details = engine.analyze_market_structure(
                    ohlcv_15m=ohlcv_15m, ohlcv_1h=ohlcv_1h, ohlcv_4h=ohlcv_4h, ohlcv_1d=ohlcv_1d, btc_ohlcv_1d=btc_ohlcv_1d
                )
                scan_stats["scanned_pairs"] += 1

                if direction in ["LONG", "SHORT"] and details.get("trade_valid", False):
                    rm = details.get("risk_management", {})
                    ps = details.get("position_sizing", {})
                    icon = "🟢" if direction == "LONG" else "🔴"
                    
                    message = (
                        f"🏛️ *فرصة SMC مؤسسية جديدة ({direction})* {icon}\n\n"
                        f"🔹 العملة: `{symbol}`\n"
                        f"⚖️ الاتجاه: `{direction}`\n"
                        f"💵 سعر الدخول (منطقة OB): `{entry_price}`\n"
                        f"🟥 وقف الخسارة المحمي: `{details.get('stop_loss')}`\n\n"
                        f"📊 *إدارة رأس المال والعقد:* \n"
                        f"• حجم العقد: `{ps.get('units')}` وحدة\n"
                        f"• القيمة بالدولار: `${ps.get('margin_usd')}`\n"
                        f"• المخاطرة المستهدفة: `${ps.get('risk_amount_usd')}`\n\n"
                        f"🟩 **الأهداف ومتابعة الصفقة:**\n"
                        f"• TP1: `{rm.get('take_profit_1')}` (نقل الوقف للتعادل)\n"
                        f"• TP2: `{rm.get('take_profit_2')}`\n"
                        f"• TP3: `{rm.get('take_profit_3')}`\n\n"
                        f"💡 *ملاحظة SMC:* `{details.get('smc_note')}`"
                    )
                    sent = send_telegram_message(message)
                    if sent:
                        scan_stats["signals_sent"] += 1
                        with history_lock:
                            signal_history[symbol] = time.time()
                time.sleep(SYMBOL_PAUSE_SECONDS)

            time.sleep(60)
        except Exception as exc:
            logger.error(f"Scanner Loop Error: {exc}")
            time.sleep(30)

def check_telegram_updates():
    last_update_id = 0
    engine = StrategyEngine(capital=BOT_CAPITAL_USD, risk_per_trade=RISK_PER_TRADE)
    
    try:
        init_resp = requests.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates?offset=-1", timeout=10)
        if init_resp.status_code == 200:
            res_list = init_resp.json().get("result", [])
            if res_list:
                last_update_id = res_list[-1]["update_id"]
    except:
        pass

    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates?offset={last_update_id + 1}&timeout=25"
            response = requests.get(url, timeout=30)
            if response.status_code != 200:
                time.sleep(3)
                continue
            
            data = response.json()
            for result in data.get("result", []):
                last_update_id = result["update_id"]
                message = result.get("message", {})
                text = message.get("text", "").strip()
                text_upper = text.upper()
                chat_id = message.get("chat", {}).get("id")
                
                if not text or str(chat_id) != str(TELEGRAM_CHAT_ID) or text.startswith("/"):
                    continue
                
                base_coin = text_upper.replace("/USDT", "").replace("USDT", "").strip()
                send_telegram_message(f"🔍 *جاري تحليل مناطق الـ SMC والسيولة لعملة `{base_coin}`...* ⏳")
                
                try:
                    all_symbols = get_all_usdt_symbols()
                    target_symbol = None
                    
                    for s in all_symbols:
                        s_base = s.split('/')[0].upper()
                        if s_base == base_coin:
                            target_symbol = s
                            break
                    
                    if not target_symbol:
                        target_symbol = f"{base_coin}/USDT:USDT"

                    btc_ohlcv_1d = bingx_call("fetch_ohlcv", "BTC/USDT:USDT", timeframe="1d", limit=25)
                    ohlcv_15m = bingx_call("fetch_ohlcv", target_symbol, timeframe="15m", limit=30)
                    ohlcv_1h = bingx_call("fetch_ohlcv", target_symbol, timeframe="1h", limit=30)
                    ohlcv_4h = bingx_call("fetch_ohlcv", target_symbol, timeframe="4h", limit=30)
                    ohlcv_1d = bingx_call("fetch_ohlcv", target_symbol, timeframe="1d", limit=25)
                    
                    if not (ohlcv_15m and ohlcv_1h and ohlcv_4h and ohlcv_1d):
                        send_telegram_message(f"❌ تعذر جلب بيانات الفريمات للعملة `{base_coin}`.")
                        continue
                    
                    direction, entry_price, details = engine.analyze_market_structure(
                        ohlcv_15m=ohlcv_15m, ohlcv_1h=ohlcv_1h, ohlcv_4h=ohlcv_4h, ohlcv_1d=ohlcv_1d, btc_ohlcv_1d=btc_ohlcv_1d
                    )
                    
                    current_price = float(ohlcv_15m[-2][4])
                    reason = details.get("reason", "شروط الـ SMC لم تكتمل بعد")
                    stop_loss = details.get("stop_loss", round(current_price * 0.98, 5))
                    rm = details.get("risk_management", {})
                    ps = details.get("position_sizing", {})

                    if details.get("trade_valid", False):
                        icon = "🟢" if direction == "LONG" else "🔴"
                        reply_msg = (
                            f"✅ *العملة وصلت لمنطقة الـ SMC وجاهزة للتنفيذ!* {icon}\n\n"
                            f"🔹 العملة: `{target_symbol}`\n"
                            f"💵 السعر الحالي: `{current_price}`\n"
                            f"⚖️ الاتجاه: `{direction}`\n\n"
                            f"🎯 *خطة الدخول والأهداف المؤكدة:*\n"
                            f"🔹 سعر الدخول (منطقة OB): `{entry_price}`\n"
                            f"🟥 وقف الخسارة الآمن: `{stop_loss}`\n"
                            f"📊 حجم العقد المقترح: `{ps.get('units')}` وحدة (${ps.get('margin_usd')})\n"
                            f"🟩 **الأهداف المنتظرة:**\n"
                            f"• TP1: `{rm.get('take_profit_1')}` (نقل الوقف للتعادل)\n"
                            f"• TP2: `{rm.get('take_profit_2')}`\n"
                            f"• TP3: `{rm.get('take_profit_3')}`\n\n"
                            f"💡 `{details.get('smc_note')}`"
                        )
                    else:
                        breakout_price = round(current_price * 1.015, 5)
                        tp1 = round(current_price * 1.035, 5)
                        tp2 = round(current_price * 1.055, 5)
                        tp3 = round(current_price * 1.085, 5)
                        
                        reply_msg = (
                            f"⏳ *العملة قيد المراقبة (في انتظار لمس منطقة Order Block)* ⏳\n\n"
                            f"🔹 العملة: `{target_symbol}`\n"
                            f"💵 السعر الحالي: `{current_price}`\n"
                            f"⚠️ السبب الفني: `{reason}`\n\n"
                            f"🎯 *الخطة الاحتياطية المحسوبة:*\n"
                            f"🔹 انتظر اختراق السعر: `{breakout_price}` للدخول\n"
                            f"🟥 وقف الخسارة الآمن: `{stop_loss}`\n"
                            f"🟩 **الأهداف الاحتياطية:**\n"
                            f"• TP1: `{tp1}`\n"
                            f"• TP2: `{tp2}`\n"
                            f"• TP3: `{tp3}`"
                        )
                    
                    send_telegram_message(reply_msg)
                    
                except Exception as inner_err:
                    logger.error(f"Analysis error for base_coin: {inner_err}")
                    send_telegram_message(f"❌ حدث خطأ تقني أثناء تحليل العملة `{base_coin}`.")
                
        except Exception as e:
            logger.error(f"Telegram listener error: {e}")
            time.sleep(5)

scanner_thread = threading.Thread(target=background_scanner, daemon=True, name="scanner")
scanner_thread.start()

telegram_listener_thread = threading.Thread(target=check_telegram_updates, daemon=True, name="telegram-listener")
telegram_listener_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
