# ==========================================
# MY EXPERT CRYPTO BOT - MAIN SERVER
# BREAKOUT + RETEST SCANNER + PRICE CHASING PROTECTION
# File: main.py
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

long_rejections = {}
long_rejections_lock = threading.Lock()
candidate_rejections = {}
candidate_rejections_lock = threading.Lock()

bingx = ccxt.bingx({
    "enableRateLimit": True,
    "timeout": 20000,
    "options": {"defaultType": "swap"}
})


@app.route("/")
def home():
    return "My Expert Crypto Bot - Breakout Retest Scanner with Price Chasing Protection is running!"


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
        print(f"Telegram error: {str(exc)[:250]}")
        return False


def _market_status_looks_paused(market):
    if market.get("active") is False:
        return True
    info = market.get("info") or {}
    for key in ("status", "contractStatus", "state", "tradeStatus", "tradingStatus"):
        value = info.get(key)
        if isinstance(value, str) and value.strip().lower() in {
            "paused", "pause", "suspended", "suspend", "offline", "delisted", "disabled", "closed"
        }:
            return True
    return False


def _looks_like_non_crypto_underlying(base):
    value = str(base or "").upper().strip()
    if not value:
        return True
    if value.startswith(("NCSK", "NCFX")):
        return True
    if "USD2" in value or re.search(r"2(?:USD|TWD|IDR|ARS|EUR|GBP|AUD|CAD|CHF|JPY|NZD)$", value):
        return True
    if len(value) > 24 or not re.fullmatch(r"[A-Z0-9]+", value):
        return True
    return False


def is_candidate_market(symbol, market):
    if not isinstance(market, dict) or _market_status_looks_paused(market):
        return False
    if not market.get("swap", False):
        return False
    if market.get("linear") is False:
        return False
    if market.get("quote") != "USDT" or market.get("settle") != "USDT":
        return False
    if not symbol.endswith("/USDT:USDT"):
        return False

    base = market.get("base") or symbol.split("/", 1)[0]
    if _looks_like_non_crypto_underlying(base):
        return False

    if str(base).upper() in {
        "USD", "EUR", "GBP", "AUD", "NZD", "CAD", "CHF", "JPY", "TWD", "IDR", "ARS", "HKD", "SGD", "KRW", "CNY", "INR", "FX"
    }:
        return False
    return True


def valid_price(value):
    try:
        number = float(value)
        return number > 0 and number == number and number not in (float("inf"), float("-inf"))
    except (TypeError, ValueError, OverflowError):
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


def _record_long_rejection(reason):
    with long_rejections_lock:
        long_rejections[reason] = long_rejections.get(reason, 0) + 1


def _record_candidate_rejection(direction, reason):
    key = f"{direction}:{reason}"
    with candidate_rejections_lock:
        candidate_rejections[key] = candidate_rejections.get(key, 0) + 1


def _is_paused_symbol(symbol):
    with paused_lock:
        return symbol in paused_symbols


def _mark_paused_symbol(symbol):
    with paused_lock:
        already_seen = symbol in paused_symbols
        paused_symbols.add(symbol)
    if not already_seen:
        print(f"Skipping BingX paused/invalid contract for this process: {symbol}")


def _is_paused_contract_error(exc):
    message = str(exc).lower()
    return "109415" in message or "is pause currently" in message or "paused" in message


def _is_temporary_api_error(exc):
    message = str(exc).lower()
    return (
        isinstance(exc, (ccxt.RateLimitExceeded, ccxt.NetworkError, ccxt.RequestTimeout, ccxt.ExchangeNotAvailable))
        or "100410" in message
        or "请稍后重试" in message
        or "try again later" in message
        or "too many requests" in message
        or "rate limit" in message
        or "temporarily unavailable" in message
    )


def bingx_call(method_name, *args, **kwargs):
    global _last_api_request, _api_cooldown_until
    method = getattr(bingx, method_name)
    last_exc = None

    for attempt in range(MAX_API_RETRIES + 1):
        with api_lock:
            now = time.monotonic()
            wait_for = max(
                0.0,
                API_MIN_INTERVAL_SECONDS - (now - _last_api_request),
                _api_cooldown_until - now,
            )
            if wait_for > 0:
                time.sleep(wait_for)
            _last_api_request = time.monotonic()

        try:
            return method(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if _is_paused_contract_error(exc) or attempt >= MAX_API_RETRIES or not _is_temporary_api_error(exc):
                raise

            delay = (2.0, 5.0, 12.0)[min(attempt, 2)]
            with api_lock:
                _api_cooldown_until = max(_api_cooldown_until, time.monotonic() + delay)
            print(
                f"Temporary BingX API error in {method_name}; retry {attempt + 1}/{MAX_API_RETRIES} "
                f"after {delay:.0f}s: {str(exc)[:180]}"
            )

    raise last_exc


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
    if _is_paused_symbol(symbol):
        return
    try:
        # جلب السعر الحي أولاً لتمريره وتجنب مطاردة السعر الممتد أثناء التحليل
        ticker = bingx_call("fetch_ticker", symbol)
        entry = ticker.get("last") or ticker.get("close")
        if not valid_price(entry):
            print(f"Skipped {symbol}: BingX returned an invalid last/close price")
            return
        entry = float(entry)

        ohlcv_4h = bingx_call("fetch_ohlcv", symbol, timeframe="4h", limit=40)
        ohlcv_1h = bingx_call("fetch_ohlcv", symbol, timeframe="1h", limit=60)
        ohlcv_15m = bingx_call("fetch_ohlcv", symbol, timeframe="15m", limit=40)

        # تمرير سعر السوق الحالي (`current_price`) لمحرك التحليل
        signal, score, volume_ratio, details, arrays = engine.analyze_multi_timeframe(
            ohlcv_4h, ohlcv_1h, ohlcv_15m, btc_ohlcv, symbol=symbol, current_price=entry
        )

        if signal not in ("LONG", "SHORT"):
            candidate_direction = details.get("candidate_direction")
            if candidate_direction in ("LONG", "SHORT"):
                if not details.get("break_retest", False):
                    reason = "no_breakout_retest"
                elif not details.get("retest_bos_valid", False) and details.get("bos") not in ("BULLISH_BOS" if candidate_direction == "LONG" else "BEARISH_BOS",):
                    reason = "no_BOS_or_retest_BOS"
                elif volume_ratio < 1.15:
                    reason = "volume_below_1.15x"
                elif not details.get("momentum", False):
                    reason = "momentum_not_confirmed"
                elif len(details.get("confirmations", [])) < 3:
                    reason = "fewer_than_3_confirmations"
                else:
                    reason = "other_entry_filter"
                _record_candidate_rejection(candidate_direction, reason)
            return
        if score < 72:
            if signal == "LONG":
                _record_long_rejection("score_below_72")
            return
        if not details.get("entry_valid", False):
            if signal == "LONG":
                _record_long_rejection("entry_invalid")
            return
        if volume_ratio < 1.15:
            if signal == "LONG":
                _record_long_rejection("volume_below_1.15x")
            return

        expected_bos = "BULLISH_BOS" if signal == "LONG" else "BEARISH_BOS"
        if details.get("bos") != expected_bos and not details.get("retest_bos_valid", False):
            if signal == "LONG":
                _record_long_rejection("bos_retest_filter")
            return
        if recent_signal(symbol, signal):
            if signal == "LONG":
                _record_long_rejection("cooldown")
            return

        highs, lows, closes = arrays
        sl, tp1, tp2, tp3, sl_pct, tp1_pct, rr = engine.calculate_risk_management(
            entry, signal, highs, lows, closes
        )

        if not all(valid_price(x) for x in (sl, tp1, tp2, tp3)):
            if signal == "LONG":
                _record_long_rejection("invalid_risk_levels")
            return
        if signal == "LONG" and not (sl < entry < tp1 < tp2 < tp3):
            _record_long_rejection("long_target_order")
            return
        if signal == "SHORT" and not (tp3 < tp2 < tp1 < entry < sl):
            return
        if sl_pct <= 0 or sl_pct > 7 or rr < 1.0:
            if signal == "LONG":
                _record_long_rejection("risk_filter")
            return

        message = build_message(
            symbol, signal, score, volume_ratio, entry,
            sl, tp1, tp2, tp3, sl_pct, tp1_pct, rr, details
        )

        if send_telegram_message(message):
            mark_signal(symbol, signal)
            print(f"Sent {symbol} {signal}; score={score}, RR={rr}")

    except (ccxt.NetworkError, ccxt.ExchangeError) as exc:
        if _is_paused_contract_error(exc):
            _mark_paused_symbol(symbol)
            return
        print(f"BingX error for {symbol}: {str(exc)[:240]}")
    except Exception as exc:
        if _is_paused_contract_error(exc):
            _mark_paused_symbol(symbol)
            return
        print(f"Processing error for {symbol}: {str(exc)[:240]}")


def _log_long_rejection_summary():
    with candidate_rejections_lock:
        if candidate_rejections:
            summary = ", ".join(f"{key}={value}" for key, value in sorted(candidate_rejections.items()))
            print(f"Candidate rejection summary: {summary}")
        else:
            print("Candidate diagnostics: no aligned candidates reached entry checks yet.")
    with long_rejections_lock:
        if long_rejections:
            summary = ", ".join(f"{key}={value}" for key, value in sorted(long_rejections.items()))
            print(f"LONG post-analysis rejection summary: {summary}")


def background_scanner():
    time.sleep(10)
    send_telegram_message(
        "🤖 *تم تشغيل استراتيجية Breakout + Retest مع حماية مطاردة السعر*\n"
        "الفحص يشترط توافق 4H و1H، كسر وإعادة اختبار 15M، "
        "BOS متوافق، فوليوم 1.15x، والتحقق الفوري من عدم امتداد السعر.\n"
        "الإشارات احتمالية وليست ضمانًا للربح."
    )
    engine = StrategyEngine()

    while True:
        try:
            markets = bingx_call("load_markets")
            eligible = []
            rejected_market_count = 0
            for symbol, market in markets.items():
                if is_candidate_market(symbol, market):
                    eligible.append(symbol)
                else:
                    rejected_market_count += 1

            symbols = [symbol for symbol in eligible if not _is_paused_symbol(symbol)]
            with paused_lock:
                paused_count = len(paused_symbols)
            print(
                f"Scan started: {len(symbols)} eligible crypto USDT swaps; "
                f"filtered markets={rejected_market_count}; paused/invalid cached={paused_count}"
            )

            btc_ohlcv = []
            try:
                btc_ohlcv = bingx_call(
                    "fetch_ohlcv", "BTC/USDT:USDT", timeframe="1h", limit=30
                )
            except Exception as exc:
                print(f"BTC context unavailable after retries: {str(exc)[:200]}")

            for index, symbol in enumerate(symbols, start=1):
                process_symbol(symbol, engine, btc_ohlcv)
                if SYMBOL_PAUSE_SECONDS > 0:
                    time.sleep(SYMBOL_PAUSE_SECONDS)
                if index % 50 == 0:
                    print(f"Scan progress: {index}/{len(symbols)} markets")

            _log_long_rejection_summary()
            print("Scan cycle completed; waiting 180 seconds.")
            time.sleep(180)

        except Exception as exc:
            print(f"Scanner loop error: {str(exc)[:250]}")
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
