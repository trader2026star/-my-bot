import logging
import ccxt
import pandas as pd
import numpy as np
from flask import Flask
import threading
import os
import time
import requests

# إعداد اللوجز
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.route('/')
def home():
    return "Institutional SMC & ICT Analyst Bot (v3.0) is running perfectly!"


class InstitutionalSMCBot:
    def __init__(self, exchange_id='bingx', api_key='', secret_key='', timeframe='4h'):
        self.exchange_id = exchange_id
        self.timeframe = timeframe 
        exchange_class = getattr(ccxt, exchange_id)
        self.exchange = exchange_class({
            'apiKey': api_key,
            'secret': secret_key,
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        })

    def fetch_ohlcv_data(self, symbol, timeframe, limit=100):
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            return None

    def get_btc_market_context(self):
        """فحص اتجاه البيتكوين العام على فريم 4 ساعات لضمان صحة السوق"""
        df_btc = self.fetch_ohlcv_data('BTC/USDT:USDT', timeframe=self.timeframe, limit=30)
        if df_btc is None or len(df_btc) < 20:
            return True # افتراض إيجابي في حال حدوث خطأ مؤقت في جلب بيانات البيتكوين
        
        ma20_btc = df_btc['close'].rolling(window=20).mean().iloc[-1]
        current_btc_close = df_btc['close'].iloc[-1]
        return current_btc_close > ma20_btc

    def evaluate_institutional_strategy(self, symbol, btc_bullish):
        df = self.fetch_ohlcv_data(symbol, timeframe=self.timeframe, limit=60)
        if df is None or len(df) < 40:
            return None

        # حساب المؤشرات الأساسية
        df['vol_ma20'] = df['volume'].rolling(window=20).mean()
        df['ma30'] = df['close'].rolling(window=30).mean()
        
        curr_close = df['close'].iloc[-1]
        curr_open = df['open'].iloc[-1]
        curr_high = df['high'].iloc[-1]
        curr_low = df['low'].iloc[-1]
        curr_vol = df['volume'].iloc[-1]
        vol_ma20 = df['vol_ma20'].iloc[-1]

        # 1. التأكيد العام للاتجاه والمتوسطات
        is_bullish_trend = curr_close > df['ma30'].iloc[-1]
        if not (is_bullish_trend and btc_bullish):
            return None

        # 2. فحص سحب السيولة (Liquidity Sweep): هل ذيل الشمعة أو الشمعة السابقة كسر قمة سابقة ثم أغلق دونها أو صعد بقوة؟
        recent_highs = df['high'].iloc[-15:-2].max()
        recent_lows = df['low'].iloc[-15:-2].min()
        
        # شرط سحب السيولة السفلي (فيك أوت للقاع ثم ارتداد) أو كسر هيكلي واضح (BOS)
        is_liquidity_sweep = (df['low'].iloc[-2] < recent_lows) and (curr_close > curr_open)
        is_bos = curr_close > recent_highs

        if not (is_liquidity_sweep or is_bos):
            return None

        # 3. فوليوم الحيتان المؤسسي (أضعاف المتوسط)
        is_whale_volume = curr_vol > (vol_ma20 * 1.4)
        if not is_whale_volume:
            return None

        # 4. تحديد منطقة الأوردربلوك (Order Block) - آخر شمعة هابطة قبل الانطلاقة
        ob_candle_low = df['low'].iloc[-2] if df['close'].iloc[-2] < df['open'].iloc[-2] else df['low'].iloc[-3]
        
        # 5. وقف الخسارة المؤسسي المبني على الهيكل (تحت أدنى قاع حقيقي أو الأوردربلوك بمانع أمان)
        structure_low = df['low'].iloc[-5:-1].min()
        stop_loss = round(min(ob_candle_low, structure_low, curr_close * 0.975), 4 if curr_close < 1 else 2)
        
        risk_distance = curr_close - stop_loss
        if risk_distance <= 0:
            return None

        risk_pct = round((risk_distance / curr_close) * 100, 2)
        if risk_pct > 6.5: # حماية رأس المال الصارم
            return None

        # 6. الأهداف الاستثمارية بدقة (R:R 1:2.5 و 1:4.0)
        tp1 = round(curr_close + (2.5 * risk_distance), 4 if curr_close < 1 else 2)
        tp2 = round(curr_close + (4.0 * risk_distance), 4 if curr_close < 1 else 2)

        tp1_pct = round(((tp1 - curr_close) / curr_close) * 100, 2)
        tp2_pct = round(((tp2 - curr_close) / curr_close) * 100, 2)

        # حساب عداد التأكيدات (Scorecard) لجودة الصفقة
        score = 2 # الأساسيات
        if is_bos: score += 1
        if is_liquidity_sweep: score += 1
        if is_whale_volume: score += 1

        clean_symbol = symbol.split('/')[0]

        report_message = f"""
🏛️ **التقرير المؤسسي لصانع السوق (SMC & ICT)** 💎
تم رصد فرصة عالية الجودة متوافقة مع سيولة الحيتان!

🔹 **العملة:** `${clean_symbol}`
📊 **سعر الدخول المثالي:** `{curr_close}`

🛑 **وقف الخسارة المؤسسي (SL):** `{stop_loss}` (`{risk_pct}%`)
*(محمي تحت أدنى قاع هيكلي / Order Block)*

🎯 **الأهداف الاستثمارية الدقيقة:**
• **TP1:** `{tp1}` (`+{tp1_pct}%`) [R:R 1:2.5]
• **TP2:** `{tp2}` (`+{tp2_pct}%`) [R:R 1:4.0]

📋 **عداد أدلة وتأكيدات الصفقة:**
✔ اتجاه عام وصعد للـ BTC: `معتمد`
✔ كسر هيكلي (BOS / MSS): `{'متوفر' if is_bos else 'غير متوفر'}`
✔ سحب سيولة (Liquidity Sweep): `{'تم رصده' if is_liquidity_sweep else 'عادي'}`
✔ فوليوم تداول مؤسسي: `قوي ({round(curr_vol/vol_ma20, 1)}x)`
⭐ **تقييم جودة الفرصة:** `{score}/5 (فرصة مؤسسية موثوقة)`
"""
        return report_message.strip()


def send_telegram_message(message):
    token = "8523562412:AAFegshLw8TrNcAIdDuLgm3uWc0ao9myMqo"
    chat_id = "7695985627"
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        logger.error(f"خطأ في إرسال رسالة تليجرام: {e}")


def bot_worker():
    send_telegram_message("🚀 تم ترقية البوت بنجاح إلى النسخة المؤسسية (Institutional SMC & ICT Engine) مع فلتر البيتكوين وسحب السيولة!")
    logger.info("بدء تشغيل حلقة الفحص المؤسسي...")
    bot = InstitutionalSMCBot(exchange_id='bingx')
    
    symbols = [
        'BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT', 'XRP/USDT:USDT', 
        'ADA/USDT:USDT', 'AVAX/USDT:USDT', 'DOGE/USDT:USDT', 'LINK/USDT:USDT', 
        'DOT/USDT:USDT', 'MATIC/USDT:USDT', 'NEAR/USDT:USDT', 'UNI/USDT:USDT', 
        'FET/USDT:USDT', 'RNDR/USDT:USDT', 'INJ/USDT:USDT', 'SUI/USDT:USDT', 
        'APT/USDT:USDT', 'ARBI/USDT:USDT', 'OP/USDT:USDT', 'PEPE/USDT:USDT', 
        'SHIB/USDT:USDT', 'WIF/USDT:USDT', 'RENDER/USDT:USDT', 'TIA/USDT:USDT'
    ]
    
    while True:
        try:
            logger.info("جاري فحص اتجاه البيتكوين وسوق العملات...")
            btc_bullish = bot.get_btc_market_context()
            
            for symbol in symbols:
                signal = bot.evaluate_institutional_strategy(symbol, btc_bullish)
                if signal:
                    send_telegram_message(signal)
                    logger.info(f"تم إرسال إشارة مؤسسية للعملة: {symbol}")
                time.sleep(2)
            
            # دورة الفحص كل 30 دقيقة
            time.sleep(1800) 
        except Exception as e:
            logger.error(f"حدث خطأ في حلقة الفحص المؤسسي: {e}")
            time.sleep(60)

bot_thread = threading.Thread(target=bot_worker, daemon=True)
bot_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
