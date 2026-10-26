# ==========================================
# MY EXPERT CRYPTO BOT - V18.1 Sniper Elite Pro (MM Shield)
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
    return "MY EXPERT CRYPTO BOT V18.1 Sniper Elite Pro Active!"

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

def notify_trade_executed(symbol, direction, entry_price, details):
    rm = details.get("risk_management", {})
    message = (
        f"💎 *قناص النخبة V18.1 - إشارة صيد مؤكدة (MM Shield)* 💎\n\n"
        f"🔹 العملة: `{symbol}`\n"
        f"⚖️ الاتجاه: `🟢 LONG`\n"
        f"💵 سعر الدخول: `{entry_price}`\n"
        f"⭐️ درجة الجودة: `{details.get('score')}/100`\n\n"
        f"🟥 وقف الخسارة (SL): `{details.get('stop_loss')}`\n"
        f"🟩 الهدف الأول (TP1): `{rm.get('take_profit_1')}`\n"
        f"🟩 الهدف الثاني (TP2): `{rm.get('take_profit_2')}`\n"
        f"🎯 الهدف الرئيسي (TP3): `{rm.get('take_profit_3')}`\n\n"
        f"🛡️ *حماية صانع السوق:* `{details.get('smc_note')}`"
    )
    return send_telegram_message(message)

def process_symbol(symbol, engine):
    try:
        now = time.time()
        with history_lock:
            if now - signal_history.get(symbol, 0) < SIGNAL_COOLDOWN_SECONDS:
                return None, None, None

        ticker = bingx_call("fetch_ticker", symbol)
        if not ticker:
            return None, None, None

        quote_volume = float(ticker.get("quoteVolume") or ticker.get("baseVolume") or 0)
        if quote_volume < 4000000:
            return None, None, None

        ohlcv_15m = bingx_call("fetch_ohlcv", symbol, timeframe="15m", limit=30)
        ohlcv_1h = bingx_call("fetch_ohlcv", symbol, timeframe="1h", limit=30)
        ohlcv_4h = bingx_call("fetch_ohlcv", symbol, timeframe="4h", limit=30)
        ohlcv_1d = bingx_call("fetch_ohlcv", symbol, timeframe="1d", limit=25)

        if not (ohlcv_15m and ohlcv_1h and ohlcv_4h and ohlcv_1d):
            return None, None, None

        direction, entry_price, details = engine.analyze_market_structure(
            ohlcv_15m=ohlcv_15m, ohlcv_1h=ohlcv_1h, ohlcv_4h=ohlcv_4h, ohlcv_1d=ohlcv_1d
        )
        scan_stats["scanned_pairs"] += 1

        if direction == "LONG" and details.get("trade_valid", False):
            return direction, entry_price, details

    except Exception as exc:
        logger.error(f"Error processing {symbol}: {exc}")
    return None, None, None

def background_scanner():
    time.sleep(5)
    send_telegram_message(
        "💎 *تم تفعيل بوت قناص النخبة V18.1 (حماية صانع السوق - MM Shield)* 💎\n"
        "أرسل الأمر `/scan` في أي وقت لفحص السوق وجلب العملات الجاهزة للدخول فوراً!"
    )
    engine = StrategyEngine(capital=BOT_CAPITAL_USD, risk_per_trade=RISK_PER_TRADE)

    while True:
        try:
            symbols = get_all_usdt_symbols()
            if not symbols:
                time.sleep(30)
                continue

            for symbol in symbols:
                direction, entry_price, details = process_symbol(symbol, engine)
                if direction == "LONG":
                    sent = notify_trade_executed(symbol, direction, entry_price, details)
                    if sent:
                        scan_stats["signals_sent"] += 1
                        with history_lock:
                            signal_history[symbol] = time.time()
                time.sleep(SYMBOL_PAUSE_SECONDS)

            time.sleep(60)
        except Exception as exc:
            logger.error(f"Scanner Loop Error: {exc}")
            time.sleep(30)

def run_manual_scan(chat_id, engine):
    """تنفيذ الفحص الشامل في مسار مستقل منعاً لحدوث Timeout مع تيليجرام"""
    try:
        send_telegram_message("🔍 *جاري بدء فحص شامل لجميع عملات السوق (V18.1 MM Shield)... قد يستغرق ذلك دقيقة أو دقيقتين* ⏳")
        all_symbols = get_all_usdt_symbols()
        ready_signals = []
        
        for s in all_symbols:
            direction, entry_price, details = process_symbol(s, engine)
            if direction == "LONG":
                ready_signals.append((s, entry_price, details))
            time.sleep(0.02)
        
        if ready_signals:
            report = f"🎯 *نتائج الفحص! العملات الجاهزة للدخول حالياً ({len(ready_signals)}):*\n\n"
            for s, ep, det in ready_signals[:10]:
                rm = det.get("risk_management", {})
                report += (
                    f"🔹 **{s}** | السعر: `{ep}` | الجودة: `{det.get('score')}/100`\n"
                    f"   • SL: `{det.get('stop_loss')}` | TP1: `{rm.get('take_profit_1')}`\n\n"
                )
            send_telegram_message(report)
        else:
            send_telegram_message("⚠️ *لم يتم العثور على عملات مستوفية لشروط القنص الصارمة (MM Shield) في هذا الفحص.*")
            
    except Exception as scan_err:
        logger.error(f"Manual scan error: {scan_err}")
        send_telegram_message("❌ حدث خطأ أثناء إجراء الفحص الشامل.")

def check_telegram_updates():
    """مستمع الرسائل: يدعم أمر /scan للفحص الفوري أو اسم عملة مفردة"""
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
                
                if not text or str(chat_id) != str(TELEGRAM_CHAT_ID):
                    continue
                
                # --- أمر الفحص الشامل /scan ---
                if text_upper in ["/SCAN", "SCAN", "فحص"]:
                    scan_thread = threading.Thread(target=run_manual_scan, args=(chat_id, engine), daemon=True)
                    scan_thread.start()
                    continue
                
                # --- فحص عملة مفردة يدوياً ---
                if text.startswith("/"):
                    continue
                
                base_coin = text_upper.replace("/USDT", "").replace("USDT", "").strip()
                send_telegram_message(f"🔍 جاري فحص استراتيجية V18.1 لعملة `{base_coin}`...")
                
                try:
                    all_symbols = get_all_usdt_symbols()
                    target_symbol = None
                    
                    for s in all_symbols:
                        s_base = s.split('/')[0].upper()
                        if s_base == base_coin or base_coin in s_base:
                            target_symbol = s
                            break
                    
                    if not target_symbol:
                        target_symbol = f"{base_coin}/USDT:USDT"

                    ohlcv_15m = bingx_call("fetch_ohlcv", target_symbol, timeframe="15m", limit=30)
                    ohlcv_1h = bingx_call("fetch_ohlcv", target_symbol, timeframe="1h", limit=30)
                    ohlcv_4h = bingx_call("fetch_ohlcv", target_symbol, timeframe="4h", limit=30)
                    ohlcv_1d = bingx_call("fetch_ohlcv", target_symbol, timeframe="1d", limit=25)
                    
                    if not (ohlcv_15m and ohlcv_1h and ohlcv_4h and ohlcv_1d):
                        send_telegram_message(f"❌ تعذر جلب بيانات الفريمات لعملة `{base_coin}`.")
                        continue
                    
                    direction, entry_price, details = engine.analyze_market_structure(
                        ohlcv_15m=ohlcv_15m, ohlcv_1h=ohlcv_1h, ohlcv_4h=ohlcv_4h, ohlcv_1d=ohlcv_1d
                    )
                    
                    current_price = float(ohlcv_15m[-1][4])
                    rm = details.get("risk_management", {})
                    stop_loss = details.get("stop_loss")
                    score = details.get("score", 0)
                    reason = details.get("reason", "تحليل تحت السيطرة")

                    if details.get("trade_valid", False):
                        reply_msg = (
                            f"✅ **العملة مؤهلة تماماً وجاهزة لصفقة LONG!**\n\n"
                            f"🔹 العملة: `{target_symbol}`\n"
                            f"💵 السعر الحالي: `{current_price}`\n"
                            f"⭐️ درجة الجودة: `{score}/100`\n\n"
                            f"🚀 **سعر الدخول المقترح:** `{entry_price}`\n"
                            f"🟥 **وقف الخسارة المحمي (SL):** `{stop_loss}`\n"
                            f"🟩 **الهدف الأول (TP1):** `{rm.get('take_profit_1')}`\n"
                            f"🟩 **الهدف الثاني (TP2):** `{rm.get('take_profit_2')}`\n"
                            f"🎯 **الهدف الرئيسي (TP3):** `{rm.get('take_profit_3')}`\n\n"
                            f"🛡️ {details.get('smc_note')}"
                        )
                    else:
                        reply_msg = (
                            f"⏳ **العملة غير جاهزة حالياً (تم رفضها بواسطة MM Shield)**\n\n"
                            f"🔹 العملة: `{target_symbol}`\n"
                            f"💵 السعر الحالي: `{current_price}`\n"
                            f"⭐️ درجة الجودة: `{score}/100`\n"
                            f"⚠️ **سبب الرفض الفني:** `{reason}`"
                        )
                    
                    send_telegram_message(reply_msg)
                    
                except Exception as inner_err:
                    logger.error(f"Analysis inner error for {base_coin}: {inner_err}")
                    send_telegram_message(f"❌ حدث خطأ أثناء تحليل العملة `{base_coin}`.")
                
        except Exception as e:
            logger.error(f"Telegram listener outer error: {e}")
            time.sleep(5)

scanner_thread = threading.Thread(target=background_scanner, daemon=True, name="mtf-poc-scanner")
scanner_thread.start()

telegram_listener_thread = threading.Thread(target=check_telegram_updates, daemon=True, name="telegram-listener")
telegram_listener_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
