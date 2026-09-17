import os
import time
import requests

# --- إعدادات التيليجرام وبايبيت ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID")
STATE_FILE = "scan_state.txt"
WATCHLIST_FILE = "watchlist.txt"  # ملف لمتابعة العملات التي تحتاج لتأكيد
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
    """جلب قائمة عملات العقود الآجلة من بايبيت"""
    url = "https://api.bybit.com/v5/market/instruments-info?category=linear"
    try:
        response = requests.get(url, timeout=10).json()
        if response.get("retCode") == 0:
            list_data = response["result"]["list"]
            symbols = [item["symbol"] for item in list_data if item["symbol"].endswith("USDT")]
            return symbols
    except Exception as e:
        print(f"Bybit API Error: {e}")
    # قائمة احتياطية في حال تعذر الاتصال
    return ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "SUIUSDT", "PEPEUSDT"]

def load_scan_state():
    """قراءة مؤشر الدفعة الحالية"""
    if not os.path.exists(STATE_FILE):
        return 0
    try:
        with open(STATE_FILE, "r") as f:
            return int(f.read().strip())
    except:
        return 0

def save_scan_state(index):
    """حفظ مؤشر الدفعة التالية"""
    try:
        with open(STATE_FILE, "w") as f:
            f.write(str(index))
    except Exception as e:
        print(f"State Save Error: {e}")

def load_watchlist():
    """تحميل قائمة العملات قيد المتابعة للتأكيد"""
    if not os.path.exists(WATCHLIST_FILE):
        return {}
    try:
        with open(WATCHLIST_FILE, "r") as f:
            lines = f.readlines()
            watchlist = {}
            for line in lines:
                parts = line.strip().split(":")
                if len(parts) == 2:
                    watchlist[parts[0]] = int(parts[1])
            return watchlist
    except:
        return {}

def save_watchlist(watchlist):
    """حفظ قائمة المتابعة"""
    try:
        with open(WATCHLIST_FILE, "w") as f:
            for symbol, score in watchlist.items():
                f.write(f"{symbol}:{score}\n")
    except Exception as e:
        print(f"Watchlist Save Error: {e}")

def analyze_market_batch():
    symbols = get_bybit_symbols()
    total_symbols = len(symbols)
    
    current_index = load_scan_state()
    if current_index >= total_symbols:
        current_index = 0  # إعادة الدورة من البداية

    batch = symbols[current_index:current_index + BATCH_SIZE]
    next_index = current_index + BATCH_SIZE
    save_scan_state(next_index if next_index < total_symbols else 0)

    watchlist = load_watchlist()
    print(f"Scanning batch from {current_index} to {current_index + len(batch)} of {total_symbols}")

    # محاكاة الفحص التحليلي للدفعة الحالية
    for symbol in batch:
        # (هنا يتم تطبيق تحليل الـ SMC الحقيقي واستخراج السكور لكل عملة)
        # كمثال توضيحي: لنفترض أننا نقيم السكور للعملة بناءً على الشروط الحالية
        
        # محاكاة لنتيجة التحليل (يمكنك ربطها بدالتك الفعلية)
        score = 50  # افتراضي للتجربة، يتم استبداله بالنتيجة الحقيقية للفحص
        
        # لو العملة جاهزة تماماً (Score >= 80)
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
            # إزالة العملة من قائمة المتابعة لو كانت موجودة
            if symbol in watchlist:
                del watchlist[symbol]
                
        # لو العملة قريبة من الجهوزية وتحتاج تأكيد (Score بين 70 و 79)
        elif 70 <= score < 80:
            watchlist[symbol] = score
            print(f"Symbol {symbol} added to watchlist with score {score}")
            
        # لو انخفضت السكورات وخرجت من نطاق المتابعة
        else:
            if symbol in watchlist:
                del watchlist[symbol]

    save_watchlist(watchlist)

if __name__ == "__main__":
    analyze_market_batch()
