# ============================================================
# MY EXPERT CRYPTO & TradFi CFD BOT - Main Controller (v69.2_FIXED)
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
    return "MY BULLISH DIVERGENCE SNIPER BOT (v69.2 Fixed) Active!"

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
                logger.warning("ضغط الطلبات مع BingX، جاري إعادة المحاولة...")
                time.sleep(delay * (attempt + 1))
            else:
                if attempt == retries - 1:
                    return None
                time.sleep(1.0)
    return None

def calculate_position_size(current_price, stop_loss, asset_type):
    try:
        if current_price <= 0 or stop_loss <= 0:
            return 0.0
        risk_amount_usd = BOT_CAPITAL_USD * RISK_PER_TRADE
        risk_per_unit = abs(current_price - stop_loss)
        if risk_per_unit == 0:
            return 0.0
        raw_size = risk_amount_usd / risk_per_unit
        return round(raw_size, 3) if asset_type == "crypto" else round(raw_size, 2)
    except Exception:
        return 0.0

def generate_analysis_report(resolved_symbol, direction, current_price, details, asset_type="crypto"):
    position_size = calculate_position_size(current_price, details.get("stop_loss", 0), asset_type)
    
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
    emoji = "🟢" if details.get("trade_valid") else "⚪"

    price_str_format = "{:.8f}" if current_price < 0.1 else ("{:.4f}" if current_price < 10 else "{:.2f}")

    cur_formatted = price_str_format.format(current_price) if current_price > 0 else "0.0000"
    sl_formatted = price_str_format.format(details.get('stop_loss', 0)) if details.get('stop_loss', 0) > 0 else "0.0000"
    tp1_formatted = price_str_format.format(rm.get('take_profit_1', 0)) if rm.get('take_profit_1', 0) > 0 else "0.0000"
    tp2_formatted = price_str_format.format(rm.get('take_profit_2', 0)) if rm.get('take_profit_2', 0) > 0 else "0.0000"
    tp3_formatted = price_str_format.format(rm.get('take_profit_3', 0)) if rm.get('take_profit_3', 0) > 0 else "0.0000"
    atr_formatted = price_str_format.format(details.get('atr', 0))

    valid_status = "✅ إشارة دايفيرجنس صحيحة ومؤكدة" if details.get("trade_valid") else "❌ لا توجد إشارة دايفيرجنس حالياً"

    report = (
        f"🚨 **فحص عملة `{resolved_symbol}`** 🚨 {emoji}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📌 *التقييم الفني:* {valid_status}\n"
        f"🔹 *السعر الحالي:* `{cur_formatted}`\n"
        f"🔹 *مؤشر RSI الحالي:* `{details.get('rsi')}`\n"
        f"🔹 *مؤشر ATR:* `{atr_formatted}`\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 *حجم العقد المقترح:* `{position_size}` Units\n"
        f"🎯 *سعر الدخول المتوقع:* `{cur_formatted}`\n"
        f"🎯 *الهدف الأول:* `{tp1_formatted}`\n"
        f"🎯 *الهدف الثاني:* `{tp2_formatted}`\n"
        f"🎯 *الهدف الثالث:* `{tp3_formatted}`\n"
        f"🛑 *الستوب لوز (ATR/القاع):* `{sl_formatted}`\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💡 *نصيحة للبوت: عند ضرب الهدف الأول، انقل الستوب لوز فوراً إلى نقطة الدخول لتأمين الصفقة.*\n\n"
        f"📝 *السبب الفني:* {details.get('reason')}"
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

            bot.reply_to(message, f"🎯 *جاري فحص الدايفيرجنس الإيجابي والـ RSI للرمز* (`{clean_text}`)...", parse_mode="Markdown")

            # تحميل الأسواق للتأكد من الصيغة الصحيحة في بينج إكس
            try:
                bingx.load_markets()
            except Exception:
                pass

            possible_symbols = [
                f"{clean_text}/USDT:USDT",
                f"{clean_text}/USDT",
                f"{clean_text}USDT"
            ]
            
            # البحث المباشر في أسواق المنصة المتاحة
            for sym in possible_symbols:
                if sym in bingx.markets:
                    resolved_symbol = sym
                    break
            else:
                # إذا لم تجد مطابقة تامة، جرب البحث الجزئي
                resolved_symbol = None
                for m in bingx.symbols:
                    if clean_text in m and "USDT" in m:
                        resolved_symbol = m
                        break
                if not resolved_symbol:
                    resolved_symbol = possible_symbols[0]

            ohlcv_15m = bingx_safe_call("fetch_ohlcv", resolved_symbol, timeframe="15m", limit=100)
            
            if not ohlcv_15m or len(ohlcv_15m) < 20:
                # محاولة بالصيغة البديلة إذا فشلت الأولى
                resolved_symbol = f"{clean_text}/USDT"
                ohlcv_15m = bingx_safe_call("fetch_ohlcv", resolved_symbol, timeframe="15m", limit=100)

            if not resolved_symbol or not ohlcv_15m or len(ohlcv_15m) < 20:
                bot.reply_to(message, f"❌ عذراً، لم يتم العثور على بيانات كافية أو تداول للرمز `{clean_text}` على المنصة.")
                return

            ohlcv_5m = bingx_safe_call("fetch_ohlcv", resolved_symbol, timeframe="5m", limit=30)
            scan_stats["scanned_pairs"] += 1
            
            direction, current_price, details = engine.analyze_market_structure(ohlcv_5m=ohlcv_5m, ohlcv_15m=ohlcv_15m, asset_type="crypto")

            report = generate_analysis_report(resolved_symbol, direction, current_price, details, "crypto")
            bot.reply_to(message, report, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Error in message handler: {e}")
            bot.reply_to(message, f"❌ حدث خطأ أثناء معالجة الطلب: {str(e)}")

def telegram_listener():
    if bot:
        logger.info("Starting Telegram Bot listener...")
        bot.infinity_polling(none_stop=True, interval=1)

def automated_signal_scanner_loop():
    while True:
        try:
            time.sleep(60)
            tickers = bingx_safe_call("fetch_tickers")
            candidate_symbols = []
            
            if tickers:
                for symbol, data in tickers.items():
                    if "/USDT" in symbol:
                        volume_24h = data.get("quoteVolume", 0) or 0
                        if volume_24h > 500000:
                            candidate_symbols.append(symbol)

            active_symbols = candidate_symbols[:15]
            if not active_symbols:
                active_symbols = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"]

            for sym in active_symbols:
                ohlcv_15m = bingx_safe_call("fetch_ohlcv", sym, timeframe="15m", limit=100)
                if not ohlcv_15m or len(ohlcv_15m) < 30:
                    continue
                
                ohlcv_5m = bingx_safe_call("fetch_ohlcv", sym, timeframe="5m", limit=30)
                scan_stats["scanned_pairs"] += 1
                
                direction, current_price, details = engine.analyze_market_structure(ohlcv_5m=ohlcv_5m, ohlcv_15m=ohlcv_15m, asset_type="crypto")
                
                if details.get("trade_valid") and direction == "LONG":
                    with positions_lock:
                        if sym in active_positions:
                            continue
                    
                    report = generate_analysis_report(sym, direction, current_price, details, "crypto")
                    send_telegram_message(f"🚨 *فرصة دايفيرجنس جديدة مؤكدة*:\n\n{report}")
                    logger.info(f"Divergence signal sent for {sym}!")
                
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
                        send_telegram_message(f"🛑 *ضرب وقف الخسارة للرمز `{symbol}` عند السعر `{current_price}`.*")
                        continue
                    
                    if current_price >= tp1 and not be_done:
                        with positions_lock:
                            if symbol in active_positions:
                                active_positions[symbol]["breakeven_done"] = True
                                active_positions[symbol]["stop_loss"] = entry
                        send_telegram_message(f"🎯 *تم تحقيق الهدف الأول (TP1) للرمز `{symbol}`! تم نقل الستوب لوز إلى نقطة الدخول (Breakeven) لتأمين الصفقة.*")
                        
                    if tp3 and current_price >= tp3:
                        with positions_lock:
                            if symbol in active_positions:
                                del active_positions[symbol]
                        send_telegram_message(f"🚀 *تم تحقيق الهدف الثالث الأقصى (TP3) بنجاح للرمز `{symbol}`!*")
                    elif current_price >= tp2 and not tp3:
                        with positions_lock:
                            if symbol in active_positions:
                                del active_positions[symbol]
                        send_telegram_message(f"🚀 *تم تحقيق الهدف الثاني (TP2) بنجاح للرمز `{symbol}`!*")

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
