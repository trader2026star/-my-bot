import os
import time
import threading
import requests
from flask import Flask

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID")
STATE_FILE = "scan_state.txt"
WATCHLIST_FILE = "watchlist.txt"
BATCH_SIZE = 5

def send_telegram_message(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram Error: {e}")

def get_bybit_symbols():
    url = "https://api.bybit.com/v5/market/instruments-info?category=linear"
    try:
        response = requests.get(url, timeout=10).json()
        if response.get("retCode") == 0:
            list_data = response["result"]["list"]
            return [item["symbol"] for item in list_data if item["symbol"].endswith("USDT")]
    except Exception as e:
        print(f"Bybit API Error: {e}")
    return ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"]

def load_scan_state():
    if not os.path.exists(STATE_FILE):
        return 0
    try:
        with open(STATE_FILE, "r") as f:
            return int(f.read().strip())
    except:
        return 0

def save_scan_state(index):
    try:
        with open(STATE_FILE, "w") as f:
            f.write(str(index))
    except Exception as e:
        print(f"State Save Error: {e}")

def load_watchlist():
    if not os.path.exists(WATCHLIST_FILE):
        return {}
    try:
        with open(WATCHLIST_FILE, "r") as f:
            watchlist = {}
            for line in f.readlines():
                parts = line.strip().split(":")
                if len(parts) == 2:
                    watchlist[parts[0]] = int(parts[1])
            return watchlist
    except:
        return {}

def save_watchlist(watchlist):
    try:
        with open(WATCHLIST_FILE, "w") as f:
            for symbol, score in watchlist.items():
                f.write(f"{symbol}:{score}\n")
    except Exception as e:
        print(f"Watchlist Save Error: {e}")

def background_scanner():
    """حلقة الفحص المستمرة في الخلفية"""
    while True:
        try:
            symbols = get_bybit_symbols()
            total_symbols = len(symbols)
            current_index = load_scan_state()
            if current_index >= total_symbols:
                current_index = 0

            batch = symbols[current_index:current_index + BATCH_SIZE]
            next_index = current_index + BATCH_SIZE
            save_scan_state(next_index if next_index < total_symbols else 0)

            watchlist = load_watchlist()
            print(f"Scanning batch from {current_index} to {current_index + len(batch)} of {total_symbols}")

            for symbol in batch:
                score = 50  # محاكاة للتحليل
                
                if score >= 80:
                    message = (
                        f"🚨 *Institutional SMC Signal* 🚀\n\n"
                        f"📊 Symbol: `{symbol}`\n"
                        f"• Decision: *MARKET SETUP READY* 🟢\n"
                        f"• Score: `{score}`\n"
                        f"• Quality: 🟢 *STRONG*\n"
                        f"• Reason: Premium/Discount Zone + MSS + OrderBlock"
                    )
                    send_telegram_message(message)
                    if symbol in watchlist:
                        del watchlist[symbol]
                elif 70 <= score < 80:
                    watchlist[symbol] = score
                else:
                    if symbol in watchlist:
                        del watchlist[symbol]

            save_watchlist(watchlist)
        except Exception as e:
            print(f"Scanner Error: {e}")
        
,        time.sleep(300)  # يفحص كل 5 دقائق أوتوماتيكياً

@app.route("/")
def home():
    return "Bot is running silently and scanning markets successfully!"

if __name__ == "__main__":
    # تشغيل الفاحص في خيط منفصل (Background Thread)
    t = threading.Thread(target=background_scanner)
    t.daemon = True
    t.start()
    
    # تشغيل سيرفر الويب لاستقبال طلبات UptimeRobot
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
