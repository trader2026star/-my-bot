# ============================================================
# MY EXPERT CRYPTO & TradFi CFD BOT - Main Controller (v65.5_SNIPER_AUTO_PRO)
# ============================================================
import os
import time
import threading
import logging
import ccxt
import requests
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
    return "MY INSTITUTIONAL SNIPER BOT (v65.5 Auto) Active!"

@app.route("/health")
def health():
    return jsonify({"status": "healthy", "stats": scan_stats, "active_positions_count": len(active_positions)}), 200

def send_telegram_message(message, chat_id=None):
    target_chat = chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not target_chat:
        return False
    try:
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
            time.sleep(0.5)
            return method(*args, **kwargs)
        except Exception as e:
            err_str = str(e)
            if "109415" in err_str:
                return None
            if "100410" in err_str or "Rate Limit" in err_str or "Too Many Requests" in err_str or "429" in err_str:
                logger.warning("ضغط الطلبات (Rate Limit) مع BingX، جاري إعادة المحاولة...")
                time.sleep(delay * (attempt + 1))
            else:
                if attempt == retries - 1:
                    return None
                time.sleep(1.0)
    return None

def calculate_position_size(current_price, stop_loss, asset_type):
    try:
        risk_amount_usd = BOT_CAPITAL_USD * RISK_PER_TRADE
        risk_per_unit = abs(current_price - stop_loss)
        if risk_per_unit == 0:
            return 0.0
        raw_size = risk_amount_usd / risk_per_unit
        return round(raw_size, 3) if asset_type == "crypto" else round(raw_size, 2)
    except Exception:
        return 0.0

def generate_analysis_report(resolved_symbol, direction, current_price, details, asset_type="crypto"):
    position_size = calculate_position_size(current_price, details.get("stop_loss"), asset_type)
    
    if details.get("trade_valid"):
        with positions_lock:
            active_positions[resolved_symbol] = {
                "side": direction,
                "entry": current_price,
                "size": position_size,
                "tp1": details["risk_management"]["take_profit_1"],
                "tp2": details["risk_management"]["take_profit_2"],
                "tp3": details["risk_management"].get("take_profit_3"),
                "stop_loss": details["stop_loss"],
                "breakeven_done": False
            }
        scan_stats["signals_sent"] += 1

    rm = details.get("risk_management", {})
    ent = details.get("entry_zone", {})
    emoji = "🟢" if direction == "LONG" else ("🔴" if direction == "SHORT" else "⚪")

    price_str_format = "{:.8f}" if current_price < 0.1 else ("{:.4f}" if current_price < 10 else "{:.2f}")

    cur_formatted = price_str_format.format(current_price)
    sl_formatted = price_str_format.format(details.get('stop_loss'))
    tp1_formatted = price_str_format.format(rm.get('take_profit_1'))
    tp2_formatted = price_str_format.format(rm.get('take_profit_2'))
    tp3_formatted = price_str_format.format(rm.get('take_profit_3'))
    atr_formatted = price_str_format.format(details.get('atr'))

    valid_status = "✅ تصلح للصفقة" if details.get("trade_valid") else "❌ لا تصلح حالياً"

    report = (
        f"🎯 *تقرير قناص السيولة المؤسسي (SMC)* (`{resolved_symbol}`) {emoji}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📌 *التقييم الفني:* {valid_status}\n"
        f"🔹 *السعر الحالي:* `{cur_formatted}`\n"
        f"🔹 *اتجاه الهيكل (SMC Bias):* `{ent.get('smc_bias')}`\n"
        f"🔹 *تدفق سيولة الحيتان (CMF):* `{ent.get('z_score')}`\n"
        f"🔹 *متوسط النطاق الحقيقي (ATR):* `{atr_formatted}`\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📊 *التأكيدات الفنية المكتشفة:*\n"
        f"  • الفجوة السعرية (FVG Up): `{'نعم 🟢' if ent.get('fvg_up') else 'لا ⚪'}`\n"
        f"  • شفط السيولة (Sweep): `{'تم بنجاح ⚡' if ent.get('sweep_down') else 'غير متوفر'}`\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 *حجم العقد المقترح:* `{position_size}` Units\n"
        f"🎯 *سعر الدخول المناسب:* `{cur_formatted}`\n"
        f"🛑 *وقف الخسارة الآمن:* `{sl_formatted}`\n\n"
        f"🎯 *الأهداف الاستراتيجية:*\n"
        f"  • الهدف الأول (TP1): `{tp1_formatted}`\n"
        f"  • الهدف الثاني (TP2): `{tp2_formatted}`\n"
        f"  • الهدف الثالث (TP3): `{tp3_formatted}`\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💡 *التحليل الفني والسبب:* {details.get('reason')}"
    )
    return report

if bot:
    @bot.message_handler(func=lambda message: True)
    def handle_all_messages(message):
        try:
            text = message.text.strip()
            clean_text = text.replace("/", "").replace("_", "").strip().upper()
            if not clean_text or len(clean_text) > 12:
                return

            bot.reply_to(message, f"🎯 *جاري فحص دفاتر الطلبات ورصد فجوات الـ SMC والسيولة للرمز* (`{clean_text}`)...", parse_mode="Markdown")

            possible_symbols = []
            asset_type = "crypto"
            
            if clean_text in ["GOLD", "XAU", "GOLDUSDT", "XAUUSDT"]:
                possible_symbols = ["GOLD/USDT:USDT", "XAU/USDT:USDT", "GOLD/USDT", "XAU/USDT", "GOLDUSDT"]
                asset_type = "stock"
            elif clean_text in ["AAPL", "TSLA", "NVDA", "MSFT", "AMZN"]:
                possible_symbols = [f"{clean_text}/USDT", f"{clean_text}USDT"]
                asset_type = "stock"
            else:
                possible_symbols = [f"{clean_text}/USDT:USDT", f"{clean_text}/USDT", f"{clean_text}USDT"]

            ohlcv_15m = None
            resolved_symbol = None

            for sym in possible_symbols:
                ohlcv_15m = bingx_safe_call("fetch_ohlcv", sym, timeframe="15m", limit=300)
                if ohlcv_15m and len(ohlcv_15m) >= 50:
                    resolved_symbol = sym
                    break

            if not resolved_symbol:
                try:
                    spot_bingx = ccxt.bingx({"enableRateLimit": True, "options": {"defaultType": "spot"}})
                    for sym in possible_symbols:
                        spot_sym = sym.replace(":USDT", "")
                        ohlcv_15m = spot_bingx.fetch_ohlcv(spot_sym, timeframe="15m", limit=300)
                        if ohlcv_15m and len(ohlcv_15m) >= 50:
                            resolved_symbol = spot_sym
                            break
                except Exception:
                    pass

            if not resolved_symbol or not ohlcv_15m:
                bot.reply_to(message, f"❌ عذراً، لم يتم العثور على بيانات كافية للرمز `{clean_text}`.")
                return

            ohlcv_5m = bingx_safe_call("fetch_ohlcv", resolved_symbol, timeframe="5m", limit=300)
            scan_stats["scanned_pairs"] += 1

            direction, current_price, details = engine.analyze_market_structure(
                ohlcv_5m=ohlcv_5m, ohlcv_15m=ohlcv_15m, asset_type=asset_type
            )

            report = generate_analysis_report(resolved_symbol, direction, current_price, details, asset_type)
            bot.reply_to(message, report, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Error in message handler: {e}")

def telegram_listener():
    if bot:
        logger.info("Starting Telegram Bot listener...")
        bot.infinity_polling(none_stop=True, interval=1)

def automated_signal_scanner_loop():
    auto_symbols = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "XRP/USDT:USDT", "DOGE/USDT:USDT", "ILV/USDT:USDT", "COW/USDT:USDT", "ATH/USDT:USDT"]
    while True:
        try:
            time.sleep(30)
            logger.info("Running automated market scan for high-probability setups...")
            for sym in auto_symbols:
                ohlcv_15m = bingx_safe_call("fetch_ohlcv", sym, timeframe="15m", limit=300)
                ohlcv_5m = bingx_safe_call("fetch_ohlcv", sym, timeframe="5m", limit=300)
                
                if not ohlcv_15m or not ohlcv_5m or len(ohlcv_15m) < 50:
                    continue
                
                scan_stats["scanned_pairs"] += 1
                direction, current_price, details = engine.analyze_market_structure(
                    ohlcv_5m=ohlcv_5m, ohlcv_15m=ohlcv_15m, asset_type="crypto"
                )
                
                if details.get("trade_valid") and direction in ["LONG", "SHORT"]:
                    with positions_lock:
                        if sym in active_positions:
                            continue
                    
                    report = generate_analysis_report(sym, direction, current_price, details, "crypto")
                    send_telegram_message(f"🚀 *تنبيه صفقة تلقائية جديدة (Auto Sniper)*:\n\n{report}")
                    logger.info(f"Automated signal sent successfully for {sym}!")
                
                time.sleep(3)
        except Exception as e:
            logger.error(f"Error in automated signal scanner loop: {e}")

def position_tracker_loop():
    while True:
        try:
            time.sleep(5)
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
                tp3 = pos.get("tp3")
                stop_loss = pos["stop_loss"]
                be_done = pos["breakeven_done"]

                if side == "LONG":
                    if current_price <= stop_loss:
                        with positions_lock:
                            if symbol in active_positions:
                                del active_positions[symbol]
                        send_telegram_message(f"🛑 *ضرب وقف الخسارة لصفقة الشراء للرمز `{symbol}` عند السعر `{current_price}`.*")
                        continue
                    
                    if current_price >= tp1 and not be_done:
                        with positions_lock:
                            if symbol in active_positions:
                                active_positions[symbol]["breakeven_done"] = True
                                active_positions[symbol]["stop_loss"] = entry
                        send_telegram_message(f"🎯 *تم تحقيق الهدف الأول (TP1) للرمز `{symbol}`! تم نقل وقف الخسارة إلى نقطة الدخول (Breakeven).*")
                        
                    if tp3 and current_price >= tp3:
                        with positions_lock:
                            if symbol in active_positions:
                                del active_positions[symbol]
                        send_telegram_message(f"🚀 *تم تحقيق الهدف الثالث الأقصى (TP3) بنجاح للرمز `{symbol}`! تم إغلاق كامل الصفقة بربح ممتازة.*")
                    elif current_price >= tp2 and not tp3:
                        with positions_lock:
                            if symbol in active_positions:
                                del active_positions[symbol]
                        send_telegram_message(f"🚀 *تم تحقيق الهدف الثاني (TP2) بنجاح للرمز `{symbol}`!*")

                elif side == "SHORT":
                    if current_price >= stop_loss:
                        with positions_lock:
                            if symbol in active_positions:
                                del active_positions[symbol]
                        send_telegram_message(f"🛑 *ضرب وقف الخسارة لصفقة البيع للرمز `{symbol}` عند السعر `{current_price}`.*")
                        continue
                    
                    if current_price <= tp1 and not be_done:
                        with positions_lock:
                            if symbol in active_positions:
                                active_positions[symbol]["breakeven_done"] = True
                                active_positions[symbol]["stop_loss"] = entry
                        send_telegram_message(f"🎯 *تم تحقيق الهدف الأول (TP1) لصفقة البيع `{symbol}`! تم تأمين الصفقة.*")
                        
                    if tp3 and current_price <= tp3:
                        with positions_lock:
                            if symbol in active_positions:
                                del active_positions[symbol]
                        send_telegram_message(f"🚀 *تم تحقيق الهدف الثالث (TP3) بنجاح للرمز `{symbol}`!*")

        except Exception as e:
            logger.error(f"Error in position tracker loop: {e}")

if __name__ == "__main__":
    tracker_thread = threading.Thread(target=position_tracker_loop, daemon=True)
    tracker_thread.start()

    scanner_thread = threading.Thread(target=automated_signal_scanner_loop, daemon=True)
    scanner_thread.start()

    if bot:
        tg_thread = threading.Thread(target=telegram_listener, daemon=True)
        tg_thread.start()

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
