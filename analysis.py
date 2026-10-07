import pandas as pd
import numpy as np

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / (loss + 1e-10)
    return 100 - (100 / (1 + rs))

def calculate_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def analyze_market_conditions(df_15m, df_1h, df_4h):
    """
    استراتيجية الارتداد من التصحيحات للاتجاه العام (Trend Pullback & RSI Reversal)
    """
    try:
        if df_15m.empty or df_1h.empty or df_4h.empty:
            return None

        # اتجاه عام صاعد قوي على فريم 4H و 1H
        df_4h['ema50'] = calculate_ema(df_4h['close'], 50)
        df_1h['ema20'] = calculate_ema(df_1h['close'], 20)
        
        if df_4h['close'].iloc[-1] < df_4h['ema50'].iloc[-1] or df_1h['close'].iloc[-1] < df_1h['ema20'].iloc[-1]:
            return None

        # فريم 15 دقيقة: البحث عن تصحيح مؤقت (Pullback) ثم ارتداد
        df_15m['rsi'] = calculate_rsi(df_15m['close'], 14)
        current_rsi = float(df_15m['rsi'].iloc[-1])
        prev_rsi = float(df_15m['rsi'].iloc[-2])

        # الشرط: الـ RSI كان نزل تحت 45 (تصحيح) وبدأ يطلع لفوق تاني (ارتداد)
        rsi_pullback_reversal = (prev_rsi <= 45) and (current_rsi > prev_rsi) and (current_rsi < 60)

        if not rsi_pullback_reversal:
            return None

        current_price = float(df_15m['close'].iloc[-1])
        
        # التأكد من أن الشمعة الحالية صاعدة
        if current_price <= float(df_15m['open'].iloc[-1]):
            return None

        # التغير في آخر 24 ساعة
        lookback = min(96, len(df_15m) - 1)
        price_24h_ago = float(df_15m['close'].iloc[-lookback])
        change_24h = round(((current_price - price_24h_ago) / price_24h_ago) * 100, 2)

        # وقف الخسارة تحت أدنى سعر في آخر 10 شمعات
        stop_loss = round(float(df_15m['low'].tail(10).min()), 4)
        if stop_loss >= current_price:
            stop_loss = round(current_price * 0.98, 4)

        risk = current_price - stop_loss
        if risk <= 0:
            return None

        tp1 = round(current_price + (risk * 1.8), 4)
        tp2 = round(current_price + (risk * 3.0), 4)
        tp3 = round(current_price + (risk * 4.2), 4)

        return {
            "signal": "LONG",
            "strength": "TREND PULLBACK & RSI REVERSAL",
            "current_price": current_price,
            "entry": current_price,
            "stop_loss": stop_loss,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "risk_reward": "1:3.0",
            "timeframe": "15m / 1H / 4H",
            "change_24h": change_24h,
            "rating": 90,
            "confidence": 90,
            "m_factor": 94,
            "v_factor": 89,
            "t_factor": 95
        }
    except Exception as e:
        print(f"Strategy 2 error: {e}")
        return None
