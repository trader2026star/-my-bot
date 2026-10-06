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
    return "Professional Crypto Scanner Engine is Running!"


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

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }

    try:
        response = requests.post(url, json=payload, timeout=20)
        if response.status_code != 200:
            print("Telegram Error:", response.status_code, response.text[:500])
            return False
        return True
    except Exception as e:
        print(f"Telegram Error: {e}")
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

SCAN_INTERVAL = int(os.environ.get("SCAN_INTERVAL", 900))
TOP_RESULTS = 4
MIN_SCORE_TO_SEND = 75
SYMBOL_DELAY = 0.15


# ============================================================
# DATA FETCH
# ============================================================

def fetch_data(symbol, timeframe, limit=100):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        if not ohlcv:
            return pd.DataFrame()

        df = pd.DataFrame(
            ohlcv,
            columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        numeric_columns = ["open", "high", "low", "close", "volume"]
        for col in numeric_columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna(subset=numeric_columns)
        return df
    except Exception as e:
        print(f"Data error {symbol} {timeframe}: {e}")
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
                if not market.get("swap", False):
                    continue
                quote = market.get("quote", "")
                settle = market.get("settle", "")
                if quote != "USDT" and settle != "USDT":
                    continue
                if market.get("linear", True) is False:
                    continue
                if market.get("active", True) is False:
                    continue
                base = market.get("base", "")
                if not base:
                    continue

                base_upper = str(base).upper()
                excluded_bases = {
                    "USD", "USDT", "USDC", "BUSD",
                    "DAI", "EUR", "GBP", "JPY",
                    "XAU", "XAG", "OIL", "GOLD", "SILVER",
                    "SPX", "NDX", "DJI",
                }
                if base_upper in excluded_bases:
                    continue
                if len(base_upper) > 15:
                    continue
                if ":USDT" not in symbol:
                    continue
                if " " in symbol:
                    continue

                symbols.append(symbol)
            except Exception:
                continue

        return sorted(list(set(symbols)))
    except Exception as e:
        print(f"Market loading error: {e}")
        return ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"]


# ============================================================
# FORMAT HELPERS
# ============================================================

def pct_from_entry(entry, target):
    try:
        if entry <= 0:
            return 0.0
        return round(((target - entry) / entry) * 100, 2)
    except Exception:
        return 0.0


# ============================================================
# BUILD TELEGRAM REPORT
# ============================================================

def build_report(top_results, total_scanned, total_candidates):
    current_time = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())

    msg = "🚀 *تقرير صفقات الزخم الذكي واختراق المقاومات*\n"
    msg += "🎯 *Professional Multi-Timeframe Trend Engine*\n"
    msg += f"⏰ `{current_time}` UTC\n"
    msg += f"📊 تم فحص `{total_scanned}` عقد BingX\n"
    msg += f"⭐ الصفقات المطابقة بنجاح: `{total_candidates}`\n\n"

    for idx, item in enumerate(top_results, 1):
        symbol = item.get("symbol", "UNKNOWN")
        entry = float(item.get("entry", 0))
        stop = float(item.get("stop_loss", 0))
        tp1 = float(item.get("tp1", 0))
        tp2 = float(item.get("tp2", 0))
        tp3 = float(item.get("tp3", 0))
        rating = item.get("rating", 0)
        
        p_tp1 = pct_from_entry(entry, tp1)
        p_tp2 = pct_from_entry(entry, tp2)
        p_tp3 = pct_from_entry(entry, tp3)

        p_sl = 0.0
        if entry > 0:
            p_sl = round(((stop - entry) / entry) * 100, 2)

        msg += f"*{idx}. {symbol}* 📈 {item.get('strength', 'LONG')}\n"
        msg += f"📈 صعود 24h: `+{item.get('change_24h', 0)}%`\n"
        msg += f"⭐ *التقييم:* `{rating}%` | الثقة: `{item.get('confidence', 0)}%`\n\n"

        msg += f"💰 السعر الحالي: `{item.get('current_price', entry)}`\n"
        msg += f"🎯 *سعر الدخول:* `{entry}`\n"
        msg += f"🛑 *وقف الخسارة:* `{stop}` (`{p_sl}%`)\n\n"

        msg += "✅ *أهداف الربح:*\n"
        msg += f"• TP1: `{tp1}` (`+{p_tp1}%`)\n"
        msg += f"• TP2: `{tp2}` (`+{p_tp2}%`)\n"
        msg += f"• TP3: `{tp3}` (`+{p_tp3}%`)\n"
        msg += f"⚖️ مخاطرة/عائد: `{item.get('risk_reward', '1:3.5')}`\n"
        msg += f"⏳ الإطار الزمني: `{item.get('timeframe', '1-4 ساعات')}`\n\n"

        msg += "━━━━━━━━━━━━━━\n\n"

    msg += "🎯 *شروط الاستراتيجية الجديدة:*\n"
    msg += "• توافق الاتجاه على فريمات 1H و 4H\n"
    msg += "• فوليوم سيولة حقيقي وزخم RSI سليم\n"
    msg += "• وقف خسارة هندسي آمن تحت القيعان\n"
    return msg


# ============================================================
# MARKET SCAN JOB
# ============================================================

def job():
    print("\n==================================================")
    print("STARTING PROFESSIONAL TREND & MOMENTUM SCANNER")
    print("==================================================")

    symbols = get_active_symbols()
    total_scanned = len(symbols)
    print(f"Total active USDT swaps: {total_scanned}")

    if not symbols:
        print("No active symbols found.")
        return

    scanned_opportunities = []
    rejected_count = 0
    errors_count = 0

    for index, symbol in enumerate(symbols, 1):
        try:
            df_15m = fetch_data(symbol, "15m", 100)
            if df_15m.empty:
                continue
            df_1h = fetch_data(symbol, "1h", 100)
            if df_1h.empty:
                continue
            df_4h = fetch_data(symbol, "4h", 100)
            if df_4h.empty:
                continue

            result = analyze_market_conditions(df_15m, df_1h, df_4h)

            if not result or result.get("signal") != "LONG":
                rejected_count += 1
                continue

            rating = float(result.get("rating", 0))
            if rating < MIN_SCORE_TO_SEND:
                rejected_count += 1
                continue

            result["symbol"] = symbol
            scanned_opportunities.append(result)

        except Exception as e:
            errors_count += 1
            print(f"Scan error {symbol}: {e}")

        time.sleep(SYMBOL_DELAY)

    scanned_opportunities.sort(
        key=lambda x: (float(x.get("rating", 0)), float(x.get("change_24h", 0))),
        reverse=True
    )

    top_results = scanned_opportunities[:TOP_RESULTS]

    print("\n==================================================")
    print(f"SCAN COMPLETE | Scanned: {total_scanned} | Candidates: {len(scanned_opportunities)} | Errors: {errors_count}")
    print("==================================================")

    if top_results:
        message = build_report(top_results, total_scanned, len(scanned_opportunities))
        send_telegram_message(message)
    else:
        print("No high-quality setups found.")
        print(f"Rejected candidates: {rejected_count}")


# ============================================================
# MAIN LOOP
# ============================================================

if __name__ == "__main__":
    print("🚀 Starting Professional Crypto Scanner Engine...")
    keep_alive()

    send_telegram_message(
        "🚀 *Professional Crypto Scanner Started*\n\n"
        "📈 استراتيجية الزخم متعدد الأطراف والسيولة الحقيقية\n"
        "🛡 فحص الترند على الفريمات الكبرى والصغرى\n"
        "✅ البوت متصل وجاهز لاصطياد أفضل الفرص عبر BingX."
    )

    while True:
        try:
            job()
        except Exception as e:
            print(f"MAIN LOOP ERROR: {e}")

        print(f"Next scan in {SCAN_INTERVAL} seconds...")
        time.sleep(SCAN_INTERVAL)
