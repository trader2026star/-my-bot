# =========================================================
# main.py - BingX AI Scanner
# AUTO WAIT MONITOR + TELEGRAM ALERTS
# Flask Thread + Safe Asyncio Event Loop
# =========================================================

import os
import asyncio
import logging
import threading
from typing import Dict, Any

from flask import Flask
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
)

from analysis import (
    scan_market,
    get_coin_analysis,
    generate_evidence_report,
    normalize_symbol,
    get_current_price,
)


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================================================
# BOT TOKEN
# =========================================================

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise RuntimeError(
        "BOT_TOKEN غير موجود في Environment Variables"
    )


# =========================================================
# FLASK
# =========================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "Bot is Running Live!"


@app.route("/health")
def health():
    return "OK"


def run_flask():
    """
    Flask runs independently in a background thread.
    Render supplies PORT dynamically.
    """
    port = int(os.environ.get("PORT", "5000"))

    logger.info("Starting Flask on port %s", port)

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False,
        threaded=True,
    )


# =========================================================
# AUTO WAIT MONITOR
# =========================================================

# symbol -> last known state
WATCHLIST: Dict[str, str] = {}

# symbol -> last alerted direction
LAST_ALERT: Dict[str, str] = {}

# Protect shared watch data
WATCH_LOCK = threading.Lock()

# Monitor interval in seconds
MONITOR_INTERVAL = int(
    os.getenv("MONITOR_INTERVAL", "60")
)


def add_to_watchlist(symbol: str):
    """
    Add a WAIT symbol to automatic monitoring.
    """
    symbol = normalize_symbol(symbol)

    if not symbol:
        return

    with WATCH_LOCK:
        WATCHLIST[symbol] = "WAIT"

    logger.info(
        "Added %s to automatic WAIT monitoring",
        symbol
    )


def remove_from_watchlist(symbol: str):
    """
    Remove symbol after a confirmed alert.
    """
    symbol = normalize_symbol(symbol)

    with WATCH_LOCK:
        WATCHLIST.pop(symbol, None)


def get_watchlist():
    """
    Return a safe copy of the current watchlist.
    """
    with WATCH_LOCK:
        return list(WATCHLIST.keys())


def is_confirmed_trade(data: Any) -> bool:
    """
    Only LONG / SHORT are considered confirmed trade states.

    WAIT / NO TRADE / invalid data are never alerted.
    """
    if not isinstance(data, dict):
        return False

    state = str(
        data.get("state", "")
    ).upper().strip()

    direction = str(
        data.get("direction", "")
    ).upper().strip()

    return (
        state in ("LONG", "SHORT")
        and direction in ("LONG", "SHORT")
        and state == direction
    )


def get_trade_direction(data: Dict[str, Any]) -> str:
    state = str(
        data.get("state", "")
    ).upper().strip()

    direction = str(
        data.get("direction", "")
    ).upper().strip()

    if state in ("LONG", "SHORT"):
        return state

    if direction in ("LONG", "SHORT"):
        return direction

    return ""


async def monitor_waiting_coins(
    application
):
    """
    Continuously monitor WAIT coins.

    WAIT -> automatic re-analysis
    LONG/SHORT confirmed -> Telegram alert
    """

    logger.info(
        "Automatic WAIT monitor started. Interval=%ss",
        MONITOR_INTERVAL,
    )

    while True:
        try:
            symbols = get_watchlist()

            if not symbols:
                await asyncio.sleep(MONITOR_INTERVAL)
                continue

            logger.info(
                "Monitoring %s WAIT coins: %s",
                len(symbols),
                ", ".join(symbols),
            )

            for symbol in symbols:

                try:
                    # get_coin_analysis is synchronous,
                    # so run it outside the asyncio event loop.
                    data = await asyncio.to_thread(
                        get_coin_analysis,
                        symbol,
                    )

                    if not data:
                        continue

                    state = str(
                        data.get("state", "")
                    ).upper().strip()

                    direction = get_trade_direction(data)

                    # -------------------------------------------------
                    # Still WAIT
                    # -------------------------------------------------

                    if state == "WAIT":
                        with WATCH_LOCK:
                            WATCHLIST[symbol] = "WAIT"

                        continue

                    # -------------------------------------------------
                    # Confirmed LONG / SHORT
                    # -------------------------------------------------

                    if is_confirmed_trade(data):

                        previous_alert = LAST_ALERT.get(symbol)

                        # Prevent duplicate alerts for same direction
                        if previous_alert == direction:
                            continue

                        report = generate_evidence_report(data)

                        alert_message = (
                            "🚨🚨 صفقة مؤكدة ظهرت 🚨🚨\n\n"
                            f"🪙 {symbol}\n"
                            f"📌 الاتجاه: {direction}\n\n"
                            "🏦 ORDER BLOCK = المحرك الأساسي\n"
                            "🧠 تم اجتياز شروط الدخول النهائية\n"
                            "📡 تم اكتشاف التحول من WAIT إلى صفقة\n\n"
                            f"{report}"
                        )

                        # Send alert to all active chats stored by bot.
                        chat_ids = get_chat_ids()

                        for chat_id in chat_ids:
                            try:
                                await application.bot.send_message(
                                    chat_id=chat_id,
                                    text=alert_message,
                                )

                            except Exception as exc:
                                logger.exception(
                                    "Failed sending alert for %s "
                                    "to chat %s: %s",
                                    symbol,
                                    chat_id,
                                    exc,
                                )

                        LAST_ALERT[symbol] = direction

                        # Remove from WAIT watchlist after alert.
                        remove_from_watchlist(symbol)

                        logger.info(
                            "AUTO ALERT SENT: %s %s",
                            symbol,
                            direction,
                        )

                except Exception as exc:
                    logger.exception(
                        "Monitor error for %s: %s",
                        symbol,
                        exc,
                    )

                # Small pause between monitored coins.
                await asyncio.sleep(1)

        except asyncio.CancelledError:
            logger.info("WAIT monitor stopped.")
            raise

        except Exception as exc:
            logger.exception(
                "WAIT monitor loop error: %s",
                exc,
            )

        await asyncio.sleep(MONITOR_INTERVAL)


# =========================================================
# ACTIVE TELEGRAM CHATS
# =========================================================

ACTIVE_CHATS = set()

ACTIVE_CHATS_LOCK = threading.Lock()


def register_chat(chat_id: int):
    with ACTIVE_CHATS_LOCK:
        ACTIVE_CHATS.add(chat_id)


def get_chat_ids():
    with ACTIVE_CHATS_LOCK:
        return list(ACTIVE_CHATS)


# =========================================================
# /START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    register_chat(update.effective_chat.id)

    await update.message.reply_text(
        "🤖 أهلاً بك في BingX AI Scanner\n\n"

        "📌 أرسل اسم العملة للتحليل:\n"
        "BTC\n"
        "ETH\n"
        "SOL\n"
        "XRP\n\n"

        "أو أي زوج USDT موجود على BingX Futures.\n\n"

        "📌 أمر الفحص الكامل:\n"
        "/scan\n\n"

        "🔎 النظام يعتمد على:\n"
        "• 1D = الاتجاه العام\n"
        "• 4H = الاتجاه الرئيسي\n"
        "• 1H = بوابة الدخول\n"
        "• 30m + 15m = تأكيد إضافي\n"
        "• Order Block + Retest\n"
        "• BOS + Market Structure\n"
        "• السيولة والحجم\n"
        "• RSI + EMA\n"
        "• القاع والتجميع\n"
        "• Support / Resistance\n"
        "• ATR\n"
        "• Entry / SL / TP\n\n"

        "🛡️ ORDER BLOCK هو المحرك الأساسي.\n\n"

        "🔔 WAIT لا تعتبر صفقة.\n"
        "🤖 إذا تحولت العملة من WAIT إلى LONG/SHORT "
        "مؤكد، سأرسل لك تنبيه تلقائيًا."
    )


# =========================================================
# /SCAN
# =========================================================

async def scan_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    register_chat(update.effective_chat.id)

    await update.message.reply_text(
        "🔍 جاري فحص BingX Futures...\n\n"

        "🏦 ORDER BLOCK = المحرك الأساسي\n"
        "📡 الأسعار تُسحب مباشرة من BingX Futures\n"
        "🧠 1D + 4H Context | 1H Primary OB\n"
        "⏱️ 30m + 15m Confirmation\n"
        "💧 Liquidity + Volume + BOS\n\n"

        "⏳ انتظر النتيجة..."
    )

    try:
        results = await asyncio.to_thread(
            scan_market,
            limit=5,
        )

    except Exception as exc:
        logger.exception(
            "Scanner error: %s",
            exc,
        )

        await update.message.reply_text(
            "❌ حدث خطأ أثناء فحص السوق.\n\n"
            "راجع Logs وحاول مرة أخرى."
        )
        return

    if not results:
        await update.message.reply_text(
            "🟡 انتهى الفحص.\n\n"

            "لم يتم العثور حالياً على صفقة قوية "
            "جاهزة للدخول.\n\n"

            "🛡️ البوت فضّل الانتظار بدلاً من "
            "إعطاء صفقة ضعيفة.\n\n"

            "🔔 العملات التي تم تحليلها كـ WAIT "
            "تتم مراقبتها تلقائياً."
        )

        return

    confirmed_results = []
    waiting_results = []

    for data in results:

        if not isinstance(data, dict):
            continue

        symbol = normalize_symbol(
            data.get("symbol", "")
        )

        state = str(
            data.get("state", "")
        ).upper().strip()

        direction = str(
            data.get("direction", "")
        ).upper().strip()

        # -------------------------------------------------
        # WAIT -> watch automatically
        # -------------------------------------------------

        if symbol and (
            state == "WAIT"
            or direction == "WAIT"
            or not is_confirmed_trade(data)
        ):
            add_to_watchlist(symbol)
            waiting_results.append(symbol)

        # -------------------------------------------------
        # Only confirmed trades are sent as opportunities
        # -------------------------------------------------

        if is_confirmed_trade(data):
            confirmed_results.append(data)

    # -----------------------------------------------------
    # Send confirmed trades only
    # -----------------------------------------------------

    if confirmed_results:

        await update.message.reply_text(
            f"🚨 تم العثور على "
            f"{len(confirmed_results)} صفقة مؤكدة.\n\n"
            "🏦 ORDER BLOCK = المحرك الأساسي\n"
            "🛡️ لن يتم إرسال WAIT كصفقة."
        )

        for data in confirmed_results:

            try:
                await update.message.reply_text(
                    generate_evidence_report(data)
                )

                symbol = normalize_symbol(
                    data.get("symbol", "")
                )

                direction = get_trade_direction(data)

                if symbol and direction:
                    LAST_ALERT[symbol] = direction

            except Exception as exc:
                logger.exception(
                    "Report error: %s",
                    exc,
                )

    else:

        await update.message.reply_text(
            "🟡 لا توجد صفقة جاهزة للدخول الآن.\n\n"
            "تم تجاهل نتائج WAIT كصفقات.\n"
            "🤖 العملات التي ظهرت WAIT دخلت المراقبة "
            "التلقائية.\n\n"
            "🔔 عند تحقق شروط الدخول سأرسل التنبيه تلقائياً."
        )

    # -----------------------------------------------------
    # Inform about automatic monitoring
    # -----------------------------------------------------

    if waiting_results:

        unique_waiting = list(
            dict.fromkeys(waiting_results)
        )

        await update.message.reply_text(
            "👁️ المراقبة التلقائية بدأت لـ:\n\n"
            + "\n".join(
                f"• {symbol}"
                for symbol in unique_waiting
            )
            + "\n\n"
            f"⏱️ إعادة الفحص كل {MONITOR_INTERVAL} ثانية.\n"
            "🔔 لن يصلك تنبيه إلا عند ظهور LONG/SHORT مؤكد."
        )


# =========================================================
# HANDLE COIN MESSAGE
# =========================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    if not update.message.text:
        return

    register_chat(update.effective_chat.id)

    text = update.message.text.strip()

    if not text:
        return

    symbol = normalize_symbol(text)

    # -----------------------------------------------------
    # Get current price
    # -----------------------------------------------------

    try:
        price = await asyncio.to_thread(
            get_current_price,
            symbol,
            True,
        )
    except Exception:
        price = None

    price_text = (
        f"💰 السعر الحالي: {price}\n"
        if price is not None
        else
        "💰 السعر الحالي: جاري جلبه من BingX...\n"
    )

    await update.message.reply_text(
        f"🔍 جاري تحليل {symbol}...\n\n"

        f"{price_text}"

        "🏦 ORDER BLOCK = المحرك الأساسي\n"
        "📊 1D = Context\n"
        "📊 4H = MTF Order Block\n"
        "⏱️ 1H = Primary Entry Zone\n"
        "⏱️ 30m + 15m = Confirmation\n\n"

        "🧠 جاري فحص:\n"
        "Order Block\n"
        "OB Retest\n"
        "BOS + Market Structure\n"
        "Liquidity + Volume\n"
        "Accumulation / Distribution\n"
        "MTF Order Blocks\n"
        "ATR + Entry / SL / TP\n\n"

        "⏳ انتظر النتيجة..."
    )

    try:

        data = await asyncio.to_thread(
            get_coin_analysis,
            symbol,
        )

    except Exception as exc:

        logger.exception(
            "Coin analysis error for %s: %s",
            symbol,
            exc,
        )

        await update.message.reply_text(
            f"❌ حدث خطأ أثناء تحليل {symbol}.\n\n"
            "حاول مرة أخرى بعد قليل."
        )

        return

    if not data:

        await update.message.reply_text(
            f"❌ لم أستطع تحليل {symbol} حالياً.\n\n"
            "تأكد أن الزوج موجود على BingX Futures "
            "وأنه USDT."
        )

        return

    state = str(
        data.get("state", "")
    ).upper().strip()

    direction = str(
        data.get("direction", "")
    ).upper().strip()

    # -----------------------------------------------------
    # WAIT -> automatic monitoring
    # -----------------------------------------------------

    if (
        state == "WAIT"
        or direction == "WAIT"
        or not is_confirmed_trade(data)
    ):

        add_to_watchlist(symbol)

        try:
            report = generate_evidence_report(data)

            await update.message.reply_text(
                report
                + "\n\n"
                "👁️ الحالة: WAIT\n"
                "🤖 تم إدخال العملة للمراقبة التلقائية.\n"
                f"⏱️ إعادة الفحص كل {MONITOR_INTERVAL} ثانية.\n"
                "🔔 سأرسل لك تنبيهًا تلقائيًا إذا تحولت "
                "إلى LONG/SHORT مؤكد."
            )

        except Exception as exc:

            logger.exception(
                "WAIT report error for %s: %s",
                symbol,
                exc,
            )

            await update.message.reply_text(
                "🟡 العملة WAIT حالياً.\n\n"
                "👁️ تم إدخالها للمراقبة التلقائية."
            )

        return

    # -----------------------------------------------------
    # Confirmed LONG / SHORT
    # -----------------------------------------------------

    if is_confirmed_trade(data):

        try:

            LAST_ALERT[symbol] = direction

            await update.message.reply_text(
                "🚨 صفقة مؤكدة\n\n"
                + generate_evidence_report(data)
            )

        except Exception as exc:

            logger.exception(
                "Report error for %s: %s",
                symbol,
                exc,
            )

            await update.message.reply_text(
                "❌ حدث خطأ أثناء إنشاء التقرير."
            )

        return

    # -----------------------------------------------------
    # Any unknown / invalid state
    # -----------------------------------------------------

    add_to_watchlist(symbol)

    await update.message.reply_text(
        f"🟡 {symbol} ليست صفقة مؤكدة حالياً.\n\n"
        "👁️ تم وضعها تحت المراقبة التلقائية.\n"
        "🔔 سيتم التنبيه فقط عند تحقق LONG/SHORT."
    )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(
    update,
    context: ContextTypes.DEFAULT_TYPE
):

    logger.error(
        "Telegram error: %s",
        context.error,
    )


# =========================================================
# MAIN BOT
# =========================================================

async def main_bot():

    application = (
        ApplicationBuilder()
        .token(TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    application.add_handler(
        CommandHandler(
            "scan",
            scan_command,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message,
        )
    )

    application.add_error_handler(
        error_handler
    )

    monitor_task = None

    try:

        # -------------------------------------------------
        # Initialize Telegram application
        # -------------------------------------------------

        logger.info(
            "Initializing Telegram application..."
        )

        await application.initialize()

        # -------------------------------------------------
        # Delete old webhook
        # -------------------------------------------------

        logger.info(
            "Deleting Telegram webhook..."
        )

        await application.bot.delete_webhook(
            drop_pending_updates=True
        )

        # -------------------------------------------------
        # Start Telegram application
        # -------------------------------------------------

        await application.start()

        # -------------------------------------------------
        # Start polling
        # -------------------------------------------------

        logger.info(
            "Starting Telegram polling..."
        )

        await application.updater.start_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )

        # -------------------------------------------------
        # Start automatic WAIT monitor
        # -------------------------------------------------

        monitor_task = asyncio.create_task(
            monitor_waiting_coins(
                application
            )
        )

        logger.info(
            "BingX AI Scanner is LIVE."
        )

        # Keep the asyncio loop alive.
        await asyncio.Event().wait()

    except asyncio.CancelledError:

        logger.info(
            "Main bot task cancelled."
        )

    except Exception as exc:

        logger.exception(
            "Fatal bot error: %s",
            exc,
        )

        raise

    finally:

        # -------------------------------------------------
        # Stop monitor
        # -------------------------------------------------

        if monitor_task:

            monitor_task.cancel()

            try:
                await monitor_task
            except asyncio.CancelledError:
                pass

        # -------------------------------------------------
        # Stop Telegram polling
        # -------------------------------------------------

        try:
            if application.updater:
                await application.updater.stop()
        except Exception:
            logger.exception(
                "Error stopping updater"
            )

        # -------------------------------------------------
        # Stop application
        # -------------------------------------------------

        try:
            await application.stop()
        except Exception:
            logger.exception(
                "Error stopping application"
            )

        # -------------------------------------------------
        # Shutdown Telegram
        # -------------------------------------------------

        try:
            await application.shutdown()
        except Exception:
            logger.exception(
                "Error shutting down application"
            )


# =========================================================
# PROGRAM ENTRY
# =========================================================

if __name__ == "__main__":

    # -----------------------------------------------------
    # Flask runs first in separate background Thread
    # -----------------------------------------------------

    flask_thread = threading.Thread(
        target=run_flask,
        daemon=True,
        name="FlaskThread",
    )

    flask_thread.start()

    logger.info(
        "Flask background thread started."
    )

    # -----------------------------------------------------
    # Telegram gets its own clean asyncio event loop
    # -----------------------------------------------------

    asyncio.run(
        main_bot()
    )
