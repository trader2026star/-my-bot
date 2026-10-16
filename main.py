# ==========================================
# ENGULFING STRATEGY BOT - MAIN (V6.0 - Engulfing Hybrid)
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
SYMBOL_PAUSE_SECONDS = max(0.10, float(os.environ.get("SYMBOL_PAUSE_SECONDS", "0.30")))
MAX_API_RETRIES = max(0, min(3, int(os.environ.get("MAX_API_RETRIES", "3"))))

signal_history = {}
active_trades = {}
history_lock = threading.Lock()
api_lock = threading.Lock()
_last_api_request = 0.0
_api_cooldown_until = 0.0

bingx = ccxt.bingx({
    "enableRateLimit": True,
    "timeout": 20000,
    "options": {"defaultType": "swap"}
})

# قائمة العملات المراقبة (تمت إضافة GTC بنجاح)
SELECTED_SYMBOLS = [
    "BTC/USDT:USDT",
    "GTC/USDT:USDT",
    "PYTH/USDT:USDT",
    "STRK/USDT:USDT",
    "ZEREBRO/USDT:USDT",
    "LDO/USDT:USDT",
    "RLC/USDT:USDT",
    "FF/USDT:USDT",
    "ZK/USDT:USDT",
    "LYN/USDT:USDT",
    "TIA/USDT:USDT",
    "GPS/USDT:USDT",
    "WCT/USDT:USDT",
    "AGT/USDT:USDT"
]


@app.route("/")
def home():
    return "Engulfing Strategy Bot is active!"


@app.route("/health")
def health():
    return {"status": "healthy", "service": "active"}, 200


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
                print(f"Skipping paused/invalid symbol error: {err_str[:80]}")
                return None
            if attempt >= MAX_API_RETRIES:
                raise
            time.sleep(2.0)

    return None


def fmt(value):
    try:
        return f"{float(value):.10g}"
    except Exception:
        return str(value)


def notify_trade_executed(symbol, signal, entry, sl, tp1, tp2, tp3, confirmations):
    conf_text = "\n".join(f"• {x}" for x in confirmations)

    msg = (
        "🚀 *إشارة صفقة جديدة (Engulfing Pattern)*\n\n"
        f"🔹 العملة: `{symbol}`\n"
        f"⚖️ الاتجاه: `{signal}`\n"
        f"💵 سعر الدخول: `{fmt(entry)}`\n"
        f"🛑 وقف الخسارة (الإبطال): `{fmt(sl)}`\n\n"
        f"🎯 *الأهداف المستهدفة:*\n"
        f"• الهدف الأول (تأمين وبداية جني أرباح): `{fmt(tp1)}`\n"
        f"• الهدف الثاني: `{fmt(tp2)}`\n"
        f"• الهدف الثالث (النهائي 1:3): `{fmt(tp3)}`\n\n"
        f"✅ *تفاصيل النموذج السعري:*\n{conf_text}\n\n"
        "⚡ *تم رصد النمط وتفعيل المتابعة اللحظية.*"
    )
    send_telegram_message(msg)


def notify_breakeven(symbol, entry):
    msg = (
        "🛡️ *تحديث حماية الصفقة (Break-even)*\n\n"
        f"🔹 العملة: `{symbol}`\n"
        f"🔒 تم بلوغ الهدف الأول ونقل وقف الخسارة لسعر الدخول: `{fmt(entry)}`\n"
        "✨ *الصفقة أصبحت آمنة تماماً!*"
    )
    send_telegram_message(msg)


def notify_trade_closed(symbol, result_type, exit_price):
    icon = "🎯" if result_type == "TARGET" else "🛑"
    title = "تم تحقيق الهدف النهائي بنجاح!" if result_type == "TARGET" else "تم ضرب وقف الخسارة."
    msg = (
        f"{icon} *إغلاق الصفقة: {title}*\n\n"
        f"🔹 العملة: `{symbol}`\n"
        f"🏁 سعر الخروج: `{fmt(exit_price)}`"
    )
    send_telegram_message(msg)


def monitor_active_trades(symbol, current_price):
    if symbol not in active_trades:
        return

    trade = active_trades[symbol]
    signal = trade["signal"]
    sl = trade["sl"]
    tp1 = trade["tp1"]
    tp3 = trade["tp3"]
    entry = trade["entry"]
    be_triggered = trade["be_triggered"]

    if signal == "LONG":
        if not be_triggered and current_price >= tp1:
            active_trades[symbol]["be_triggered"] = True
            active_trades[symbol]["sl"] = entry
            notify_breakeven(symbol, entry)
        elif current_price >= tp3:
            notify_trade_closed(symbol, "TARGET", current_price)
            del active_trades[symbol]
        elif current_price <= sl:
            notify_trade_closed(symbol, "STOP", current_price)
            del active_trades[symbol]

    elif signal == "SHORT":
        if not be_triggered and current_price <= tp1:
            active_trades[symbol]["be_triggered"] = True
            active_trades[symbol]["sl"] = entry
            notify_breakeven(symbol, entry)
        elif current_price <= tp3:
            notify_trade_closed(symbol, "TARGET", current_price)
            del active_trades[symbol]
        elif current_price >= sl:
            notify_trade_closed(symbol, "STOP", current_price)
            del active_trades[symbol]


def process_symbol(symbol, engine):
    try:
        ticker = bingx_call("fetch_ticker", symbol)
        if not ticker:
            return
        current_price = float(ticker.get("last") or ticker.get("close") or 0)
        if current_price <= 0:
            return

        if symbol in active_trades:
            monitor_active_trades(symbol, current_price)
            return

        global signal_history
        now_time = time.time()
        with history_lock:
            last_time = signal_history.get(symbol, 0)
            if now_time - last_time < SIGNAL_COOLDOWN_SECONDS:
                return

        ohlcv_1h = bingx_call("fetch_ohlcv", symbol, timeframe="1h", limit=30)
        ohlcv_5m = bingx_call("fetch_ohlcv", symbol, timeframe="5m", limit=30)
        if not ohlcv_1h or not ohlcv_5m:
            return

        signal, score, volume_ratio, details, arrays = engine.analyze_institutional_setup(
            ohlcv_1h, ohlcv_5m, symbol=symbol
        )

        if signal not in ("LONG", "SHORT") or score < 80:
            return

        target_price = details.get("predictive_entry", current_price)
        highs, lows, closes = arrays
        sl, tp1, tp2, tp3, sl_pct, tp3_pct, rr = engine.calculate_risk_management(
            target_price, signal, highs, lows, closes
        )

        notify_trade_executed(
            symbol, signal, current_price, sl, tp1, tp2, tp3, 
            details.get("confirmations", [])
        )

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
    print("Engulfing Strategy Scanner started...", flush=True)
    time.sleep(5)
    send_telegram_message("🤖 *تم تفعيل بوت النماذج الابتلاعية (Engulfing Bot) بنجاح وقيد العمل*")
    engine = StrategyEngine()

    while True:
        try:
            for symbol in SELECTED_SYMBOLS:
                process_symbol(symbol, engine)
                time.sleep(SYMBOL_PAUSE_SECONDS)

            time.sleep(20)
        except Exception as exc:
            print(f"Scanner error: {str(exc)[:150]}", flush=True)
            time.sleep(20)


scanner_thread = threading.Thread(target=background_scanner, daemon=True, name="engulfing-scanner")
scanner_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
