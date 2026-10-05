import time
import os
import requests
import ccxt
import pandas as pd
from flask import Flask
from threading import Thread

from analysis import analyze_market_conditions


# ============================================================
# APP / RENDER
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "Crypto Multi-Criteria Scanner Bot is Running!"


@app.route("/health")
def health():
    return "OK"


def run_flask():
    port = int(os.environ.get("PORT", 8080))

    app.run(
        host="0.0.0.0",
        port=port,
        threaded=True
    )


def keep_alive():
    t = Thread(
        target=run_flask,
        daemon=True
    )
    t.start()


# ============================================================
# TELEGRAM
# ============================================================

TELEGRAM_TOKEN = (
    os.environ.get("TELEGRAM_BOT_TOKEN")
    or os.environ.get("TELEGRAM_TOKEN")
    or ""
)

CHAT_ID = (
    os.environ.get("TELEGRAM_CHAT_ID")
    or os.environ.get("CHAT_ID")
    or ""
)


def send_telegram_message(message):

    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Telegram credentials missing.")
        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }

    try:

        response = requests.post(
            url,
            json=payload,
            timeout=20
        )

        if response.status_code != 200:
            print(
                "Telegram Error:",
                response.status_code,
                response.text[:500]
            )
            return False

        return True

    except Exception as e:

        print(
            f"Telegram Error: {e}"
        )

        return False


# ============================================================
# BINGX
# ============================================================

exchange = ccxt.bingx({

    "enableRateLimit": True,

    "options": {
        "defaultType": "swap"
    }

})


# ============================================================
# SETTINGS
# ============================================================

# 15 دقيقة مناسبة لاصطياد الانطلاقة المبكرة
SCAN_INTERVAL = int(
    os.environ.get(
        "SCAN_INTERVAL",
        900
    )
)

# عدد أفضل الصفقات المرسلة
TOP_RESULTS = 4

# حد أدنى للتقييم
MIN_SCORE_TO_SEND = 74

# تأخير بسيط بين العملات
SYMBOL_DELAY = 0.15


# ============================================================
# DATA FETCH
# ============================================================

def fetch_data(
    symbol,
    timeframe,
    limit=100
):

    try:

        ohlcv = exchange.fetch_ohlcv(
            symbol,
            timeframe,
            limit=limit
        )

        if not ohlcv:
            return pd.DataFrame()

        df = pd.DataFrame(
            ohlcv,
            columns=[
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume"
            ]
        )

        numeric_columns = [
            "open",
            "high",
            "low",
            "close",
            "volume"
        ]

        for col in numeric_columns:

            df[col] = pd.to_numeric(
                df[col],
                errors="coerce"
            )

        df = df.dropna(
            subset=numeric_columns
        )

        return df

    except Exception as e:

        print(
            f"Data error {symbol} {timeframe}: {e}"
        )

        return pd.DataFrame()


# ============================================================
# MARKET FILTER
# ============================================================

def get_active_symbols():

    try:

        exchange.load_markets()

        symbols = []

        for symbol, market in exchange.markets.items():

            try:

                # ------------------------------------------------
                # Futures / Swap فقط
                # ------------------------------------------------

                if not market.get(
                    "swap",
                    False
                ):
                    continue

                # ------------------------------------------------
                # USDT settled فقط
                # ------------------------------------------------

                quote = market.get(
                    "quote",
                    ""
                )

                settle = market.get(
                    "settle",
                    ""
                )

                if quote != "USDT" and settle != "USDT":
                    continue

                # ------------------------------------------------
                # Linear contracts فقط
                # ------------------------------------------------

                if market.get(
                    "linear",
                    True
                ) is False:
                    continue

                # ------------------------------------------------
                # Active
                # ------------------------------------------------

                if market.get(
                    "active",
                    True
                ) is False:
                    continue

                base = market.get(
                    "base",
                    ""
                )

                if not base:
                    continue

                # ------------------------------------------------
                # فلترة العملات الغريبة
                # ------------------------------------------------

                base_upper = str(
                    base
                ).upper()

                # رموز ليست مناسبة لفحص Crypto scanner
                excluded_bases = {

                    "USD",
                    "USDT",
                    "USDC",
                    "BUSD",

                    "DAI",
                    "EUR",
                    "GBP",
                    "JPY",

                    "XAU",
                    "XAG",

                    "OIL",
                    "GOLD",
                    "SILVER",

                    "SPX",
                    "NDX",
                    "DJI",

                }

                if base_upper in excluded_bases:
                    continue

                # ------------------------------------------------
                # اسم العملة يجب أن يكون معقول
                # ------------------------------------------------

                if len(base_upper) > 15:
                    continue

                # ------------------------------------------------
                # لازم يكون عقد USDT واضح
                # ------------------------------------------------

                if ":USDT" not in symbol:
                    continue

                # ------------------------------------------------
                # منع الرموز التي تحتوي على فراغات
                # ------------------------------------------------

                if " " in symbol:
                    continue

                symbols.append(symbol)

            except Exception:
                continue

        # إزالة التكرار
        symbols = sorted(
            list(set(symbols))
        )

        return symbols

    except Exception as e:

        print(
            f"Market loading error: {e}"
        )

        return [
            "BTC/USDT:USDT",
            "ETH/USDT:USDT",
            "SOL/USDT:USDT"
        ]


# ============================================================
# FORMAT HELPERS
# ============================================================

def pct_from_entry(
    entry,
    target
):

    try:

        if entry <= 0:
            return 0.0

        return round(
            (
                (target - entry)
                / entry
            ) * 100,
            2
        )

    except Exception:
        return 0.0


def format_confirmations(item):

    confirmations = item.get(
        "confirmations",
        []
    )

    if not confirmations:
        return "NONE"

    # نعرض أهم العناصر فقط حتى لا تصبح رسالة Telegram ضخمة
    return ", ".join(
        str(x)
        for x in confirmations[:10]
    )


def format_warnings(item):

    warnings = item.get(
        "warnings",
        []
    )

    if not warnings:
        return "NONE"

    return ", ".join(
        str(x)
        for x in warnings[:6]
    )


# ============================================================
# BUILD TELEGRAM REPORT
# ============================================================

def build_report(
    top_results,
    total_scanned,
    total_candidates
):

    current_time = time.strftime(
        "%Y-%m-%d %H:%M:%S",
        time.gmtime()
    )

    msg = ""

    msg += (
        "🏆 *أفضل الصفقات المرشحة*\n"
    )

    msg += (
        "🧠 *Expert Multi-Timeframe Scanner*\n"
    )

    msg += (
        f"⏰ `{current_time}` UTC\n"
    )

    msg += (
        f"📊 تم فحص `{total_scanned}` عقد BingX\n"
    )

    msg += (
        f"🎯 الصفقات المطابقة: `{total_candidates}`\n\n"
    )

    for idx, item in enumerate(
        top_results,
        1
    ):

        symbol = item.get(
            "symbol",
            "UNKNOWN"
        )

        entry = float(
            item.get(
                "entry",
                0
            )
        )

        stop = float(
            item.get(
                "stop_loss",
                0
            )
        )

        tp1 = float(
            item.get(
                "tp1",
                0
            )
        )

        tp2 = float(
            item.get(
                "tp2",
                0
            )
        )

        tp3 = float(
            item.get(
                "tp3",
                0
            )
        )

        rating = item.get(
            "rating",
            0
        )

        confidence = item.get(
            "confidence",
            0
        )

        quality = item.get(
            "quality",
            "VALID"
        )

        p_tp1 = pct_from_entry(
            entry,
            tp1
        )

        p_tp2 = pct_from_entry(
            entry,
            tp2
        )

        p_tp3 = pct_from_entry(
            entry,
            tp3
        )

        p_sl = 0.0

        if entry > 0:
            p_sl = round(
                (
                    (stop - entry)
                    / entry
                ) * 100,
                2
            )

        msg += (
            f"*{idx}. {symbol}*\n"
        )

        msg += (
            f"🚀 {item.get('strength', 'LONG')}\n"
        )

        msg += (
            f"⭐ *التقييم:* `{rating}/100` "
            f"| الثقة `{confidence}%`\n"
        )

        msg += (
            f"🏅 *Quality:* `{quality}`\n\n"
        )

        msg += (
            f"💰 السعر: `{entry}`\n"
        )

        msg += (
            f"🎯 الدخول: `{entry}`\n"
        )

        msg += (
            f"🛑 SL: `{stop}` "
            f"({p_sl}%)\n"
        )

        msg += (
            "🎯 *الأهداف:*\n"
        )

        msg += (
            f"• TP1 `{tp1}` "
            f"(+{p_tp1}%)\n"
        )

        msg += (
            f"• TP2 `{tp2}` "
            f"(+{p_tp2}%)\n"
        )

        msg += (
            f"• TP3 `{tp3}` "
            f"(+{p_tp3}%)\n"
        )

        msg += (
            f"⚖️ R:R `{item.get('risk_reward', '-')}`\n"
        )

        msg += "\n"

        msg += (
            "🧠 *Structure:*\n"
        )

        msg += (
            f"4H `{item.get('trend_4h', '-')}` | "
            f"1H `{item.get('trend_1h', '-')}` | "
            f"15M `{item.get('trend_15m', '-')}`\n"
        )

        msg += (
            f"🏦 BOS: `{item.get('bos', False)}` "
            f"| Liquidity Sweep: `{item.get('liquidity_sweep', False)}`\n"
        )

        msg += (
            f"📦 FVG: `{item.get('fvg', False)}` "
            f"| OB: `{item.get('order_block', False)}`\n"
        )

        msg += (
            f"📊 Volume: `{item.get('volume_ratio', 0)}x`\n"
        )

        msg += (
            f"📈 RSI: `{item.get('rsi', '-')}`\n"
        )

        msg += (
            f"₿ BTC: `{item.get('btc_state', '-')}`\n"
        )

        msg += (
            f"📌 Confirmations:\n"
            f"`{format_confirmations(item)}`\n"
        )

        warnings = format_warnings(item)

        if warnings != "NONE":

            msg += (
                f"⚠️ Warnings:\n"
                f"`{warnings}`\n"
            )

        msg += (
            f"⏳ `{item.get('timeframe', '-')}`\n"
        )

        msg += "\n"

        # فاصل
        if idx < len(top_results):

            msg += (
                "━━━━━━━━━━━━━━\n\n"
            )

    msg += (
        "🎯 *منطق الفلترة:*\n"
        "• 4H + 1H + 15M trend\n"
        "• BOS / Liquidity Sweep\n"
        "• Real Breakout\n"
        "• Volume confirmation\n"
        "• RSI + Momentum\n"
        "• FVG / Order Block\n"
        "• BTC context\n"
        "• Dynamic ATR stop\n"
        "• Anti-chase protection\n"
        "• Risk filter\n\n"
    )

    msg += (
        "⚠️ *إدارة المخاطر:*\n"
        "لا تستخدم حجم الصفقة كنسبة مخاطرة ثابتة. "
        "حدد المخاطرة أولاً ثم احسب حجم العقد بناءً على المسافة إلى SL.\n"
    )

    return msg


# ============================================================
# MARKET SCAN
# ============================================================

def job():

    print(
        "\n"
        "==================================================\n"
        "STARTING FULL BINGX MARKET SCAN\n"
        "=================================================="
    )

    # --------------------------------------------------------
    # Load symbols
    # --------------------------------------------------------

    symbols = get_active_symbols()

    total_scanned = len(
        symbols
    )

    print(
        f"Total active USDT swaps: {total_scanned}"
    )

    if not symbols:

        print(
            "No active symbols found."
        )

        return

    # --------------------------------------------------------
    # BTC context
    # مهم جدًا:
    # يتم جلب BTC مرة واحدة فقط
    # وليس لكل عملة
    # --------------------------------------------------------

    print(
        "Loading BTC context..."
    )

    btc_15m = fetch_data(
        "BTC/USDT:USDT",
        "15m",
        100
    )

    btc_1h = fetch_data(
        "BTC/USDT:USDT",
        "1h",
        100
    )

    btc_4h = fetch_data(
        "BTC/USDT:USDT",
        "4h",
        100
    )

    btc_context = None

    # التحليل الحالي يقبل DataFrame واحدًا لـBTC.
    # نستخدم 1H لأنه أفضل كسياق عام من 15M فقط.
    if not btc_1h.empty:

        btc_context = btc_1h

    scanned_opportunities = []

    rejected_count = 0

    errors
