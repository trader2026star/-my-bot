# ==========================================
# MY EXPERT CRYPTO BOT - LIQUIDITY SWEEP EDITION
# File: main.py
# Anti-Trap Strategy: Stop Hunt & Liquidity Sweep Scanner
# ==========================================

import os
import re
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

API_MIN_INTERVAL_SECONDS = max(0.25, float(os.environ.get("API_MIN_INTERVAL_SECONDS", "0.50")))
SYMBOL_PAUSE_SECONDS = max(0.10, float(os.environ.get("SYMBOL_PAUSE_SECONDS", "0.50")))
MAX_API_RETRIES = max(0, min(3, int(os.environ.get("MAX_API_RETRIES", "3"))))

signal_history = {}
history_lock = threading.Lock()
api_lock = threading.Lock()
_last_api_request = 0.0
_api_cooldown_until = 0.0

paused_symbols = set()
paused_lock = threading.Lock()

bingx = ccxt.bingx({
    "enableRateLimit": True,
    "timeout": 20000,
    "options": {"defaultType": "swap"}
})


@app.route("/")
def home():
    return "My Expert Crypto Bot - Liquidity Sweep Strategy Scanner is active!"


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


def _is_paused_symbol(symbol):
    with paused_lock:
        return symbol in paused_symbols


def _mark_paused_symbol(symbol):
    with paused_lock:
        paused_symbols.add(symbol)


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


def build_sweep_message(symbol, signal, score, entry, sweep_target, sl, tp1, tp2, tp3, sl_pct, tp1_pct, rr, details):
    confirmations = "\n".join(f"• {x}" for x in details.get("confirmations", [])) or "• لا توجد تأكيدات"
    zone = details.get("ote_zone", [0, 0])

    return (
        "🚨 *إشارة سحب سيولة واصطياد الوقف (Stop Hunt Sweep)*\n\n"
        f"🔹 *العملة:* `{symbol}`\n"
        f"⚖️ *الاتجاه الجديد (عكس القطيع):* `{signal}`\n"
        f"⭐ *التقييم:* `{score}/100`\n"
        f"📏 *نطاق السيولة المسحوبة (القمة/القاع):* `[{fmt(zone[0])} - {fmt(zone[1])}]`\n"
        f"💵 *سعر الدخول الحالي:* `{fmt(entry)}`\n\n"
        f"🛑 *وقف الخسارة المحصن:* `{fmt(sl)}` ({sl_pct}%)\n"
        f"🎯 *TP1:* `{fmt(tp1)}` ({tp1_pct}%)\n"
        f"🎯 *TP2:* `{fmt(tp2)}`\n"
        f"🎯 *TP3:* `{fmt(tp3)}`\n"
        f"⚖️ *R:R تقديري:* `{rr}`\n\n"
        f"✅ *تفاصيل الانعكاس:*\n{confirmations}\n\n"
        "تم رصد كسر وقوف الخسارة للمتداولين التقليديين والدخول مع صانع السوق."
    )


def process_symbol(symbol, engine):
    if _is_paused_symbol(symbol):
        return
    
    global signal_history
    now_time = time.time()
    with history_lock:
        last_time = signal_history.get(symbol, 0)
        if now_time - last_time < SIGNAL_COOLDOWN_SECONDS:
            return

    try:
        ohlcv_4h = bingx_call("fetch_ohlcv", symbol, timeframe="4h", limit=100)
        ohlcv_1h = bingx_call("fetch_ohlcv", symbol, timeframe="1h", limit=100)
        ohlcv_15m = bingx_call("fetch_ohlcv", symbol, timeframe="15m", limit=100)

        signal, score, volume_ratio, details, arrays = engine.analyze_multi_timeframe(
            ohlcv_4h, ohlcv_1h, ohlcv_15m, symbol=symbol
        )

        if signal not in ("LONG", "SHORT") or score < 75:
            return

        ticker = bingx_call("fetch_ticker", symbol)
        entry = float(ticker.get("last") or ticker.get("close") or 0)
        if entry <= 0:
            return

        sweep_target = details.get("predictive_entry", entry)
        highs, lows, closes = arrays
        sl, tp1, tp2, tp3, sl_pct, tp1_pct, rr = engine.calculate_risk_management(
            sweep_target, signal, highs, lows, closes
        )

        message = build_sweep_message(
            symbol, signal, score, entry, sweep_target,
            sl, tp1, tp2, tp3, sl_pct, tp1_pct, rr, details
        )

        if send_telegram_message(message):
            with history_lock:
                signal_history[symbol] = time.time()
            print(f"Sent Liquidity Sweep signal for {symbol} successfully.")

    except Exception as exc:
        if "paused" in str(exc).lower():
            _mark_paused_symbol(symbol)
        else:
            print(f"Error processing {symbol}: {str(exc)[:100]}")


def background_scanner():
    time.sleep(15)
    send_telegram_message("🤖 *تم تفعيل بوت سحب السيولة (Stop Hunt Engine) بنجاح*")
    engine = StrategyEngine()

    while True:
        try:
            markets = bingx_call("load_markets")
            symbols = [
                s for s, m in markets.items() 
                if m.get("swap") and m.get("linear") and s.endswith("/USDT:USDT") 
                and not any(x in s.upper() for x in ("TEST", "DEMO", "FAKE", "NCSK", "BULL", "BEAR"))
                and m.get("active", True)
            ]

            for symbol in symbols:
                process_symbol(symbol, engine)
                time.sleep(SYMBOL_PAUSE_SECONDS)

            time.sleep(180)
        except Exception as exc:
            print(f"Scanner error: {str(exc)[:150]}")
            time.sleep(60)


threading.Thread(target=background_scanner, daemon=True, name="sweep-scanner").start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
