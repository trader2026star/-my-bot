import os
import logging
import threading
import requests
from flask import Flask
from analysis import SmartMoneyTradingAnalyst

# =========================================================
# LOGGING
# =========================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)

# =========================================================
# FLASK
# =========================================================
app = Flask(__name__)

# =========================================================
# TELEGRAM
# =========================================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# =========================================================
# BINGX API
# =========================================================
API_KEY = os.getenv("API_KEY", "")
SECRET_KEY = os.getenv("SECRET_KEY", "")

# =========================================================
# SINGLE ANALYST INSTANCE
# =========================================================
analyst_engine = SmartMoneyTradingAnalyst(
    exchange_id="bingx",
    api_key=API_KEY,
    secret_key=SECRET_KEY
)

# =========================================================
# SCAN LOCK
# منع تشغيل أكثر من Scan في نفس الوقت
# =========================================================
scan_lock = threading.Lock()


# =========================================================
# TELEGRAM
# =========================================================
def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("Telegram environment variables are missing.")
        return False

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown"
        }

        response = requests.post(
            url,
            json=payload,
            timeout=15
        )

        response.raise_for_status()

        return True

    except Exception as e:
        logger.error(f"Telegram error: {e}")
        return False


# =========================================================
# GET SYMBOLS
# =========================================================
def get_scan_symbols(limit=10):
    try:
        exchange = analyst_engine.exchange

        # لا نعيد load_markets في كل طلب
        if not exchange.markets:
            exchange.load_markets()

        symbols = []

        for symbol in exchange.symbols:

            if not symbol.endswith("/USDT:USDT"):
                continue

            # استبعاد بعض العقود غير المرغوبة
            if symbol.startswith("NC"):
                continue

            # التأكد أن السوق Swap
            market = exchange.markets.get(symbol)

            if not market:
                continue

            if market.get("swap") is not True:
                continue

            symbols.append(symbol)

        # ترتيب ثابت بدل العشوائية
        symbols = sorted(set(symbols))

        return symbols[:limit]

    except Exception as e:
        logger.error(f"Failed to get symbols: {e}")
        return []


# =========================================================
# MARKET SCAN
# =========================================================
def run_market_scan():

    # منع تشغيل Scan متزامنين
    if not scan_lock.acquire(blocking=False):
        logger.warning("Scan already running. Ignoring duplicate request.")

        return (
            "⚠️ يوجد فحص للسوق قيد التنفيذ بالفعل.\n"
            "لن يتم تشغيل فحص آخر في نفس الوقت."
        )

    try:

        logger.info("==========================================")
        logger.info("STARTING MARKET SCAN")
        logger.info("==========================================")

        symbols_to_scan = get_scan_symbols(limit=10)

        if not symbols_to_scan:
            error_message = "⚠️ لم يتم العثور على عقود USDT Futures صالحة."

            send_telegram_message(error_message)

            return error_message

        logger.info(
            f"Scanning {len(symbols_to_scan)} symbols: "
            f"{', '.join(symbols_to_scan)}"
        )

        telegram_msg = (
            "🚨 *Smart Money Rotating Report (BingX)* 🚀\n\n"
            f"📊 عدد العملات المفحوصة: {len(symbols_to_scan)}\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
        )

        html_output = (
            "<h2>Smart Money Scanner Active 🚀</h2>"
            f"<p>Scanning {len(symbols_to_scan)} USDT Futures contracts.</p>"
        )

        # =================================================
        # SEQUENTIAL SCANNING
        # مهم جدًا للذاكرة
        # =================================================
        for index, symbol in enumerate(symbols_to_scan, start=1):

            logger.info(
                f"[{index}/{len(symbols_to_scan)}] "
                f"Analyzing {symbol}"
            )

            telegram_msg += f"📊 *Symbol: {symbol}*\n"

            html_output += (
                f"<h3>Analysis for {symbol}</h3>"
                "<ul>"
            )

            try:

                result = analyst_engine.evaluate_strategy(
                    symbol=symbol,
                    account_balance=1000.0,
                    risk_percentage=0.01
                )

                if not result:
                    result = {
                        "Decision": "NO TRADE ⏳",
                        "Reason": "EMPTY ANALYSIS RESULT",
                        "Score": 0,
                        "Quality": "WEAK"
                    }

                for key, value in result.items():

                    html_output += (
                        f"<li><b>{key}:</b> {value}</li>"
                    )

                    telegram_msg += (
                        f"• *{key}*: {value}\n"
                    )

            except Exception as ex:

                logger.exception(
                    f"Error analyzing {symbol}"
                )

                html_output += (
                    f"<li><b>Error:</b> "
                    f"{str(ex)}</li>"
                )

                telegram_msg += (
                    "• Error analyzing this coin.\n"
                )

            html_output += "</ul><hr>"
            telegram_msg += "-------------------\n"

        # =================================================
        # SEND ONE TELEGRAM MESSAGE
        # =================================================
        send_telegram_message(telegram_msg)

        logger.info("MARKET SCAN FINISHED")

        return html_output

    except Exception as e:

        logger.exception(
            "General market scanner error"
        )

        error_msg = (
            f"⚠️ *Market Scanner Error:*\n"
            f"`{str(e)}`"
        )

        send_telegram_message(error_msg)

        return (
            "<h3>Scanner Error</h3>"
            f"<p>{str(e)}</p>"
        )

    finally:

        scan_lock.release()


# =========================================================
# HEALTH CHECK
# =========================================================
@app.route("/")
def home():

    return """
    <html>
        <head>
            <title>BingX Smart Money Scanner</title>
        </head>

        <body>
            <h2>🚀 BingX Smart Money Scanner is Running</h2>

            <p>
                Scanner engine is online.
            </p>

            <p>
                Use the scan endpoint to start a market scan.
            </p>
        </body>
    </html>
    """


# =========================================================
# MANUAL SCAN ENDPOINT
# =========================================================
@app.route("/scan")
def scan():

    return run_market_scan()


# =========================================================
# HEALTH
# =========================================================
@app.route("/health")
def health():

    return {
        "status": "ok",
        "scanner": "online"
    }


# =========================================================
# LOCAL RUN
# =========================================================
if __name__ == "__main__":

    port = int(
        os.environ.get("PORT", 10000)
    )

    app.run(
        host="0.0.0.0",
        port=port,
        threaded=False
    )
