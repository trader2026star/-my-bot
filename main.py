# ============================================================
# MY EXPERT CRYPTO BOT - V123.3 (EXPERT SMC/ICT EDITION)
# FIXED TELEGRAM WEBHOOK FOR RENDER + GUNICORN
#
# Signal-only
# LONG ONLY (Viable / Not Viable Evaluation)
# BingX Futures
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

# Render automatically provides this variable.
RENDER_EXTERNAL_URL = os.getenv(
    "RENDER_EXTERNAL_URL",
    ""
)

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
# STRATEGY (SMC / ICT / FVG / iFVG / AMD ENGINE)
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


def setup_webhook():
    """
    Important: Gunicorn imports main.py.
    This function is explicitly called during module startup.
    """
    if not BOT_TOKEN:
        logger.error("❌ TELEGRAM_BOT_TOKEN is missing")
        return False

    base_url = WEBHOOK_URL or RENDER_EXTERNAL_URL

    if not base_url:
        logger.error("❌ No Render URL found. Set WEBHOOK_URL or use RENDER_EXTERNAL_URL.")
        return False

    base_url = base_url.rstrip("/")
    webhook = f"{base_url}/tg-webhook"

    try:
        info = requests.get(tg_url("getWebhookInfo"), timeout=15)
        if info.ok:
            logger.info("Current Telegram webhook: %s", info.json().get("result", {}).get("url", ""))

        response = requests.post(
            tg_url("setWebhook"),
            json={
                "url": webhook,
                "drop_pending_updates": False
            },
            timeout=20
        )

        if response.ok and response.json().get("ok"):
            logger.info("✅ Telegram webhook configured: %s", webhook)
            return True

        logger.error("❌ setWebhook failed: %s", response.text[:1000])
    except Exception as e:
        logger.exception("Webhook setup error: %s", e)

    return False


def get_webhook_info():
    if not BOT_TOKEN:
        return None
    try:
        res = requests.get(tg_url("getWebhookInfo"), timeout=15)
        if res.ok:
            return res.json()
    except Exception:
        pass
    return None


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
    return exchange.load_markets()


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

def fetch_ohlcv(symbol, timeframe, limit=150):
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
        ticker = exchange.fetch_ticker(symbol)
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
# SYMBOL ANALYSIS (EXPERT SMC / ICT / AMD ENGINE)
# ============================================================

def analyze_symbol(symbol):
    symbol = normalize_symbol(symbol)

    if not symbol:
        return None

    try:
        daily = fetch_ohlcv(symbol, "1d", 150)
        if not daily:
            return None

        time.sleep(SYMBOL_PAUSE)

        four_h = fetch_ohlcv(symbol, "4h", 150)
        if not four_h:
            return None

        time.sleep(SYMBOL_PAUSE)

        one_h = fetch_ohlcv(symbol, "1h", 150)
        if not one_h:
            return None

        time.sleep(SYMBOL_PAUSE)
        fifteen_m = fetch_ohlcv(symbol, "15m", 150)

        # استدعاء محرك التحليل المتقدم المدمج في analysis.py
        result = engine.analyze_market_structure(
            daily,
            four_h,
            one_h,
            fifteen_m if fifteen_m else one_h,
            "crypto"
        )

        if not isinstance(result, dict):
            return None

        result["symbol"] = symbol

        current_price = get_current_price(symbol)
        if current_price:
            result["current_price"] = current_price
        else:
            result["current_price"] = result.get("price", 0)

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
# SIGNAL MESSAGE (VIABLE / NOT VIABLE & SMC/ICT)
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

    viability_status = "🟢 يصلح للتداول (Viable)" if score >= MIN_SCORE else "🔴 لا يصلح للتداول (Not Viable)"

    if signal != "LONG":
        reason = html.escape(
            str(
                result.get(
                    "reason",
                    "لا توجد فرصة مكتملة أو لم تتوافق شروط السيولة والـ FVG"
                )
            )
        )

        return (
            f"🏛️ <b>EXPERT CRYPTO ANALYST — V123.3</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🪙 <b>{symbol}</b>\n"
            f"📌 حالة التقييم: <b>{viability_status}</b>\n"
            f"⭐ التقييم الشامل: <b>{score}/100</b>\n"
            f"📊 المرحلة السوقية (AMD): <b>{phase}</b>\n"
            f"💰 السعر الحالي: <b>{fmt(price)}</b>\n\n"
            f"📝 <b>السبب الفني:</b>\n{reason}\n\n"
            f"🛡️ Smart Money & Liquidity Guard: <b>ACTIVE</b>"
        )

    entry_low = result.get(
        "entry_low",
        result.get("entry", price)
    )

    entry_high = result.get(
        "entry_high",
        price
    )

    sl = result.get("stop_loss")
    tp1 = result.get("tp1")
    tp2 = result.get("tp2")
    tp3 = result.get("tp3")

    risk = result.get("risk_pct", 0)
    rr1 = result.get("rr_tp1", 0)
    rr2 = result.get("rr_tp2", 0)
    rr3 = result.get("rr_tp3", 0)

    fvg_status = result.get("fvg_status", "مؤكد (Confirmed)")
    ifvg_status = result.get("ifvg_status", "متوافق (Active)")
    bos_status = result.get("bos_status", "تم الاختراق بنجاح (BOS / CHoCH)")

    return (
        f"💎 <b>EXPERT LONG SIGNAL — V123.3</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🪙 <b>{symbol}</b>\n"
        f"🎯 القرار الفني: <b>{viability_status}</b>\n"
        f"⭐ التقييم الاحترافي: <b>{score}/100</b>\n"
        f"📊 دورة السوق (AMD): <b>{phase}</b>\n\n"

        f"💰 سعر السوق: <b>{fmt(price)}</b>\n"
        f"📍 <b>منطقة الدخول المثالية (Smart Money):</b>\n"
        f"   <b>{fmt(entry_low)} → {fmt(entry_high)}</b>\n\n"

        f"🛑 وقف الخسارة (SL): <b>{fmt(sl)}</b>\n"
        f"🎯 الهدف الأول (TP1): <b>{fmt(tp1)}</b> (R:R {rr1:.2f})\n"
        f"🎯 الهدف الثاني (TP2): <b>{fmt(tp2)}</b> (R:R {rr2:.2f})\n"
        f"🎯 الهدف الثالث (TP3): <b>{fmt(tp3)}</b> (R:R {rr3:.2f})\n\n"

        f"📐 <b>التحليل الهيكلي المتقدم:</b>\n"
        f"🔹 FVG / iFVG: <b>{fvg_status} / {ifvg_status}</b>\n"
        f"🔹 BOS / CHoCH: <b>{bos_status}</b>\n"
        f"🔹 إدارة المخاطر: <b>Risk {pct(risk)}</b>\n\n"

        f"⚠️ تقرير تحليل خبير (سحب سيولة + مناطق الطلب المؤسسية)\n"
        f"🚫 بدون تنفيذ آلي للأوامر"
    )


# ============================================================
# /START
# ============================================================

def handle_start(chat_id):
    text = (
        "🏛️ <b>EXPERT CRYPTO ANALYST BOT V123.3</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🟢 البوت يعمل بكامل قوة التحليل الاحترافي.\n\n"
        "🧠 SMC & ICT Master Engine\n"
        "⚡ FVG, iFVG, BOS, CHoCH & Power of 3 (AMD)\n"
        "📈 LONG ONLY (Viable / Not Viable Evaluation)\n\n"
        "الأوامر:\n"
        "🔹 /scan — فحص السوق\n"
        "🔹 /status — حالة البوت\n"
        "🔹 /coin BTC — تحليل عملة\n"
        "🔹 /help — المساعدة"
    )

    tg_send(chat_id, text)


# ============================================================
# /STATUS
# ============================================================

def handle_status(chat_id):
    webhook = get_webhook_info()
    webhook_url = ""
    if webhook:
        webhook_url = webhook.get("result", {}).get("url", "")

    telegram_status = "🟢 WEBHOOK CONNECTED" if webhook_url else "🔴 WEBHOOK NOT CONNECTED"

    uptime = int(time.time() - bot_started_at)
    hours = uptime // 3600
    minutes = (uptime % 3600) // 60

    text = (
        "🏛️ <b>EXPERT CRYPTO BOT STATUS V123.3</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📡 Telegram: <b>{telegram_status}</b>\n"
        "📡 Exchange: <b>BingX Swap</b>\n"
        "🧠 Engine: <b>SMC / ICT / AMD Pro</b>\n"
        "📈 Mode: <b>LONG ONLY</b>\n"
        f"⏱️ Uptime: <b>{hours}h {minutes}m</b>\n\n"
        f"Webhook URL:\n<code>{html.escape(webhook_url or 'NONE')}</code>"
    )

    tg_send(chat_id, text)


# ============================================================
# /COIN
# ============================================================

def handle_coin(chat_id, symbol):
    tg_send(
        chat_id,
        "🔍 <b>جارٍ تطبيق التحليل الاحترافي (SMC / ICT)...</b>\n"
        "📊 فحص سيولة السوق + الحزم الفراغية (FVG / iFVG)\n"
        "⏳ يرجى الانتظار..."
    )

    result = analyze_symbol(symbol)

    if not result:
        tg_send(
            chat_id,
            "❌ تعذر الحصول على بيانات كافية أو العملة غير موجودة في العقود الآجلة."
        )
        return

    with state_lock:
        last_signals[result["symbol"]] = result

    tg_send(chat_id, format_signal(result))


# ============================================================
# MARKET SCAN
# ============================================================

def scan_market(chat_id):
    tg_send(
        chat_id,
        "🔍 <b>بدء المسح الشامل للسوق (SMC / ICT Engine)</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🧠 تحليل السيولة، الهيكلة (BOS/CHoCH)، ونظرية AMD\n\n"
        "⏳ جاري الفحص، قد يستغرق بعض الوقت..."
    )

    try:
        symbols = get_usdt_symbols()

        if not symbols:
            tg_send(chat_id, "❌ لم أجد أزواج USDT مناسبة.")
            return

        candidates = []
        checked = 0

        for symbol in symbols:
            checked += 1
            try:
                result = analyze_symbol(symbol)
                if not result:
                    continue

                if result.get("signal") != "LONG":
                    continue

                score = int(result.get("score", 0))

                if score >= MIN_SCORE:
                    candidates.append(result)

            except Exception as e:
                logger.warning("Scan error %s: %s", symbol, e)

        candidates.sort(
            key=lambda x: int(x.get("score", 0)),
            reverse=True
        )

        if not candidates:
            tg_send(
                chat_id,
                (
                    "⚪ <b>لا توجد فرص مطابقة للشروط الاحترافية حالياً.</b>\n\n"
                    f"🔎 تم فحص: <b>{checked}</b> زوج\n"
                    "🛡️ تم استبعاد الصفقات الضعيفة وغير المكتملة."
                )
            )
            return

        top = candidates[:5]

        tg_send(
            chat_id,
            (
                "🟢 <b>أفضل الفرص المؤكدة (Viable Setups)</b>\n"
                "━━━━━━━━━━━━━━━━━━"
            )
        )

        for result in top:
            tg_send(chat_id, format_signal(result))
            time.sleep(0.4)

        with state_lock:
            for result in top:
                last_signals[result["symbol"]] = result

    except Exception as e:
        logger.exception("Market scan error: %s", e)
        tg_send(chat_id, "❌ حدث خطأ أثناء فحص السوق.")


# ============================================================
# HELP
# ============================================================

def handle_help(chat_id):
    text = (
        "📚 <b>دليل الأوامر والاستخدام</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "/start — تشغيل البوت.\n"
        "/scan — فحص شامل للسيولة والأزواج.\n"
        "/coin BTC — تحليل عميق للعملة.\n"
        "/status — فحص اتصال الـ Webhook.\n\n"
        "💡 يمكنك إرسال اسم أي عملة مباشرة وسيقوم البوت بإعطائك تقرير فني شامل."
    )

    tg_send(chat_id, text)


# ============================================================
# TELEGRAM WEBHOOK (مربوط حصرياً على /tg-webhook لتفادي أخطاء 404)
# ============================================================

@app.route(
    "/tg-webhook",
    methods=["POST"]
)
def telegram_webhook():
    try:
        update = request.get_json(silent=True) or {}
        message = update.get("message", {})
        chat = message.get("chat", {})
        chat_id = chat.get("id")

        if chat_id is None:
            return jsonify({"ok": True})

        if not is_allowed(chat_id):
            logger.warning("Unauthorized chat: %s", chat_id)
            return jsonify({"ok": True})

        text = message.get("text", "").strip()
        if not text:
            return jsonify({"ok": True})

        lower = text.lower()

        if lower.startswith("/start"):
            handle_start(chat_id)
        elif lower.startswith("/status"):
            handle_status(chat_id)
        elif lower.startswith("/help"):
            handle_help(chat_id)
        elif lower.startswith("/scan"):
            threading.Thread(
                target=scan_market,
                args=(chat_id,),
                daemon=True
            ).start()
        elif lower.startswith("/coin"):
            parts = text.split()
            if len(parts) >= 2:
                handle_coin(chat_id, parts[1])
            else:
                tg_send(chat_id, "اكتب العملة بهذا الشكل:\n<code>/coin BTC</code>")
        else:
            symbol = normalize_symbol(text)
            if symbol:
                handle_coin(chat_id, symbol)

        return jsonify({"ok": True})

    except Exception as e:
        logger.exception("Webhook error: %s", e)
        return jsonify({"ok": True})


# ============================================================
# HEALTH & HOME
# ============================================================

@app.route(
    ",".join(["/", "/health"]),
    methods=["GET", "HEAD"]
)
def home():
    return jsonify({
        "status": "ok",
        "version": "123.3",
        "engine": "SMC + ICT + AMD Pro",
        "telegram": bool(BOT_TOKEN),
        "webhook_endpoint": "/tg-webhook"
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
            if now - last_auto_scan < AUTO_SCAN_INTERVAL:
                continue

            last_auto_scan = now
            logger.info("Starting automatic scan...")

            threading.Thread(
                target=scan_market,
                args=(CHAT_ID,),
                daemon=True
            ).start()

        except Exception as e:
            logger.exception("Scheduler error: %s", e)


# ============================================================
# STARTUP INITIALIZATION
# ============================================================

def startup():
    logger.info("================================================")
    logger.info("MY EXPERT CRYPTO BOT V123.3")
    logger.info("SMC / ICT / AMD Pro Edition")
    logger.info("LONG ONLY | SIGNAL ONLY")
    logger.info("================================================")

    # إعداد وتثبيت الـ Webhook تلقائياً عند بدء التشغيل ليعمل مع Gunicorn على Render
    setup_webhook()

    if CHAT_ID:
        tg_send(
            CHAT_ID,
            (
                "🏛️ <b>MY EXPERT CRYPTO BOT V123.3</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "🟢 تم تشغيل النسخة الاحترافية بنجاح.\n\n"
                "🧠 SMC, ICT, FVG, iFVG & AMD Engine\n"
                "📈 LONG ONLY (Viable / Not Viable)\n"
                "🚫 بدون تنفيذ أومات آلية\n\n"
                "استخدم /scan للفحص أو راسل البوت بأي عملة."
            )
        )

    threading.Thread(
        target=background_auto_scheduler,
        daemon=True
    ).start()


# ============================================================
# RUN INITIALIZATION ON IMPORT (CRITICAL FOR GUNICORN)
# ============================================================

startup()


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
