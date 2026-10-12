
# ==========================================
# MY EXPERT CRYPTO BOT
# ADVANCED SMC & QUANTITATIVE SCANNER
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

# Keep the current Render environment variable names.
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
    return "My Expert Crypto Bot - Advanced SMC Scanner is running!"


@app.route("/health")
def health():
    return {
        "status": "healthy",
        "service": "active"
    }, 200


def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(
            "Telegram credentials missing. "
            "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID."
        )
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }

    try:
        response = requests.post(
            url,
            json=payload,
            timeout=15
        )

        if response.status_code != 200:
            print(
                f"Telegram HTTP error: "
                f"{response.status_code} {response.text[:300]}"
            )
            return False

        result = response.json()

        if not result.get("ok", False):
            print(f"Telegram API error: {result}")
            return False

        return True

    except Exception as exc:
        print(f"Telegram sending error: {exc}")
        return False


def is_candidate_market(symbol, market):
    """Accept active BingX USDT perpetual swap markets."""
    if not market.get("active", True):
        return False

    if not market.get("swap", False):
        return False

    if not symbol.endswith("/USDT:USDT"):
        return False

    base = symbol.split("/")[0].upper()

    # Exclude obvious fiat symbols without broad substring exclusions.
    excluded_bases = {
        "EUR", "GBP", "AUD", "NZD",
        "CAD", "CHF", "JPY", "FX"
    }

    if base in excluded_bases:
        return False

    return True


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
    price = ticker.get("last")

    if not valid_price(price):
        price = ticker.get("close")

    if not valid_price(price):
        return None

    return float(price)


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
    symbol,
    signal,
    score,
    volume_ratio,
    entry,
    sl,
    tp1,
    tp2,
    tp3,
    sl_pct,
    tp1_pct,
    rr_ratio,
    details
):
    confirmations = details.get("confirmations", [])
    exclusions = details.get("reasons_excluded", [])

    confirmations_text = "\n".join(
        f"• {item}" for item in confirmations
    ) or "• لا توجد تأكيدات إضافية"

    exclusions_text = "\n".join(
        f"• {item}" for item in exclusions
    ) or "• لا توجد ملاحظات إضافية"

    ob_zone = details.get("ob_zone")

    if ob_zone:
        ob_text = (
            f"{format_price(ob_zone[0])} - "
            f"{format_price(ob_zone[1])}"
        )
    else:
        ob_text = "غير محددة"

    return (
        "📊 *إشارة SMC مرشحة — ليست ضمانًا للربح*\n\n"
        f"🔹 *العملة:* `{symbol}`\n"
        f"⚖️ *الاتجاه:* `{signal}`\n"
        f"⭐ *درجة الإعداد:* `{score}/100`\n"
        f"📈 *الفوليوم:* `{volume_ratio}x المتوسط`\n"
        f"💵 *سعر الدخول المرجعي:* `{format_price(entry)}`\n\n"
        f"🛑 *وقف الخسارة:* `{format_price(sl)}` "
        f"(-{sl_pct}%)\n"
        f"🎯 *TP1:* `{format_price(tp1)}` "
        f"(+{tp1_pct}%)\n"
        f"🎯 *TP2:* `{format_price(tp2)}`\n"
        f"🎯 *TP3:* `{format_price(tp3)}`\n"
        f"⚖️ *نسبة العائد للمخاطرة التقديرية:* `{rr_ratio}`\n\n"
        f"🧭 *اتجاه 4H:* `{details.get('trend_4h')}`\n"
        f"🧭 *اتجاه 1H:* `{details.get('trend_1h')}`\n"
        f"₿ *اتجاه BTC:* `{details.get('btc_trend')}`\n"
        f"🧱 *BOS:* `{details.get('bos')}`\n"
        f"🔄 *MSS:* `{details.get('mss')}`\n"
        f"💧 *Liquidity Sweep:* `{details.get('sweep')}`\n"
        f"🟦 *FVG:* `{details.get('fvg')}`\n"
        f"📦 *منطقة OB المرشحة:* `{ob_text}`\n"
        f"📉 *الدعم التقريبي:* "
        f"`{format_price(details.get('support'))}`\n"
        f"📈 *المقاومة التقريبية:* "
        f"`{format_price(details.get('resistance'))}`\n\n"
        f"✅ *التأكيدات المرصودة:*\n{confirmations_text}\n\n"
        f"⚠️ *ملاحظات المخاطر:*\n{exclusions_text}\n\n"
        f"🔎 *ملاحظة الدخول:* "
        f"{details.get('retest_advice', 'راجع الشارت قبل التنفيذ')}\n\n"
        "⚠️ السعر قد يتغير قبل تنفيذ الصفقة. "
        "راجع السبريد والرافعة وحجم الصفقة بنفسك."
    )


def process_symbol(symbol, engine, btc_ohlcv):
    try:
        # Multi-timeframe data from BingX.
        ohlcv_4h = bingx.fetch_ohlcv(
            symbol, timeframe="4h", limit=40
        )
        ohlcv_1h = bingx.fetch_ohlcv(
            symbol, timeframe="1h", limit=60
        )
        ohlcv_15m = bingx.fetch_ohlcv(
            symbol, timeframe="15m", limit=40
        )

        if not ohlcv_4h or not ohlcv_1h or not ohlcv_15m:
            return

        signal, score, volume_ratio, details, price_arrays = (
            engine.analyze_multi_timeframe(
                ohlcv_4h,
                ohlcv_1h,
                ohlcv_15m,
                btc_ohlcv
            )
        )

        # Strict entry filters.
        if signal not in ("LONG", "SHORT"):
            return

        if score < 70:
            return

        if not details.get("entry_valid", False):
            return

        if volume_ratio < 1.0:
            return

        if already_sent_recently(symbol, signal):
            return

        entry = get_entry_price(symbol)

        if not valid_price(entry):
            print(f"Invalid price for {symbol}; skipped.")
            return

        highs, lows, closes = price_arrays

        # This method returns SEVEN values.
        sl, tp1, tp2, tp3, sl_pct, tp1_pct, rr_ratio = (
            engine.calculate_risk_management(
                entry,
                signal,
                highs,
                lows,
                closes
            )
        )

        if not all(
            valid_price(x)
            for x in (sl, tp1, tp2, tp3)
        ):
            print(f"Invalid risk levels for {symbol}; skipped.")
            return

        # Check price ordering for the selected direction.
        if signal == "LONG":
            if not (sl < entry < tp1 < tp2 < tp3):
                print(f"Incorrect LONG price order: {symbol}")
                return

        elif signal == "SHORT":
            if not (tp3 < tp2 < tp1 < entry < sl):
                print(f"Incorrect SHORT price order: {symbol}")
                return

        # Reject excessive stop distance and poor estimated R:R.
        if sl_pct <= 0 or sl_pct > 7:
            print(f"Risk filter rejected {symbol}: SL={sl_pct}%")
            return

        if rr_ratio < 1.0:
            print(f"R:R filter rejected {symbol}: RR={rr_ratio}")
            return

        message = build_signal_message(
            symbol=symbol,
            signal=signal,
            score=score,
            volume_ratio=volume_ratio,
            entry=entry,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            tp3=tp3,
            sl_pct=sl_pct,
            tp1_pct=tp1_pct,
            rr_ratio=rr_ratio,
            details=details
        )

        # Start cooldown only if Telegram confirms delivery.
        if send_telegram_message(message):
            mark_signal_sent(symbol, signal)
            print(
                f"Signal sent: {symbol} {signal}, "
                f"score={score}, RR={rr_ratio}"
            )

    except (ccxt.NetworkError, ccxt.ExchangeError) as exc:
        print(f"BingX error for {symbol}: {exc}")

    except Exception as exc:
        print(f"Error processing {symbol}: {exc}")


def background_scanner():
    time.sleep(10)

    send_telegram_message(
        "🤖 *تم تشغيل ماسح السوق SMC بنجاح*\n"
        "تم تفعيل فلاتر الاتجاه والهيكل والسيولة والفوليوم "
        "وإدارة المخاطر.\n"
        "الإشارات احتمالية وليست ضمانًا للربح."
    )

    engine = StrategyEngine()

    while True:
        try:
            markets = bingx.load_markets()

            symbols = [
                symbol
                for symbol, market in markets.items()
                if is_candidate_market(symbol, market)
            ]

            print(f"Scanner cycle started. Markets: {len(symbols)}")

            btc_ohlcv = []

            try:
                btc_ohlcv = bingx.fetch_ohlcv(
                    "BTC/USDT:USDT",
                    timeframe="1h",
                    limit=30
                )
            except Exception as exc:
                print(f"BTC context unavailable: {exc}")

            for index, symbol in enumerate(symbols, start=1):
                try:
                    process_symbol(symbol, engine, btc_ohlcv)

                except Exception as exc:
                    print(f"Unexpected error for {symbol}: {exc}")

                # Gentle pacing helps reduce API pressure.
                time.sleep(0.35)

            print("Scanner cycle completed.")
            time.sleep(180)

        except Exception as exc:
            print(f"Global scanner error: {exc}")
            time.sleep(60)


def start_scanner_once():
    # Avoid duplicate threads within the same Python process.
    if not getattr(app, "_scanner_started", False):
        app._scanner_started = True

        thread = threading.Thread(
            target=background_scanner,
            daemon=True,
            name="bingx-background-scanner"
        )
        thread.start()


start_scanner_once()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False
    )
