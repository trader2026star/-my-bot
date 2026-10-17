# ==========================================
# MAIN BOT ENGINE (BingX & Telegram Connected)
# Advanced SMC & Live Trades Tracker Integrated
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
SYMBOL_PAUSE_SECONDS = max(0.10, float(os.environ.get("SYMBOL_PAUSE_SECONDS", "0.20")))
MAX_API_RETRIES = max(0, min(3, int(os.environ.get("MAX_API_RETRIES", "3"))))

signal_history = {}
active_trades = {}  # قاموس لتتبع الصفقات المفتوحة لحساب الأهداف والوقف
history_lock = threading.Lock()
trades_lock = threading.Lock()
api_lock = threading.Lock()
_last_api_request = 0.0
_api_cooldown_until = 0.0

# اتصال منصة بينجكس (دون أي تغيير)
bingx = ccxt.bingx({
    "enableRateLimit": True,
    "timeout": 20000,
    "options": {"defaultType": "swap"}
})

@app.route("/")
def home():
    return "Crypto SMC & Breakout Bot is active!"

@app.route("/health")
def health():
    return {"status": "healthy", "service": "active"}, 200

# أدوات الاتصال بتليجرام (دون أي تغيير)
def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
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
            err_str = str(exc)
            if "pause" in err_str or "109415" in err_str or "invalid" in err_str.lower():
                return None
            if attempt >= MAX_API_RETRIES:
                raise
            time.sleep(2.0)
    return None

def get_all_usdt_symbols():
    try:
        markets = bingx_call("load_markets")
        if not markets:
            return []
        symbols = []
        for symbol, market in markets.items():
            if market.get("linear", False) and market.get("quote") == "USDT" and market.get("active", True):
                if "/USDT:USDT" in symbol:
                    symbols.append(symbol)
        return symbols
    except Exception:
        return []

def notify_trade_executed(symbol, direction, entry_price, details):
    rm = details["risk_management"]
    direction_emoji = "🟢 LONG" if direction == "LONG" else "🔴 SHORT"
    
    msg = (
        f"🚀 *إشارة صفقة جديدة (SMC Breakout & Retest)*\n\n"
        f"🔹 العملة: `{symbol}`\n"
        f"⚖️ الاتجاه: `{direction_emoji}`\n"
        f"💵 سعر الدخول: `{entry_price}`\n"
        f"🛑 وقف الخسارة: `{details['stop_loss']}`\n"
        f"🎯 الهدف المقترح: `{rm['take_profit_target']}`\n"
        f"💰 المخاطرة المحسوبة: `${rm['allowed_risk_usd']}` (2%)\n"
        f"📊 النمط: `{details.get('setup', 'SMC 15M Setup')}`\n\n"
        "✅ *تم فحص اتجاه 4H/1H، الهيكل، والزخم بنجاح.*"
    )
    send_telegram_message(msg)

def process_symbol(symbol, engine):
    try:
        ticker = bingx_call("fetch_ticker", symbol)
        if not ticker:
            return
        current_price = float(ticker.get("last") or ticker.get("close") or 0)
        if current_price <= 0:
            return

        global signal_history
        now_time = time.time()
        with history_lock:
            last_time = signal_history.get(symbol, 0)
            if now_time - last_time < SIGNAL_COOLDOWN_SECONDS:
                return

        # جلب البيانات متعددة الفريمات لتطبيق الاستراتيجية الجديدة
        ohlcv_4h = bingx_call("fetch_ohlcv", symbol, timeframe="4h", limit=30)
        ohlcv_1h = bingx_call("fetch_ohlcv", symbol, timeframe="1h", limit=30)
        ohlcv_15m = bingx_call("fetch_ohlcv", symbol, timeframe="15m", limit=40)

        if not ohlcv_4h or not ohlcv_1h or not ohlcv_15m:
            return

        # فحص الاستراتيجية الجديدة (SMC + 4H/1H Trend + 15M Breakout/Retest)
        direction, entry_price, details = engine.analyze_market_structure(ohlcv_4h, ohlcv_1h, ohlcv_15m)

        if direction in ("LONG", "SHORT"):
            notify_trade_executed(symbol, direction, entry_price, details)
            
            # تسجيل الصفقة في المتابعة الحية لتتبع الأهداف والاستوب
            with trades_lock:
                active_trades[symbol] = {
                    "direction": direction,
                    "entry_price": entry_price,
                    "stop_loss": details["stop_loss"],
                    "take_profit": details["risk_management"]["take_profit_target"],
                    "timestamp": time.time()
                }

            with history_lock:
                signal_history[symbol] = time.time()

    except Exception as exc:
        print(f"Error processing {symbol}: {str(exc)[:100]}", flush=True)

# ==========================================
# نظام تتبع الصفقات الحي (TP / SL Tracker)
# ==========================================
def live_trade_tracker():
    """تتبع حركة الصفقات النشطة وإرسال إشعارات الأهداف والوقف فور تحققها"""
    while True:
        try:
            time.sleep(15)
            with trades_lock:
                if not active_trades:
                    continue

                symbols_to_check = list(active_trades.keys())

            for symbol in symbols_to_check:
                ticker = bingx_call("fetch_ticker", symbol)
                if not ticker:
                    continue
                current_price = float(ticker.get("last") or ticker.get("close") or 0)
                if current_price <= 0:
                    continue

                with trades_lock:
                    trade = active_trades.get(symbol)
                    if not trade:
                        continue

                    direction = trade["direction"]
                    tp = trade["take_profit"]
                    sl = trade["stop_loss"]

                    # فحص صفقات الـ LONG
                    if direction == "LONG":
                        if current_price >= tp:
                            msg = (
                                f"🎯 *تم تحقيق الهدف بنجاح! (Take Profit)*\n\n"
                                f"🔹 العملة: `{symbol}`\n"
                                f"📈 الاتجاه: `LONG`\n"
                                f"💵 سعر الدخول: `{trade['entry_price']}`\n"
                                f"🎯 السعر الحالي: `{current_price}` (وصل للهدف: `{tp}`)\n"
                                f"🎉 *صفقة رابحة وفقاً لإدارة المخاطر!*"
                            )
                            send_telegram_message(msg)
                            del active_trades[symbol]
                        elif current_price <= sl:
                            msg = (
                                f"🛑 *تم ضرب وقف الخسارة (Stop Loss)*\n\n"
                                f"🔹 العملة: `{symbol}`\n"
                                f"📈 الاتجاه: `LONG`\n"
                                f"💵 سعر الدخول: `{trade['entry_price']}`\n"
                                f"🛑 السعر الحالي: `{current_price}` (ضرب الاستوب: `{sl}`)\n"
                                f"🛡️ *خسارة منضبطة ضمن نطاق المخاطرة 2%*"
                            )
                            send_telegram_message(msg)
                            del active_trades[symbol]

                    # فحص صفقات الـ SHORT
                    elif direction == "SHORT":
                        if current_price <= tp:
                            msg = (
                                f"🎯 *تم تحقيق الهدف بنجاح! (Take Profit)*\n\n"
                                f"🔹 العملة: `{symbol}`\n"
                                f"📉 الاتجاه: `SHORT`\n"
                                f"💵 سعر الدخول: `{trade['entry_price']}`\n"
                                f"🎯 السعر الحالي: `{current_price}` (وصل للهدف: `{tp}`)\n"
                                f"🎉 *صفقة رابحة وفقاً لإدارة المخاطر!*"
                            )
                            send_telegram_message(msg)
                            del active_trades[symbol]
                        elif current_price >= sl:
                            msg = (
                                f"🛑 *تم ضرب وقف الخسارة (Stop Loss)*\n\n"
                                f"🔹 العملة: `{symbol}`\n"
                                f"📉 الاتجاه: `SHORT`\n"
                                f"💵 سعر الدخول: `{trade['entry_price']}`\n"
                                f"🛑 السعر الحالي: `{current_price}` (ضرب الاستوب: `{sl}`)\n"
                                f"🛡️ *خسارة منضبطة ضمن نطاق المخاطرة 2%*"
                            )
                            send_telegram_message(msg)
                            del active_trades[symbol]

                time.sleep(SYMBOL_PAUSE_SECONDS)

        except Exception as exc:
            print(f"Tracker error: {str(exc)[:150]}", flush=True)
            time.sleep(10)

def background_scanner():
    time.sleep(5)
    send_telegram_message("🤖 *تم تفعيل بوت التداول المتقدم (SMC + Multi-Timeframe + Risk Management) بنجاح*")
    engine = StrategyEngine(capital=10000, risk_per_trade=0.02, reward_ratio=2.0)

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
            print(f"Scanner error: {str(exc)[:150]}", flush=True)
            time.sleep(30)

# تشغيل الفاحص وخيط التتبع في الخلفية
scanner_thread = threading.Thread(target=background_scanner, daemon=True, name="smc-bot-scanner")
tracker_thread = threading.Thread(target=live_trade_tracker, daemon=True, name="trade-tracker")

scanner_thread.start()
tracker_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
