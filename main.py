# ==========================================
# MY EXPERT CRYPTO BOT - ICT OTE EDITION
# File: main.py
# Fibonacci OTE (61.8% - 78.6%) + FVG / OB Scanner
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
_market_context_previous = None
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
    return "My Expert Crypto Bot - ICT OTE Strategy Scanner is running!"


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
    if not value or value.startswith(("NCSK", "NCFX")) or "USD2" in value:
        return True
    if len(value) > 24 or not re.fullmatch(r"[A-Z0-9]+", value):
        return True
    return False


def is_candidate_market(symbol, market):
    if not isinstance(market, dict) or _market_status_looks_paused(market):
        return False
    if not market.get("swap", False) or market.get("linear") is False:
        return False
    if market.get("quote") != "USDT" or market.get("settle") != "USDT":
        return False
    if not symbol.endswith("/USDT:USDT"):
        return False
    base = market.get("base") or symbol.split("/", 1)[0]
    if _looks_like_non_crypto_underlying(base):
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


def _is_paused_symbol(symbol):
    with paused_lock:
        return symbol in paused_symbols


def _mark_paused_symbol(symbol):
    with paused_lock:
        paused_symbols.add(symbol)


def _is_paused_contract_error(exc):
    message = str(exc).lower()
    return "109415" in message or "is pause currently" in message or "paused" in message


def _is_temporary_api_error(exc):
    message = str(exc).lower()
    return (
        isinstance(exc, (ccxt.RateLimitExceeded, ccxt.NetworkError, ccxt.RequestTimeout, ccxt.ExchangeNotAvailable))
        or "100410" in message or "try again later" in message or "rate limit" in message
    )


def bingx_call(method_name, *args, **kwargs):
    global _last_api_request, _api_cooldown_until
    method = getattr(bingx, method_name)
    last_exc = None

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
            last_exc = exc
            if _is_paused_contract_error(exc) or attempt >= MAX_API_RETRIES or not _is_temporary_api_error(exc):
                raise
            delay = (2.0, 5.0, 12.0)[min(attempt, 2)]
            with api_lock:
                _api_cooldown_until = max(_api_cooldown_until, time.monotonic() + delay)

    raise last_exc


def get_market_context():
    global _market_context_previous
    try:
        response = requests.get("https://api.coingecko.com/api/v3/global", timeout=8)
        if response.status_code != 200:
            return {"source": "unavailable"}
        data = (response.json() or {}).get("data") or {}
        total = float(((data.get("total_market_cap") or {}).get("usd")) or 0)
        btc_dom = float((data.get("market_cap_percentage") or {}).get("btc") or 0)
        day_change = data.get("market_cap_change_percentage_24h_usd")
        day_change = float(day_change) if day_change is not None else None
        _market_context_previous = {"total_market_cap": total, "btc_dominance": btc_dom, "time": time.time()}
        return {"source": "CoinGecko global", "total_market_cap_usd": total, "btc_dominance_pct": btc_dom, "market_cap_change_pct": day_change}
    except Exception:
        return {"source": "unavailable"}


def build_ote_message(symbol, signal, score, entry, ote_target,
                      sl, tp1, tp2, tp3, sl_pct, tp1_pct, rr, details):
    confirmations = "\n".join(f"• {x}" for x in details.get("confirmations", [])) or "• لا توجد تأكيدات"
    exclusions = "\n".join(f"• {x}" for x in details.get("reasons_excluded", [])) or "• لا توجد ملاحظات"
    ote_zone = details.get("ote_zone", [0, 0])

    return (
        "🎯 *إشارة صيد مناطق OTE المثالية (مدرسة ICT)*\n\n"
        f"🔹 *العملة:* `{symbol}`\n"
        f"⚖️ *الاتجاه:* `{signal}`\n"
        f"⭐ *التقييم:* `{score}/100`\n"
        f"📏 *نطاق القمة والقاع:* `[{fmt(ote_zone[0])} - {fmt(ote_zone[1])}]`\n"
        f"💵 *سعر السوق الحالي:* `{fmt(entry)}`\n"
        f"🎯 *سعر الدخول المثالي (OTE Target):* `{fmt(ote_target)}`\n\n"
        f"🛑 *وقف الخسارة:* `{fmt(sl)}` ({sl_pct}%)\n"
        f"🎯 *TP1:* `{fmt(tp1)}` ({tp1_pct}%)\n"
        f"🎯 *TP2:* `{fmt(tp2)}`\n"
        f"🎯 *TP3:* `{fmt(tp3)}`\n"
        f"⚖️ *R:R تقديري:* `{rr}`\n\n"
        f"✅ *تفاصيل منطقة التصحيح (61.8% - 78.6%):*\n{confirmations}\n\n"
        f"⚠️ *ملاحظات الفلترة:*\n{exclusions}\n\n"
        "تم رصد التصحيح العميق بدقة، يرجى الالتزام بإدارة المخاطر ووضع الأوامر المعلقة في مناطق OTE."
    )


def process_symbol(symbol, engine, btc_ohlcv, market_context=None):
    if _is_paused_symbol(symbol):
        return
    try:
