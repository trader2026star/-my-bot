# ==========================================
# MY EXPERT CRYPTO BOT - TOP-DOWN ANALYSIS V8.0
# BingX + Telegram + Multi-Timeframe Alignment + SL/TP Tracker
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
SIGNAL_COOLDOWN_SECONDS = max(60, int(os.environ.get("SIGNAL_COOLDOWN_SECONDS", "7200")))
API_MIN_INTERVAL_SECONDS = max(0.25, float(os.environ.get("API_MIN_INTERVAL_SECONDS", "0.50")))
SYMBOL_PAUSE_SECONDS = max(0.10, float(os.environ.get("SYMBOL_PAUSE_SECONDS", "0.20")))
MAX_API_RETRIES = max(0, min(3, int(os.environ.get("MAX_API_RETRIES", "2"))))

BOT_CAPITAL_USD = max(1.0, float(os.environ.get("BOT_CAPITAL_USD", "1000")))
RISK_PER_TRADE = min(0.02, max(0.001, float(os.environ.get("RISK_PER_TRADE", "0.01"))))

consecutive_losses = 0
max_allowed_consecutive_losses = 2
bot_locked_out = False
lockout_reset_time = 0

signal_history = {}
active_trades = {}
history_lock = threading.Lock()
trades_lock = threading.Lock()
api_lock = threading.Lock()
_last_api_request = 0.0
_api_cooldown_until = 0.0

bingx = ccxt.bingx({
    "enableRateLimit": True,
    "timeout": 20000,
    "options": {"defaultType": "swap"}
})

@app.route("/")
def home():
    return "Top-Down Analysis Bot V8.0 is active!"

@app.route("/health")
def health():
    return {"status": "healthy", "locked_out": bot_locked_out}, 200


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
    except Exception:
        return False


def bingx_call(method_name, *args, **kwargs):
    global _last_api_request, _api_cooldown_until
    method = getattr(bingx, method_name)
    for attempt in range(MAX_API_RETRIES + 1):
        with api_lock:
            now = time.monotonic()
            wait_for = max(
                0.0,
                API_MIN_INTERVAL_SECONDS - (now - _last_api_request),
                _api_cooldown_until - now
            )
            if wait_for > 0:
                time.sleep(wait_for)
            _last_api_request = time.monotonic()
        try:
            return method(*args, **kwargs)
        except Exception as exc:
            err = str(exc).lower()
            if any(x in err for x in ("109415", "invalid symbol", "does not have market")):
                return None
            if attempt >= MAX_API_RETRIES:
                return None
            time.sleep(1.5 * (attempt + 1))
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
                sym_upper = symbol.upper()
                base_asset = symbol.split('/')[0].upper()
                if any(x in sym_upper for x in ["TEST", "UP/", "DOWN/", "BULL", "BEAR", "TZA", "USD/"]):
                    continue
                if any(char.isdigit() for char in base_asset) and not base_asset.startswith("1000"):
                    continue
                if len(base_asset) > 8:
                    continue
                symbols.append(symbol)
        return sorted(set(symbols))
    except Exception:
        return []


def notify_trade_executed(symbol, direction, entry_price, details):
    rm = details.get("risk_management", {})
    if not rm or "take_profit_1" not in rm or "stop_loss" not in details:
        return False

    message = (
        f"🎯 *إشارة التحليل الهرمي المتوافق (Top-Down Analysis)* 🎯\n\n"
        f"🔹 العملة: `{symbol}`\n"
        f"⚖️ الاتجاه: `🟢 LONG (شراء)`\n"
        f"📈 توافق الفريمات: `4H اتجاه صاعد ➔ 1H مستوى رئيسي ➔ 15M تنفيذ`\n"
        f"💵 سعر الدخول: `{entry_price}`\n"
        f"🟥 وقف الخسارة (Stop Loss): `{rm['stop_loss']}`\n"
        f"🟩 الهدف الأول (TP 1): `{rm['take_profit_1']}`\n"
        f"🟩 الهدف الثاني (TP 2): `{rm['take_profit_2']}`\n"
        f"📍 المستوى الرئيسي (Key Level): `{details.get('key_level')}`\n\n"
        f"⚠️ *متابعة الأهداف والستوب الآلي مفعلة بنجاح.*"
    )
    return send_telegram_message(message)


def process_symbol(symbol, engine):
    global bot_locked_out, lockout_reset_time
    if bot_locked_out:
        if time.time() > lockout_reset_time:
            bot_locked_out = False
            consecutive_losses = 0
            send_telegram_message("♻️ *تم فك الحماية المؤقتة واستئناف العمل.*")
        else:
            return

    try:
        now = time.time()
        with history_lock:
            if now - signal_history.get(symbol, 0) < SIGNAL_COOLDOWN_SECONDS:
                return

        ticker = bingx_call("fetch_ticker", symbol)
        if not ticker:
            return
        market_price = float(ticker.get("last") or ticker.get("close") or 0)
        quote_volume = float(ticker.get("quoteVolume") or ticker.get("baseVolume") or 0)
        
        if market_price <= 0 or quote_volume < 500000:
            return

        ohlcv_4h = bingx_call("fetch_ohlcv", symbol, timeframe="4h", limit=40)
        ohlcv_1h = bingx_call("fetch_ohlcv", symbol, timeframe="1h", limit=50)
        ohlcv_15m = bingx_call("fetch_ohlcv", symbol, timeframe="15m", limit=40)
        if not ohlcv_4h or not ohlcv_1h or not ohlcv_15m:
            return

        direction, entry_price, details = engine.analyze_market_structure(
            ohlcv_4h, ohlcv_1h, ohlcv_15m
        )
        if direction != "LONG" or not details:
            return

        sent = notify_trade_executed(symbol, direction, entry_price, details)
        if not sent:
            return

        with trades_lock:
            active_trades[symbol] = {
                "direction": direction,
                "entry_price": float(entry_price),
                "stop_loss": float(details["stop_loss"]),
                "take_profit": float(details["risk_management"]["take_profit_2"]),
                "timestamp": time.time()
            }
        with history_lock:
            signal_history[symbol] = time.time()

    except Exception:
        pass


def live_trade_tracker():
    global consecutive_losses, bot_locked_out, lockout_reset_time
    max_trade_duration_seconds = 43200
    
    while True:
        try:
            time.sleep(15)
            now = time.time()
            with trades_lock:
                symbols = list(active_trades.keys())
            
            for symbol in symbols:
                ticker = bingx_call("fetch_ticker", symbol)
                if not ticker:
                    continue
                price = float(ticker.get("last") or ticker.get("close") or 0)
                if price <= 0:
                    continue

                message = None
                with trades_lock:
                    trade = active_trades.get(symbol)
                    if not trade:
                        continue
                    direction = trade["direction"]
                    tp, sl = trade["take_profit"], trade["stop_loss"]
                    
                    hit_tp = price >= tp
                    hit_sl = price <= sl
                    expired = (now - trade["timestamp"]) > max_trade_duration_seconds
                    
                    if hit_tp or hit_sl or expired:
                        if hit_tp:
                            consecutive_losses = 0
                            result_title = "🎯 *تم تحقيق الهدف بنجاح! (Take Profit)*"
                        elif hit_sl:
                            consecutive_losses += 1
                            result_title = "🛑 *تم ضرب وقف الخسارة! (Stop Loss)*"
                            if consecutive_losses >= max_allowed_consecutive_losses:
                                bot_locked_out = True
                                lockout_reset_time = time.time() + 14400
                                send_telegram_message(
                                    "🛡️ *درع الحماية الآلي مفعل*\n"
                                    "تم إيقاف البوت مؤقتًا لمدة 4 ساعات لحماية الرصيد."
                                )
                        else:
                            result_title = "⏰ *إغلاق زمني للصفقة*"

                        message = (
                            f"{result_title}\n\n"
                            f"🔹 العملة: `{symbol}`\n"
                            f"📊 الاتجاه: `{direction}`\n"
                            f"💵 سعر الإشارة: `{trade['entry_price']}`\n"
                            f"📍 السعر الحالي: `{price}`\n"
                            f"🎯 الهدف النهائي: `{tp}` | 🛑 الوقف: `{sl}`"
                        )
                        del active_trades[symbol]
                
                if message:
                    send_telegram_message(message)
                time.sleep(SYMBOL_PAUSE_SECONDS)
        except Exception:
            time.sleep(10)


def background_scanner():
    time.sleep(5)
    send_telegram_message(
        "🤖 *تم تشغيل بوت التحليل الهرمي (Top-Down Analysis V8.0)*\n"
        "التحليل من أعلى لأسفل (4H اتجاه ➔ 1H مستويات ➔ 15M دخول) مفعل بنجاح."
    )
    engine = StrategyEngine(
        capital=BOT_CAPITAL_USD,
        risk_per_trade=RISK_PER_TRADE
    )
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
        except Exception:
            time.sleep(30)


scanner_thread = threading.Thread(target=background_scanner, daemon=True, name="topdown-bot-scanner")
tracker_thread = threading.Thread(target=live_trade_tracker, daemon=True, name="trade-tracker")
scanner_thread.start()
tracker_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
