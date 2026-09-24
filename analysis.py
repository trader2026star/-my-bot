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

    def fetch_ohlcv_data(self, symbol, timeframe, limit=200):
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            logger.error(f"خطأ في جلب بيانات {symbol}: {e}")
            return None

    def evaluate_strategy(self, symbol):
        # جلب البيانات اللحظية واليومية لتطبيق أدوات الزخم والمتوسطات المتحركة معا
        df_lower = self.fetch_ohlcv_data(symbol, timeframe=self.timeframe, limit=100)
        df_higher = self.fetch_ohlcv_data(symbol, timeframe='4h', limit=200)
        
        if df_lower is None or df_higher is None or len(df_lower) < 50 or len(df_higher) < 200:
            return None

        current_price = df_lower['close'].iloc[-1]
        
        # 1. فلتر الزخم ونسبة التغير (24h Change)
        price_24h_ago = df_lower['close'].iloc[0]
        change_24h = ((current_price - price_24h_ago) / price_24h_ago) * 100
        has_momentum = change_24h > 3.0  

        if not has_momentum:
            return None

        # 2. أداة المتوسطات المتحركة (50 و 200) للتأكد أن السعر فوق المتوسطات (اتجاه صاعد حقيقي)[span_1](start_span)[span_1](end_span)
        ma_50 = df_higher['close'].rolling(window=50).mean().iloc[-1]
        ma_200 = df_higher['close'].rolling(window=200).mean().iloc[-1]
        
        # شرط الاتجاه بناءً على المتوسطات المتحركة (السعر فوق المتوسطات وميول صاعدة)[span_2](start_span)[span_2](end_span)
        is_above_mas = (current_price > ma_50) and (ma_50 > ma_200)

        if not is_above_mas:
            return None

        # 3. حساب مسافة وقف الخسارة بدقة خلف أدنى سعر سابق
        recent_low = df_lower['low'].iloc[-10:].min()
        stop_loss = round(min(recent_low, current_price * 0.95), 4 if current_price < 1 else 2)
        
        risk_distance = current_price - stop_loss
        if risk_distance <= 0:
            return None

        risk_pct = round((risk_distance / current_price) * 100, 2)

        # 4. حساب الأهداف بمضاعفات المخاطرة والعائد الصارمة (1:1.8, 1:3.0, 1:4.5)[span_3](start_span)[span_3](end_span)
        tp1 = round(current_price + (1.8 * risk_distance), 4 if current_price < 1 else 2)
        tp2 = round(current_price + (3.0 * risk_distance), 4 if current_price < 1 else 2)
        tp3 = round(current_price + (4.5 * risk_distance), 4 if current_price < 1 else 2)

        tp1_pct = round(((tp1 - current_price) / current_price) * 100, 2)
        tp2_pct = round(((tp2 - current_price) / current_price) * 100, 2)
        tp3_pct = round(((tp3 - current_price) / current_price) * 100, 2)

        clean_symbol = symbol.split('/')[0]

        # صياغة التقرير المدمج بأدوات الزخم والمتوسطات المتحركة وإدارة المخاطر
        report_message = f"""
توصيات تحليل السوق الشامل ⚡
(الزخم + المتوسطات المتحركة + إدارة المخاطرة) 🤖

${clean_symbol} توصية ممتازة 🚀
الزخم موجود، والسعر فوق المتوسطات المتحركة (اتجاه صاعد مدعوم)[span_4](start_span)[span_4](end_span)[span_5](start_span)[span_5](end_span).

📊 بيانات التداول:
• السعر الحالي: {current_price}
• التغير 24h: +{round(change_24h, 2)}%[span_6](start_span)[span_6](end_span)

🛑 وقف الخسارة: {stop_loss}
• المسافة: {risk_pct}%[span_7](start_span)[span_7](end_span)

🎯 الأهداف (Risk/Reward):
TP1: {tp1} (1:1.8 | +{tp1_pct}%)[span_8](start_span)[span_8](end_span)
TP2: {tp2} (1:3.0 | +{tp2_pct}%)[span_9](start_span)[span_9](end_span)
TP3: {tp3} (1:4.5 | +{tp3_pct}%)[span_10](start_span)[span_10](end_span)

📈 أدوات التأكيد المطبقة:
✔ قياس الزخم ونسبة التغير الإيجابي[span_11](start_span)[span_11](end_span)
✔ المتوسطات المتحركة (MA 50 & 200): السعر في منطقة الميل الصاعد[span_12](start_span)[span_12](end_span)
✔ مضاعفات العائد للمخاطرة بدقة[span_13](start_span)[span_13](end_span)

💡 الأهداف الرئيسية مناسبة للسوينج، وللسكالبينج قسم كل هدف إلى 3 أهداف فرعية[span_14](start_span)[span_14](end_span).
"""
        return {"Decision": report_message.strip(), "Symbol": symbol}
