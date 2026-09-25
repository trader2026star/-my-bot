import logging
import ccxt
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

class ExpertAnalystBot:
    def __init__(self, exchange_id='bingx', api_key='', secret_key=''):
        self.exchange_id = exchange_id
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

    def evaluate_strategy(self, symbol):
        # 1. فحص الاتجاه العام على فريم 4 ساعات (تأكيد سيولة الحيتان والاتجاه القوي)
        df_4h = self.fetch_ohlcv_data(symbol, timeframe='4h', limit=50)
        if df_4h is None or len(df_4h) < 30:
            return None

        df_4h['vol_ma20'] = df_4h['volume'].rolling(window=20).mean()
        is_4h_bullish = df_4h['close'].iloc[-1] > df_4h['open'].iloc[-1]
        is_4h_whale_vol = df_4h['volume'].iloc[-1] > (df_4h['vol_ma20'].iloc[-1] * 1.5)

        # شرط أساسي: الـ 4 ساعات لازم يكون صاعد وبفوليوم قوي
        if not (is_4h_bullish and is_4h_whale_vol):
            return None

        # 2. التوقيت الدقيق على فريم 15 دقيقة لاقتناص الدخول بدون تأخير
        df_15m = self.fetch_ohlcv_data(symbol, timeframe='15m', limit=50)
        if df_15m is None or len(df_15m) < 30:
            return None

        current_close = df_15m['close'].iloc[-1]
        current_open = df_15m['open'].iloc[-1]
        current_volume = df_15m['volume'].iloc[-1]
        avg_volume_15m = df_15m['volume'].rolling(window=20).mean().iloc[-1]
        body_size = abs(current_close - current_open)
        avg_body_size = abs(df_15m['close'] - df_15m['open']).rolling(window=10).mean().iloc[-1]

        is_green_15m = current_close > current_open
        is_breakout_15m = is_green_15m and (body_size > avg_body_size * 1.2) and (current_volume > avg_volume_15m * 1.4)

        if not is_breakout_15m:
            return None

        # 3. إدارة المخاطر الدقيقة (وقف خسارة محمي تحت أدنى قاع حديث)
        recent_low = min(df_15m['low'].iloc[-3], df_15m['low'].iloc[-2], df_15m['low'].iloc[-1])
        stop_loss = round(min(recent_low, current_close * 0.985), 4 if current_close < 1 else 2)
        
        risk_distance = current_close - stop_loss
        if risk_distance <= 0:
            return None

        risk_pct = round((risk_distance / current_close) * 100, 2)
        if risk_pct > 4.5:  # لو المسافة كبيرة أكتر من اللازم نتجنب الصفقة حفاظاً على رأس المال
            return None

        # 4. حساب الأهداف بنسب عائد ممتازة (1:2.2 و 1:4.0)
        tp1 = round(current_close + (2.2 * risk_distance), 4 if current_close < 1 else 2)
        tp2 = round(current_close + (4.0 * risk_distance), 4 if current_close < 1 else 2)

        tp1_pct = round(((tp1 - current_close) / current_close) * 100, 2)
        tp2_pct = round(((tp2 - current_close) / current_close) * 100, 2)

        clean_symbol = symbol.split('/')[0]

        report_message = f"""
💎 النظام المثالي المؤكد (4H Trend + 15M Entry) 🚀
تم اصطياد فرصة عالية الاحتمالية مطابقة لمعايير السيولة والهيكل!

🔹 العملة: ${clean_symbol}
📊 سعر الدخول المثالي: {current_close}

🛑 وقف الخسارة (آمن ومحمي): {stop_loss} ({risk_pct}%)

🎯 الأهداف الاستثمارية:
• TP1 (مضمون نسبياً): {tp1} (+{tp1_pct}%) [Risk/Reward 1:2.2]
• TP2 (الهدف الكامل): {tp2} (+{tp2_pct}%) [Risk/Reward 1:4.0]

🛡️ شروط التأكيد المطبقة:
✔ توافق اتجاه وفوليوم الحيتان (4 ساعات)
✔ اقتناص الانطلاقة المبكرة بدقة (15 دقيقة)
✔ وقف خسارة ضيق ومحمي لمنع أي خسائر مفاجئة
"""
        return {"Decision": report_message.strip(), "Symbol": symbol}
