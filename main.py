import time
import os
import requests
import ccxt
import pandas as pd
from flask import Flask
from threading import Thread
from analysis import analyze_market_conditions

app = Flask('')

@app.route('/')
def home():
    return "Crypto Multi-Criteria Scanner Bot is Running!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.start()

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")

def send_telegram_message(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Telegram credentials missing.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Telegram Error: {e}")

exchange = ccxt.bingx({
    'enableRateLimit': True,
    'options': {'defaultType': 'swap'}
})

def fetch_data(symbol, timeframe, limit=100):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        return df
    except Exception as e:
        return pd.DataFrame()

def get_active_symbols():
    try:
        exchange.load_markets()
        symbols = [
            symbol for symbol, market in exchange.markets.items() 
            if market.get('swap', False) and market.get('quote', '') == 'USDT' and market.get('active', True)
        ]
        return symbols
    except Exception as e:
        return ['BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT']

def job():
    print("--- Starting Full Market Scan (Criteria Matching) ---")
    symbols = get_active_symbols()
    total_scanned = len(symbols)
    print(f"Total symbols checked: {total_scanned}")
    
    scanned_opportunities = []
    
    for symbol in symbols:
        try:
            df_15m = fetch_data(symbol, '15m')
            df_1h = fetch_data(symbol, '1h')
            df_4h = fetch_data(symbol, '4h')
            
            if df_15m.empty or df_1h.empty or df_4h.empty:
                continue
                
            result = analyze_market_conditions(df_15m, df_1h, df_4h)
            if result.get("signal") == "LONG":
                result['symbol'] = symbol
                scanned_opportunities.append(result)
        except Exception as e:
            continue
        time.sleep(0.2)
        
    if scanned_opportunities:
        # ترتيب العملات تنازلياً حسب التقييم الأعلى
        scanned_opportunities.sort(key=lambda x: x['rating'], reverse=True)
        top_4 = scanned_opportunities[:4] # اختيار أفضل 4 صفقات مثل الصورة
        
        current_time = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        msg = f"🏆 **أفضل {len(top_4)} صفقة من العملات الصاعدة**\n"
        msg += f"⏰ وقت التحليل: `{current_time}` (UTC)\n"
        msg += f"📊 تم فحص `{total_scanned}` عملة صاعدة واختيار الأفضل\n\n"
        
        for idx, item in enumerate(top_4, 1):
            # حساب نسب أهداف الربح مئوية للعرض
            p_tp1 = round(((item['tp1'] - item['entry']) / item['entry']) * 100, 1)
            p_tp2 = round(((item['tp2'] - item['entry']) / item['entry']) * 100, 1)
            p_tp3 = round(((item['tp3'] - item['entry']) / item['entry']) * 100, 1)

            msg += f"*{idx}. {item['symbol']}* 📈 {item['strength']}\n"
            msg += f"📈 صعود 24h: `+{item['change_24h']}%`\n"
            msg += f"⭐ التقييم: `{item['rating']}%` | الثقة: `{item['confidence']}%`\n"
            msg += f"💰 السعر الحالي: `{item['entry']}`\n"
            msg += f"🎯 سعر الدخول: `{item['entry']}`\n"
            msg += f"🛑 وقف الخسارة: `{item['stop_loss']}`\n"
            msg += f"✅ أهداف الربح:\n"
            msg += f"• TP1: `{item['tp1']}` (+{p_tp1}%)\n"
            msg += f"• TP2: `{item['tp2']}` (+{p_tp2}%)\n"
            msg += f"• TP3: `{item['tp3']}` (+{p_tp3}%)\n"
            msg += f"⚖️ مخاطرة/عائد: `{item['risk_reward']}`\n"
            msg += f"⏳ الإطار الزمني: `{item['timeframe']}`\n"
            msg += f"📊 العوامل: M{item['m_factor']}% V{item['v_factor']}% T{item['t_factor']}%\n\n"
            
        # إضافة معايير الاختيار وإدارة رأس المال تماماً مثل الصورة
        msg += "🎯 *معايير الاختيار:*\n"
        msg += "• صعود قوي في 24 ساعة\n"
        msg += "• تقييم شامل أعلى من 70%\n"
        msg += "• حجم تداول مرتفع\n"
        msg += "• زخم صعودي مستمر\n"
        msg += "• نسبة مخاطرة/عائد جيدة\n\n"
        msg += "⚠️ *إدارة رأس المال:*\n"
        msg += "• استخدم فقط 2-5% من رأس المال في الصفقة\n"
        msg += "• خذ ربح جزئي عند TP1 و TP2\n"
        msg += "• حرك وقف الخسارة عند تحقيق الأهداف"
        
        send_telegram_message(msg)
    else:
        print("No opportunities met the criteria in this cycle.")

if __name__ == "__main__":
    keep_alive()
    send_telegram_message("🚀 تم تشغيل بوت فحص العملات بمعايير الفحص المتقدمة بنجاح.")
    
    while True:
        job()
        time.sleep(3600)
