import os
import logging
import threading

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

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN غير موجود في Environment Variables")

app = Flask(__name__)

# Single canonical WAIT message. It is the ONLY message allowed for a
# non-market setup. No entry/SL/TP/reasons are sent with it.
MARKET_ENTRY_MESSAGE = (
    "🟡 انتهى الفحص. لم يتم العثور حالياً على فرصة دخول فوري كاملة الشروط على هذه العملة."
)


@app.route("/")
def home():
    return "BingX AI Scanner is running."


@app.route("/health")
def health():
    return "OK"


def run_flask():
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


def _structure_confirmed(data):
    """Return True only when MSS OR BOS is actually present."""
    if not isinstance(data, dict):
        return False

    mss = str(data.get("ict_mss") or data.get("mss") or "NONE").strip().upper()
    bos = str(data.get("ict_bos") or data.get("bos") or "NONE").strip().upper()

    # Treat all NONE/empty-like values as no confirmation.
    invalid = {"", "NONE", "NULL", "N/A", "NA", "FALSE", "0"}
    return mss not in invalid or bos not in invalid


def _is_market_entry(data):
    """Final hard Telegram gate: only confirmed MARKET trades pass."""
    if not isinstance(data, dict):
        return False

    direction = str(data.get("direction") or "").strip().upper()
    gate = str(data.get("entry_gate") or "").strip().upper()

    # Never expose WAIT / NO TRADE / WATCH as a trade.
    if direction not in ("LONG", "SHORT"):
        return False

    # analysis.py must explicitly mark the institutional/direct gate as passed.
    if gate != "PASSED":
        return False

    # Mandatory user rule: MSS != NONE OR BOS != NONE.
    if not _structure_confirmed(data):
        return False

    return True


def _filter_market_results(results):
    """Filter before counting, announcing, ranking, or reporting."""
    if not isinstance(results, (list, tuple)):
        return []

    valid = []
    for data in results:
        try:
            if _is_market_entry(data):
                valid.append(data)
            else:
                symbol = data.get("symbol", "UNKNOWN") if isinstance(data, dict) else "UNKNOWN"
                logger.info("Rejected non-MARKET result: %s", symbol)
        except Exception:
            logger.exception("Invalid scanner result rejected")
    return valid


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    await update.message.reply_text(
        "🤖 أهلاً بك في BingX AI Scanner\n\n"
        "📌 أرسل اسم العملة للتحليل:\n"
        "BTC\nETH\nSOL\nXRP\n\n"
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
        "🛡️ ORDER BLOCK هو المحرك الأساسي."
    )


async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    await update.message.reply_text(
        "🔍 جاري فحص BingX Futures...\n\n"
        "🏦 ORDER BLOCK = المحرك الأساسي\n"
        "📡 الأسعار تُسحب مباشرة من BingX Futures\n"
        "🧠 1D + 4H Context | 1H Primary OB | 30m + 15m Confirmation\n"
        "💧 Liquidity + Volume + BOS\n\n"
        "⏳ انتظر النتيجة..."
    )

    try:
        # scan_market may internally evaluate WAIT setups, but this handler
        # removes them before they can be counted or displayed.
        raw_results = scan_market(limit=5)
        results = _filter_market_results(raw_results)
    except Exception as exc:
        logger.exception("Scanner error: %s", exc)
        await update.message.reply_text(
            "❌ حدث خطأ أثناء فحص السوق.\n\nراجع Logs وحاول مرة أخرى."
        )
        return

    # ZERO MARKET TRADES = exactly one final message and immediate return.
    if not results:
        await update.message.reply_text(MARKET_ENTRY_MESSAGE)
        return

    # Count only actual MARKET entries.
    await update.message.reply_text(
        f"✅ انتهى الفحص.\n\n"
        f"🎯 تم العثور على {len(results)} فرص دخول فوري.\n"
        f"💰 كل نتيجة تتضمن السعر الحالي من BingX.\n"
        f"🏦 سيتم إرسال صفقات MARKET المؤكدة فقط."
    )

    for data in results:
        # Final fail-closed gate immediately before report generation.
        if not _is_market_entry(data):
            logger.warning(
                "Blocked non-MARKET result immediately before report: %s",
                data.get("symbol", "UNKNOWN"),
            )
            continue

        try:
            report = generate_evidence_report(data)
            if report:
                await update.message.reply_text(report)
        except Exception as exc:
            logger.exception("Report error: %s", exc)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    if not text:
        return

    symbol = normalize_symbol(text)

    # Progress message is intentionally generic. It is NOT a trade report.
    try:
        price = get_current_price(symbol, True)
    except Exception:
        price = None

    price_text = (
        f"💰 السعر الحالي: {price}\n"
        if price is not None
        else "💰 السعر الحالي: جاري جلبه من BingX...\n"
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
        data = get_coin_analysis(symbol)
    except Exception as exc:
        logger.exception("Coin analysis error for %s", symbol)
        await update.message.reply_text(
            f"❌ حدث خطأ أثناء تحليل {symbol}.\n\nحاول مرة أخرى بعد قليل."
        )
        return

    # HARD RETURN for every non-MARKET setup.
    # This prevents generate_evidence_report() from printing plan numbers,
    # direction, entry zone, TP, SL, or decision reasons for WAIT.
    if not _is_market_entry(data):
        await update.message.reply_text(MARKET_ENTRY_MESSAGE)
        return

    try:
        # Fail closed one last time before sending the detailed report.
        if not _is_market_entry(data):
            await update.message.reply_text(MARKET_ENTRY_MESSAGE)
            return

        report = generate_evidence_report(data)
        if report:
            await update.message.reply_text(report)
    except Exception as exc:
        logger.exception("Report error for %s", symbol)
        await update.message.reply_text("❌ حدث خطأ أثناء إنشاء التقرير.")


async def error_handler(update, context):
    logger.error("Telegram error: %s", context.error)


def main():
    threading.Thread(target=run_flask, daemon=True).start()

    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("scan", scan_command))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    application.add_error_handler(error_handler)

    print("Telegram bot is starting...")
    print("Flask server is starting...")

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
