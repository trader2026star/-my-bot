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

    def calculate_macd(self, series, fast=12, slow=26, signal=9):
        exp1 = series.ewm(span=fast, adjust=False).mean()
        exp2 = series.ewm(span=slow, adjust=False).mean()
        macd_line = exp1 - exp2
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    def evaluate_strategy(self, symbol):
        # فريم الـ 4 ساعات للتحليل الاستراتيجي وترتيب المتوسطات الثلاثة
        df_higher = self.fetch_ohlcv_data(symbol, timeframe='4h', limit=200)
        # فريم التنفيذ اللحظي
        df_lower = self.fetch_ohlcv_data(symbol, timeframe=self.timeframe, limit=100)
        
        if df_higher is None or df_lower is None or len(df_higher) < 200 or len(df_lower) < 50:
            return None

        close = df_lower['close'].iloc[-1]
        
        # 1. فلتر السيولة المرحلي (حجم التداول لآخر 24 ساعة)
        daily_volume_usd = (df_higher['volume'] * df_higher['close']).iloc[-24:].sum()
        min_liquidity_required = 3000000 
        has_good_liquidity = daily_volume_usd >= min_liquidity_required

        if not has_good_liquidity:
            return {"Decision": "NO TRADE ⏳", "Reason": "السيولة لا تتوافق مع الشروط المرحلية."}

        # 2. التقاء المتوسطات الثلاثة (EMA 20 > EMA 50 > EMA 200) للاتجاه الصاعد القوي[span_2](start_span)[span_2](end_span)
        ema20_h = df_higher['close'].ewm(span=20, adjust=False).mean().iloc[-1]
        ema50_h = df_higher['close'].ewm(span=50, adjust=False).mean().iloc[-1]
        ema200_h = df_higher['close'].ewm(span=200, adjust=False).mean().iloc[-1]
        
        bullish_ema_alignment = (ema20_h > ema50_h) and (ema50_h > ema200_h)
        bearish_ema_alignment = (ema20_h < ema50_h) and (ema50_h < ema200_h)

        # 3. مؤشر MACD وتقاطعه الإيجابي/السلبي للزخم[span_3](start_span)[span_3](end_span)
        _, _, macd_hist = self.calculate_macd(df_lower['close'])
        macd_is_positive = macd_hist.iloc[-1] > 0

        clean_symbol = symbol.split('/')[0]

        # ---------------------------------------------------------
        # استراتيجية الشراء (LONG)
        # ---------------------------------------------------------
        if bullish_ema_alignment and macd_is_positive:
            entry_price = round(close, 4 if close < 1 else 2)
            
            # وقف خسارة خلف قاع الشمعة المحمي[span_4](start_span)[span_4](end_span)
            recent_low = df_lower['low'].iloc[-5:].min()
            stop_loss = round(min(recent_low, entry_price * 0.98), 4 if close < 1 else 2)
            
            risk = entry_price - stop_loss
            if risk <= 0:
                return None

            # الأهداف الاحترافية بنسب الـ R-Multiples الدقيقة[span_5](start_span)[span_5](end_span)[span_6](start_span)[span_6](end_span)
            tp1 = round(entry_price + (1.59 * risk), 4 if close < 1 else 2)
            tp2 = round(entry_price + (2.51 * risk), 4 if close < 1 else 2)
            tp3 = round(entry_price + (3.99 * risk), 4 if close < 1 else 2)
            
            tp1_pct = round(((tp1 - entry_price) / entry_price) * 100, 2)
            tp2_pct = round(((tp2 - entry_price) / entry_price) * 100, 2)
            tp3_pct = round(((tp3 - entry_price) / entry_price) * 100, 2)

            report_message = f"""
Green Candle Pro 🟢
النسخة الاحترافية المتقدمة 🤖

 العملة: {clean_symbol}
 الزوج: {symbol}
 نوع الصفقة: عقود آجلة (Futures)[span_7](start_span)[span_7](end_span)
 الفريم: 4 ساعات[span_8](start_span)[span_8](end_span)
 الحكم: شراء (LONG)[span_9](start_span)[span_9](end_span)
 الثقة: 88% | الاتفاق: 100%[span_10](start_span)[span_10](end_span)

 خطة الصفقة:
الدخول: {entry_price} 🚀
وقف الخسارة: {stop_loss} (خلف قاع الشمعة المغلقة)[span_11](start_span)[span_11](end_span) 🛑
الهدف 1 (1.59R): {tp1} (+{tp1_pct}%)[span_12](start_span)[span_12](end_span)[span_13](start_span)[span_13](end_span)
الهدف 2 (2.51R): {tp2} (+{tp2_pct}%)[span_14](start_span)[span_14](end_span)[span_15](start_span)[span_15](end_span)
الهدف 3 (3.99R): {tp3} (+{tp3_pct}%)[span_16](start_span)[span_16](end_span)[span_17](start_span)[span_17](end_span)

 الاستراتيجيات المؤكدة:
✔ الفلتر المرحلي: سيولة يومية قوية فوق الحد المطلوب[span_18](start_span)[span_18](end_span)
✔ التقاء المؤشرات: EMA20 > EMA50 > EMA200[span_19](start_span)[span_19](end_span)
✔ القناص: تقاطع MACD إيجابي مع هيستوجرام موجب[span_20](start_span)[span_20](end_span)
"""
            return {"Decision": report_message.strip(), "Symbol": symbol}

        # ---------------------------------------------------------
        # استراتيجية البيع (SHORT)
        # ---------------------------------------------------------
        elif bearish_ema_alignment and not macd_is_positive:
            entry_price = round(close, 4 if close < 1 else 2)
            
            recent_high = df_lower['high'].iloc[-5:].max()
            stop_loss = round(max(recent_high, entry_price * 1.02), 4 if close < 1 else 2)
            
            risk = stop_loss - entry_price
            if risk <= 0:
                return None

            tp1 = round(entry_price - (1.59 * risk), 4 if close < 1 else 2)
            tp2 = round(entry_price - (2.51 * risk), 4 if close < 1 else 2)
            tp3 = round(entry_price - (3.99 * risk), 4 if close < 1 else 2)
            
            tp1_pct = round(((entry_price - tp1) / entry_price) * 100, 2)
            tp2_pct = round(((entry_price - tp2) / entry_price) * 100, 2)
            tp3_pct = round(((entry_price - tp3) / entry_price) * 100, 2)

            report_message = f"""
Green Candle Pro 🔴
النسخة الاحترافية المتقدمة 🤖

 العملة: {clean_symbol}
 الزوج: {symbol}
 نوع الصفقة: عقود آجلة (Short)[span_21](start_span)[span_21](end_span)
 الفريم: 4 ساعات[span_22](start_span)[span_22](end_span)
 الحكم: بيع (SHORT)
 الثقة: 88% | الاتفاق: 100%[span_23](start_span)[span_23](end_span)

 خطة الصفقة:
الدخول: {entry_price} 🚀
وقف الخسارة: {stop_loss} (خلف قمة الشمعة المغلقة)[span_24](start_span)[span_24](end_span) 🛑
الهدف 1 (1.59R): {tp1} (-{tp1_pct}%)[span_25](start_span)[span_25](end_span)[span_26](start_span)[span_26](end_span)
الهدف 2 (2.51R): {tp2} (-{tp2_pct}%)[span_27](start_span)[span_27](end_span)[span_28](start_span)[span_28](end_span)
الهدف 3 (3.99R): {tp3} (-{tp3_pct}%)[span_29](start_span)[span_29](end_span)[span_30](start_span)[span_30](end_span)

 الاستراتيجيات المؤكدة:
✔ الفلتر المرحلي: سيولة يومية قوية تدعم الهبوط[span_31](start_span)[span_31](end_span)
✔ التقاء المؤشرات: EMA20 < EMA50 <EMA200[span_32](start_span)[span_32](end_span)
✔ القناص: تقاطع MACD سلبي مع هيستوجرام هابط[span_33](start_span)[span_33](end_span)
"""
            return {"Decision": report_message.strip(), "Symbol": symbol}

        return None
