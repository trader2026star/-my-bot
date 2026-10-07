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

def analyze_market_conditions(df_15m, df_1h, df_4h):
    """
    استراتيجية اقتناص شمعة الانفجار الحقيقي المؤكدة (Confirmed Volume Explosion)
    1. رصد شمعة انفجار سعرية صاعدة قوية على فريم 15 دقيقة (جسم الشمعة كبير وإغلاق قرب القمة).
    2. تأكيد الانفجار بفوليوم تداول ضخم يفوق متوسط الشموع السابقة بوضوح.
    3. التأكد من أن الانفجار في بداية الحركة (ليس بعد ارتفاع فلكي متأخر).
    """
    try:
        if df_15m is None or df_1h is None or df_4h is None:
            return None
        if df_15m.empty or df_1h.empty or df_4h.empty:
            return None

        # 1. الاتجاه العام صاعد على فريم 4 ساعات
        df_4h['ema50'] = calculate_ema(df_4h['close'], 50)
        if df_4h['close'].iloc[-1] <= df_4h['ema50'].iloc[-1]:
            return None

        # 2. فريم 15 دقيقة: رصد شمعة الانفجار الحقيقي
        current_close = float(df_15m['close'].iloc[-1])
        current_open = float(df_15m['open'].iloc[-1])
        current_high = float(df_15m['high'].iloc[-1])
        current_low = float(df_15m['low'].iloc[-1])

        # حساب التغير في آخر 24 ساعة (نسمح بالعملات التي تبدأ الانفجار أو في بدايات الصعود الهادئ)
        lookback = min(96, len(df_15m) - 1)
        price_24h_ago = float(df_15m['close'].iloc[-lookback])
        change_24h = round(((current_close - price_24h_ago) / price_24h_ago) * 100, 2)

        # استبعاد العملات التي طارت بشكل جنوني مبالغ فيه لتجنب القمم المتأخرة
        if change_24h > 15.0 or change_24h < -2.0:
            return None

        # خصائص شمعة الانفجار القوية:
        # - شمعة خضراء قوية (الإغلاق أعلى من الافتتاح بوضوح)
        body_size = current_close - current_open
        total_range = current_high - current_low
        
        if total_range <= 0:
            return None
            
        is_strong_body = (body_size / total_range) >= 0.6  # جسم الشمعة يمثل 60% على الأقل من إجمالي طولها
        is_bullish = current_close > current_open

        # تأكيد الفوليوم الانفجاري (الفوليوم الحالي أكبر من متوسط آخر 20 شمعة بضعفين على الأقل!)
        volume_sma = df_15m['volume'].rolling(window=20).mean().iloc[-1]
        current_volume = float(df_15m['volume'].iloc[-1])
        is_explosion_volume = current_volume > (volume_sma * 2.0)

        # شرط الانفجار المتحقق: شمعة قوية جداً + فوليوم انفجاري مؤكد
        if not (is_bullish and is_strong_body and is_explosion_volume):
            return None

        # 3. وقف الخسارة الهندسي: تحت أدنى سعر شمعة الانفجار مباشرة مع حماية ATR
        df_15m['atr'] = calculate_atr(df_15m, 14)
        current_atr = float(df_15m['atr'].iloc[-1])
        
        stop_loss = round(current_low - (current_atr * 0.5), 4)
        if stop_loss >= current_close:
            stop_loss = round(current_close * 0.98, 4)

        risk = current_close - stop_loss
        if risk <= 0:
            return None

        # الأهداف الاستثمارية مبنية على قوة الانفجار
        tp1 = round(current_close + (risk * 2.0), 4)
        tp2 = round(current_close + (risk * 3.5), 4)
        tp3 = round(current_close + (risk * 5.0), 4)

        return {
            "signal": "LONG",
            "strength": "CONFIRMED VOLUME EXPLOSION",
            "current_price": current_close,
            "entry": current_close,
            "stop_loss": stop_loss,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "risk_reward": "1:3.5+",
            "timeframe": "15m / 4H",
            "change_24h": change_24h,
            "rating": 98,
            "confidence": 98,
            "m_factor": 99,
            "v_factor": 99,
            "t_factor": 96
        }

    except Exception as e:
        print(f"Explosion Strategy Error: {e}")
        return None
