# ==========================================
# ADVANCED INSTITUTIONAL LIQUIDITY BOT - MAIN (V4 - Full Telegram Alerts)
# Focus: STRK/USDT & PYTH/USDT + Full Lifecycle Notifications
# ==========================================

import os
import time
import threading
import requests
import ccxt
from flask import Flask
from analysis import StrategyEngine

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
SIGNAL_COOLDOWN_SECONDS = int(os.environ.get("SIGNAL_COOLDOWN_SECONDS", "3600"))

API_MIN_INTERVAL_SECONDS = max(0.25, float(os.environ.get("API_MIN_INTERVAL_SECONDS", "0.50")))
SYMBOL_PAUSE_SECONDS = max(0.10, float(os.environ.get("SYMBOL_PAUSE_SECONDS", "0.50")))
MAX_API_RETRIES = max(0, min(3, int(os.environ.get("MAX_API_RETRIES", "3"))))

signal_history = {}
active_trades = {}  # لتتبع الصفقات المفتوحة وإدارة الـ Break-even والأهداف
history_lock = threading.Lock()
api_lock = threading.Lock()
_last_api_request = 0.0
_api_cooldown_until = 0.0

bingx = ccxt.bingx({
    "enableRateLimit": True,
    "timeout": 20000,
    "options": {"defaultType": "swap"}
})

# قائمة العملات المستهدفة حصرياً أو فحص السوق كله
TARGET_SYMBOLS = ["STRK/USDT:USDT", "PYTH/USDT:USDT"]


@app.route("/")
def home():
    return "Advanced Institutional Liquidity Bot (V4 with Full Alerts) is active!"


@app.route("/health")
def health():
    return {"status": "healthy", "service": "active"}, 200


def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID.")
        return False
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True
            },
            timeout=15
        )
        return response.status_code == 200
    except Exception as exc:
        print(f"Telegram error: {str(exc)[:150]}")
        return False


def bingx_call(method_name, *args, **kwargs):
    global _last_api_request, _api_cooldown_until
    method = getattr(bingx, method_name)

    for attempt in range(MAX_API_RETRIES + 1):
        with api_lock:
            now = time.monotonic()
            wait_for = max(0.0, API_MIN_INTERVAL_SECONDS - (now - _last_api_request), _api_cooldown_until - now)
            if wait_for > 0:
                time.sleep(wait_for)
            _last_api_request = time.monotonic()

        try:
            return method(*args, **kwargs)
        except Exception as exc:
            if attempt >= MAX_API_RETRIES:
                raise
            time.sleep(2.0)

    raise Exception("Max retries reached")


def fmt(value):
    try:
        return f"{float(value):.10g}"
    except Exception:
        return str(value)


def notify_order_setup(symbol, signal, entry, sl, tp3):
    msg = (
        "🔍 *1. رصد مسح سيولة وتجهيز أمر معلق*\n\n"
        f"🔹 العملة: `{symbol}`\n"
        f"⚖️ الاتجاه: `{signal}`\n"
        f"💵 سعر الدخول المقترح: `{fmt(entry)}`\n"
        f"🛑 وقف الخسارة المقترح: `{fmt(sl)}`\n"
        f"🎯 الهدف المقترح (1:3): `{fmt(tp3)}`\n\n"
        "⏳ *جاري مراقبة التفعيل اللحظي للسعر...*"
    )
    send_telegram_message(msg)


def notify_trade_executed(symbol, signal, entry, sl, tp1, tp3):
    msg = (
        "🚀 *2. تم تفعيل الصفقة بنجاح في السوق!*\n\n"
        f"🔹 العملة: `{symbol}`\n"
        f"⚖️ النوع: `{signal}`\n"
        f"💵 سعر التفعيل الفعلي: `{fmt(entry)}`\n"
        f"🛑 وقف الخسارة: `{fmt(sl)}`\n"
        f"🛡️ نقطة تأمين الوقف (Break-even): `{fmt(tp1)}`\n"
        f"🎯 الهدف النهائي (1:3): `{fmt(tp3)}`\n\n"
        "⚡ *الصفقة تسير وفق الخوارزمية المؤسسية.*"
    )
    send_telegram_message(msg)


def notify_breakeven(symbol, entry):
    msg = (
        "🛡️ *3. تحديث حماية الصفقة (Break-even)*\n\n"
        f"🔹 العملة: `{symbol}`\n"
        f"✅ تم تحقيق الهدف الأول ووصول السعر لمنطقة التأمين.\n"
        f"🔒 تم نقل وقف الخسارة تلقائياً إلى سعر الدخول: `{fmt(entry)}`\n"
        "✨ *الصفقة أصبحت خالية من المخاطر تماماً!*"
    )
    send_telegram_message(msg)


def notify_trade_closed(symbol, result_type, exit_price):
    icon = "🎯" if result_type == "TARGET" else "🛑"
    title = "تم تحقيق الهدف النهائي بنجاح!" if result_type == "TARGET" else "تم ضرب وقف الخسارة المؤمّن."
    msg = (
        f"{icon} *4. إغلاق الصفقة: {title}*\n\n"
        f"🔹 العملة: `{symbol}`\n"
        f"🏁 سعر الخروج: `{fmt(exit_price)}`\n"
        "📊 *سيتم البحث عن فرصة جديدة قريباً.*"
    )
    send_telegram_message(msg)


def monitor_active_trades(symbol, current_price):
    """مراقبة الصفقات المفتوحة لتفعيل الBreak-even أو إغلاقها عند الأهداف"""
    if symbol not in active_trades:
        return

    trade = active_trades[symbol]
    signal = trade["signal"]
    entry = trade["entry"]
    sl = trade["sl"]
    tp1 = trade["tp1"]
    tp3 = trade["tp3"]
    be_triggered = trade["be_triggered"]

    if signal == "LONG":
        # فحص Break-even عند الوصول للهدف الأول TP1
        if not be_triggered and current_price >= tp1:
            active_trades[symbol]["be_triggered"] = True
            active_trades[symbol]["sl"] = entry  # نقل الـ SL لسعر الدخول
            notify_breakeven(symbol, entry)
        
        # فحص ضرب الهدف النهائي TP3
        elif current_price >= tp3:
            notify_trade_closed(symbol, "TARGET", current_price)
            del active_trades[symbol]
        
        # فحص ضرب وقف الخسارة SL
        elif current_price <= sl:
            notify_trade_closed(symbol, "STOP", current_price)
            del active_trades[symbol]

    elif signal == "SHORT":
        # فحص Break-even عند الهبوط للهدف الأول TP1
        if not be_triggered and current_price <= tp1:
            active_trades[symbol]["be_triggered"] = True
            active_trades[symbol]["sl"] = entry
            notify_breakeven(symbol, entry)
        
        # فحص ضرب الهدف النهائي TP3
        elif current_price <= tp3:
            notify_trade_closed(symbol, "TARGET", current_price)
            del active_trades[symbol]
        
        # فحص ضرب وقف الخسارة SL
        elif current_price >= sl:
            notify_trade_closed(symbol, "STOP", current_price)
            del active_trades[symbol]


def process_symbol(symbol, engine):
    try:
        ticker = bingx_call("fetch_ticker", symbol)
        current_price = float(ticker.get("last") or ticker.get("close") or 0)
        if current_price <= 0:
            return

        # إذا كانت الصفقة مفتوحة ومُتتبعة، افحص حالتها أولاً
        if symbol in active_trades:
            monitor_active_trades(symbol, current_price)
            return

        global signal_history
        now_time = time.time()
        with history_lock:
            last_time = signal_history.get(symbol, 0)
            if now_time - last_time < SIGNAL_COOLDOWN_SECONDS:
                return

        # جلب البيانات والتحليل
        ohlcv_1h = bingx_call("fetch_ohlcv", symbol, timeframe="1h", limit=50)
        ohlcv_5m = bingx_call("fetch_ohlcv", symbol, timeframe="5m", limit=50)

        signal, score, volume_ratio, details, arrays = engine.analyze_institutional_setup(
            ohlcv_1h, ohlcv_5m, symbol=symbol
        )

        if signal not in ("LONG", "SHORT") or score < 75:
            return

        target_price = details.get("predictive_entry", current_price)
        highs, lows, closes = arrays
        sl, tp1, tp2, tp3, sl_pct, tp3_pct, rr = engine.calculate_risk_management(
            target_price, signal, highs, lows, closes
        )

        # 1. إرسال تنبيه رصد الفرصة وتجهيز الأمر
        notify_order_setup(symbol, signal, target_price, sl, tp3)

        # 2. إرسال تنبيه تفعيل الصفقة فوراً
        notify_trade_executed(symbol, signal, current_price, sl, tp1, tp3)

        # تسجيل الصفقة في قائمة المتابعة الحية
        active_trades[symbol] = {
            "signal": signal,
            "entry": current_price,
            "sl": sl,
            "tp1": tp1,
            "tp3": tp3,
            "be_triggered": False
        }

        with history_lock:
            signal_history[symbol] = time.time()

    except Exception as exc:
        print(f"Error processing {symbol}: {str(exc)[:100]}", flush=True)


def background_scanner():
    print("Background scanner thread with Full Telegram Alerts started...", flush=True)
    time.sleep(10)
    send_telegram_message("🤖 *تم تفعيل بوت السيولة البنكية المتقدمة (V4) مع الإشعارات التلقائية الكاملة بنجاح*")
    engine = StrategyEngine()

    while True:
        try:
            # دمج العملات المستهدفة (STRK, PYTH) مع فحص الأسواق النشطة
            markets = bingx_call("load_markets")
            all_symbols = [
                s for s, m in markets.items() 
                if m.get("swap") and m.get("linear") and s.endswith("/USDT:USDT") 
                and not any(x in s.upper() for x in ("TEST", "DEMO", "FAKE", "NCSK", "BULL", "BEAR"))
                and m.get("active", True)
            ]
            
            # التأكد من إعطاء الأولوية للعملات المطلوبة STRK و PYTH وضمن القائمة النشطة
            symbols_to_scan = list(set(TARGET_SYMBOLS + all_symbols))

            for symbol in symbols_to_scan:
                process_symbol(symbol, engine)
                time.sleep(SYMBOL_PAUSE_SECONDS)

            time.sleep(120)
        except Exception as exc:
            print(f"Scanner error: {str(exc)[:150]}", flush=True)
            time.sleep(60)


scanner_thread = threading.Thread(target=background_scanner, daemon=True, name="institutional-scanner-v4")
scanner_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
