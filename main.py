# ============================================================
# main.py — Bot V122.0
# MTF Swing Accumulation Telegram Scanner
#
# Signal-only:
#   Does NOT execute exchange orders.
#
# Analysis:
#   1D -> Bias
#   4H -> Structure
#   1H -> Accumulation / Entry
#
# LONG ONLY
# ============================================================

import os
import re
import time
import threading
import logging
import sqlite3
from collections import deque

import ccxt
import requests
from flask import Flask, jsonify, request

from analysis import StrategyEngine


# ============================================================
# LOGGING / APP
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

logger = logging.getLogger("MainBot")

app = Flask(__name__)


# ============================================================
# ENVIRONMENT
# ============================================================

TELEGRAM_BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN",
    "",
).strip()

TELEGRAM_CHAT_ID = os.environ.get(
    "TELEGRAM_CHAT_ID",
    "",
).strip()

ALLOWED_CHAT_IDS = {
    c.strip()
    for c in os.environ.get(
        "ALLOWED_CHAT_IDS",
        "",
    ).split(",")
    if c.strip()
}

if TELEGRAM_CHAT_ID:
    ALLOWED_CHAT_IDS.add(
        TELEGRAM_CHAT_ID
    )


DB_PATH = os.environ.get(
    "DB_PATH",
    "/tmp/bot_state.db",
)


# ============================================================
# BINGX
# ============================================================

bingx = ccxt.bingx(
    {
        "enableRateLimit": True,
        "timeout": 20000,
        "options": {
            "defaultType": "swap",
        },
    }
)


# ============================================================
# ENGINE
# ============================================================

engine = StrategyEngine(
    capital=10000.0,
    risk_per_trade=0.01,
    min_score=70,
)


# ============================================================
# LOCKS / STATE
# ============================================================

db_lock = threading.RLock()
exchange_lock = threading.RLock()
scan_lock = threading.Lock()

scan_stats = {
    "scanned_pairs": 0,
    "signals_sent": 0,
    "errors": 0,
}

_seen_updates = deque(
    maxlen=500
)

_seen_lock = threading.Lock()

_all_markets_cache = []
_markets_cache_time = 0

_sent_signals_cache = {}

# Minimum time before the same symbol can send another
# automatic signal.
SIGNAL_COOLDOWN_SECONDS = 14400


# ============================================================
# DATABASE
# ============================================================

def _db():
    conn = sqlite3.connect(
        DB_PATH,
        timeout=15,
    )

    conn.row_factory = sqlite3.Row

    return conn


def db_query(
    sql,
    params=(),
    one=False,
):
    with db_lock:
        conn = _db()

        try:
            cur = conn.execute(
                sql,
                params,
            )

            rows = cur.fetchall()

            conn.commit()

            if one:
                return (
                    rows[0]
                    if rows
                    else None
                )

            return rows

        finally:
            conn.close()


def db_init():
    try:
        db_query(
            """
            CREATE TABLE IF NOT EXISTS bot_state (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )

    except Exception as exc:
        logger.error(
            "DB init error: %s",
            exc,
        )


# ============================================================
# EXCHANGE WRAPPER
# ============================================================

def ex_call(
    fn,
    *args,
    **kwargs,
):
    with exchange_lock:
        return fn(
            *args,
            **kwargs,
        )


# ============================================================
# MARKET UNIVERSE
# ============================================================

def get_full_market_universe():
    global _all_markets_cache
    global _markets_cache_time

    try:
        if (
            not _all_markets_cache
            or (
                time.time()
                - _markets_cache_time
                > 1800
            )
        ):
            markets = ex_call(
                bingx.load_markets,
                True,
            )

            universe = []

            for symbol, market in markets.items():

                if not market.get(
                    "swap",
                    False,
                ):
                    continue

                if not market.get(
                    "active",
                    True,
                ):
                    continue

                if market.get(
                    "quote"
                ) != "USDT":
                    continue

                if market.get(
                    "settle"
                ) != "USDT":
                    continue

                universe.append(
                    symbol
                )

            # Stable ordering for predictable scans.
            _all_markets_cache = sorted(
                set(universe)
            )

            _markets_cache_time = (
                time.time()
            )

        if _all_markets_cache:
            return _all_markets_cache

        return [
            "BTC/USDT:USDT",
            "ETH/USDT:USDT",
            "SOL/USDT:USDT",
        ]

    except Exception as exc:
        logger.error(
            "Market universe error: %s",
            exc,
        )

        return [
            "BTC/USDT:USDT",
            "ETH/USDT:USDT",
            "SOL/USDT:USDT",
        ]


# ============================================================
# SYMBOL NORMALIZATION
# ============================================================

_SYM_RE = re.compile(
    r"^[A-Z0-9]{2,20}$"
)


def base_of(raw):
    s = (
        str(raw)
        .strip()
        .upper()
        .replace(" ", "")
        .replace("_", "")
        .replace("-", "/")
    )

    s = s.split(":")[0]

    if "/" in s:
        s = s.split("/")[0]

    elif (
        s.endswith("USDT")
        and len(s) > 4
    ):
        s = s[:-4]

    if (
        s in (
            "USDT",
            "USDC",
            "BUSD",
        )
        or not _SYM_RE.match(s)
    ):
        return None

    return s


# ============================================================
# OHLCV
# ============================================================

def fetch_ohlcv(
    symbol_raw,
    timeframe,
    limit=100,
):
    base = base_of(
        symbol_raw
    )

    if not base:
        return None, None

    candidates = [
        f"{base}/USDT:USDT",
        f"{base}/USDT",
    ]

    for symbol in candidates:

        try:
            bars = ex_call(
                bingx.fetch_ohlcv,
                symbol,
                timeframe=timeframe,
                limit=limit,
            )

            if bars and len(bars) > 10:
                return (
                    symbol,
                    bars,
                )

        except Exception as exc:
            logger.debug(
                "fetch_ohlcv %s %s failed: %s",
                symbol,
                timeframe,
                exc,
            )

            # Small pause prevents hammering
            # the exchange after a temporary error.
            time.sleep(0.15)

    return None, None


# ============================================================
# TELEGRAM
# ============================================================

def tg_send(
    message,
    chat_id=None,
):
    target = (
        chat_id
        or TELEGRAM_CHAT_ID
    )

    if (
        not TELEGRAM_BOT_TOKEN
        or not target
    ):
        return False

    try:
        response = requests.post(
            (
                "https://api.telegram.org/"
                f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            ),
            json={
                "chat_id": target,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=15,
        )

        if response.ok:
            return True

        logger.warning(
            "Telegram HTTP %s",
            response.status_code,
        )

        return False

    except Exception as exc:
        logger.error(
            "Telegram send error: %s",
            exc,
        )

        return False


# ============================================================
# FORMATTING
# ============================================================

def decimals_for(price):
    try:
        price = float(price)

        if price < 0.0001:
            return 10

        if price < 0.01:
            return 8

        if price < 0.1:
            return 7

        if price < 1:
            return 6

        if price < 100:
            return 4

        return 2

    except Exception:
        return 4


def format_num(
    value,
    decimals,
):
    try:
        value = float(value)

        if value <= 0:
            return "N/A"

        return f"{value:.{decimals}f}"

    except Exception:
        return "N/A"


# ============================================================
# SYMBOL ANALYSIS
# ============================================================

def analyze_symbol(
    symbol_raw,
    chat_id=None,
    manual=False,
):
    try:
        # ----------------------------------------------------
        # DAILY
        # ----------------------------------------------------

        resolved, candles_daily = fetch_ohlcv(
            symbol_raw,
            "1d",
            80,
        )

        if (
            not resolved
            or not candles_daily
            or len(candles_daily) < 40
        ):
            if manual:
                tg_send(
                    (
                        f"❌ الأصل "
                        f"<code>{symbol_raw}</code> "
                        "غير متوفر أو بياناته اليومية غير كافية."
                    ),
                    chat_id,
                )

            return False, None

        # ----------------------------------------------------
        # 4H
        # ----------------------------------------------------

        _, candles4h = fetch_ohlcv(
            resolved,
            "4h",
            60,
        )

        if (
            not candles4h
            or len(candles4h) < 35
        ):
            if manual:
                tg_send(
                    (
                        f"❌ <code>{symbol_raw}</code>\n"
                        "بيانات 4H غير كافية للتحليل."
                    ),
                    chat_id,
                )

            return False, None

        # ----------------------------------------------------
        # 1H
        # ----------------------------------------------------

        _, candles1h = fetch_ohlcv(
            resolved,
            "1h",
            60,
        )

        if (
            not candles1h
            or len(candles1h) < 30
        ):
            if manual:
                tg_send(
                    (
                        f"❌ <code>{symbol_raw}</code>\n"
                        "بيانات 1H غير كافية للتحليل."
                    ),
                    chat_id,
                )

            return False, None

        scan_stats[
            "scanned_pairs"
        ] += 1

        # ----------------------------------------------------
        # ENGINE
        # ----------------------------------------------------

        direction, price, signal = (
            engine.analyze_market_structure(
                candles_daily,
                candles4h,
                candles1h,
            )
        )

        # ----------------------------------------------------
        # LONG SIGNAL
        # ----------------------------------------------------

        if direction == "LONG":

            sym_name = (
                resolved
                .split("/")[0]
            )

            full_sym_name = (
                sym_name + "$"
            )

            # Automatic cooldown.
            if not manual:
                last_sent = (
                    _sent_signals_cache.get(
                        sym_name,
                        0,
                    )
                )

                if (
                    time.time()
                    - last_sent
                    < SIGNAL_COOLDOWN_SECONDS
                ):
                    return (
                        False,
                        signal,
                    )

                _sent_signals_cache[
                    sym_name
                ] = time.time()

            d = decimals_for(
                price
            )

            entry_low = signal.get(
                "entry_low",
                0,
            )

            entry_high = signal.get(
                "entry_high",
                0,
            )

            stop_loss = signal.get(
                "stop_loss",
                0,
            )

            tps = signal.get(
                "take_profits",
                [],
            )

            while len(tps) < 3:
                tps.append(0)

            score = int(
                signal.get(
                    "score",
                    0,
                )
            )

            rsi = float(
                signal.get(
                    "rsi",
                    50,
                )
            )

            details = (
                signal.get(
                    "details",
                    {}
                )
                or {}
            )

            quality = details.get(
                "quality",
                "B",
            )

            risk_pct = float(
                details.get(
                    "risk_pct",
                    0,
                )
            )

            rr_final = float(
                details.get(
                    "rr_tp3",
                    0,
                )
            )

            volume_ratio = float(
                details.get(
                    "volume_ratio",
                    1,
                )
            )

            # ------------------------------------------------
            # Telegram message
            # ------------------------------------------------

            msg = (
                "🚀 <b>MY EXPERT CRYPTO BOT V122.0</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "🟢 <b>LONG — Swing Accumulation</b>\n\n"

                f"💎 <b>العملة:</b> "
                f"<code>{full_sym_name}</code>\n"

                f"⭐ <b>التقييم:</b> "
                f"<code>{score}/100</code> "
                f"({quality})\n\n"

                "📍 <b>منطقة الدخول:</b>\n"
                f"<code>"
                f"{format_num(entry_low, d)}"
                f" — "
                f"{format_num(entry_high, d)}"
                f"</code>\n\n"

                "🎯 <b>الأهداف:</b>\n"
                f"🥇 TP1: "
                f"<code>{format_num(tps[0], d)}</code>\n"
                f"🥈 TP2: "
                f"<code>{format_num(tps[1], d)}</code>\n"
                f"🥉 TP3: "
                f"<code>{format_num(tps[2], d)}</code>\n\n"

                "🔴 <b>وقف الخسارة:</b>\n"
                f"<code>{format_num(stop_loss, d)}</code>\n\n"

                f"📊 <b>RSI 1H:</b> "
                f"<code>{rsi:.1f}</code>\n"

                f"📈 <b>Volume:</b> "
                f"<code>{volume_ratio:.2f}x</code>\n"

                f"🛡️ <b>المخاطرة التقريبية:</b> "
                f"<code>{risk_pct:.2f}%</code>\n"

                f"⚖️ <b>R:R حتى TP3:</b> "
                f"<code>1:{rr_final:.1f}</code>\n\n"

                "🧭 <b>التحليل:</b>\n"
                "• 1D Bias صاعد\n"
                "• 4H Structure صاعد\n"
                "• 1H Accumulation مؤكدة\n"
                "• Momentum / Volume confirmation\n\n"

                "⚠️ <b>إشارة تحليلية فقط — لا ينفذ البوت أي أوامر.</b>\n"
                "⚠️ <b>إدارة رأس المال أهم من الرافعة.</b>\n"
                "💡 <b>الرافعة المقترحة للمحرك: 3x–5x.</b>"
            )

            sent = tg_send(
                msg,
                chat_id,
            )

            if sent:
                scan_stats[
                    "signals_sent"
                ] += 1

            return True, signal

        # ----------------------------------------------------
        # MANUAL NEUTRAL
        # ----------------------------------------------------

        if manual:

            details = (
                signal.get(
                    "details",
                    {}
                )
                if signal
                else {}
            )

            score = (
                signal.get(
                    "score",
                    0,
                )
                if signal
                else 0
            )

            reason = (
                signal.get(
                    "reason",
                    "الشروط غير مكتملة",
                )
                if signal
                else "الشروط غير مكتملة"
            )

            msg = (
                f"📊 <b>تحليل الأصل:</b> "
                f"<code>{symbol_raw}</code>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"⭐ <b>Score:</b> "
                f"<code>{score}/100</code>\n\n"
                "⚪ <b>لا توجد صفقة LONG مكتملة حاليًا.</b>\n\n"
                f"🔎 <b>السبب:</b>\n"
                f"{reason}\n\n"
                "🧭 المحرك ينتظر توافق:\n"
                "1️⃣ Daily Bias\n"
                "2️⃣ 4H Structure\n"
                "3️⃣ 1H Accumulation / Entry"
            )

            tg_send(
                msg,
                chat_id,
            )

        return False, signal

    except Exception as exc:

        scan_stats[
            "errors"
        ] += 1

        logger.exception(
            "analyze_symbol error: %s",
            exc,
        )

        if manual:
            tg_send(
                (
                    f"❌ حدث خطأ أثناء تحليل "
                    f"<code>{symbol_raw}</code>."
                ),
                chat_id,
            )

        return False, None


# ============================================================
# FULL MARKET SCAN
# ============================================================

def run_full_scan(
    chat_id=None,
):
    if not scan_lock.acquire(
        blocking=False
    ):
        if chat_id:
            tg_send(
                "⏳ يوجد فحص شامل قيد التشغيل حاليًا.",
                chat_id,
            )

        return

    try:

        if chat_id:
            tg_send(
                (
                    "🔍 <b>جارٍ مسح سوق BingX...</b>\n"
                    "🧭 Daily → 4H → 1H\n"
                    "🎯 البحث عن فرص LONG فقط."
                ),
                chat_id,
            )

        symbols = (
            get_full_market_universe()
        )

        found = 0

        # Scan the complete universe,
        # but sequentially to protect API rate limits.
        for index, sym in enumerate(
            symbols
        ):

            ok, _ = analyze_symbol(
                sym,
                chat_id=chat_id,
                manual=False,
            )

            if ok:
                found += 1

            # Small throttle.
            time.sleep(0.25)

        if chat_id:
            tg_send(
                (
                    "✅ <b>انتهى فحص السوق.</b>\n\n"
                    f"🔎 الأزواج المفحوصة: "
                    f"<code>{len(symbols)}</code>\n"
                    f"🟢 فرص LONG المكتشفة: "
                    f"<code>{found}</code>\n"
                    f"📊 إجمالي الإشارات المرسلة: "
                    f"<code>{scan_stats['signals_sent']}</code>"
                ),
                chat_id,
            )

    except Exception as exc:

        scan_stats[
            "errors"
        ] += 1

        logger.exception(
            "Full Scan error: %s",
            exc,
        )

        if chat_id:
            tg_send(
                "❌ حدث خطأ أثناء الفحص الشامل.",
                chat_id,
            )

    finally:
        scan_lock.release()


# ============================================================
# BACKGROUND SCHEDULER
# ============================================================

def background_auto_scheduler():
    time.sleep(15)

    while True:

        try:
            if TELEGRAM_CHAT_ID:
                run_full_scan(
                    chat_id=None
                )

        except Exception as exc:
            logger.exception(
                "Background scheduler error: %s",
                exc,
            )

        # Every 4 hours.
        time.sleep(
            14400
        )


# ============================================================
# HELP
# ============================================================

HELP_TEXT = (
    "🤖 <b>MY EXPERT CRYPTO BOT V122.0</b>\n"
    "━━━━━━━━━━━━━━━━━━\n\n"
    "🧭 <b>أسلوب التحليل:</b>\n"
    "• 1D = الاتجاه العام\n"
    "• 4H = الهيكل\n"
    "• 1H = التجميع والدخول\n\n"
    "🟢 <b>نوع الإشارات:</b> LONG فقط\n\n"
    "📌 أرسل رمز العملة مثل:\n"
    "<code>BTC</code>\n"
    "<code>ETH</code>\n"
    "<code>SOL</code>\n\n"
    "🔍 <code>/scan</code>\n"
    "لفحص سوق BingX والبحث عن فرص LONG."
)


# ============================================================
# TELEGRAM UPDATE
# ============================================================

def handle_update(data):

    try:

        message = (
            data.get("message")
            or data.get(
                "edited_message"
            )
        )

        if not message:
            return

        chat_id = (
            message
            .get("chat", {})
            .get("id")
        )

        text = (
            message.get("text")
            or ""
        ).strip()

        if (
            not chat_id
            or not text
        ):
            return

        if (
            str(chat_id)
            not in ALLOWED_CHAT_IDS
        ):
            return

        parts = text.split()

        cmd = (
            parts[0]
            .split("@")[0]
            .lower()
        )

        # ----------------------------------------------------
        # START / HELP
        # ----------------------------------------------------

        if cmd in (
            "/start",
            "/help",
        ):
            tg_send(
                HELP_TEXT,
                chat_id,
            )

        # ----------------------------------------------------
        # SCAN
        # ----------------------------------------------------

        elif cmd == "/scan":

            threading.Thread(
                target=run_full_scan,
                args=(chat_id,),
                daemon=True,
            ).start()

        # ----------------------------------------------------
        # COIN
        # ----------------------------------------------------

        else:

            if not base_of(
                parts[0]
            ):
                tg_send(
                    (
                        "❌ رمز غير صالح.\n"
                        "مثال: <code>BTC</code> أو "
                        "<code>BARD</code>"
                    ),
                    chat_id,
                )

            else:

                analyze_symbol(
                    parts[0],
                    chat_id=chat_id,
                    manual=True,
                )

    except Exception as exc:

        logger.exception(
            "handle_update error: %s",
            exc,
        )


# ============================================================
# FLASK
# ============================================================

@app.route("/")
def index():

    return jsonify(
        {
            "status": "running",
            "version": "V122.0-MTF-SwingAccumulation",
            "direction": "LONG_ONLY",
            "timeframes": [
                "1D",
                "4H",
                "1H",
            ],
            "stats": scan_stats,
        }
    )


@app.route("/health")
def health():
    return "OK", 200


# ============================================================
# TELEGRAM WEBHOOK
# ============================================================

@app.route(
    "/tg-webhook",
    methods=["POST"],
)
def telegram_webhook():

    data = (
        request.get_json(
            silent=True
        )
        or {}
    )

    uid = data.get(
        "update_id"
    )

    with _seen_lock:

        if (
            uid is not None
            and uid in _seen_updates
        ):
            return "OK", 200

        if uid is not None:
            _seen_updates.append(
                uid
            )

    threading.Thread(
        target=handle_update,
        args=(data,),
        daemon=True,
    ).start()

    return "OK", 200


# ============================================================
# BOOTSTRAP
# ============================================================

def bootstrap():

    db_init()

    logger.info(
        "MY EXPERT CRYPTO BOT V122.0 "
        "MTF Swing Accumulation bootstrapped."
    )

    logger.info(
        "Analysis: 1D -> 4H -> 1H"
    )

    logger.info(
        "Direction: LONG ONLY"
    )

    threading.Thread(
        target=background_auto_scheduler,
        daemon=True,
    ).start()


bootstrap()


# ============================================================
# LOCAL START
# ============================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=int(
            os.environ.get(
                "PORT",
                5000,
            )
        ),
        threaded=True,
    )
