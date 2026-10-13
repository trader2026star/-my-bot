# ==========================================
# MY EXPERT CRYPTO BOT
# BREAKOUT + RETEST SCANNER
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
SIGNAL_COOLDOWN_SECONDS = int(os.environ.get("SIGNAL_COOLDOWN_SECONDS", "7200"))

signal_history = {}
history_lock = threading.Lock()

bingx = ccxt.bingx({
    "enableRateLimit": True,
    "timeout": 20000,
    "options": {"defaultType": "swap"}
})


@app.route("/")
def home():
    return "My Expert Crypto Bot - Breakout Retest Scanner is running!"


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
        if response.status_code != 200:
            print(f"Telegram HTTP error: {response.status_code} {response.text[:300]}")
            return False
        result = response.json()
        if not result.get("ok"):
            print(f"Telegram API error: {result}")
            return False
        return True
    except Exception as exc:
        print(f"Telegram error: {exc}")
        return False


def is_candidate_market(symbol, market):
    if not market.get("active", True):
        return False
    if not market.get("swap", False):
        return False
    if not symbol.endswith("/USDT:USDT"):
        return False
    base = symbol.split("/")[0].upper()
    return base not in {"EUR", "GBP", "AUD", "NZD", "CAD", "CHF", "JPY", "FX"}


def valid_price(value):
    try:
        number = float(value)
        return number > 0 and number == number
    except (TypeError, ValueError):
        return False


def fmt(value):
    try:
        return f"{float(value):.10g}"
    except (TypeError, ValueError):
        return str(value)


def recent_signal(symbol, signal):
    key = f"{symbol}_{signal}"
    with history_lock:
        previous = signal_history.get(key, 0)
        return time.time() - previous < SIGNAL_COOLDOWN_SECONDS


def mark_signal(symbol, signal):
    with history_lock:
        signal_history[f"{symbol}_{signal}"] = time.time()


def build_message(symbol, signal, score, volume_ratio, entry,
                  sl, tp1, tp2, tp3, sl_pct, tp1_pct, rr, details):
    confirmations = "\n".join(
        f"• {x}" for x in details.get("confirmations", [])
    ) or "• لا توجد تأكيدات إضافية"
    exclusions = "\n".join(
        f"• {x}" for x in details.get("reasons_excluded", [])
    ) or "• لا توجد ملاحظات إضافية"

    return (
        "📊 *إشارة كسر وإعادة اختبار — ليست ضمانًا للربح*\n\n"
        f"🔹 *العملة:* `{symbol}`\n"
        f"⚖️ *الاتجاه:* `{signal}`\n"
        f"⭐ *التقييم:* `{score}/100`\n"
        f"📈 *فوليوم 15M:* `{volume_ratio}x`\n"
        f"💵 *سعر السوق المرجعي:* `{fmt(entry)}`\n"
        f"🧱 *مستوى الكسر:* `{fmt(details.get('break_level'))}`\n\n"
        f"🛑 *وقف الخسارة:* `{fmt(sl)}` ({sl_pct}%)\n"
        f"🎯 *TP1:* `{fmt(tp1)}` ({tp1_pct}%)\n"
        f"🎯 *TP2:* `{fmt(tp2)}`\n"
        f"🎯 *TP3:* `{fmt(tp3)}`\n"
        f"⚖️ *R:R تقديري:* `{rr}`\n\n"
        f"🧭 *اتجاه 4H:* `{details.get('trend_4h')}` | "
        f"*اتجاه 1H:* `{details.get('trend_1h')}`\n"
        f"₿ *اتجاه BTC:* `{details.get('btc_trend')}`\n"
        f"🧱 *BOS:* `{details.get('bos')}`\n"
        f"💧 *Liquidity Sweep:* `{details.get('sweep')}`\n"
        f"🟦 *FVG:* `{details.get('fvg')}`\n\n"
        f"✅ *التأكيدات:*\n{confirmations}\n\n"
        f"⚠️ *الملاحظات:*\n{exclusions}\n\n"
        "راجع السبريد والرافعة وحجم الصفقة قبل التنفيذ. "
        "قد يتغير السعر قبل وصول الإشعار."
    )


def process_symbol(symbol, engine, btc_ohlcv):
    try:
        ohlcv_4h = bingx.fetch_ohlcv(symbol, timeframe="4h", limit=40)
        ohlcv_1h = bingx.fetch_ohlcv(symbol, timeframe="1h", limit=60)
        ohlcv_15m = bingx.fetch_ohlcv(symbol, timeframe="15m", limit=40)

        signal, score, volume_ratio, details, arrays = engine.analyze_multi_timeframe(
            ohlcv_4h, ohlcv_1h, ohlcv_15m, btc_ohlcv
        )

        if signal not in ("LONG", "SHORT") or score < 75:
            return
        if not details.get("entry_valid", False) or volume_ratio < 1.25:
            return
        expected_bos = "BULLISH_BOS" if signal == "LONG" else "BEARISH_BOS"
        if details.get("bos") != expected_bos and not details.get("retest_bos_valid", False):
            print(f"BOS/retest filter rejected {symbol}: BOS={details.get('bos')} retest={details.get('retest_bos_valid')}")
            return
        if recent_signal(symbol, signal):
            return

        ticker = bingx.fetch_ticker(symbol)
        entry = ticker.get("last") or ticker.get("close")
        if not valid_price(entry):
            return
        entry = float(entry)

        highs, lows, closes = arrays
        sl, tp1, tp2, tp3, sl_pct, tp1_pct, rr = engine.calculate_risk_management(
            entry, signal, highs, lows, closes
        )

        if not all(valid_price(x) for x in (sl, tp1, tp2, tp3)):
            return
        if signal == "LONG" and not (sl < entry < tp1 < tp2 < tp3):
            return
        if signal == "SHORT" and not (tp3 < tp2 < tp1 < entry < sl):
            return
        if sl_pct <= 0 or sl_pct > 7 or rr < 1.0:
            print(f"Risk filter rejected {symbol}: SL={sl_pct}% RR={rr}")
            return

        message = build_message(
            symbol, signal, score, volume_ratio, entry,
            sl, tp1, tp2, tp3, sl_pct, tp1_pct, rr, details
        )

        # Cooldown begins only after Telegram confirms delivery.
        if send_telegram_message(message):
            mark_signal(symbol, signal)
            print(f"Sent {symbol} {signal}; score={score}, RR={rr}")

    except (ccxt.NetworkError, ccxt.ExchangeError) as exc:
        print(f"BingX error for {symbol}: {exc}")
    except Exception as exc:
        print(f"Processing error for {symbol}: {exc}")


def background_scanner():
    time.sleep(10)
    send_telegram_message(
        "🤖 *تم تشغيل استراتيجية Breakout + Retest*\n"
        "الفحص يشترط توافق 4H و1H، كسر وإعادة اختبار 15M، "
        "BOS ساعة في نفس الاتجاه، وفوليوم 1.25x على الأقل، "
        "مع إدارة المخاطر.\n"
        "الإشارات احتمالية وليست ضمانًا للربح."
    )
    engine = StrategyEngine()

    while True:
        try:
            markets = bingx.load_markets()
            symbols = [
                symbol for symbol, market in markets.items()
                if is_candidate_market(symbol, market)
            ]
            print(f"Scan started: {len(symbols)} eligible markets")

            btc_ohlcv = []
            try:
                btc_ohlcv = bingx.fetch_ohlcv(
                    "BTC/USDT:USDT", timeframe="1h", limit=30
                )
            except Exception as exc:
                print(f"BTC context unavailable: {exc}")

            for symbol in symbols:
                process_symbol(symbol, engine, btc_ohlcv)
                time.sleep(0.35)

            time.sleep(180)

        except Exception as exc:
            print(f"Scanner loop error: {exc}")
            time.sleep(60)


def start_scanner_once():
    if not getattr(app, "_scanner_started", False):
        app._scanner_started = True
        threading.Thread(
            target=background_scanner,
            daemon=True,
            name="bingx-scanner"
        ).start()


start_scanner_once()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
