# ============================================================
# MY EXPERT CRYPTO & TradFi CFD BOT - Main Controller (v52.0 - Full Edition)
# ============================================================
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

# تهيئة الاتصال بمنصة BingX مع الدعم الشامل للعقود والأسواق التقليدية
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
    return "MY EXPERT CRYPTO & TradFi CFD BOT Active!"

@app.route("/health")
def health():
    return jsonify({"status": "healthy", "stats": scan_stats, "active_positions_count": len(active_positions)}), 200

def send_telegram_message(message, chat_id=None):
    target_chat = chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not target_chat:
        return False
    try:
        import requests
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": target_chat, "text": message, "parse_mode": "Markdown", "disable_web_page_preview": True},
            timeout=15
        )
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Telegram error: {e}")
        return False

def bingx_safe_call(method_name, *args, **kwargs):
    method = getattr(bingx, method_name, None)
    if not method:
        return None
    
    retries = 3
    delay = 2.5
    for attempt in range(retries):
        try:
            time.sleep(0.6)
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

# ==========================================
# معالج رسائل تليجرام المباشر (مع تصحيح رموز الذهب و CFD تلقائياً)
# ==========================================
if bot:
    @bot.message_handler(func=lambda message: True)
    def handle_all_messages(message):
        try:
            text = message.text.strip()
            clean_text = text.replace("/", "").strip()
            
            if not clean_text or len(clean_text) > 12:
                return

            query_name = clean_text.upper()
            
            if query_name in ["GOLD", "XAU", "GOLDUSDT", "XAUUSDT"]:
                symbol = "GOLD/USDT:USDT"
            elif "/" not in query_name:
                symbol = f"{query_name}/USDT:USDT"
            else:
                symbol = query_name
                if not symbol.endswith(":USDT") and "GOLD" not in symbol:
                    symbol += ":USDT"

            bot.reply_to(message, f"🔍 جاري البحث وتحليل الرمز `{symbol}`...", parse_mode="Markdown")

            ohlcv_5m = bingx_safe_call("fetch_ohlcv", symbol, timeframe="5m", limit=35)
            
            if not ohlcv_5m and "GOLD" in symbol:
                for alt_sym in ["XAU/USDT:USDT", "GOLD/USDT", "XAUUSDT"]:
                    ohlcv_5m = bingx_safe_call("fetch_ohlcv", alt_sym, timeframe="5m", limit=35)
                    if ohlcv_5m:
                        symbol = alt_sym
                        break

            ohlcv_15m = bingx_safe_call("fetch_ohlcv", symbol, timeframe="15m", limit=35)
            ohlcv_1h = bingx_safe_call("fetch_ohlcv", symbol, timeframe="1h", limit=35)

            if not ohlcv_5m or not ohlcv_1h:
                bot.reply_to(message, f"❌ تعذر جلب بيانات الرمز `{symbol}` من المنصة. قد يكون هذا السوق مقفلاً حالياً أو يتبع صيغة مختلفة.")
                return

            direction, current_price, details = engine.analyze_market_structure(
                ohlcv_5m=ohlcv_5m, ohlcv_15m=ohlcv_15m, ohlcv_1h=ohlcv_1h
            )

            rm = details.get("risk_management", {})
            scenario = details.get("closest_scenario")

            if scenario == "BREAKOUT":
                scenario_title = "🚀 السيناريو الأقرب: (اختراق المقاومة)"
                trigger_label = "📍 سعر الاختراق المؤكد للدخول:"
            else:
                scenario_title = "🛡️ السيناريو الأقرب: (الارتداد من الدعم)"
                trigger_label = "📍 سعر الدعم المؤكد للشراء:"

            report = (
                f"📊 *التحليل الفني المباشر* (`{symbol}`)\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"🔹 *السعر الحالي:* `{current_price}`\n"
                f"🔹 *الاتجاه العام (1H):* `{details.get('market_trend')}`\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"{scenario_title}\n\n"
                f"{trigger_label} `{details.get('trigger_price')}`\n"
                f"🛑 *وقف الخسارة (SL):* `{details.get('stop_loss')}`\n\n"
                f"🎯 *الأهداف المؤكدة:*\n"
                f"  • الهدف الأول (TP1): `{rm.get('take_profit_1')}`\n"
                f"  • الهدف الثاني (TP2): `{rm.get('take_profit_2')}`\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"💡 *رؤية التحليل:* {details.get('reason')}"
            )

            bot.reply_to(message, report, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Error in message handler: {e}")

def telegram_listener():
    if bot:
        logger.info("Starting Telegram Bot listener for CFD & Crypto...")
        bot.infinity_polling(none_stop=True, interval=1)

def position_tracker_loop():
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
                        send_telegram_message(f"🛑 *ضرب وقف الخسارة لصفقة الشراء (LONG) للرمز `{symbol}` وتم الخروج.*")
                        continue

                    if current_price >= tp2:
                        with positions_lock:
                            if symbol in active_positions:
                                del active_positions[symbol]
                        send_telegram_message(f"🎯 *تم تحقيق الهدف الثاني (TP2) للرمز `{symbol}`! تبريكات الأرباح.*")
                        continue

                    if not be_done and current_price >= tp1:
                        active_positions[symbol]["stop_loss"] = entry
                        active_positions[symbol]["breakeven_done"] = True
                        send_telegram_message(
                            f"🛡️ *تفعيل حماية رأس المال (Breakeven) للرمز `{symbol}`!*\n"
                            f"• تم ضرب الهدف الأول (`{tp1}`).\n"
                            f"• نقل وقف الخسارة إلى سعر الدخول (`{entry}`)."
                        )

                elif side == "SHORT":
                    if current_price >= stop_loss:
                        with positions_lock:
                            if symbol in active_positions:
                                del active_positions[symbol]
                        send_telegram_message(f"🛑 *ضرب وقف الخسارة لصفقة البيع (SHORT) للرمز `{symbol}` وتم الخروج.*")
                        continue

                    if current_price <= tp2:
                        with positions_lock:
                            if symbol in active_positions:
                                del active_positions[symbol]
                        send_telegram_message(f"🎯 *تم تحقيق الهدف الثاني (TP2) للرمز `{symbol}`! تبريكات الأرباح.*")
                        continue

                    if not be_done and current_price <= tp1:
                        active_positions[symbol]["stop_loss"] = entry
                        active_positions[symbol]["breakeven_done"] = True
                        send_telegram_message(
                            f"🛡️ *تفعيل حماية رأس المال (Breakeven) للرمز `{symbol}`!*\n"
                            f"• تم ضرب الهدف الأول (`{tp1}`).\n"
                            f"• نقل وقف الخسارة إلى سعر الدخول (`{entry}`)."
                        )

            time.sleep(15)
        except Exception as e:
            logger.error(f"Tracker Error: {e}")
            time.sleep(30)

def background_scanner():
    time.sleep(5)
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        send_telegram_message("🛡️ *تم تفعيل بوت التداول الشامل (Crypto & TradFi CFD) بنجاح!*")

    while True:
        try:
            markets = bingx_safe_call("load_markets")
            if not markets:
                time.sleep(30)
                continue
                
            symbols = [s for s, m in markets.items() if (m.get("linear") or m.get("swap")) and m.get("quote") in ["USDT", "USD"]]
            
            priority_symbols = ["GOLD/USDT:USDT", "BTC/USDT:USDT", "ETH/USDT:USDT"]
            for ps in priority_symbols:
                if ps in markets and ps not in symbols:
                    symbols.insert(0, ps)

            btc_ohlcv_15m = bingx_safe_call("fetch_ohlcv", "BTC/USDT:USDT", timeframe="15m", limit=30)

            for symbol in symbols:
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
                            f"🔹 الرمز / السوق: `{symbol}`\n"
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
                                    "tp1": rm.get('take_profit_1'),
                                    "tp2": rm.get('take_profit_2'),
                                    "breakeven_done": False
                                }
                except Exception as sub_exc:
                    logger.error(f"Error scanning {symbol}: {sub_exc}")
                    continue

                time.sleep(1.8)

            time.sleep(60)
        except Exception as exc:
            logger.error(f"Scanner Loop Error: {exc}")
            time.sleep(30)

# تشغيل خيوط الخلفية
threading.Thread(target=background_scanner, daemon=True, name="scanner").start()
threading.Thread(target=position_tracker_loop, daemon=True, name="tracker").start()
if bot:
    threading.Thread(target=telegram_listener, daemon=True, name="telegram_listener").start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
