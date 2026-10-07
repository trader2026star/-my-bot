import os
import time
import ccxt
import requests
import pandas as pd
from flask import Flask, jsonify
from threading import Thread

# استيراد ملف التحليل الخاص بالاستراتيجية المعتمدة (Trend Pullback & RSI Reversal)
import analysis

app = Flask(__name__)

# إعدادات البوت والاتصال بـ BingX عبر CCXT
exchange = ccxt.bingx({
    'enableRateLimit': True,
    'options': {
        'defaultType': 'swap',  # تداول العقود الآجلة (Futures)
    }
})

TELEGRAM_BOT_TOKEN = (
    os.environ.get("TELEGRAM_BOT_TOKEN")
    or os.environ.get("TELEGRAM_TOKEN")
    or ""
)

TELEGRAM_CHAT_ID = (
    os.environ.get("TELEGRAM_CHAT_ID")
    or os.environ.get("CHAT_ID")
    or ""
)

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials missing.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
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

def fetch_ohlcv_data(symbol):
    try:
        tf_15m = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=100)
        tf_1h = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=100)
        tf_4h = exchange.fetch_ohlcv(symbol, timeframe='4h', limit=100)
        
        if not tf_15m or not tf_1h or not tf_4h:
            return None, None, None

        df_15m = pd.DataFrame(tf_15m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df_1h = pd.DataFrame(tf_1h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df_4h = pd.DataFrame(tf_4h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        numeric_columns = ['open', 'high', 'low', 'close', 'volume']
        for col in numeric_columns:
            df_15m[col] = pd.to_numeric(df_15m[col], errors='coerce')
            df_1h[col] = pd.to_numeric(df_1h[col], errors='coerce')
            df_4h[col] = pd.to_numeric(df_4h[col], errors='coerce')
            
        return df_15m.dropna(), df_1h.dropna(), df_4h.dropna()
    except Exception as e:
        print(f"Error fetching data for {symbol}: {e}")
        return None, None, None

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
                
                # قائمة استبعاد صارمة للعملات الوهمية، المؤشرات، أو الرموز الغريبة
                if "NCSK" in base_upper or "TEST" in base_upper or "USD" in base_upper:
                    continue
                
                excluded_bases = {
                    "USD", "USDT", "USDC", "BUSD",
                    "DAI", "EUR", "GBP", "JPY",
                    "XAU", "XAG", "OIL", "GOLD", "SILVER",
                    "SPX", "NDX", "DJI",
                }
                if base_upper in excluded_bases:
                    continue
                if ":USDT" not in symbol:
                    continue

                symbols.append(symbol)
            except Exception:
                continue
        return sorted(list(set(symbols)))
    except Exception as e:
        print(f"Market loading error: {e}")
        return ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"]

def run_trading_bot():
    print("Trend Pullback & RSI Reversal Bot Started (Filtered)...")
    while True:
        try:
            symbols = get_active_symbols()
            print(f"Scanning {len(symbols)} valid markets...")

            for symbol in symbols:
                df_15m, df_1h, df_4h = fetch_ohlcv_data(symbol)
                if df_15m is not None and not df_15m.empty:
                    signal = analysis.analyze_market_conditions(df_15m, df_1h, df_4h)
                    if signal:
                        msg = (
                            f"🚀 *تنبيه صفقة شراء آمنة (Trend Pullback)* 🚀\n\n"
                            f"📌 *العملة:* `{symbol}`\n"
                            f"🟢 *الاتجاه:* `{signal['signal']}`\n"
                            f"📊 *النموذج:* `{signal['strength']}`\n"
                            f"💰 *سعر الدخول:* `{signal['entry']}`\n"
                            f"🛑 *وقف الخسارة الهندسي:* `{signal['stop_loss']}`\n"
                            f"🎯 *الهدف الأول:* `{signal['tp1']}`\n"
                            f"🎯 *الهدف الثاني:* `{signal['tp2']}`\n"
                            f"🎯 *الهدف الثالث:* `{signal['tp3']}`\n"
                            f"📈 *نسبة المخاطرة للعائد:* `{signal['risk_reward']}`\n"
                            f"📊 *التغير (24س):* `+{signal['change_24h']}%`\n"
                        )
                        send_telegram_message(msg)
                        time.sleep(2)
                
                time.sleep(0.2)
            
            print("Completed scanning cycle. Waiting for next cycle...")
            time.sleep(300) # الانتظار 5 دقائق لدورة الفحص القادمة
        except Exception as e:
            print(f"Main loop error: {e}")
            time.sleep(60)

@app.route('/')
def home():
    return jsonify({"status": "Active", "message": "Trend Pullback Bot is running with strict filters!"})

@app.route('/health')
def health():
    return "OK"

if __name__ == '__main__':
    t = Thread(target=run_trading_bot)
    t.daemon = True
    t.start()
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, threaded=True)
