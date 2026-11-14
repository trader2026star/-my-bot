# ============================================================
# MY EXPERT CRYPTO BOT - V123.0
# SWING TIMING / ANTI-CHASE EDITION
#
# Signal-only
# LONG ONLY
# BingX Futures
#
# Commands:
#   /start
#   /scan
#   /status
#   /help
#   /coin BTC
#
# Also accepts:
#   BTC
#   ETH
#   SOL
#
# Environment:
#   TELEGRAM_BOT_TOKEN
#   TELEGRAM_CHAT_ID
#   ALLOWED_CHAT_IDS
#   CAPITAL
#   RISK_PER_TRADE
#   MIN_SCORE
#   AUTO_SCAN_INTERVAL_SECONDS
# ============================================================

import os
import time
import html
import logging
import threading
import requests
import ccxt

from flask import Flask, request, jsonify

from analysis import StrategyEngine


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("MY_EXPERT_CRYPTO_BOT_V123")


# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    os.getenv("BOT_TOKEN", "")
)

CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    os.getenv("CHAT_ID", "")
)

ALLOWED_CHAT_IDS = os.getenv(
    "ALLOWED_CHAT_IDS",
    ""
)

CAPITAL = float(
    os.getenv("CAPITAL", "10000")
)

RISK_PER_TRADE = float(
    os.getenv("RISK_PER_TRADE", "0.01")
)

MIN_SCORE = int(
    os.getenv("MIN_SCORE", "72")
)

AUTO_SCAN_INTERVAL = int(
    os.getenv(
        "AUTO_SCAN_INTERVAL_SECONDS",
        "14400"
    )
)

API_MIN_INTERVAL = float(
    os.getenv(
        "API_MIN_INTERVAL_SECONDS",
        "0.35"
    )
)

SYMBOL_PAUSE = float(
    os.getenv(
        "SYMBOL_PAUSE_SECONDS",
        "0.10"
    )
)


# ============================================================
# FLASK
# ============================================================

app = Flask(__name__)


# ============================================================
# BINGX
# ============================================================

exchange = ccxt.bingx({
    "enableRateLimit": True,
    "timeout": 20000,
    "options": {
        "defaultType": "swap"
    }
})


# ============================================================
# STRATEGY
# ============================================================

engine = StrategyEngine(
    capital=CAPITAL,
    risk_per_trade=RISK_PER_TRADE,
    min_score=MIN_SCORE
)


# ============================================================
# STATE
# ============================================================

last_api_call = 0.0
last_auto_scan = 0.0

state_lock = threading.Lock()

last_signals = {}

bot_started_at = time.time()


# ============================================================
# TELEGRAM
# ============================================================

def tg_url(method):
    return (
        f"https://api.telegram.org/bot"
        f"{BOT_TOKEN}/{method}"
    )


def tg_send(chat_id, text):
    if not BOT_TOKEN or not chat_id:
        logger.warning(
            "Telegram credentials missing"
        )
        return False

    try:
        response = requests.post(
            tg_url("sendMessage"),
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            },
            timeout=15
        )

        if response.ok:
            return True

        logger.error(
            "Telegram send failed: %s %s",
            response.status_code,
            response.text[:500]
        )

        return False

    except Exception as e:
        logger.exception(
            "Telegram send error: %s",
            e
        )
        return False


def tg_delete_webhook():
    if not BOT_TOKEN:
        return

    try:
        requests.get(
            tg_url("deleteWebhook"),
            params={
                "drop_pending_updates": False
            },
            timeout=15
        )
    except Exception:
        pass


# ============================================================
# AUTH
# ============================================================

def is_allowed(chat_id):
    if not ALLOWED_CHAT_IDS:
        if not CHAT_ID:
            return True

        return str(chat_id) == str(CHAT_ID)

    allowed = {
        x.strip()
        for x in ALLOWED_CHAT_IDS.split(",")
        if x.strip()
    }

    return str(chat_id) in allowed


# ============================================================
# API THROTTLE
# ============================================================

def api_pause():
    global last_api_call

    now = time.time()

    elapsed = now - last_api_call

    if elapsed < API_MIN_INTERVAL:
        time.sleep(
            API_MIN_INTERVAL - elapsed
        )

    last_api_call = time.time()


# ============================================================
# SYMBOL NORMALIZATION
# ============================================================

def normalize_symbol(symbol):
    if not symbol:
        return None

    symbol = (
        str(symbol)
        .upper()
        .strip()
        .replace(" ", "")
        .replace("-", "/")
    )

    if ":" in symbol:
        symbol = symbol.split(":")[0]

    if "/" not in symbol:
        if symbol.endswith("USDT"):
            base = symbol[:-4]
            symbol = f"{base}/USDT"
        else:
            symbol = f"{symbol}/USDT"

    return symbol


# ============================================================
# MARKETS
# ============================================================

def load_markets():
    api_pause()

    markets = exchange.load_markets()

    return markets


def get_usdt_symbols():
    markets = load_markets()

    symbols = []

    for symbol, market in markets.items():
        try:
            if not market.get("active", True):
                continue

            if market.get("quote") != "USDT":
                continue

            if market.get("type") != "swap":
                continue

            if market.get("linear") is not True:
                continue

            base = str(
                market.get("base", "")
            ).upper()

            # Crypto-only protection
            blocked_words = (
                "USD",
                "EUR",
                "GBP",
                "JPY",
                "INDEX",
                "1000",
                "COMMODITY",
                "GOLD",
                "SILVER",
                "OIL",
            )

            if any(
                word in base
                for word in blocked_words
            ):
                continue

            symbols.append(symbol)

        except Exception:
            continue

    return sorted(set(symbols))


# ============================================================
# OHLCV
# ============================================================

def fetch_ohlcv(symbol, timeframe, limit=100):
    try:
        api_pause()

        return exchange.fetch_ohlcv(
            symbol,
            timeframe=timeframe,
            limit=limit
        )

    except Exception as e:
        logger.warning(
            "OHLCV failed %s %s: %s",
            symbol,
            timeframe,
            e
        )

        return None


# ============================================================
# CURRENT PRICE
# ============================================================

def get_current_price(symbol):
    try:
        api_pause()

        ticker = exchange.fetch_ticker(
            symbol
        )

        price = (
            ticker.get("last")
            or ticker.get("close")
            or ticker.get("mark")
        )

        if price:
            return float(price)

    except Exception as e:
        logger.warning(
            "Price failed %s: %s",
            symbol,
            e
        )

    return None


# ============================================================
# SYMBOL ANALYSIS
# ============================================================

def analyze_symbol(symbol):
    symbol = normalize_symbol(symbol)

    if not symbol:
        return None

    try:
        daily = fetch_ohlcv(
            symbol,
            "1d",
            100
        )

        if not daily:
            return None

        time.sleep(SYMBOL_PAUSE)

        four_h = fetch_ohlcv(
            symbol,
            "4h",
            100
        )

        if not four_h:
            return None

        time.sleep(SYMBOL_PAUSE)

        one_h = fetch_ohlcv(
            symbol,
            "1h",
            100
        )

        if not one_h:
            return None

        result = engine.analyze_market_structure(
            daily,
            four_h,
            one_h,
            "crypto"
        )

        if not isinstance(result, dict):
            return None

        result["symbol"] = symbol

        current_price = get_current_price(
            symbol
        )

        if current_price:
            result["current_price"] = current_price
        else:
            result["current_price"] = result.get(
                "price",
                0
            )

        return result

    except Exception as e:
        logger.exception(
            "Analyze symbol error %s: %s",
            symbol,
            e
        )

        return None


# ============================================================
# NUMBER FORMAT
# ============================================================

def fmt(value):
    try:
        value = float(value)

        if value >= 1000:
            return f"{value:,.2f}"

        if value >= 1:
            return f"{value:.4f}"

        if value >= 0.01:
            return f"{value:.6f}"

        return f"{value:.8f}"

    except Exception:
        return "-"


def pct(value):
    try:
        return f"{float(value):.2f}%"
    except Exception:
        return "-"


# ============================================================
# SIGNAL MESSAGE
# ============================================================

def format_signal(result):
    symbol = html.escape(
        str(result.get("symbol", "-"))
    )

    signal = result.get(
        "signal",
        "NO TRADE"
    )

    score = result.get(
        "score",
        0
    )

    phase = result.get(
        "phase",
        "-"
    )

    price = result.get(
        "current_price",
        result.get("price", 0)
    )

    # --------------------------------------------------------
    # NO TRADE
    # --------------------------------------------------------

    if signal != "LONG":
        reason = html.escape(
            str(
                result.get(
                    "reason",
                    "لا توجد فرصة مكتملة"
                )
            )
        )

        return (
            f"🔍 <b>MY EXPERT CRYPTO BOT V123.0</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🪙 <b>{symbol}</b>\n"
            f"📌 الحالة: ⚪ <b>NO TRADE</b>\n"
            f"⭐ التقييم: <b>{score}/100</b>\n"
            f"📊 المرحلة: <b>{phase}</b>\n"
            f"💰 السعر: <b>{fmt(price)}</b>\n"
            f"📝 السبب:\n"
            f"{reason}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🛡️ Anti-Chase فعال\n"
            f"⏳ لا نطارد الصعود"
        )

    # --------------------------------------------------------
    # LONG
    # --------------------------------------------------------

    entry_low = result.get(
        "entry_low",
        result.get("entry", price)
    )

    entry_high = result.get(
        "entry_high",
        price
    )

    sl = result.get(
        "stop_loss"
    )

    tp1 = result.get("tp1")
    tp2 = result.get("tp2")
    tp3 = result.get("tp3")

    risk = result.get(
        "risk_pct",
        0
    )

    rr1 = result.get(
        "rr_tp1",
        0
    )

    rr2 = result.get(
        "rr_tp2",
        0
    )

    rr3 = result.get(
        "rr_tp3",
        0
    )

    rsi = result.get(
        "rsi",
        0
    )

    volume = result.get(
        "volume_ratio",
        0
    )

    pullback = result.get(
        "pullback_depth",
        0
    )

    extension = result.get(
        "extension_atr",
        0
    )

    reason = html.escape(
        str(
            result.get(
                "reason",
                ""
            )
        )
    )

    return (
        f"🟢 <b>LONG SIGNAL — V123.0</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🪙 <b>{symbol}</b>\n"
        f"📌 الحالة: 🟢 <b>LONG</b>\n"
        f"⭐ التقييم: <b>{score}/100</b>\n"
        f"📊 المرحلة: <b>{phase}</b>\n\n"

        f"💰 السعر الحالي: <b>{fmt(price)}</b>\n"
        f"🎯 منطقة الدخول:\n"
        f"   <b>{fmt(entry_low)} → {fmt(entry_high)}</b>\n\n"

        f"🛑 وقف الخسارة: <b>{fmt(sl)}</b>\n"
        f"📈 TP1: <b>{fmt(tp1)}</b> "
        f"(R:R {rr1:.2f})\n"
        f"📈 TP2: <b>{fmt(tp2)}</b> "
        f"(R:R {rr2:.2f})\n"
        f"📈 TP3: <b>{fmt(tp3)}</b> "
        f"(R:R {rr3:.2f})\n\n"

        f"🛡️ المخاطرة: <b>{pct(risk)}</b>\n"
        f"📉 RSI 1H: <b>{rsi:.1f}</b>\n"
        f"📊 Volume: <b>{volume:.2f}x</b>\n"
        f"↩️ Pullback: <b>{pullback:.2f}%</b>\n"
        f"📐 Extension: <b>{extension:.2f} ATR</b>\n\n"

        f"🧭 Daily: <b>BULLISH</b>\n"
        f"🏛️ 4H: <b>BULLISH</b>\n"
        f"⏱️ 1H: <b>RECLAIM CONFIRMED</b>\n\n"

        f"📝 {reason}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ إشارة تحليلية وليست ضماناً للربح\n"
        f"🚫 البوت لا ينفذ أي أوامر"
    )


# ============================================================
# /START
# ============================================================

def handle_start(chat_id):
    text = (
        "🏛️ <b>MY EXPERT CRYPTO BOT V123.0</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🧠 Swing Timing + Anti-Chase Engine\n\n"
        "النسخة الجديدة لا تشتري لمجرد أن الاتجاه صاعد.\n\n"
        "✅ Daily Bias\n"
        "✅ 4H Structure\n"
        "✅ 1H Pullback\n"
        "✅ Reclaim / MSS\n"
        "✅ Entry Timing\n"
        "✅ Anti-Chase Shield\n"
        "✅ Late Trend Protection\n\n"
        "الأوامر:\n"
        "🔹 /scan — فحص السوق\n"
        "🔹 /status — حالة البوت\n"
        "🔹 /coin BTC — تحليل عملة\n"
        "🔹 /help — المساعدة"
    )

    tg_send(
        chat_id,
        text
    )


# ============================================================
# /STATUS
# ============================================================

def handle_status(chat_id):
    uptime = int(
        time.time() - bot_started_at
    )

    hours = uptime // 3600
    minutes = (
        uptime % 3600
    ) // 60

    text = (
        "🏛️ <b>MY EXPERT CRYPTO BOT V123.0</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🟢 الحالة: <b>ONLINE</b>\n"
        "📡 Exchange: <b>BingX</b>\n"
        "🧠 Strategy: <b>V123 Swing Timing</b>\n"
        "📈 Mode: <b>LONG ONLY</b>\n"
        "🛡️ Anti-Chase: <b>ACTIVE</b>\n"
        "🚫 Order Execution: <b>OFF</b>\n"
        f"⏱️ Uptime: <b>{hours}h {minutes}m</b>"
    )

    tg_send(
        chat_id,
        text
    )


# ============================================================
# /COIN
# ============================================================

def handle_coin(
    chat_id,
    symbol
):
    tg_send(
        chat_id,
        "🔍 جارٍ تحليل العملة على BingX...\n"
        "⏳ Daily → 4H → 1H"
    )

    result = analyze_symbol(
        symbol
    )

    if not result:
        tg_send(
            chat_id,
            "❌ تعذر الحصول على بيانات كافية لهذه العملة."
        )
        return

    with state_lock:
        last_signals[
            result["symbol"]
        ] = result

    tg_send(
        chat_id,
        format_signal(result)
    )


# ============================================================
# MARKET SCAN
# ============================================================

def scan_market(chat_id):
    tg_send(
        chat_id,
        "🔍 <b>بدأ فحص السوق...</b>\n"
        "🧠 V123 يبحث عن:\n"
        "Daily bullish + 4H structure + "
        "Pullback + Reclaim\n\n"
        "🛡️ الصفقات المتأخرة سيتم رفضها."
    )

    try:
        symbols = get_usdt_symbols()

        if not symbols:
            tg_send(
                chat_id,
                "❌ لم أجد أزواج USDT مناسبة."
            )
            return

        candidates = []

        checked = 0

        for symbol in symbols:
            checked += 1

            try:
                result = analyze_symbol(
                    symbol
                )

                if not result:
                    continue

                if result.get(
                    "signal"
                ) != "LONG":
                    continue

                score = int(
                    result.get(
                        "score",
                        0
                    )
                )

                if score >= MIN_SCORE:
                    candidates.append(
                        result
                    )

            except Exception as e:
                logger.warning(
                    "Scan error %s: %s",
                    symbol,
                    e
                )

        candidates.sort(
            key=lambda x: int(
                x.get("score", 0)
            ),
            reverse=True
        )

        if not candidates:
            tg_send(
                chat_id,
                (
                    "⚪ <b>لا توجد صفقة LONG مكتملة حالياً.</b>\n\n"
                    f"🔎 تم فحص: <b>{checked}</b> زوج\n"
                    "🛡️ البوت رفض الدخولات المتأخرة "
                    "بدلاً من مطاردة القمم.\n\n"
                    "⏳ الأفضل انتظار Pullback + Reclaim."
                )
            )

            return

        # Send top candidates only
        top = candidates[:5]

        header = (
            "🟢 <b>V123 LONG OPPORTUNITIES</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"🎯 أفضل {len(top)} فرص حالية\n"
            "🛡️ Anti-Chase ACTIVE\n\n"
        )

        tg_send(
            chat_id,
            header
        )

        for result in top:
            tg_send(
                chat_id,
                format_signal(result)
            )

            time.sleep(0.5)

        with state_lock:
            for result in top:
                last_signals[
                    result["symbol"]
                ] = result

    except Exception as e:
        logger.exception(
            "Market scan error: %s",
            e
        )

        tg_send(
            chat_id,
            "❌ حدث خطأ أثناء فحص السوق."
        )


# ============================================================
# HELP
# ============================================================

def handle_help(chat_id):
    text = (
        "📚 <b>MY EXPERT CRYPTO BOT</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "/start\n"
        "تشغيل القائمة الرئيسية.\n\n"
        "/scan\n"
        "فحص أزواج BingX والبحث عن LONG مكتمل.\n\n"
        "/coin BTC\n"
        "تحليل BTC بالتفصيل.\n\n"
        "/status\n"
        "حالة البوت.\n\n"
        "🧠 الاستراتيجية:\n"
        "Daily → 4H → 1H\n"
        "Trend → Pullback → Reclaim → Entry\n\n"
        "🛡️ لا يتم شراء الحركة بعد امتدادها."
    )

    tg_send(
        chat_id,
        text
    )


# ============================================================
# TELEGRAM WEBHOOK
# ============================================================

@app.route(
    "/telegram",
    methods=["POST"]
)
def telegram_webhook():
    try:
        update = request.get_json(
            silent=True
        ) or {}

        message = update.get(
            "message",
            {}
        )

        chat = message.get(
            "chat",
            {}
        )

        chat_id = chat.get(
            "id"
        )

        if chat_id is None:
            return jsonify(
                {"ok": True}
            )

        if not is_allowed(chat_id):
            logger.warning(
                "Unauthorized chat: %s",
                chat_id
            )

            return jsonify(
                {"ok": True}
            )

        text = (
            message.get(
                "text",
                ""
            )
            .strip()
        )

        if not text:
            return jsonify(
                {"ok": True}
            )

        lower = text.lower()

        if lower.startswith(
            "/start"
        ):
            handle_start(
                chat_id
            )

        elif lower.startswith(
            "/status"
        ):
            handle_status(
                chat_id
            )

        elif lower.startswith(
            "/help"
        ):
            handle_help(
                chat_id
            )

        elif lower.startswith(
            "/scan"
        ):
            threading.Thread(
                target=scan_market,
                args=(chat_id,),
                daemon=True
            ).start()

        elif lower.startswith(
            "/coin"
        ):
            parts = text.split()

            if len(parts) >= 2:
                handle_coin(
                    chat_id,
                    parts[1]
                )
            else:
                tg_send(
                    chat_id,
                    "اكتب مثلاً:\n"
                    "<code>/coin BTC</code>"
                )

        else:
            # Direct coin query
            symbol = normalize_symbol(
                text
            )

            if symbol:
                handle_coin(
                    chat_id,
                    symbol
                )

        return jsonify(
            {"ok": True}
        )

    except Exception as e:
        logger.exception(
            "Webhook error: %s",
            e
        )

        return jsonify(
            {"ok": True}
        )


# ============================================================
# HEALTH
# ============================================================

@app.route(
    "/",
    methods=["GET"]
)
def home():
    return (
        "MY EXPERT CRYPTO BOT V123.0 "
        "ONLINE"
    )


@app.route(
    "/health",
    methods=["GET"]
)
def health():
    return jsonify({
        "status": "ok",
        "version": "123.0",
        "strategy": (
            "Swing Timing + Anti-Chase"
        ),
        "mode": "LONG_ONLY",
        "signal_only": True
    })


# ============================================================
# AUTO SCAN
# ============================================================

def background_auto_scheduler():
    global last_auto_scan

    while True:
        try:
            time.sleep(30)

            if not CHAT_ID:
                continue

            now = time.time()

            if (
                now - last_auto_scan
                < AUTO_SCAN_INTERVAL
            ):
                continue

            last_auto_scan = now

            logger.info(
                "Starting automatic scan..."
            )

            threading.Thread(
                target=scan_market,
                args=(CHAT_ID,),
                daemon=True
            ).start()

        except Exception as e:
            logger.exception(
                "Scheduler error: %s",
                e
            )


# ============================================================
# STARTUP
# ============================================================

def startup():
    logger.info(
        "================================================"
    )

    logger.info(
        "MY EXPERT CRYPTO BOT V123.0"
    )

    logger.info(
        "Swing Timing + Anti-Chase"
    )

    logger.info(
        "LONG ONLY | SIGNAL ONLY"
    )

    logger.info(
        "================================================"
    )

    # Prevent stale webhook configuration
    tg_delete_webhook()

    if CHAT_ID:
        tg_send(
            CHAT_ID,
            (
                "🏛️ <b>MY EXPERT CRYPTO BOT V123.0</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "🟢 تم تشغيل النسخة الجديدة.\n\n"
                "🧠 Trend + Pullback + Reclaim\n"
                "🛡️ Anti-Chase Shield: ACTIVE\n"
                "🚫 Late Entry Shield: ACTIVE\n"
                "📈 LONG ONLY\n"
                "🚫 بدون تنفيذ أوامر\n\n"
                "استخدم /scan للفحص."
            )
        )

    threading.Thread(
        target=background_auto_scheduler,
        daemon=True
    ).start()


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    startup()

    port = int(
        os.getenv(
            "PORT",
            "10000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
