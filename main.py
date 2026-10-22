# ==========================================
# MY EXPERT CRYPTO BOT - BUTTERFLY ENGINE V12.0
# Features: Clean Market Filtering & Butterfly Double Bottom Strategy
# ==========================================
import os
import time
import threading
import logging
import requests
import ccxt
from flask import Flask, jsonify, request
from analysis import StrategyEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("MainBot")

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
SIGNAL_COOLDOWN_SECONDS = max(60, int(os.environ.get("SIGNAL_COOLDOWN_SECONDS", "1800")))
API_MIN_INTERVAL_SECONDS = max(0.25, float(os.environ.get("API_MIN_INTERVAL_SECONDS", "0.35")))
SYMBOL_PAUSE_SECONDS = max(0.05, float(os.environ.get("SYMBOL_PAUSE_SECONDS", "0.10")))
MAX_API_RETRIES = max(0, min(3, int(os.environ.get("MAX_API_RETRIES", "2"))))

BOT_CAPITAL_USD = max(1.0, float(os.environ.get("BOT_CAPITAL_USD", "1000")))
RISK_PER_TRADE = min(0.05, max(0.001, float(os.environ.get("RISK_PER_TRADE", "0.01"))))
DEBUG_MODE = os.environ.get("DEBUG_MODE", "false").lower() == "true"

consecutive_losses = 0
max_allowed_consecutive_losses = 2
bot_locked_out = False
lockout_reset_time = 0

signal_history = {}
active_trades = {}
scan_stats = {
    "scanned_pairs": 0,
    "fetch_failures": 0,
    "patterns_detected": 0,
    "breakouts_confirmed": 0,
    "retests_confirmed": 0,
    "rejected_low_score": 0,
    "rejection_reasons": {},
    "cooldown_blocked": 0,
    "signals_sent": 0
}

history_lock = threading.Lock()
trades_lock = threading.Lock()
api_lock = threading.Lock()
_last_api_request = 0.0

bingx = ccxt.bingx({
    "enableRateLimit": True,
    "timeout": 20000,
    "options": {"defaultType": "swap"}
})

@app.route("/")
def home():
    return f"MY EXPERT CRYPTO BOT V12.0 (Butterfly Double Bottom Strategy) is active! Debug Mode: {DEBUG_MODE}"

@app.route("/health")
def health():
    return jsonify({"status": "healthy", "locked_out": bot_locked_out, "stats": scan_stats}), 200

@app.route("/debug")
def debug_stats():
    return jsonify(scan_stats), 200


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
    except Exception as e:
        logger.error(f"Telegram error: {e}")
        return False


def bingx_call(method_name, *args, **kwargs):
    global _last_api_request
    method = getattr(bingx, method_name)
    for attempt in range(MAX_API_RETRIES + 1):
        with api_lock:
            now = time.monotonic()
            wait_for = max(0.0, API_MIN_INTERVAL_SECONDS - (now - _last_api_request))
            if wait_for > 0:
                time.sleep(wait_for)
            _last_api_request = time.monotonic()
        try:
            return method(*args, **kwargs)
        except Exception as exc:
            if attempt >= MAX_API_RETRIES:
                return None
            time.sleep(1.0 * (attempt + 1))
    return None


def get_all_usdt_symbols():
    """فلترة دقيقة لمنع ظهور أي عملات وهمية، تجريبية، أو مشتقات غريبة"""
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
                base_asset = symbol.split('/')[0].upper()
                sym_upper = symbol.upper()
                
                # منع الرموز التجريبية، الوهمية، أو التي تحتوي على حروف مريبة
                if any(x in sym_upper for x in ["TEST", "UP/", "DOWN/", "BULL", "BEAR", "USD2", "DIS2", "DAL2"]):
                    continue
                if "SKD" in base_asset or len(base_asset) > 9:
                    continue
                if any(char.isdigit() for char in base_asset) and not base_asset.startswith("1000"):
                    continue
                    
                symbols.append(symbol)
        return sorted(set(symbols))
    except Exception as e:
        logger.error(f"Error loading markets: {e}")
        return []


def notify_trade_executed(symbol, direction, entry_price, details):
    rm = details.get("risk_management", {})
    dir_emoji = "🟢 LONG (شراء - قاع مزدوج للفراشة)" if direction == "LONG" else "🔴 SHORT (بيع)"

    message = (
        f"🦋 *إشارة نموذج الفراشة: القاع المزدوج مؤكدة* 🦋\n\n"
        f"🔹 العملة: `{symbol}`\n"
        f"⚖️ الاتجاه: `{dir_emoji}`\n"
        f"💵 سعر الدخول: `{entry_price}`\n"
        f"📍 خط العنق (Neckline): `{details.get('neckline')}`\n"
        f"⭐️ درجة التقييم: `{details.get('score')}/100`\n\n"
        f"🟥 وقف الخسارة (SL): `{details.get('stop_loss')}`\n"
        f"🟩 الهدف الأول (TP1): `{rm.get('take_profit_1')}`\n"
        f"🟩 الهدف الثاني (TP2): `{rm.get('take_profit_2')}`\n"
        f"🟩 الهدف الثالث (TP3): `{rm.get('take_profit_3')}`\n"
        f"📐 نسبة العائد/المخاطرة: `{rm.get('reward_ratio')}`\n\n"
        f"ℹ️ *ملاحظة الاستراتيجية:* {details.get('smc_note')}"
    )
    return send_telegram_message(message)


def process_symbol(symbol, engine, btc_ohlcv_1h):
    global bot_locked_out, lockout_reset_time, scan_stats
    if bot_locked_out:
        if time.time() > lockout_reset_time:
            bot_locked_out = False
            send_telegram_message("♻️ *تم فك الحماية المؤقتة واستئناف العمل.*")
        else:
            return

    try:
        now = time.time()
        with history_lock:
            if now - signal_history.get(symbol, 0) < SIGNAL_COOLDOWN_SECONDS:
                scan_stats["cooldown_blocked"] += 1
                return

        ticker = bingx_call("fetch_ticker", symbol)
        if not ticker:
            scan_stats["fetch_failures"] += 1
            return

        quote_volume = float(ticker.get("quoteVolume") or ticker.get("baseVolume") or 0)
        if quote_volume < 500000: # رفع حد السيولة الأدنى لتصفية العملات الضعيفة
            return

        ohlcv_30m = bingx_call("fetch_ohlcv", symbol, timeframe="30m", limit=45)
        if not ohlcv_30m:
            scan_stats["fetch_failures"] += 1
            return

        direction, entry_price, details = engine.analyze_market_structure(
            ohlcv_30m, btc_ohlcv_1h=btc_ohlcv_1h, debug=DEBUG_MODE
        )

        scan_stats["scanned_pairs"] += 1

        if direction == "NEUTRAL":
            reason = details.get("reason", "Unknown")
            scan_stats["rejection_reasons"][reason] = scan_stats["rejection_reasons"].get(reason, 0) + 1
            return

        scan_stats["patterns_detected"] += 1
        if details.get("state") == "BREAKOUT_CONFIRMED":
            scan_stats["breakouts_confirmed"] += 1
        elif details.get("state") == "RETEST_CONFIRMED":
            scan_stats["retests_confirmed"] += 1

        sent = notify_trade_executed(symbol, direction, entry_price, details)
        if sent:
            scan_stats["signals_sent"] += 1
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

    except Exception as exc:
        logger.error(f"Error processing {symbol}: {exc}")


def background_scanner():
    time.sleep(5)
    send_telegram_message(
        "🤖 *تم تشغيل محرك نموذج الفراشة: القاع المزدوج (V12.0)*\n"
        "تم تفعيل استراتيجية القاع المزدوج بدقة تامة مع تصفية العملات الوهمية."
    )
    engine = StrategyEngine(capital=BOT_CAPITAL_USD, risk_per_trade=RISK_PER_TRADE)

    while True:
        try:
            for k in list(scan_stats.keys()):
                if isinstance(scan_stats[k], int):
                    scan_stats[k] = 0
                elif isinstance(scan_stats[k], dict):
                    scan_stats[k].clear()

            symbols = get_all_usdt_symbols()
            if not symbols:
                time.sleep(30)
                continue

            btc_ohlcv = bingx_call("fetch_ohlcv", "BTC/USDT:USDT", timeframe="1h", limit=25)

            for symbol in symbols:
                process_symbol(symbol, engine, btc_ohlcv)
                time.sleep(SYMBOL_PAUSE_SECONDS)

            logger.info(f"Scan Complete. Valid Pairs Scanned: {scan_stats['scanned_pairs']}")
            time.sleep(60)
        except Exception as exc:
            logger.error(f"Scanner Loop Error: {exc}")
            time.sleep(30)


scanner_thread = threading.Thread(target=background_scanner, daemon=True, name="butterfly-scanner")
scanner_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
