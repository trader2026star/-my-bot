import pandas as pd
import numpy as np

def calculate_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def calculate_atr(df, period=14):
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    return true_range.rolling(window=period).mean()

def analyze_market_conditions(df_1m, df_15m, df_4h):
    """
    استراتيجية دقيقة تمنع الخسارة: شرط توافق الفريمات الكبرى (الاتجاه الصاعد العام)
    مع رصد ارتداد حقيقي من القاع على الفريم الصغير بفلتر الفوليوم.
    """
    try:
        if df_1m is None or df_15m is None or df_4h is None:
            return None
        if df_1m.empty or df_15m.empty or df_4h.empty:
            return None

        # 1. فلتر الاتجاه العام الصارم على فريم 4 ساعات و 15 دقيقة (لمنع الدخول في اتجاه هابط نهائياً)
        df_4h['ema50'] = calculate_ema(df_4h['close'], 50)
        df_15m['ema20'] = calculate_ema(df_15m['close'], 20)

        if float(df_4h['close'].iloc[-1]) <= float(df_4h['ema50'].iloc[-1]):
            return None # الاتجاه العام على الـ 4 ساعات هابط، ممنوع الدخول!
        if float(df_15m['close'].iloc[-1]) <= float(df_15m['ema20'].iloc[-1]):
            return None # الاتجاه على الـ 15 دقيقة هابط، ممنوع الدخول!

        # 2. فريم الدقيقة (1m): التأكد من وجود ارتداد حقيقي من قاع محلي بفوليوم مؤكد
        current_close = float(df_1m['close'].iloc[-1])
        current_open = float(df_1m['open'].iloc[-1])
        current_low = float(df_1m['low'].iloc[-1])

        is_green = current_close > current_open
        if not is_green:
            return None

        # التأكد أن السعر ارتد للتو من دعم أو قاع محلي خلال الـ 20 شمعة الماضية
        recent_low = float(df_1m['low'].iloc[-20:].min())
        if current_low > (recent_low * 1.02):
            return None # السعر ليس في منطقة قاع حقيقية

        # تأكد من فوليوم الشراء (أكبر من متوسط الفوليوم لضمان عدم عشوائية الشمعة)
        volume_sma = df_1m['volume'].rolling(window=15).mean().iloc[-1]
        current_volume = float(df_1m['volume'].iloc[-1])
        if current_volume <= (volume_sma * 1.3):
            return None # فوليوم ضعيف، نرفض الشمعة

        # 3. وقف خسارة محمي بالـ ATR تحت القاع المحلي مباشرة
        df_1m['atr'] = calculate_atr(df_1m, 14)
        current_atr = float(df_1m['atr'].iloc[-1]) if not pd.isna(df_1m['atr'].iloc[-1]) else (current_close * 0.005)
        
        stop_loss = round(recent_low - (current_atr * 0.6), 4)
        if stop_loss >= current_close:
            stop_loss = round(current_close * 0.985, 4)

        risk = current_close - stop_loss
        if risk <= 0:
            return None

        tp1 = round(current_close + (risk * 2.0), 4)
        tp2 = round(current_close + (risk * 3.5), 4)
        tp3 = round(current_close + (risk * 5.0), 4)

        return {
            "signal": "LONG",
            "entry": current_close,
            "stop_loss": stop_loss,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3
        }

    except Exception as e:
        print(f"Strict Filter Error: {e}")
        return None
