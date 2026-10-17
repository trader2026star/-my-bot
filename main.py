# ==========================================
# MAIN BOT ENGINE (BingX & Telegram Connected)
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
active_trades = {}
history_lock = threading.Lock()
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
    return "Crypto Full Bot (On-Chain + Technical + Risk) is active!"

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

def notify_trade_executed(symbol, data):
    rm = data["risk_management"]
    msg = (
        "🚀 *إشارة صفقة جديدة (Advanced Bot Filter)*\n\n"
        f"🔹 العملة: `{symbol}`\n"
        f"⚖️ الاتجاه: `LONG`\n"
        f"💵 سعر الدخول: `{data['entry_price']}`\n"
        f"🛑 وقف الخسارة: `{data['stop_loss']}`\n"
        f"🎯 الهدف المقترح (1:2): `{rm['take_profit_target']}`\n"
        f"💰 القيمة المخاطر بها: `${rm['allowed_risk_usd']}`\n"
        "✅ *اجتاز الفلاتر الفنية، الحيتان، وإدارة المخاطر بنجاح.*"
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

        # جلب تاريخ الأسعار لفحص المؤشرات الفنية
        ohlcv = bingx_call("fetch_ohlcv", symbol, timeframe="1h", limit=220)
        if not ohlcv or len(ohlcv) < 50:
            return

        closes = [row[4] for row in ohlcv]
        lows = [row[3] for row in ohlcv]
        
        # تحديد نقطة وقف الخسارة تحت أدنى قاع حديث تلقائياً
        stop_loss_price = float(min(lows[-10:])) * 0.995

        # تنفيذ فحص استراتيجية الفلاتر المتسلسلة الجديدة
        result = engine.execute_bot_logic(symbol, closes, stop_loss_price)

        if result.get("status") == "EXECUTE_LONG_TRADE":
            notify_trade_executed(symbol, result)
            with history_lock:
                signal_history[symbol] = time.time()

    except Exception as exc:
        print(f"Error processing {symbol}: {str(exc)[:100]}", flush=True)

def background_scanner():
    time.sleep(5)
    send_telegram_message("🤖 *تم تفعيل بوت التداول المتقدم (Multi-Filter & Risk Management) بنجاح*")
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

scanner_thread = threading.Thread(target=background_scanner, daemon=True, name="full-bot-scanner")
scanner_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
