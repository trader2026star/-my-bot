# ==========================================
# 24/7 ADVANCED SMC & QUANTITATIVE SCANNER (main.py)
# Developed for Mohamed Barakat (trader2026star)
# ==========================================

import os
import time
import threading
import requests
from flask import Flask
from analysis import StrategyEngine
import ccxt

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')

# فترة منع تكرار إرسال نفس الإشارة لنفس العملة (بالثواني - افتراضياً ساعتين)
SIGNAL_COOLDOWN_SECONDS = int(os.environ.get('SIGNAL_COOLDOWN_SECONDS', 7200))
signal_history = {}

def send_telegram_message(message):
    try:
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            return
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown"
        }
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

bingx = ccxt.bingx({
    'enableRateLimit': True,
    'options': {
        'defaultType': 'swap'
    }
})

@app.route('/')
def home():
    return "My Expert Crypto Bot - Advanced SMC & Quantitative Scanner is running live!"

@app.route('/health')
def health():
    return {"status": "healthy", "service": "active"}, 200

def background_scanner():
    time.sleep(15)
    send_telegram_message("🤖 *تم تشغيل ماسح السوق المتقدم (SMC) بنجاح!* النظام يراقب السوق على مدار 24 ساعة.")
    
    while True:
        try:
            markets = bingx.load_markets()
            all_symbols = []
            for sym, mkt in markets.items():
                # الشروط: نشط، سواب، ينتهي بـ /USDT:USDT، والتأكد من استبعاد أي رموز فوركس أو حروف مركبة وهمية
                if (mkt.get('active', True) and 
                    mkt.get('swap', False) and 
                    sym.endswith('/USDT:USDT')):
                    
                    base_currency = sym.split('/')[0]
                    # استبعاد الرموز التي تحتوي على بادئات فوركس أو رموز افتراضية غريبة
                    if any(x in base_currency for x in ['EUR', 'GBP', 'AUD', 'NZD', 'CAD', 'CHF', 'JPY', 'FX', 'NC']):
                        continue
                        
                    all_symbols.append(sym)
            
            engine = StrategyEngine()
            
            # جلب بيانات البيتكوين المرجعية
            btc_ohlcv = []
            try:
                btc_ohlcv = bingx.fetch_ohlcv('BTC/USDT:USDT', timeframe='1h', limit=20)
            except Exception:
                pass

            for symbol in all_symbols:
                try:
                    ohlcv_4h = bingx.fetch_ohlcv(symbol, timeframe='4h', limit=15)
                    ohlcv_1h = bingx.fetch_ohlcv(symbol, timeframe='1h', limit=25)
                    ohlcv_15m = bingx.fetch_ohlcv(symbol, timeframe='15m', limit=15)
                    
                    if not ohlcv_4h or not ohlcv_1h or not ohlcv_15m:
                        continue

                    signal, score, vol_ratio, details, price_arrays = engine.analyze_multi_timeframe(
                        ohlcv_4h, ohlcv_1h, ohlcv_15m, btc_ohlcv
                    )

                    # رفض الإشارات الضعيفة أو المحايدة
                    if signal == "NEUTRAL" or score < 70:
                        continue

                    # نظام منع تكرار الإشارات المتتالية
                    current_time = time.time()
                    cooldown_key = f"{symbol}_{signal}"
                    if cooldown_key in signal_history:
                        if current_time - signal_history[cooldown_key] < SIGNAL_COOLDOWN_SECONDS:
                            continue
                    
                    signal_history[cooldown_key] = current_time

                    ticker = bingx.fetch_ticker(symbol)
                    entry_price = ticker['last']
                    
                    highs, lows, closes = price_arrays
                    sl, tp1, tp2, tp3, sl_pct, tp1_pct = engine.calculate_risk_management(
                        entry_price, signal, highs, lows
                    )

                    confirmations_text = "\n".join([f"• {c}" for c in details.get('confirmations', [])])
                    exclusions_text = "\n".join([f"• {e}" for e in details.get('reasons_excluded', [])]) or "• لا توجد موانع"

                    msg = (
                        f"🚨 *فرصة SMC مؤكدة عالية الجودة!* 🚨\n\n"
                        f"🔹 *العملة:* `{symbol}`\n"
                        f"⚖️ *الاتجاه:* `{signal}`\n"
                        f"⭐ *التقييم الشامل:* `{score}/100`\n"
                        f"📈 *حجم التداول:* `{vol_ratio}x المتوسط`\n"
                        f"🔹 *سعر الدخول المرجعي:* `{entry_price}`\n\n"
                        f"🛑 *وقف الخسارة:* `{sl}` (-{sl_pct}%)\n"
                        f"🎯 *الهدف الأول:* `{tp1}` (+{tp1_pct}%)\n"
                        f"🎯 *الهدف الثاني:* `{tp2}`\n"
                        f"🎯 *الهدف الثالث:* `{tp3}`\n\n"
                        f"✅ *تأكيدات السوق (SMC & Trend):*\n{confirmations_text}\n\n"
                        f"⚠️ *ملاحظات الاستبعاد:*\n{exclusions_text}"
                    )
                    
                    send_telegram_message(msg)
                    time.sleep(10) # مهلة فاصلة بين العملات لتفادي قيود المنصة

                except Exception as inner_err:
                    print(f"Error processing {symbol}: {inner_err}")
            
            # استراحة قبل دورة الفحص الشامل الجديدة للسوق
            time.sleep(600)

        except Exception as e:
            print(f"Global scanner loop error: {e}")
            time.sleep(60)

scanner_thread = threading.Thread(target=background_scanner, daemon=True)
scanner_thread.start()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
