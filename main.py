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
        "Expert Futures Analyst Bot v4.1 "
        "is running perfectly!"
    )


@app.route('/health')
def health():
    return "OK"


# =========================================================
# TELEGRAM (Updated with 429 Rate Limit Handling)
# =========================================================

def send_telegram_message(message):

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

    # محاولة الإرسال مع تكرارها لو حصل ضغط (Rate Limit)
    while True:
        try:
            response = requests.post(
                url,
                json=payload,
                timeout=15
            )

            if response.ok:
                return True

            data = response.json()
            error_code = data.get("error_code")

            # لو حصل خطأ 429 (Too Many Requests)
            if error_code == 429:
                parameters = data.get("parameters", {})
                retry_after = parameters.get("retry_after", 10)
                logger.warning(
                    "Telegram rate limited (429). Retrying after %s seconds...",
                    retry_after
                )
                time.sleep(retry_after)
                continue  # إعادة المحاولة بعد انتهاء وقت الانتظار

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

        for symbol, market in markets.items():

            try:

                if not market.get(
                    'active',
                    True
                ):
                    continue

                if market.get(
                    'swap'
                ) is not True:
                    continue

                if market.get(
                    'quote'
                ) != 'USDT':
                    continue

                if market.get(
                    'settle'
                ) != 'USDT':
                    continue

                base = str(
                    market.get(
                        'base',
                        ''
                    )
                ).upper()

                # 🛑 استبعاد العقود الوهمية أو اللي فيها اسماء غريبة وموقوفة
                if 'USD/USDT' in symbol or ('USD' in base and not base.endswith('USDT')):
                    continue

                if any(
                    item in base
                    for item in blocked
                ):
                    continue

                symbols.append(symbol)

            except Exception:
                continue

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
# PRICE FORMAT
# =========================================================

def format_price(price):

    try:

        price = float(price)

        if price >= 100:
            return f"{price:.4f}"

        if price >= 1:
            return f"{price:.5f}"

        if price >= 0.01:
            return f"{price:.7f}"

        if price >= 0.0001:
            return f"{price:.9f}"

        return f"{price:.12f}"

    except Exception:
        return str(price)


# =========================================================
# SIGNAL MESSAGE BUILDER
# =========================================================

def build_signal_message(signal):

    if not signal:
        return None

    symbol = signal.get(
        'symbol',
        ''
    )

    decision = signal.get(
        'decision',
        ''
    )

    score = signal.get(
        'score',
        0
    )

    quality = signal.get(
        'quality',
        'UNKNOWN'
    )

    if not symbol or not decision:
        logger.warning(
            "Invalid signal data: symbol=%s decision=%s",
            symbol,
            decision
        )
        return None

    direction = str(
        decision
    ).upper()

    symbol_display = str(
        symbol
    )

    confirmations = signal.get(
        'confirmations',
        []
    )

    if not isinstance(
        confirmations,
        list
    ):
        confirmations = []

    confirmation_count = signal.get(
        'confirmation_count',
        len(confirmations)
    )

    confirmation_text = (
        ', '.join(
            str(x)
            for x in confirmations
        )
        if confirmations
        else 'NONE'
    )

    trend_4h = signal.get(
        'trend_4h',
        'UNKNOWN'
    )

    trend_1h = signal.get(
        'trend_1h',
        'UNKNOWN'
    )

    btc_context = signal.get(
        'btc_context',
        'UNKNOWN'
    )

    rsi = signal.get(
        'rsi_15m',
        0
    )

    volume_ratio = signal.get(
        'volume_ratio',
        0
    )

    entry = signal.get(
        'entry'
    )

    sl = signal.get(
        'sl'
    )

    tp1 = signal.get(
        'tp1'
    )

    tp2 = signal.get(
        'tp2'
    )

    tp3 = signal.get(
        'tp3'
    )

    risk_pct = signal.get(
        'risk_pct',
        0
    )

    risk_filter = signal.get(
        'risk_filter',
        'UNKNOWN'
    )

    structure_confirmation = signal.get(
        'structure_confirmation',
        'UNKNOWN'
    )

    btc_conflict = signal.get(
        'btc_conflict',
        False
    )

    if btc_conflict:
        btc_label = (
            f"{btc_context} ⚠️ CONFLICT"
        )
    else:
        btc_label = str(
            btc_context
        )

    entry_quality = signal.get(
        'entry_quality',
        'DIRECT'
    )

    try:
        rsi_text = f"{float(rsi):.1f}"
    except Exception:
        rsi_text = str(rsi)

    try:
        volume_text = (
            f"{float(volume_ratio):.2f}x"
        )
    except Exception:
        volume_text = str(volume_ratio)

    try:
        risk_text = (
            f"{float(risk_pct):.2f}%"
        )
    except Exception:
        risk_text = str(risk_pct)

    message = (
        "🚨 EXPERT FUTURES SIGNAL 🚨\n\n"

        f"📊 Symbol: {symbol_display}\n"
        f"🎯 Decision: {direction}\n"
        f"⭐ Score: {score}\n"
        f"🏷 Quality: {quality}\n\n"

        f"📌 Confirmations: "
        f"{confirmation_count}/3+\n"
        f"🧠 {confirmation_text}\n\n"

        f"📈 4H Trend: {trend_4h}\n"
        f"📊 1H Trend: {trend_1h}\n"
        f"₿ BTC Context: {btc_label}\n\n"

        f"💪 RSI 15M: {rsi_text}\n"
        f"🔊 Volume: {volume_text}\n\n"

        f"💰 Entry: {format_price(entry)}\n"
        f"🛑 SL: {format_price(sl)} "
        f"({risk_text})\n\n"

        f"🎯 TP1: {format_price(tp1)} | R:R 1:2\n"
        f"🎯 TP2: {format_price(tp2)} | R:R 1:3.5\n"
        f"🎯 TP3: {format_price(tp3)} | R:R 1:5\n\n"

        f"🛡 Risk Filter: {risk_filter}\n"
        f"📋 Structure Confirmation: "
        f"{structure_confirmation}\n"
        f"⚡ Entry Status: {entry_quality}\n\n"

        "⚠️ Setup signal — not a guaranteed result."
    )

    return message


# =========================================================
# DUPLICATE PROTECTION
# =========================================================

sent_signals = {}

SIGNAL_COOLDOWN = 60 * 60


def should_send_signal(signal):

    if not signal:
        return False

    symbol = str(
        signal.get(
            'symbol',
            ''
        )
    ).strip().upper()

    direction = str(
        signal.get(
            'decision',
            ''
        )
    ).strip().upper()

    if not symbol or not direction:

        logger.warning(
            "Invalid duplicate key: "
            "symbol=%r direction=%r",
            symbol,
            direction
        )

        return False

    key = (
        f"{symbol}:{direction}"
    )

    now = time.time()

    last_sent = sent_signals.get(
        key,
        0
    )

    if (
        now - last_sent
        < SIGNAL_COOLDOWN
    ):

        remaining = int(
            SIGNAL_COOLDOWN -
            (now - last_sent)
        )

        logger.info(
            "Duplicate blocked: %s "
            "(%ss remaining)",
            key,
            remaining
        )

        return False

    return True


def mark_signal_sent(signal):

    if not signal:
        return

    symbol = str(
        signal.get(
            'symbol',
            ''
        )
    ).strip().upper()

    direction = str(
        signal.get(
            'decision',
            ''
        )
    ).strip().upper()

    if not symbol or not direction:
        return

    key = (
        f"{symbol}:{direction}"
    )

    sent_signals[key] = time.time()


# =========================================================
# BOT WORKER
# =========================================================

def bot_worker():

    logger.info(
        "Starting Expert Futures Analyst..."
    )

    startup_sent = send_telegram_message(
        "🚀 تم تشغيل Expert Futures Analyst Bot\n\n"
        "🧠 Multi-Timeframe Analysis\n"
        "📊 4H + 1H + 15M\n"
        "🟢 LONG + 🔴 SHORT\n"
        "💧 Liquidity / BOS / Momentum / Volume\n"
        "🛡 Dynamic Risk Management"
    )

    if startup_sent:
        logger.info(
            "Startup Telegram message sent successfully."
        )
    else:
        logger.warning(
            "Startup Telegram message was not sent."
        )

    api_key = os.environ.get(
        'BINGX_API_KEY',
        os.environ.get(
            'API_KEY',
            ''
        )
    )

    secret_key = os.environ.get(
        'BINGX_SECRET_KEY',
        os.environ.get(
            'SECRET_KEY',
            ''
        )
    )

    bot = ExpertAnalystBot(
        exchange_id='bingx',
        api_key=api_key,
        secret_key=secret_key,
        timeframe='15m'
    )

    symbols = get_bingx_symbols()

    last_symbol_refresh = time.time()

    while True:

        try:

            if (
                time.time()
                - last_symbol_refresh
                > 1800
            ):

                new_symbols = (
                    get_bingx_symbols()
                )

                if new_symbols:

                    symbols = new_symbols

                    logger.info(
                        "Symbol list refreshed: %s symbols",
                        len(symbols)
                    )

                last_symbol_refresh = (
                    time.time()
                )

            logger.info(
                "Starting market scan: %s symbols",
                len(symbols)
            )

            signals_found = 0
            analyzed_count = 0

            for symbol in symbols:

                try:

                    analyzed_count += 1

                    signal = (
                        bot.evaluate_strategy(
                            symbol
                        )
                    )

                    if not signal:
                        continue

                    score = signal.get('score', 0)
                    decision = str(signal.get('decision', '')).upper()

                    # 🛑 فلترة الصفقات الوهمية أو اللي من غير سكور لمنع الضغط نهائياً
                    if score <= 0 or decision in ['NEUTRAL', 'NO_TRADE', '']:
                        continue

                    logger.info(
                        "Candidate signal: %s %s score=%s",
                        signal.get('symbol', symbol),
                        decision,
                        score
                    )

                    if not should_send_signal(
                        signal
                    ):
                        continue

                    message = (
                        build_signal_message(
                            signal
                        )
                    )

                    if not message:
                        logger.warning(
                            "Signal message build failed: %s",
                            symbol
                        )
                        continue

                    sent = send_telegram_message(
                        message
                    )

                    if sent:

                        mark_signal_sent(
                            signal
                        )

                        signals_found += 1

                        logger.info(
                            "Signal sent successfully: "
                            "%s %s",
                            signal.get(
                                'symbol'
                            ),
                            signal.get(
                                'decision'
                            )
                        )

                    else:

                        logger.warning(
                            "Telegram send failed: %s %s",
                            signal.get(
                                'symbol'
                            ),
                            signal.get(
                                'decision'
                            )
                        )

                    # -----------------------------------------
                    # RATE LIMIT PROTECTION
                    # -----------------------------------------

                    time.sleep(1.5)

                except Exception as e:

                    logger.warning(
                        "Error analyzing %s: %s",
                        symbol,
                        e
                    )

                    time.sleep(1)

            logger.info(
                "Scan finished. "
                "Analyzed: %s | "
                "Signals sent: %s",
                analyzed_count,
                signals_found
            )

            logger.info(
                "Next market scan in 15 minutes."
            )

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
