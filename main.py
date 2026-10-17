# ==========================================
# MY EXPERT CRYPTO BOT - FINAL INTEGRATED VERSION
# BingX + Telegram + Selective SMC Scanner + Live TP/SL Tracker
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
REWARD_RATIO = max(1.0, float(os.environ.get("REWARD_RATIO", "2.0")))

signal_history = {}
active_trades = {}  # تتبع افتراضي للصفقات لمراقبة الأهداف والاستوب
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
    return "My Expert Crypto Bot - SMC Scanner & TP/SL Tracker is active!"

@app.route("/health")
def health():
    return {"status": "healthy", "service": "active"}, 200


def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram not configured: missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID", flush=True)
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
        if response.status_code != 200:
            print(f"Telegram HTTP {response.status_code}: {response.text[:200]}", flush=True)
        return response.status_code == 200
    except Exception as exc:
        print(f"Telegram error: {str(exc)[:150]}", flush=True)
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
                print(f"BingX {method_name} failed: {str(exc)[:160]}", flush=True)
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
                # منع العملات الوهمية أو عقود الاختبار والتسليم القديمة
                if any(x in sym_upper for x in ["TEST", "UP/", "DOWN/", "BULL", "BEAR"]):
                    continue
                symbols.append(symbol)
        return sorted(set(symbols))
    except Exception as exc:
        print(f"Market loading error: {str(exc)[:150]}", flush=True)
        return []


def notify_trade_executed(symbol, direction, entry_price, details):
    rm = details.get("risk_management", {})
    if not rm or "take_profit_target" not in rm or "stop_loss" not in details:
        print(f"Invalid signal details for {symbol}; not sending alert", flush=True)
        return False

    emoji = "🟢 LONG" if direction == "LONG" else "🔴 SHORT"
    fvg = details.get("fvg")
    ob = details.get("order_block")
    fvg_text = f"{fvg.get('low')} - {fvg.get('high')} ({fvg.get('type')})" if fvg else "غير متوفر"
    ob_text = f"{ob.get('low')} - {ob.get('high')}" if ob else "غير متوفر"
    sweep_text = "نعم" if details.get("liquidity_sweep") else "لا"
    mss_text = "نعم" if details.get("mss") else "لا"

    message = (
        f"🎯 *إشارة انتقائية — SMC + Breakout/Retest*\n\n"
        f"🔹 العملة: `{symbol}`\n"
        f"⚖️ الاتجاه: `{emoji}`\n"
        f"⭐ تقييم الإعداد: `{details.get('score', 0)}/100`\n"
        f"💵 سعر الإشارة: `{entry_price}`\n"
        f"🛑 وقف الخسارة: `{details['stop_loss']}`\n"
        f"🎯 الهدف: `{rm['take_profit_target']}`\n"
        f"📐 العائد/المخاطرة المستهدف: `1:{rm.get('reward_ratio', REWARD_RATIO)}`\n"
        f"💰 مخاطرة نموذجية: `${rm.get('allowed_risk_usd', 0)}` ({rm.get('risk_percent', 0)}%)\n\n"
        f"📈 اتجاه 4H: `{details.get('trend_4h', 'N/A')}` | 1H: `{details.get('trend_1h', 'N/A')}`\n"
        f"₿ اتجاه BTC: `{details.get('btc_trend', 'N/A')}`\n"
        f"📊 الفوليوم: `{details.get('volume_ratio', 0)}x` | RSI: `{details.get('rsi', 0)}`\n"
        f"🧱 BOS: `نعم` | MSS: `{mss_text}` | سحب سيولة: `{sweep_text}`\n"
        f"🟦 FVG: `{fvg_text}` | OB: `{ob_text}`\n\n"
        f"⚠️ *تنبيه:* متابعة افتراضية للأهداف ووقف الخسارة."
    )
    return send_telegram_message(message)


def process_symbol(symbol, engine):
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
        
        # فلتر السيولة: منع العملات الميتة أو الوهمية (أقل من 50 ألف دولار حجم تداول)
        if market_price <= 0 or quote_volume < 50000:
            return

        ohlcv_4h = bingx_call("fetch_ohlcv", symbol, timeframe="4h", limit=40)
        ohlcv_1h = bingx_call("fetch_ohlcv", symbol, timeframe="1h", limit=40)
        ohlcv_15m = bingx_call("fetch_ohlcv", symbol, timeframe="15m", limit=60)
        if not ohlcv_4h or not ohlcv_1h or not ohlcv_15m:
            return

        btc_ohlcv_1h = None
        if symbol != "BTC/USDT:USDT":
            btc_ohlcv_1h = bingx_call("fetch_ohlcv", "BTC/USDT:USDT", timeframe="1h", limit=40)
            if not btc_ohlcv_1h:
                return

        direction, entry_price, details = engine.analyze_market_structure(
            ohlcv_4h, ohlcv_1h, ohlcv_15m, btc_ohlcv_1h=btc_ohlcv_1h
        )
        if direction not in ("LONG", "SHORT") or not details:
            return

        level = float(details.get("breakout_level") or 0)
        atr = float(details.get("atr") or 0)
        if level > 0 and atr > 0 and abs(market_price - float(entry_price)) > 0.75 * atr:
            return

        sent = notify_trade_executed(symbol, direction, entry_price, details)
        if not sent:
            return

        with trades_lock:
            active_trades[symbol] = {
                "direction": direction,
                "entry_price": float(entry_price),
                "stop_loss": float(details["stop_loss"]),
                "take_profit": float(details["risk_management"]["take_profit_target"]),
                "timestamp": time.time(),
                "score": details.get("score", 0)
            }
        with history_lock:
            signal_history[symbol] = time.time()

    except Exception as exc:
        print(f"Error processing {symbol}: {str(exc)[:180]}", flush=True)


def live_trade_tracker():
    """مراقبة الصفقات المفتوحة وإرسال تنبيه تيليجرام فوري عند ضرب الهدف أو الستوب"""
    while True:
        try:
            time.sleep(15)
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
                    
                    hit_tp = price >= tp if direction == "LONG" else price <= tp
                    hit_sl = price <= sl if direction == "LONG" else price >= sl
                    
                    if hit_tp or hit_sl:
                        result_title = "🎯 *تم تحقيق الهدف بنجاح! (Take Profit)*" if hit_tp else "🛑 *تم ضرب وقف الخسارة! (Stop Loss)*"
                        message = (
                            f"{result_title}\n\n"
                            f"🔹 العملة: `{symbol}`\n"
                            f"📊 الاتجاه: `{direction}`\n"
                            f"💵 سعر الإشارة الأصلي: `{trade['entry_price']}`\n"
                            f"📍 السعر الحالي المرصود: `{price}`\n"
                            f"🎯 الهدف المحسوب: `{tp}` | 🛑 الوقف: `{sl}`\n\n"
                            f"🛡️ *تمت متابعة الصفقة الافتراضية بنجاح.*"
                        )
                        del active_trades[symbol]
                
                if message:
                    send_telegram_message(message)
                time.sleep(SYMBOL_PAUSE_SECONDS)
        except Exception as exc:
            print(f"Tracker error: {str(exc)[:180]}", flush=True)
            time.sleep(10)


def background_scanner():
    time.sleep(5)
    send_telegram_message(
        "🤖 *تم تشغيل الفاحص الانتقائي SMC + تتبع الأهداف الحي*\n"
        "فحص 4H/1H/15M + منع العملات الوهمية + مراقبة الأهداف والوقف."
    )
    engine = StrategyEngine(
        capital=BOT_CAPITAL_USD,
        risk_per_trade=RISK_PER_TRADE,
        reward_ratio=REWARD_RATIO
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
        except Exception as exc:
            print(f"Scanner error: {str(exc)[:180]}", flush=True)
            time.sleep(30)


scanner_thread = threading.Thread(target=background_scanner, daemon=True, name="smc-bot-scanner")
tracker_thread = threading.Thread(target=live_trade_tracker, daemon=True, name="trade-tracker")
scanner_thread.start()
tracker_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
