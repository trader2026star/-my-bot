# ============================================================
# MY EXPERT CRYPTO BOT - V123.1
# FIXED TELEGRAM WEBHOOK FOR RENDER + GUNICORN
#
# LONG ONLY
# SIGNAL ONLY - NO ORDER EXECUTION
# Compatible with analysis.py V123.0
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

logger = logging.getLogger("MY_EXPERT_CRYPTO_BOT")


# ============================================================
# ENVIRONMENT
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

# Render automatically provides this variable.
RENDER_EXTERNAL_URL = os.getenv(
    "RENDER_EXTERNAL_URL",
    ""
)

# Optional manual URL if needed.
WEBHOOK_URL = os.getenv(
    "WEBHOOK_URL",
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
# TELEGRAM URL
# ============================================================

def telegram_url(method):
    return (
        f"https://api.telegram.org/"
        f"bot{BOT_TOKEN}/{method}"
    )


# ============================================================
# TELEGRAM SEND
# ============================================================

def tg_send(chat_id, text):
    if not BOT_TOKEN:
        logger.error(
            "TELEGRAM_BOT_TOKEN is missing"
        )
        return False

    if not chat_id:
        logger.error(
            "Telegram chat_id is missing"
        )
        return False

    try:
        response = requests.post(
            telegram_url("sendMessage"),
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            },
            timeout=20
        )

        if response.ok:
            logger.info(
                "Telegram message sent successfully"
            )
            return True

        logger.error(
            "Telegram send failed: %s | %s",
            response.status_code,
            response.text[:1000]
        )

        return False

    except Exception as e:
        logger.exception(
            "Telegram send exception: %s",
            e
        )
        return False


# ============================================================
# SET WEBHOOK
# ============================================================

def setup_webhook():
    """
    Important:
    Gunicorn imports main.py.
    Therefore startup() under __main__ is NOT executed.
    This function is explicitly called during module startup.
    """

    if not BOT_TOKEN:
        logger.error(
            "❌ TELEGRAM_BOT_TOKEN is missing"
        )
        return False

    base_url = (
        WEBHOOK_URL
        or RENDER_EXTERNAL_URL
    )

    if not base_url:
        logger.error(
            "❌ No Render URL found."
        )
        logger.error(
            "Set WEBHOOK_URL or use RENDER_EXTERNAL_URL."
        )
        return False

    base_url = base_url.rstrip("/")

    webhook = (
        f"{base_url}/telegram"
    )

    try:
        # First inspect bot status
        info = requests.get(
            telegram_url("getWebhookInfo"),
            timeout=15
        )

        if info.ok:
            logger.info(
                "Current Telegram webhook: %s",
                info.json().get(
                    "result",
                    {}
                ).get(
                    "url",
                    ""
                )
            )

        # Set webhook
        response = requests.post(
            telegram_url("setWebhook"),
            json={
                "url": webhook,
                "drop_pending_updates": False
            },
            timeout=20
        )

        if response.ok:
            data = response.json()

            if data.get("ok"):
                logger.info(
                    "✅ Telegram webhook configured:"
                )
                logger.info(
                    "%s",
                    webhook
                )
                return True

        logger.error(
            "❌ setWebhook failed: %s",
            response.text[:1000]
        )

    except Exception as e:
        logger.exception(
            "Webhook setup error: %s",
            e
        )

    return False


# ============================================================
# WEBHOOK STATUS
# ============================================================

def get_webhook_info():
    if not BOT_TOKEN:
        return None

    try:
        response = requests.get(
            telegram_url("getWebhookInfo"),
            timeout=15
        )

        if response.ok:
            return response.json()

    except Exception as e:
        logger.error(
            "Webhook info error: %s",
            e
        )

    return None


# ============================================================
# AUTH
# ============================================================

def is_allowed(chat_id):

    if not ALLOWED_CHAT_IDS:

        if not CHAT_ID:
            return True

        return (
            str(chat_id)
            == str(CHAT_ID)
        )

    allowed = {
        x.strip()
        for x in ALLOWED_CHAT_IDS.split(",")
        if x.strip()
    }

    return (
        str(chat_id)
        in allowed
    )


# ============================================================
# API THROTTLE
# ============================================================

def api_pause():

    global last_api_call

    now = time.time()

    elapsed = (
        now - last_api_call
    )

    if elapsed < API_MIN_INTERVAL:
        time.sleep(
            API_MIN_INTERVAL - elapsed
        )

    last_api_call = time.time()


# ============================================================
# SYMBOL
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

    try:
        api_pause()

        return exchange.load_markets()

    except Exception as e:

        logger.error(
            "load_markets failed: %s",
            e
        )

        return {}


# ============================================================
# USDT SYMBOLS
# ============================================================

def get_usdt_symbols():

    markets = load_markets()

    symbols = []

    for symbol, market in markets.items():

        try:

            if not market.get(
                "active",
                True
            ):
                continue

            if market.get(
                "quote"
            ) != "USDT":
                continue

            if market.get(
                "type"
            ) != "swap":
                continue

            if market.get(
                "linear"
            ) is not True:
                continue

            base = str(
                market.get(
                    "base",
                    ""
                )
            ).upper()

            blocked = (
                "INDEX",
                "COMMODITY",
                "GOLD",
                "SILVER",
                "OIL",
                "EUR",
                "GBP",
                "JPY"
            )

            if any(
                x in base
                for x in blocked
            ):
                continue

            symbols.append(
                symbol
            )

        except Exception:
            continue

    return sorted(
        set(symbols)
    )


# ============================================================
# OHLCV
# ============================================================

def fetch_ohlcv(
    symbol,
    timeframe,
    limit=100
):

    try:

        api_pause()

        data = exchange.fetch_ohlcv(
            symbol,
            timeframe=timeframe,
            limit=limit
        )

        if not data:
            return None

        return data

    except Exception as e:

        logger.warning(
            "OHLCV failed %s %s: %s",
            symbol,
            timeframe,
            e
        )

        return None


# ============================================================
# PRICE
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
# ANALYZE SYMBOL
# ============================================================

def analyze_symbol(symbol):

    symbol = normalize_symbol(
        symbol
    )

    if not symbol:
        return None

    try:

        logger.info(
            "Analyzing %s",
            symbol
        )

        daily = fetch_ohlcv(
            symbol,
            "1d",
            100
        )

        if not daily:
            return None

        time.sleep(
            SYMBOL_PAUSE
        )

        four_h = fetch_ohlcv(
            symbol,
            "4h",
            100
        )

        if not four_h:
            return None

        time.sleep(
            SYMBOL_PAUSE
        )

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

        if not isinstance(
            result,
            dict
        ):
            return None

        result["symbol"] = symbol

        current_price = (
            get_current_price(
                symbol
            )
        )

        result["current_price"] = (
            current_price
            or result.get(
                "price",
                0
            )
        )

        return result

    except Exception as e:

        logger.exception(
            "Analyze error %s: %s",
            symbol,
            e
        )

        return None


# ============================================================
# FORMAT
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
# FORMAT SIGNAL
# ============================================================

def format_signal(result):

    symbol = html.escape(
        str(
            result.get(
                "symbol",
                "-"
            )
        )
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
        result.get(
            "price",
            0
        )
    )

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
            f"🔍 <b>MY EXPERT CRYPTO BOT V123.1</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🪙 <b>{symbol}</b>\n"
            f"📌 الحالة: ⚪ <b>NO TRADE</b>\n"
            f"⭐ التقييم: <b>{score}/100</b>\n"
            f"📊 المرحلة: <b>{phase}</b>\n"
            f"💰 السعر: <b>{fmt(price)}</b>\n\n"
            f"📝 {reason}\n\n"
            f"🛡️ Anti-Chase ACTIVE\n"
            f"⏳ لا نطارد الصعود"
        )

    entry_low = result.get(
        "entry_low",
        result.get(
            "entry",
            price
        )
    )

    entry_high = result.get(
        "entry_high",
        price
    )

    sl = result.get(
        "stop_loss"
    )

    tp1 = result.get(
        "tp1"
    )

    tp2 = result.get(
        "tp2"
    )

    tp3 = result.get(
        "tp3"
    )

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

    return (
        f"🟢 <b>LONG SIGNAL — V123.1</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🪙 <b>{symbol}</b>\n"
        f"⭐ Score: <b>{score}/100</b>\n"
        f"📊 Phase: <b>{phase}</b>\n\n"

        f"💰 السعر: <b>{fmt(price)}</b>\n"
        f"🎯 الدخول:\n"
        f"<b>{fmt(entry_low)} → {fmt(entry_high)}</b>\n\n"

        f"🛑 SL: <b>{fmt(sl)}</b>\n"
        f"🎯 TP1: <b>{fmt(tp1)}</b> "
        f"R:R {rr1:.2f}\n"
        f"🎯 TP2: <b>{fmt(tp2)}</b> "
        f"R:R {rr2:.2f}\n"
        f"🎯 TP3: <b>{fmt(tp3)}</b> "
        f"R:R {rr3:.2f}\n\n"

        f"🛡️ Risk: <b>{pct(risk)}</b>\n"
        f"📉 RSI: <b>{rsi:.1f}</b>\n"
        f"📊 Volume: <b>{volume:.2f}x</b>\n"
        f"↩️ Pullback: <b>{pullback:.2f}%</b>\n"
        f"📐 Extension: <b>{extension:.2f} ATR</b>\n\n"

        f"🧭 Daily: BULLISH\n"
        f"🏛️ 4H: BULLISH\n"
        f"⏱️ 1H: RECLAIM CONFIRMED\n\n"

        f"⚠️ إشارة تحليلية فقط\n"
        f"🚫 بدون تنفيذ أوامر"
    )


# ============================================================
# START
# ============================================================

def handle_start(chat_id):

    tg_send(
        chat_id,
        (
            "🏛️ <b>MY EXPERT CRYPTO BOT V123.1</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🟢 البوت يعمل الآن.\n\n"
            "🧠 Swing Timing Engine\n"
            "🛡️ Anti-Chase Shield\n"
            "📈 LONG ONLY\n"
            "🚫 Signal Only\n\n"
            "الأوامر:\n"
            "/scan\n"
            "/coin BTC\n"
            "/status\n"
            "/help"
        )
    )


# ============================================================
# STATUS
# ============================================================

def handle_status(chat_id):

    webhook = get_webhook_info()

    webhook_url = ""

    if webhook:

        webhook_url = (
            webhook.get(
                "result",
                {}
            ).get(
                "url",
                ""
            )
        )

    if webhook_url:
        telegram_status = (
            "🟢 WEBHOOK CONNECTED"
        )
    else:
        telegram_status = (
            "🔴 WEBHOOK NOT CONNECTED"
        )

    uptime = int(
        time.time()
        - bot_started_at
    )

    hours = uptime // 3600

    minutes = (
        uptime % 3600
    ) // 60

    tg_send(
        chat_id,
        (
            "🏛️ <b>MY EXPERT CRYPTO BOT V123.1</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🟢 Bot: ONLINE\n"
            f"📡 Telegram: <b>{telegram_status}</b>\n"
            "📡 Exchange: BingX\n"
            "🧠 Strategy: V123.0\n"
            "📈 Mode: LONG ONLY\n"
            "🛡️ Anti-Chase: ACTIVE\n"
            "🚫 Orders: OFF\n"
            f"⏱️ Uptime: {hours}h {minutes}m\n\n"
            f"Webhook:\n<code>{html.escape(webhook_url or 'NONE')}</code>"
        )
    )


# ============================================================
# HELP
# ============================================================

def handle_help(chat_id):

    tg_send(
        chat_id,
        (
            "📚 <b>الأوامر</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "/start\n"
            "تشغيل البوت.\n\n"
            "/scan\n"
            "فحص السوق.\n\n"
            "/coin BTC\n"
            "تحليل BTC.\n\n"
            "/status\n"
            "حالة Telegram وWebhook.\n\n"
            "/help\n"
            "المساعدة."
        )
    )


# ============================================================
# COIN
# ============================================================

def handle_coin(
    chat_id,
    symbol
):

    tg_send(
        chat_id,
        (
            "🔍 <b>جارٍ التحليل...</b>\n"
            "Daily → 4H → 1H\n"
            "🛡️ Anti-Chase يعمل"
        )
    )

    result = analyze_symbol(
        symbol
    )

    if not result:

        tg_send(
            chat_id,
            (
                "❌ لم أستطع الحصول على "
                "بيانات كافية للعملة."
            )
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
# SCAN
# ============================================================

def scan_market(chat_id):

    tg_send(
        chat_id,
        (
            "🔍 <b>بدأ فحص السوق</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🧠 Daily → 4H → 1H\n"
            "↩️ Pullback\n"
            "🔄 Reclaim\n"
            "🛡️ Anti-Chase\n\n"
            "⏳ انتظر..."
        )
    )

    try:

        symbols = get_usdt_symbols()

        logger.info(
            "Scan symbols: %s",
            len(symbols)
        )

        if not symbols:

            tg_send(
                chat_id,
                "❌ لم أجد أزواج USDT."
            )

            return

        candidates = []

        for symbol in symbols:

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
                    "Scan %s: %s",
                    symbol,
                    e
                )

        candidates.sort(
            key=lambda x: int(
                x.get(
                    "score",
                    0
                )
            ),
            reverse=True
        )

        if not candidates:

            tg_send(
                chat_id,
                (
                    "⚪ <b>لا توجد صفقة LONG مكتملة.</b>\n\n"
                    f"🔎 تم فحص: {len(symbols)} زوج\n"
                    "🛡️ تم رفض الدخولات المتأخرة.\n"
                    "⏳ ننتظر Pullback + Reclaim."
                )
            )

            return

        top = candidates[:5]

        tg_send(
            chat_id,
            (
                "🟢 <b>أفضل فرص LONG حالياً</b>\n"
                "━━━━━━━━━━━━━━━━━━"
            )
        )

        for result in top:

            with state_lock:

                last_signals[
                    result["symbol"]
                ] = result

            tg_send(
                chat_id,
                format_signal(result)
            )

            time.sleep(0.4)

    except Exception as e:

        logger.exception(
            "Scan error: %s",
            e
        )

        tg_send(
            chat_id,
            "❌ حدث خطأ أثناء فحص السوق."


        )


# ============================================================
# TELEGRAM WEBHOOK ENDPOINT
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

        logger.info(
            "Telegram update received"
        )

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

        if not is_allowed(
            chat_id
        ):

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

        logger.info(
            "Telegram command from %s: %s",
            chat_id,
            text
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
                    "اكتب:\n<code>/coin BTC</code>"
                )

        else:

            # Direct coin name
            handle_coin(
                chat_id,
                text
            )

        return jsonify(
            {"ok": True}
        )

    except Exception as e:

        logger.exception(
            "Webhook processing error: %s",
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
        "MY EXPERT CRYPTO BOT V123.1 "
        "ONLINE"
    )


@app.route(
    "/health",
    methods=["GET"]
)
def health():

    return jsonify({
        "status": "ok",
        "version": "123.1",
        "telegram": bool(
            BOT_TOKEN
        ),
        "render_url": bool(
            RENDER_EXTERNAL_URL
            or WEBHOOK_URL
        ),
        "strategy": (
            "Swing Timing + Anti-Chase"
        ),
        "mode": "LONG_ONLY",
        "signal_only": True
    })


# ============================================================
# STARTUP INITIALIZATION
# ============================================================

def initialize():

    logger.info(
        "=========================================="
    )

    logger.info(
        "MY EXPERT CRYPTO BOT V123.1"
    )

    logger.info(
        "Initializing..."
    )

    if not BOT_TOKEN:

        logger.error(
            "❌ TELEGRAM_BOT_TOKEN NOT FOUND"
        )

    else:

        logger.info(
            "✅ Telegram token found"
        )

    # IMPORTANT:
    # This executes when Gunicorn imports main.py.
    setup_webhook()

    logger.info(
        "Initialization complete"
    )

    logger.info(
        "=========================================="
    )


# ============================================================
# RUN INITIALIZATION ON IMPORT
# ============================================================

initialize()


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

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
