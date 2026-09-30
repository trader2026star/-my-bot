import os
import time
import logging
import threading
import requests
from flask import Flask, request, jsonify
from analysis import ExpertCISDBot

# =========================================================
# CONFIGURATION & LOGGING
# =========================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "YOUR_TELEGRAM_CHAT_ID")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "https://my-bot-zag6.onrender.com")

app = Flask(__name__)
bot = ExpertCISDBot(exchange_id='bingx')

# =========================================================
# TELEGRAM SENDER & TEST
# =========================================================
def send_telegram_alert(signal):
    if TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN" or not TELEGRAM_BOT_TOKEN:
        logger.info("Telegram token not set.")
        return

    market_label = "🟢 [SPOT - CISD صفقة العمر]" if signal['market_type'] == 'SPOT' else "🚀 [FUTURES - CISD تسليم السعر الحوتي]"

    msg = f"""
{market_label} 💎

📊 Symbol: {signal['symbol']}
🎯 Decision: {signal['decision']}
⭐ Score: {signal['score']}/100
🏷 Quality: {signal['quality']}

🧠 Confirmations: {', '.join(signal['confirmations'])}

📈 4H Trend: {signal['trend_4h']}
📊 1H Trend: {signal['trend_1h']}
💪 RSI 15M: {signal['rsi_15m']:.1f}
🔊 Volume Surge: {signal['volume_ratio']:.2f}x

💰 Entry Price: {signal['entry']:.7f}
🛑 Stop Loss: {signal['sl']:.7f} ({signal['risk_pct']}%)

🎯 TP1 (1:2): {signal['tp1']:.7f}
🎯 TP2 (1:3.5): {signal['tp2']:.7f}
🎯 TP3 (Elite Target): {signal['tp3']:.7f}

⚡ Strategy: CISD (Change in the State of Delivery) + FVG
⚠️ إدارة رأس المال هي الأساس للوصول للهدف المنشود.
"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
        logger.info(f"تم إرسال التنبيه عبر تيليجرام للعملة: {signal['symbol']}")
    except Exception as e:
        logger.error("Telegram error: %s", e)

def send_test_startup_message():
    if TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN" or not TELEGRAM_BOT_TOKEN:
        logger.warning("⚠️ التوكن غير مُعرّف، لن يتم إرسال رسالة تيليجرام.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    msg = "🟢 **تم إقلاع بوت CISD Elite بنجاح تام!**\nالسيرفر يعمل الآن ويبحث عن الصفقات الحوتية 🚀"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}
    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200:
            logger.info("✅ تم إرسال رسالة الاختبار بنجاح إلى تيليجرام!")
        else:
            logger.error(f"❌ فشل إرسال التيليجرام، الرد: {res.text}")
    except Exception as e:
        logger.error(f"Telegram test error: {e}")

# =========================================================
# BACKGROUND SCANNER LOOP & WEBHOOK
# =========================================================
def self_ping():
    while True:
        try:
            time.sleep(240)
            requests.get(RENDER_EXTERNAL_URL, timeout=10)
        except:
            pass

def background_scanner():
    spot_symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "AVAX/USDT", "LINK/USDT", "SUI/USDT", "NEAR/USDT", "RENDER/USDT", "FET/USDT", "INJ/USDT", "ARB/USDT", "TIA/USDT"]
    futures_symbols = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "XRP/USDT:USDT", "AVAX/USDT:USDT", "LINK/USDT:USDT", "SUI/USDT:USDT", "NEAR/USDT:USDT", "RENDER/USDT:USDT", "FET/USDT:USDT", "INJ/USDT:USDT", "ARB/USDT:USDT", "TIA/USDT:USDT"]
    
    symbols_to_scan = [(s, "spot") for s in spot_symbols] + [(s, "swap") for s in futures_symbols]
    sent_cooldown = {}

    logger.info("🚀 CISD Elite Scanner started successfully with %d assets.", len(symbols_to_scan))
    
    while True:
        try:
            for symbol, m_type in symbols_to_scan:
                signal = bot.evaluate_strategy(symbol, m_type)
                if signal:
                    cooldown_key = f"{symbol}_{signal['market_type']}"
                    if time.time() - sent_cooldown.get(cooldown_key, 0) > 10800:
                        send_telegram_alert(signal)
                        sent_cooldown[cooldown_key] = time.time()
                time.sleep(1.0)
        except Exception as e:
            logger.error("Scanner loop error: %s", e)
        time.sleep(60)

# =========================================================
# تشغيل خيوط الخلفية فور إقلاع السيرفر
# =========================================================
scanner_thread_started = False

def start_background_threads():
    global scanner_thread_started
    if not scanner_thread_started:
        try:
            threading.Thread(target=background_scanner, daemon=True).start()
            threading.Thread(target=self_ping, daemon=True).start()
            threading.Thread(target=send_test_startup_message, daemon=True).start()
            
            logger.info("🚀 تم بدء تشغيل خيوط الخلفية ورسالة الاختبار بنجاح تام!")
            scanner_thread_started = True
        except Exception as e:
            logger.error(f"فشل تشغيل خيوط الخلفية: {e}")

start_background_threads()

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    if not data or 'symbol' not in data:
        return jsonify({"status": "error"}), 400
    signal = bot.evaluate_strategy(data['symbol'], data.get('market_type', 'swap'))
    if signal:
        send_telegram_alert(signal)
        return jsonify({"status": "success", "signal": signal}), 200
    return jsonify({"status": "filtered"}), 200

@app.route('/')
def index():
    start_background_threads()
    return "CISD Elite Sniper Bot is running and hunting for life-changing setups!", 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
