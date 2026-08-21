import os
import threading
from flask import Flask, request

import requests

from analysis import (
    analyze_symbol,
    scan_market,
    prepare_trade,
    format_price
)


# =========================================================
# SETTINGS
# =========================================================

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

if not TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")

RENDER_URL = os.environ.get(
    "RENDER_URL",
    "https://my-bot-mtyr.onrender.com"
).rstrip("/")

WEBHOOK_PATH = "/telegram/webhook"
WEBHOOK_URL = RENDER_URL + WEBHOOK_PATH

TELEGRAM_API = f"https://api.telegram.org/bot{TOKEN}"

app = Flask(__name__)


# =========================================================
# TELEGRAM
# =========================================================

def telegram_request(method, data=None):

    try:

        r = requests.post(
            f"{TELEGRAM_API}/{method}",
            json=data or {},
            timeout=20
        )

        print(
            "Telegram:",
            method,
            r.status_code,
            r.text[:500]
        )

        return r.json()

    except Exception as e:

        print(
            "Telegram ERROR:",
            repr(e)
        )

        return None


def send_message(chat_id, text):

    # Telegram message limit protection
    max_len = 3900

    if len(text) <= max_len:

        return telegram_request(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": text
            }
        )

    parts = [
        text[i:i + max_len]
        for i in range(
            0,
            len(text),
            max_len
        )
    ]

    result = None

    for part in parts:

        result = telegram_request(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": part
            }
        )

    return result


# =========================================================
# FORMAT ANALYSIS
# =========================================================

def fmt_pct(value):

    if value is None:
        return "-"

    return f"{value:+.2f}%"


def fmt_rsi(value):

    if value is None:
        return "-"

    return f"{value:.1f}"


def direction_text(result):

    signal = result["signal"]

    if signal in (
        "EARLY_LONG",
        "WATCH_LONG"
    ):
        return "🟢 LONG"

    if signal in (
        "SHORT",
        "WATCH_SHORT"
    ):
        return "🔴 SHORT"

    return "⚪ WAIT"


def timeframe_direction(bull, bear):

    if bull > bear:
        return "🟢 صاعد"

    if bear > bull:
        return "🔴 هابط"

    return "⚪ محايد"


def format_coin_analysis(result):

    symbol = result["symbol"]
    price = result["price"]

    signal = result["signal"]

    long_score = result["long_score"]
    short_score = result["short_score"]

    trade = prepare_trade(result)

    text = (
        f"📊 تحليل {symbol}\n\n"

        f"💰 السعر: {format_price(price)}\n\n"

        f"🎯 الاتجاه النهائي: "
        f"{direction_text(result)}\n"

        f"🟢 Long: {long_score}/100\n"
        f"🔴 Short: {short_score}/100\n\n"

        f"📊 MULTI TIMEFRAME\n\n"

        f"15m: "
        f"{timeframe_direction("
            f"result['tf15_bull'], "
            f"result['tf15_bear']"
        )}\n"

        f"30m: "
        f"{timeframe_direction("
            f"result['tf30_bull'], "
            f"result['tf30_bear']"
        )}\n"

        f"1H: "
        f"{timeframe_direction("
            f"result['tf1h_bull'], "
            f"result['tf1h_bear']"
        )}\n"

        f"4H: "
        f"{timeframe_direction("
            f"result['tf4h_bull'], "
            f"result['tf4h_bear']"
        )}\n"

        f"1D: "
        f"{timeframe_direction("
            f"result['tf1d_bull'], "
            f"result['tf1d_bear']"
        )}\n\n"

        f"📈 RSI\n"
        f"15m: {fmt_rsi(result['rsi15'])}\n"
        f"1H: {fmt_rsi(result['rsi1h'])}\n"
        f"4H: {fmt_rsi(result['rsi4h'])}\n"
        f"1D: {fmt_rsi(result['rsi1d'])}\n\n"

        f"📊 EMA\n"
        f"EMA9: {format_price(result['ema9'])}\n"
        f"EMA20: {format_price(result['ema20'])}\n"
        f"EMA50: {format_price(result['ema50'])}\n"
        f"EMA200: {format_price(result['ema200'])}\n\n"

        f"📦 Volume: "
        f"{result['volume_ratio']:.2f}x\n"

        f"📈 Volume Trend: "
        f"{result['volume_trend']:.2f}x\n\n"

        f"📉 الحركة\n"
        f"15m: {fmt_pct(result['change15'])}\n"
        f"30m: {fmt_pct(result['change30'])}\n"
        f"1H: {fmt_pct(result['change1h'])}\n"
        f"4H: {fmt_pct(result['change4h'])}\n"
        f"1D: {fmt_pct(result['change1d'])}\n\n"

        f"🔎 MARKET STRUCTURE\n"
        f"🟢 Accumulation: "
        f"{'YES ✅' if result['accumulation'] else 'NO'}\n"

        f"🔴 Distribution: "
        f"{'YES ⚠️' if result['distribution'] else 'NO'}\n"

        f"🚀 Late Pump Risk: "
        f"{'HIGH ⚠️' if result['late_pump'] else 'LOW ✅'}\n"
    )

    # =====================================================
    # TRADE
    # =====================================================

    if trade:

        text += (
            "\n\n"
            "🎯 الصفقة المقترحة\n\n"

            f"النوع: {trade['side']}\n"
            f"Entry: {trade['entry']}\n"
            f"SL: {trade['stop']}\n"
            f"TP1: {trade['tp1']}\n"
            f"TP2: {trade['tp2']}\n"
            f"TP3: {trade['tp3']}\n"
        )

    else:

        text += (
            "\n\n"
            "⏳ لا توجد صفقة قوية حاليًا.\n"
            "الأفضل الانتظار بدل الدخول بدون تأكيد."
        )

    # =====================================================
    # REASONS
    # =====================================================

    reasons = []

    if signal in (
        "EARLY_LONG",
        "WATCH_LONG"
    ):

        reasons = result.get(
            "long_reasons",
            []
        )

    elif signal in (
        "SHORT",
        "WATCH_SHORT"
    ):

        reasons = result.get(
            "short_reasons",
            []
        )

    if reasons:

        text += "\n\n🧠 أسباب الإشارة:\n"

        for reason in reasons[:6]:

            text += f"• {reason}\n"

    return text


# =========================================================
# SCAN FORMAT
# =========================================================

def format_scan_result(results):

    if not results:

        return (
            "🔎 Scanner\n\n"
            "⚪ لم توجد عملات تحقق شروط الإشارة "
            "حاليًا.\n\n"
            "وده أفضل من إجبار البوت على صفقة ضعيفة."
        )

    text = (
        "🔥 Crypto Zero Reversal\n"
        "📡 Multi-Timeframe Scanner\n\n"
        "15m + 30m + 1H + 4H + 1D\n\n"
    )

    for index, result in enumerate(
        results[:8],
        1
    ):

        trade = prepare_trade(result)

        text += (
            f"#{index}\n"
            f"🪙 {result['symbol']}\n"
            f"💰 السعر: "
            f"{format_price(result['price'])}\n"

            f"📌 الإشارة: "
            f"{result['signal']}\n"

            f"🟢 Long: "
            f"{result['long_score']}/100\n"

            f"🔴 Short: "
            f"{result['short_score']}/100\n\n"

            f"📊 الاتجاهات:\n"
            f"15m: "
            f"{timeframe_direction("
                f"result['tf15_bull'], "
                f"result['tf15_bear']"
            )}\n"

            f"30m: "
            f"{timeframe_direction("
                f"result['tf30_bull'], "
                f"result['tf30_bear']"
            )}\n"

            f"1H: "
            f"{timeframe_direction("
                f"result['tf1h_bull'], "
                f"result['tf1h_bear']"
            )}\n"

            f"4H: "
            f"{timeframe_direction("
                f"result['tf4h_bull'], "
                f"result['tf4h_bear']"
            )}\n"

            f"1D: "
            f"{timeframe_direction("
                f"result['tf1d_bull'], "
                f"result['tf1d_bear']"
            )}\n\n"

            f"RSI 15m: "
            f"{fmt_rsi(result['rsi15'])}\n"

            f"Volume: "
            f"{result['volume_ratio']:.2f}x\n"

            f"Volume Trend: "
            f"{result['volume_trend']:.2f}x\n"

            f"15m: "
            f"{fmt_pct(result['change15'])}\n"

            f"30m: "
            f"{fmt_pct(result['change30'])}\n"

            f"1H: "
            f"{fmt_pct(result['change1h'])}\n"

            f"4H: "
            f"{fmt_pct(result['change4h'])}\n"

            f"1D: "
            f"{fmt_pct(result['change1d'])}\n"
        )

        if trade:

            text += (
                "\n🎯 الصفقة:\n"
                f"النوع: {trade['side']}\n"
                f"Entry: {trade['entry']}\n"
                f"SL: {trade['stop']}\n"
                f"TP1: {trade['tp1']}\n"
                f"TP2: {trade['tp2']}\n"
                f"TP3: {trade['tp3']}\n"
            )

        text += "\n"
        text += "━━━━━━━━━━━━━━\n\n"

    return text


# =========================================================
# BACKGROUND SCAN
# =========================================================

def run_scan(chat_id):

    try:

        send_message(
            chat_id,
            "🔎 بدأ فحص السوق الحقيقي...\n\n"
            "⏳ جاري تحليل:\n"
            "15m + 30m + 1H + 4H + 1D\n\n"
            "🟢 البحث عن التجميع قبل الـPump\n"
            "🔴 البحث عن ضعف الترند والتوزيع\n"
            "📊 فحص السيولة والحجم والزخم\n\n"
            "انتظر النتيجة..."
        )

        results = scan_market(
            limit=20
        )

        message = format_scan_result(
            results
        )

        send_message(
            chat_id,
            message
        )

    except Exception as e:

        print(
            "SCAN BACKGROUND ERROR:",
            repr(e)
        )

        send_message(
            chat_id,
            "❌ حدث خطأ أثناء فحص السوق.\n\n"
            f"{repr(e)}"
        )


# =========================================================
# ROUTES
# =========================================================

@app.route("/", methods=["GET", "HEAD"])
def home():

    return (
        "Crypto Zero Reversal Bot is running.",
        200
    )


@app.route("/health", methods=["GET"])
def health():

    return "OK", 200


@app.route(
    WEBHOOK_PATH,
    methods=["POST"]
)
def telegram_webhook():

    try:

        update = request.get_json(
            silent=True
        )

        print(
            "UPDATE:",
            update
        )

        if not update:
            return "OK", 200

        message = update.get(
            "message"
        )

        if not message:
            return "OK", 200

        chat = message.get(
            "chat",
            {}
        )

        chat_id = chat.get(
            "id"
        )

        text = message.get(
            "text",
            ""
        ).strip()

        if not chat_id:
            return "OK", 200

        print(
            "CHAT:",
            chat_id,
            "TEXT:",
            text
        )

        # =================================================
        # START
        # =================================================

        if text.startswith("/start"):

            send_message(
                chat_id,

                "🚀 Crypto Zero Reversal شغال!\n\n"

                "📊 Multi-Timeframe Analysis\n"
                "15m + 30m + 1H + 4H + 1D\n\n"

                "الأوامر:\n\n"

                "/scan\n"
                "🔎 فحص السوق الحقيقي\n\n"

                "/coin BTCUSDT\n"
                "📊 تحليل عملة\n\n"

                "البوت لا يجبر صفقة إذا لم توجد "
                "تأكيدات كافية."
            )

            return "OK", 200

        # =================================================
        # SCAN
        # =================================================

        if text.lower().startswith(
            "/scan"
        ):

            thread = threading.Thread(
                target=run_scan,
                args=(chat_id,),
                daemon=True
            )

            thread.start()

            return "OK", 200

        # =================================================
        # COIN
        # =================================================

        if text.lower().startswith(
            "/coin"
        ):

            parts = text.split()

            if len(parts) < 2:

                send_message(
                    chat_id,
                    "اكتب العملة هكذا:\n\n"
                    "/coin BTCUSDT"
                )

                return "OK", 200

            symbol = parts[1].upper()

            if not symbol.endswith(
                "USDT"
            ):

                symbol += "USDT"

            send_message(
                chat_id,
                f"📊 جاري تحليل {symbol}...\n\n"
                "⏳ 15m + 30m + 1H + 4H + 1D\n"
                "⏳ جاري فحص الاتجاه والحجم والزخم..."
            )

            try:

                result = analyze_symbol(
                    symbol
                )

                if not result:

                    send_message(
                        chat_id,
                        f"❌ لم أستطع جلب بيانات "
                        f"{symbol} من Binance."
                    )

                    return "OK", 200

                message = format_coin_analysis(
                    result
                )

                send_message(
                    chat_id,
                    message
                )

            except Exception as e:

                print(
                    "COIN ERROR:",
                    repr(e)
                )

                send_message(
                    chat_id,
                    "❌ حدث خطأ أثناء التحليل:\n\n"
                    f"{repr(e)}"
                )

            return "OK", 200

        # =================================================
        # UNKNOWN
        # =================================================

        send_message(
            chat_id,

            "👋 البوت متصل.\n\n"

            "استخدم:\n"
            "/start\n"
            "/scan\n"
            "/coin BTCUSDT"
        )

        return "OK", 200

    except Exception as e:

        print(
            "WEBHOOK ERROR:",
            repr(e)
        )

        return "OK", 200


# =========================================================
# WEBHOOK
# =========================================================

def setup_webhook():

    print(
        "SETTING WEBHOOK:",
        WEBHOOK_URL
    )

    try:

        requests.post(
            f"{TELEGRAM_API}/deleteWebhook",
            json={
                "drop_pending_updates": True
            },
            timeout=20
        )

        requests.post(
            f"{TELEGRAM_API}/setWebhook",
            json={
                "url": WEBHOOK_URL,
                "drop_pending_updates": True
            },
            timeout=20
        )

        info = requests.get(
            f"{TELEGRAM_API}/getWebhookInfo",
            timeout=20
        )

        print(
            "WEBHOOK INFO:",
            info.text[:1000]
        )

    except Exception as e:

        print(
            "WEBHOOK SETUP ERROR:",
            repr(e)
        )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    setup_webhook()

    port = int(
        os.environ.get(
            "PORT",
            "10000"
        )
    )

    print(
        f"Starting Flask on 0.0.0.0:{port}"
    )

    app.run(
        host="0.0.0.0",
        port=port,
        threaded=True
    )
