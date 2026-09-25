import logging
import ccxt
import pandas as pd
import numpy as np
from flask import Flask
import threading
import os
import time
import requests

from analysis import ExpertAnalystBot


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


# =========================================================
# FLASK
# =========================================================

app = Flask(__name__)


@app.route('/')
def home():
    return (
        "Expert Futures Analyst Bot v4.0 "
        "is running perfectly!"
    )


@app.route('/health')
def health():
    return "OK"


# =========================================================
# TELEGRAM
# =========================================================

def send_telegram_message(message):

    # نفس فكرة الاتصال القديمة:
    # Telegram Bot API + requests.
    #
    # لكن التوكن والـchat_id يتم أخذهم من Environment
    # حتى لا يتم كشفهم داخل GitHub/Render.

    token = os.environ.get(
        'TELEGRAM_BOT_TOKEN',
        os.environ.get('BOT_TOKEN', '')
    )

    chat_id = os.environ.get(
        'TELEGRAM_CHAT_ID',
        os.environ.get('CHAT_ID', '')
    )

    if not token or not chat_id:
        logger.error(
            "Telegram credentials are missing."
        )
        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{token}/sendMessage"
    )

    payload = {
        'chat_id': chat_id,
        'text': message
    }

    try:

        response = requests.post(
            url,
            json=payload,
            timeout=15
        )

        if response.ok:
            return True

        logger.error(
            "Telegram error: %s",
            response.text
        )

        return False

    except Exception as e:

        logger.error(
            "Telegram connection error: %s",
            e
        )

        return False


# =========================================================
# SYMBOL DISCOVERY
# =========================================================

def get_bingx_symbols():

    try:

        exchange = ccxt.bingx({
            'enableRateLimit': True,
            'options': {
                'defaultType': 'swap'
            }
        })

        markets = exchange.load_markets()

        symbols = []

        for symbol, market in markets.items():

            try:

                if not market.get('active', True):
                    continue

                if market.get('swap') is not True:
                    continue

                if market.get('quote') != 'USDT':
                    continue

                if market.get('settle') != 'USDT':
                    continue

                base = str(
                    market.get('base', '')
                ).upper()

                # استبعاد أصول ليست Crypto
                blocked = [
                    'SP500',
                    'NASDAQ',
                    'DXY',
                    'GOLD',
                    'SILVER',
                    'OIL',
                    'WTI',
                    'BRENT'
                ]

                if any(
                    item in base
                    for item in blocked
                ):
                    continue

                symbols.append(symbol)

            except Exception:
                continue

        # إزالة التكرار
        symbols = list(
            dict.fromkeys(symbols)
        )

        logger.info(
            "BingX crypto symbols discovered: %s",
            len(symbols)
        )

        return symbols

    except Exception as e:

        logger.error(
            "Symbol discovery failed: %s",
            e
        )

        # fallback
        return [
            'BTC/USDT:USDT',
            'ETH/USDT:USDT',
            'SOL/USDT:USDT',
            'XRP/USDT:USDT',
            'ADA/USDT:USDT',
            'AVAX/USDT:USDT',
            'DOGE/USDT:USDT',
            'LINK/USDT:USDT',
            'DOT/USDT:USDT',
            'NEAR/USDT:USDT',
            'UNI/USDT:USDT',
            'FET/USDT:USDT',
            'INJ/USDT:USDT',
            'SUI/USDT:USDT',
            'APT/USDT:USDT',
            'OP/USDT:USDT',
            'PEPE/USDT:USDT',
            'SHIB/USDT:USDT',
            'WIF/USDT:USDT',
            'RENDER/USDT:USDT',
            'TIA/USDT:USDT'
        ]


# =========================================================
# DUPLICATE PROTECTION
# =========================================================

sent_signals = {}

SIGNAL_COOLDOWN = 60 * 60


def should_send_signal(signal):

    if not signal:
        return False

    symbol = signal.get(
        'Symbol',
        ''
    )

    direction = signal.get(
        'Direction',
        ''
    )

    key = (
        f"{symbol}:{direction}"
    )

    now = time.time()

    last_sent = sent_signals.get(
        key,
        0
    )

    if now - last_sent < SIGNAL_COOLDOWN:

        logger.info(
            "Duplicate blocked: %s",
            key
        )

        return False

    sent_signals[key] = now

    return True


# =========================================================
# BOT WORKER
# =========================================================

def bot_worker():

    logger.info(
        "Starting Expert Futures Analyst..."
    )

    send_telegram_message(
        "🚀 تم تشغيل Expert Futures Analyst Bot\n\n"
        "🧠 Multi-Timeframe Analysis\n"
        "📊 4H + 1H + 15M\n"
        "🟢 LONG + 🔴 SHORT\n"
        "💧 Liquidity / BOS / Momentum / Volume\n"
        "🛡 Dynamic Risk Management"
    )

    # نفس اتصال BingX عبر CCXT
    # مع تمرير المفاتيح إن كانت موجودة.
    api_key = os.environ.get(
        'BINGX_API_KEY',
        os.environ.get('API_KEY', '')
    )

    secret_key = os.environ.get(
        'BINGX_SECRET_KEY',
        os.environ.get('SECRET_KEY', '')
    )

    bot = ExpertAnalystBot(
        exchange_id='bingx',
        api_key=api_key,
        secret_key=secret_key,
        timeframe='15m'
    )

    # أول تحميل للعملات
    symbols = get_bingx_symbols()

    last_symbol_refresh = time.time()

    while True:

        try:

            # تحديث قائمة العملات كل 30 دقيقة
            if (
                time.time() -
                last_symbol_refresh
                > 1800
            ):

                new_symbols = (
                    get_bingx_symbols()
                )

                if new_symbols:
                    symbols = new_symbols

                last_symbol_refresh = (
                    time.time()
                )

            logger.info(
                "Starting market scan: %s symbols",
                len(symbols)
            )

            signals_found = 0

            for symbol in symbols:

                try:

                    signal = (
                        bot.evaluate_strategy(
                            symbol
                        )
                    )

                    if signal:

                        if should_send_signal(
                            signal
                        ):

                            message = signal.get(
                                'Decision',
                                ''
                            )

                            if message:

                                if send_telegram_message(
                                    message
                                ):

                                    signals_found += 1

                                    logger.info(
                                        "Signal sent: %s %s",
                                        symbol,
                                        signal.get(
                                            'Direction'
                                        )
                                    )

                    # حماية من Rate Limits
                    time.sleep(0.7)

                except Exception as e:

                    logger.warning(
                        "Error analyzing %s: %s",
                        symbol,
                        e
                    )

                    time.sleep(1)

            logger.info(
                "Scan finished. Signals sent: %s",
                signals_found
            )

            # دورة جديدة كل 15 دقيقة
            time.sleep(900)

        except Exception as e:

            logger.exception(
                "Worker error: %s",
                e
            )

            time.sleep(60)


# =========================================================
# START BACKGROUND WORKER
# =========================================================

bot_thread = threading.Thread(
    target=bot_worker,
    daemon=True
)

bot_thread.start()


# =========================================================
# RUN FLASK
# =========================================================

if __name__ == '__main__':

    port = int(
        os.environ.get(
            'PORT',
            10000
        )
    )

    app.run(
        host='0.0.0.0',
        port=port
    )
