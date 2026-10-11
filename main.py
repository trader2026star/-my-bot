# ==========================================
# MY EXPERT CRYPTO BOT - HIGH PRECISION SMC
# File: main.py
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

SIGNAL_COOLDOWN_SECONDS = int(
    os.environ.get("SIGNAL_COOLDOWN_SECONDS", "7200")
)

signal_history = {}
history_lock = threading.Lock()

bingx = ccxt.bingx({
    "enableRateLimit": True,
    "timeout": 20000,
    "options": {
        "defaultType": "swap"
    }
})


@app.route("/")
def home():
    return "Institutional SMC & Daily Sweep Scanner Running!"


@app.route("/health")
def health():
    return {
        "status": "healthy",
        "service": "active"
    }, 200


def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }

    try:
        response = requests.post(url, json=payload, timeout=15)
        return response.status_code == 200 and response.json().get("ok", False)
    except Exception:
        return False


def is_candidate_market(symbol, market):
    if not market.get("active", True) or not market.get("swap", False):
        return False
    return symbol.endswith("/USDT:USDT")


def valid_price(value):
    try:
        number = float(value)
        return number > 0 and number == number
    except (TypeError, ValueError):
        return False


def format_price(value):
    try:
        return f"{float(value):.10g}"
    except (TypeError, ValueError):
        return str(value)


def get_entry_price(symbol):
    ticker = bingx.fetch_ticker(symbol)
    price = ticker.get("last") or ticker.get("close")
    return float(price) if valid_price(price) else None


def already_sent_recently(symbol, signal):
    key = f"{symbol}_{signal}"
    now = time.time()
    with history_lock:
        previous = signal_history.get(key)
        if previous and now - previous < SIGNAL_COOLDOWN_SECONDS:
            return True
    return False


def mark_signal_sent(symbol, signal):
    key = f"{symbol}_{signal}"
    with history_lock:
        signal_history[key] = time.time()


def build_signal_message(
    symbol, signal, score, entry, sl, tp1, tp2, sl_pct, tp1_pct, details
):
    confirmations_text = "\n".join(f"• {item}" for item in details.get("confirmations", []))
    
    return (
        "🎯 *إشارة مؤسسية فائقة الدقة (SMC & Daily Sweep)*\n\n"
        f"🔹 *العملة:* `{symbol}`\n"
        f"⚖️ *الاتجاه:* `{signal}`\n"
        f"⭐ *قوة الإعداد:* `{score}/100`\n"
        f"💵 *سعر الدخول الحاضر:* `{format_price(entry)}`\n\n"
        f"🛑 *وقف الخسارة المحمي:* `{format_price(sl)}` (-{sl_pct}%)\n"
        f"🎯 *الهدف الأول (50% المنتصف):* `{format_price(tp1)}` (+{tp1_pct}%)\n"
        f"🎯 *الهدف الثاني (الطرف المقابل):* `{format_price(tp2)}`\n\n"
        f"📅 *الاتجاه الأسبوعي:* `{details.get('trend_weekly')}`\n"
        f"📈 *قمة اليوم السابق:* `{format_price(details.get('daily_high'))}`\n"
        f"📉 *قاع اليوم السابق:* `{format_price(details.get('daily_low'))}`\n\n"
        f"✅ *التأكيدات الهيكلية المرصودة:*\n{confirmations_text}\n\n"
        f"💡 *نصيحة التنفيذ:* {details.get('retest_advice')}"
    )


def process_symbol(symbol, engine):
    try:
        ohlcv_weekly = bingx.fetch_ohlcv(symbol, timeframe="1w", limit=10)
        ohlcv_daily = bingx.fetch_ohlcv(symbol, timeframe="1d", limit=10)
        ohlcv_15m = bingx.fetch_ohlcv(symbol, timeframe="15m", limit=30)

        if not ohlcv_weekly or not ohlcv_daily or not ohlcv_15m:
            return

        signal, score, _, details, price_arrays = engine.analyze_multi_timeframe(
            ohlcv_weekly, ohlcv_daily, ohlcv_15m
        )

        if signal not in ("LONG", "SHORT") or score < 75:
            return

        if not details.get("entry_valid", False):
            return

        if already_sent_recently(symbol, signal):
            return

        entry = get_entry_price(symbol)
        if not valid_price(entry):
            return

        highs, lows, closes = price_arrays
        daily_high = details.get("daily_high")
        daily_low = details.get("daily_low")

        sl, tp1, tp2, tp3, sl_pct, tp1_pct, rr_ratio = engine.calculate_risk_management(
            entry, signal, highs, lows, daily_high, daily_low
        )

        # فلاتر حماية صارمة لسلامة الأرقام والاتجاه
        if signal == "SHORT" and (sl <= entry or tp1 >= entry):
            return
        if signal == "LONG" and (sl >= entry or tp1 <= entry):
            return

        if sl_pct <= 0.1 or sl_pct > 5.5:  # استبعاد الأوقاف الشاسعة أو المتناهية الصغر
            return

        message = build_signal_message(
            symbol=symbol,
            signal=signal,
            score=score,
            entry=entry,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            sl_pct=sl_pct,
            tp1_pct=tp1_pct,
            details=details
        )

        if send_telegram_message(message):
            mark_signal_sent(symbol, signal)

    except Exception as exc:
        print(f"Error processing {symbol}: {exc}")


def background_scanner():
    time.sleep(10)
    send_telegram_message("🚀 *تم إطلاق المحرك المؤسسي المطور بدعم الساعات الثلاث للسيولة (بتوقيت مكة)*")

    engine = StrategyEngine()

    while True:
        try:
            markets = bingx.load_markets()
            symbols = [s for s, m in markets.items() if is_candidate_market(s, m)]

            for symbol in symbols:
                process_symbol(symbol, engine)
                time.sleep(0.35)

            time.sleep(180)
        except Exception as exc:
            print(f"Global error: {exc}")
            time.sleep(60)


def start_scanner_once():
    if not getattr(app, "_scanner_started", False):
        app._scanner_started = True
        thread = threading.Thread(target=background_scanner, daemon=True)
        thread.start()


start_scanner_once()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
