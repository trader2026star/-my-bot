# ==========================================
# MY EXPERT CRYPTO BOT - Main Controller (v40.0 - Safe Execution Edition)
# ==========================================
import os
import time
import threading
import logging
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
BOT_CAPITAL_USD = max(1.0, float(os.environ.get("BOT_CAPITAL_USD", "10000")))
RISK_PER_TRADE = min(0.05, max(0.001, float(os.environ.get("RISK_PER_TRADE", "0.01"))))

active_positions = {}
positions_lock = threading.Lock()
scan_stats = {"scanned_pairs": 0, "signals_sent": 0}

bingx = ccxt.bingx({
    "enableRateLimit": True,
    "timeout": 20000,
    "options": {"defaultType": "swap"},
    "apiKey": os.environ.get("BINGX_API_KEY", ""),
    "secret": os.environ.get("BINGX_SECRET_KEY", "")
})

engine = StrategyEngine(capital=BOT_CAPITAL_USD, risk_per_trade=RISK_PER_TRADE)

bot = None
try:
    import telebot
    if TELEGRAM_BOT_TOKEN:
        bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
        logger.info("Telegram Bot initialized successfully.")
except Exception as e:
    logger.warning(f"Telegram initialization warning: {e}")

@app.route("/")
def home():
    return "MY EXPERT CRYPTO BOT (Ultimate SMC & Market Guard Edition) Active!"

@app.route("/health")
def health():
    return jsonify({"status": "healthy", "stats": scan_stats, "active_positions_count": len(active_positions)}), 200

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        import requests
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown", "disable_web_page_preview": True},
            timeout=15
        )
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Telegram error: {e}")
        return False

def position_tracker_loop():
    """متابع الصفقات لتنفيذ خاصية Breakeven تلقائياً عند ضرب الهدف الأول TP1"""
    while True:
        try:
            with positions_lock:
                positions_to_check = list(active_positions.items())

            for symbol, pos in positions_to_check:
                ticker = bingx.fetch_ticker(symbol)
                if not ticker:
                    continue
                current_price = float(ticker.get("last", 0))
                if current_price <= 0:
                    continue

                entry = pos["entry"]
                tp1 = pos["tp1"]
                tp2 = pos["tp2"]
                stop_loss = pos["stop_loss"]
                be_done = pos["breakeven_done"]

                # التحقق من ضرب وقف الخسارة أو الهدف الثاني
                if current_price <= stop_loss:
                    with positions_lock:
                        if symbol in active_positions:
                            del active_positions[symbol]
                    send_telegram_message(f"🛑 *ضرب وقف الخسارة للعملة `{symbol}` وتم الخروج.*")
                    continue

                if current_price >= tp2:
                    with positions_lock:
                        if symbol in active_positions:
                            del active_positions[symbol]
                    send_telegram_message(f"🎯 *تم تحقيق الهدف الثاني (TP2) بالكامل للعملة `{symbol}`! تبريكات الأرباح.*")
                    continue

                # تفعيل Breakeven عند ضرب الهدف الأول TP1
                if not be_done and current_price >= tp1:
                    active_positions[symbol]["stop_loss"] = entry  # نقل الوقف لسعر الدخول
                    active_positions[symbol]["breakeven_done"] = True
                    send_telegram_message(
                        f"🛡️ *تفعيل حماية رأس المال (Breakeven) للعملة `{symbol}`!*\n"
                        f"• تم ضرب الهدف الأول (`{tp1}`).\n"
                        f"• تم نقل وقف الخسارة تلقائياً إلى سعر الدخول (`{entry}`) لضمان صفقة خالية من المخاطر."
                    )

            time.sleep(15)
        except Exception as e:
            logger.error(f"Tracker Error: {e}")
            time.sleep(30)

def background_scanner():
    time.sleep(5)
    send_telegram_message("🛡️ *تم تفعيل بوت التداول الآمن (Market Guard + SMC) بنجاح والاستعداد للرصد الصارم!*")

    while True:
        try:
            markets = bingx.load_markets()
            symbols = [s for s, m in markets.items() if m.get("linear") and m.get("quote") == "USDT" and m.get("swap")]
            
            # جلب بيانات البيتكوين أولاً لفلتر الحماية
            btc_ohlcv_15m = bingx.fetch_ohlcv("BTC/USDT:USDT", timeframe="15m", limit=30)

            for symbol in symbols:
                if symbol == "BTC/USDT:USDT":
                    continue
                
                with positions_lock:
                    if symbol in active_positions:
                        continue

                try:
                    ohlcv_5m = bingx.fetch_ohlcv(symbol, timeframe="5m", limit=35)
                    ohlcv_15m = bingx.fetch_ohlcv(symbol, timeframe="15m", limit=35)
                    ohlcv_1h = bingx.fetch_ohlcv(symbol, timeframe="1h", limit=35)

                    if not (ohlcv_5m and ohlcv_15m and ohlcv_1h):
                        continue

                    direction, entry_price, details = engine.analyze_market_structure(
                        ohlcv_5m=ohlcv_5m, ohlcv_15m=ohlcv_15m, ohlcv_1h=ohlcv_1h, btc_ohlcv_15m=btc_ohlcv_15m
                    )
                    scan_stats["scanned_pairs"] += 1

                    if direction == "LONG" and details.get("trade_valid", False):
                        rm = details.get("risk_management", {})
                        ent = details.get("entry_zone", {})
                        
                        message = (
                            f"🚀 *فرصة صفقات نخبة مؤكدة (LONG)* 🟢\n"
                            f"🔹 العملة: `{symbol}`\n"
                            f"━━━━━━━━━━━━━━━━━━━\n"
                            f"📍 *السعر الحالي / الدخول:* `{entry_price}`\n"
                            f"📍 *منطقة الطلب (OB):* `{ent.get('order_block')}`\n"
                            f"🛑 *وقف الخسارة الأمان:* `{details.get('stop_loss')}`\n"
                            f"━━━━━━━━━━━━━━━━━━━\n"
                            f"🎯 *الأهداف الاستراتيجية:*\n"
                            f"  • TP1 (تحويل Breakeven): `{rm.get('take_profit_1')}`\n"
                            f"  • TP2 (1:2.5 العائد): `{rm.get('take_profit_2')}`\n"
                            f"━━━━━━━━━━━━━━━━━━━\n"
                            f"💡 *التحقق الفني:* {details.get('reason')}"
                        )
                        sent = send_telegram_message(message)
                        if sent:
                            scan_stats["signals_sent"] += 1
                            with positions_lock:
                                active_positions[symbol] = {
                                    "entry": entry_price,
                                    "stop_loss": details.get("stop_loss"),
                                    "tp1": rm.get("take_profit_1"),
                                    "tp2": rm.get("take_profit_2"),
                                    "breakeven_done": False
                                }
                except Exception as sub_exc:
                    logger.error(f"Error scanning {symbol}: {sub_exc}")
                    continue

                time.sleep(0.2)

            time.sleep(60)
        except Exception as exc:
            logger.error(f"Scanner Loop Error: {exc}")
            time.sleep(30)

if bot:
    @bot.message_handler(func=lambda message: True)
    def handle_query(message):
        text = message.text.strip().upper()
        if not text or text.startswith("/"):
            return
        symbol = f"{text}/USDT:USDT" if "USDT" not in text else text
        bot.reply_to(message, f"🔍 جارٍ فحص الشروط الـ 5 الصارمة للعملة **{symbol}**...", parse_mode="Markdown")
        try:
            ohlcv_5m = bingx.fetch_ohlcv(symbol, timeframe="5m", limit=35)
            ohlcv_15m = bingx.fetch_ohlcv(symbol, timeframe="15m", limit=35)
            ohlcv_1h = bingx.fetch_ohlcv(symbol, timeframe="1h", limit=35)
            btc_ohlcv_15m = bingx.fetch_ohlcv("BTC/USDT:USDT", timeframe="15m", limit=30)

            direction, entry_price, details = engine.analyze_market_structure(
                ohlcv_5m=ohlcv_5m, ohlcv_15m=ohlcv_15m, ohlcv_1h=ohlcv_1h, btc_ohlcv_15m=btc_ohlcv_15m
            )
            
            if not details.get("trade_valid", False):
                bot.reply_to(message, f"❌ العملة لا تتطابق مع الشروط الصارمة:\n_{details.get('reason')}_", parse_mode="Markdown")
                return

            rm = details.get("risk_management", {})
            msg = (
                f"🟢 *نتيجة فحص العملة `{symbol}`: تطابق تام!*\n"
                f"📍 الدخول: `{entry_price}`\n"
                f"🛑 وقف الخسارة: `{details.get('stop_loss')}`\n"
                f"🎯 TP1: `{rm.get('take_profit_1')}` | TP2: `{rm.get('take_profit_2')}`\n"
                f"💡 {details.get('reason')}"
            )
            bot.reply_to(message, msg, parse_mode="Markdown")
        except Exception as e:
            bot.reply_to(message, f"⚠️ خطأ أثناء الفحص: {str(e)}")

# تشغيل خيوط الخلفية
threading.Thread(target=background_scanner, daemon=True, name="scanner").start()
threading.Thread(target=position_tracker_loop, daemon=True, name="tracker").start()

if bot:
    threading.Thread(target=bot.infinity_polling, daemon=True, name="polling").start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
