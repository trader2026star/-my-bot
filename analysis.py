import logging
import ccxt
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

class ExpertAnalystBot:
    def __init__(self, exchange_id='bingx', api_key='', secret_key='', timeframe='15m'):
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
            logger.error(f"خطأ في جلب بيانات {symbol}: {e}")
            return None

    def evaluate_strategy(self, symbol):
        # جلب البيانات اللحظية لقياس الزخم والتغير بدقة
        df_lower = self.fetch_ohlcv_data(symbol, timeframe=self.timeframe, limit=100)
        
        if df_lower is None or len(df_lower) < 50:
            return None

        current_price = df_lower['close'].iloc[-1]
        
        # 1. فلتر الزخم ونسبة التغير (مستوحى من أداة المتابعة اللحظية)
        price_24h_ago = df_lower['close'].iloc[0]
        change_24h = ((current_price - price_24h_ago) / price_24h_ago) * 100
        
        # شرط أن تكون العملة في حالة زخم صاعد نشط وقوي
        has_momentum = change_24h > 3.0  

        if not has_momentum:
            return None

        # 2. حساب مسافة وقف الخسارة بدقة خلف أدنى سعر سابق
        recent_low = df_lower['low'].iloc[-10:].min()
        stop_loss = round(min(recent_low, current_price * 0.95), 4 if current_price < 1 else 2)
        
        risk_distance = current_price - stop_loss
        if risk_distance <= 0:
            return None

        risk_pct = round((risk_distance / current_price) * 100, 2)

        # 3. حساب الأهداف بناءً على مضاعفات المخاطرة والعائد الدقيقة (1:1.8 ، 1:3.0 ، 1:4.5)[span_1](start_span)[span_1](end_span)
        tp1 = round(current_price + (1.8 * risk_distance), 4 if current_price < 1 else 2)
        tp2 = round(current_price + (3.0 * risk_distance), 4 if current_price < 1 else 2)
        tp3 = round(current_price + (4.5 * risk_distance), 4 if current_price < 1 else 2)

        tp1_pct = round(((tp1 - current_price) / current_price) * 100, 2)
        tp2_pct = round(((tp2 - current_price) / current_price) * 100, 2)
        tp3_pct = round(((tp3 - current_price) / current_price) * 100, 2)

        clean_symbol = symbol.split('/')[0]

        # صياغة التقرير الاحترافي المطابق تماماً لنمط التوصيات المطلوب
        report_message = f"""
توصيات كريبتو هاند ⚡
النسخة المتقدمة بالزخم وإدارة المخاطرة 🤖

${clean_symbol} توصية ممتازة 🚀
الزخم موجود واحتمالية استمرار الحركة قائمة[span_2](start_span)[span_2](end_span).

📊 بيانات التداول:
• السعر الحالي: {current_price}
• التغير 24h: +{round(change_24h, 2)}%[span_3](start_span)[span_3](end_span)

🛑 وقف الخسارة: {stop_loss}
• المسافة: {risk_pct}%[span_4](start_span)[span_4](end_span)

🎯 الأهداف (Risk/Reward):
TP1: {tp1} (1:1.8 | +{tp1_pct}%)[span_5](start_span)[span_5](end_span)
TP2: {tp2} (1:3.0 | +{tp2_pct}%)[span_6](start_span)[span_6](end_span)
TP3: {tp3} (1:4.5 | +{tp3_pct}%)[span_7](start_span)[span_7](end_span)

📈 نسب المخاطرة/العائد:
⚠️ الهدف 1: 1:1.8
⭐ الهدف 2: 1:3.0
🔥 الهدف 3: 1:4.5

💡 الأهداف الرئيسية مناسبة للسوينج، وللسكالبينج قسم كل هدف إلى 3 أهداف فرعية[span_8](start_span)[span_8](end_span).
"""
        return {"Decision": report_message.strip(), "Symbol": symbol}
