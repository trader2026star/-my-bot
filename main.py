# ==========================================
# MY EXPERT CRYPTO BOT - Main Controller (v45.0 - Silent & Clean Polling Edition)
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
    return "MY EXPERT CRYPTO BOT (Bi-Directional SMC & Silent Polling Edition) Active!"

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

def bingx_safe_call(method_name, *args, **kwargs):
    """دالة اتصال آمنة لمنصة بينجكس مع معالجة ذكية لتجاوز حد الطلبات (Rate Limit 100410)"""
    method = getattr(bingx, method_name, None)
    if not method:
        return None
    
    retries = 3
    delay = 2.0
    for attempt in range(retries):
        try:
            time.sleep(0.4)
            return method(*args, **kwargs)
        except Exception as e:
            err_str = str(e)
            if "100410" in err_str or "Rate Limit" in err_str or "Too Many Requests" in err_str or "429" in err_str:
                logger.warning(f"ضغط الطلبات (Rate Limit) مع BingX، جاري إعادة المحاولة... (محاولة {attempt+1})")
                time.sleep(delay * (attempt + 1))
            else:
                if attempt == retries - 1:
                    logger.error(f"خطأ في استدعاء BingX {method_name}: {e}")
                    return None
                time.sleep(1.0)
    return None

def position_tracker_loop():
    """متابع الصفقات (LONG & SHORT) لتنفيذ Breakeven تلقائياً عند ضرب TP1"""
    while True:
        try:
            with positions_lock:
                positions_to_check = list(active_positions.items())

            for symbol, pos in positions_to_check:
                ticker = bingx_safe_call("fetch_ticker", symbol)
                if not ticker:
                    continue
                current_price = float(ticker.get("last", 0))
                if current_price <= 0:
                    continue

                side = pos["side"]
                entry = pos["entry"]
                tp1 = pos["tp1"]
                tp2 = pos["tp2"]
                stop_loss = pos["stop_loss"]
                be_done = pos["breakeven_done"]

                if side == "LONG":
                    if current_price <= stop_loss:
                        with positions_lock:
                            if symbol in active_positions:
                                del active_positions[symbol]
                        send_telegram_message(f"🛑 *ضرب وقف الخسارة لصفقة الشراء (LONG) للعملة `{symbol}` وتم الخروج.*")
                        continue

                    if current_price >= tp2:
                        with positions_lock:
                            if symbol in active_positions:
                                del active_positions[symbol]
                        send_telegram_message(f"🎯 *تم تحقيق الهدف الثاني (TP2) بالكامل لصفقة (LONG) على العملة `{symbol}`! تبريكات الأرباح.*")
                        continue

                    if not be_done and current_price >= tp1:
                        active_positions[symbol]["stop_loss"] = entry
                        active_positions[symbol]["breakeven_done"] = True
                        send_telegram_message(
                            f"🛡️ *تفعيل حماية رأس المال (Breakeven) لصفقة (LONG) على العملة `{symbol}`!*\n"
                            f"• تم ضرب الهدف الأول (`{tp1}`).\n"
                            f"• تم نقل وقف الخسارة تلقائياً إلى سعر الدخول (`{entry}`)."
                        )

                elif side == "SHORT":
                    if current_price >= stop_loss:
                        with positions_lock:
                            if symbol in active_positions:
                                del active_positions[symbol]
                        send_telegram_message(f"🛑 *ضرب وقف الخسارة لصفقة البيع (SHORT) للعملة `{symbol}` وتم الخروج.*")
                        continue

                    if current_price <= tp2:
                        with positions_lock:
                            if symbol in active_positions:
                                del active_positions[symbol]
                        send_telegram_message(f"🎯 *تم تحقيق الهدف الثاني (TP2) بالكامل لصفقة (SHORT) على العملة `{symbol}`! تبريكات الأرباح.*")
                        continue

                    if not be_done and current_price <= tp1:
                        active_positions[symbol]["stop_loss"] = entry
                        active_positions[symbol]["breakeven_done"] = True
                        send_telegram_message(
                            f"🛡️ *تفعيل حماية رأس المال (Breakeven) لصفقة (SHORT) على العملة `{symbol}`!*\n"
                            f"• تم ضرب الهدف الأول (`{tp1}`).\n"
                            f"• تم نقل وقف الخسارة تلقائياً إلى سعر الدخول (`{entry}`)."
                        )

            time.sleep(15)
        except Exception as e:
            logger.error(f"Tracker Error: {e}")
            time.sleep(30)

def background_scanner():
    time.sleep(5)
    send_telegram_message("🛡️ *تم تفعيل بوت التداول الذكي (Bi-Directional SMC) بنجاح!*")

    while True:
        try:
            markets = bingx_safe_call("load_markets")
            if not markets:
                time.sleep(30)
                continue
                
            symbols = [s for s, m in markets.items() if m.get("linear") and m.get("quote") == "USDT" and m.get("swap")]
            btc_ohlcv_15m = bingx_safe_call("fetch_ohlcv", "BTC/USDT:USDT", timeframe="15m", limit=30)

            for symbol in symbols:
                if symbol == "BTC/USDT:USDT":
                    continue
                
                with positions_lock:
                    if symbol in active_positions:
                        continue

                try:
                    ohlcv_5m = bingx_safe_call("fetch_ohlcv", symbol, timeframe="5m", limit=35)
                    ohlcv_15m = bingx_safe_call("fetch_ohlcv", symbol, timeframe="15m", limit=35)
                    ohlcv_1h = bingx_safe_call("fetch_ohlcv", symbol, timeframe="1h", limit=35)

                    if not (ohlcv_5m and ohlcv_1h):
                        continue

                    direction, entry_price, details = engine.analyze_market_structure(
                        ohlcv_5m=ohlcv_5m, ohlcv_15m=ohlcv_15m, ohlcv_1h=ohlcv_1h, btc_ohlcv_15m=btc_ohlcv_15m
                    )
                    scan_stats["scanned_pairs"] += 1

                    if direction in ["LONG", "SHORT"] and details.get("trade_valid", False):
                        rm = details.get("risk_management", {})
                        ent = details.get("entry_zone", {})
                        emoji = "🟢" if direction == "LONG" else "🔴"
                        
                        message = (
                            f"🚀 *فرصة صفقات نخبة مؤكدة ({direction})* {emoji}\n"
                            f"🔹 العملة: `{symbol}`\n"
                            f"━━━━━━━━━━━━━━━━━━━\n"
                            f"📍 *السعر الحالي / الدخول:* `{entry_price}`\n"
                            f"📍 *منطقة الطلب/العرض (OB):* `{ent.get('order_block')}`\n"
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
                                    "side": direction,
                                    "entry": entry_price,
                                    "stop_loss": details.get("stop_loss"),
                                    "tp1": rm.get("take_profit_1"),
                                    "tp2": rm.get("take_profit_2"),
                                    "breakeven_done": False
                                }
                except Exception as sub_exc:
                    logger.error(f"Error scanning {symbol}: {sub_exc}")
                    continue

                time.sleep(0.8)

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
        bot.reply_to(message, f"🔍 جارٍ فحص الشروط الصارمة للعملة **{symbol}**...", parse_mode="Markdown")
        try:
            ohlcv_5m = bingx_safe_call("fetch_ohlcv", symbol, timeframe="5m", limit=35)
            ohlcv_15m = bingx_safe_call("fetch_ohlcv", symbol, timeframe="15m", limit=35)
            ohlcv_1h = bingx_safe_call("fetch_ohlcv", symbol, timeframe="1h", limit=35)
            btc_ohlcv_15m = bingx_safe_call("fetch_ohlcv", "BTC/USDT:USDT", timeframe="15m", limit=30)

            direction, entry_price, details = engine.analyze_market_structure(
                ohlcv_5m=ohlcv_5m, ohlcv_15m=ohlcv_15m, ohlcv_1h=ohlcv_1h, btc_ohlcv_15m=btc_ohlcv_15m
            )
            
            if not details.get("trade_valid", False):
                bot.reply_to(message, f"❌ العملة لا تتطابق مع الشروط:\n_{details.get('reason')}_", parse_mode="Markdown")
                return

            rm = details.get("risk_management", {})
            msg = (
                f"🟢 *نتيجة فحص العملة `{symbol}` ({direction}): تطابق تام!*\n"
                f"📍 الدخول: `{entry_price}`\n"
                f"🛑 وقف الخسارة: `{details.get('stop_loss')}`\n"
                f"🎯 TP1: `{rm.get('take_profit_1')}` | TP2: `{rm.get('take_profit_2')}`\n"
                f"💡 {details.get('reason')}"
            )
            bot.reply_to(message, msg, parse_mode="Markdown")
        except Exception as e:
            bot.reply_to(message, f"⚠️ خطأ أثناء الفحص: {str(e)}")

# إزالة الـ Webhook القديم بأمان
if bot:
    try:
        bot.remove_webhook()
        time.sleep(1)
    except Exception:
        pass

# تشغيل خيوط الخلفية
threading.Thread(target=background_scanner, daemon=True, name="scanner").start()
threading.Thread(target=position_tracker_loop, daemon=True, name="tracker").start()

if bot:
    def run_polling():
        while True:
            try:
                # تشغيل آمن صامت يتجاوز أي تعارض محتمل 409 بدون طباعة أخطاء مزعجة
                bot.infinity_polling(timeout=60, long_polling_timeout=30, skip_pending=True)
            except Exception:
                time.sleep(15) # انتظار هادئ وإعادة المحاولة في الخلفية

    threading.Thread(target=run_polling, daemon=True, name="polling").start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
