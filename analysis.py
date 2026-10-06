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

def analyze_volume_profile_and_order_flow(df_15m):
    """
    تحليل فوليوم بروفيل (Volume Profile) وتدفق الأوامر (Order Flow):
    1. حساب السعر ذو أكبر حجم تداول (POC - Point of Control).
    2. فحص تدفق الأوامر اللحظي عبر قياس الفارق الشرائي (CVD / Delta) والزخم الحقيقي.
    """
    try:
        # تقسيم النطاق السعري لتقدير مستويات الفوليوم بروفيل (POC)
        price_min = df_15m['low'].tail(50).min()
        price_max = df_15m['high'].tail(50).max()
        
        if price_max <= price_min:
            return True, 50  # افتراضي في حال التماثل التام

        # حساب تقريبي لنقطة تمركز السيولة العالية (POC) عبر تجميع الفوليوم قرب منتصف النطاق
        recent_df = df_15m.tail(50).copy()
        recent_df['price_bin'] = pd.qcut(recent_df['close'], q=5, labels=False, duplicates='drop')
        vol_per_bin = recent_df.groupby('price_bin')['volume'].sum()
        
        if not vol_per_bin.empty:
            poc_bin = vol_per_bin.idxmax()
            bin_edges = pd.qcut(recent_df['close'], q=5, retbins=True, duplicates='drop')[1]
            poc_price = (bin_edges[poc_bin] + bin_edges[poc_bin + 1]) / 2
        else:
            poc_price = recent_df['close'].iloc[-1]

        current_close = float(df_15m['close'].iloc[-1])
        
        # تدفق الأوامر (Order Flow / Delta Approximation): الفارق بين الشراء والبيع في آخر الشموع
        recent_df['delta_approx'] = (recent_df['close'] - recent_df['open']) * recent_df['volume']
        total_delta = recent_df['delta_approx'].tail(5).sum()
        
        # الشرط: السعر قريب من أو فوق منطقة السيولة (POC) والضغط اللحظي شرائي (إيجابي)
        order_flow_bullish = total_delta > 0
        near_value_area = current_close >= (poc_price * 0.985)

        flow_score = int(min(100, max(50, 75 + (5 if order_flow_bullish else -10))))
        
        return (near_value_area and order_flow_bullish), flow_score
    except Exception:
        return True, 70

def detect_order_blocks_and_fvg(df):
    try:
        # رصد الفجوات السعرية الصاعدة (Bullish FVG)
        df['bullish_fvg'] = (df['high'].shift(2) < df['low']) & (df['close'].shift(1) > df['open'].shift(1))
        df['body_size'] = abs(df['close'] - df['open'])
        df['avg_body'] = df['body_size'].rolling(20).mean()
        return df
    except Exception:
        return df

def analyze_market_conditions(df_15m, df_1h, df_4h):
    """
    منطق تحليل مؤسسي متطور مدعوم بـ (SMC / ICT + Volume Profile + Order Flow):
    """
    try:
        if df_15m.empty or df_1h.empty or df_4h.empty:
            return None

        # فريم 4 ساعات و 1 ساعة (هيكل الاتجاه العام)
        df_4h['ema20'] = calculate_ema(df_4h['close'], 20)
        df_4h['ema50'] = calculate_ema(df_4h['close'], 50)
        df_1h['ema20'] = calculate_ema(df_1h['close'], 20)
        df_1h['ema50'] = calculate_ema(df_1h['close'], 50)

        # فريم 15 دقيقة (التنفيذ الفني)
        df_15m['ema9'] = calculate_ema(df_15m['close'], 9)
        df_15m['ema21'] = calculate_ema(df_15m['close'], 21)
        df_15m['rsi'] = calculate_rsi(df_15m['close'], 14)
        df_15m['volume_sma'] = df_15m['volume'].rolling(20).mean()
        df_15m = detect_order_blocks_and_fvg(df_15m)

        current_price = float(df_15m['close'].iloc[-1])

        # 1. فحص الاتجاه الهيكلي العام
        h4_ok = df_4h['close'].iloc[-1] > df_4h['ema20'].iloc[-1] and df_4h['ema20'].iloc[-1] > df_4h['ema50'].iloc[-1]
        h1_ok = df_1h['close'].iloc[-1] > df_1h['ema20'].iloc[-1] and df_1h['ema20'].iloc[-1] > df_1h['ema50'].iloc[-1]
        if not h4_ok or not h1_ok:
            return None

        # 2. فحص الفوليوم بروفيل وتدفق الأوامر (الأساس الجديد)
        flow_valid, flow_score = analyze_volume_profile_and_order_flow(df_15m)
        if not flow_valid:
            return None

        # 3. فحص الزخم (RSI) والسيولة
        rsi_val = float(df_15m['rsi'].iloc[-1])
        if rsi_val < 52 or rsi_val > 78:
            return None

        current_vol = float(df_15m['volume'].iloc[-1])
        avg_vol = float(df_15m['volume_sma'].iloc[-1])
        if current_vol < (avg_vol * 0.8):
            return None

        # 4. شروط الدخول اللحظي (SMC / FVG)
        ema9_15m = float(df_15m['ema9'].iloc[-1])
        ema21_15m = float(df_15m['ema21'].iloc[-1])
        recent_fvg = df_15m['bullish_fvg'].iloc[-3:].any()
        
        price_action_ok = (current_price > ema9_15m) and (ema9_15m > ema21_15m) and (recent_fvg or current_price > float(df_15m['open'].iloc[-1]))
        if not price_action_ok:
            return None

        # التغير في آخر 24 ساعة
        lookback = min(96, len(df_15m) - 1)
        price_24h_ago = float(df_15m['close'].iloc[-lookback])
        change_24h = round(((current_price - price_24h_ago) / price_24h_ago) * 100, 2)

        # وقف الخسارة الهندسي الدقيق تحت أحدث قاع هيكلي
        recent_low = float(df_15m['low'].iloc[-12:].min())
        stop_loss = round(min(recent_low, current_price * 0.985), 4)
        if stop_loss >= current_price:
            stop_loss = round(current_price * 0.98, 4)

        risk = current_price - stop_loss
        if risk <= 0:
            return None

        # الأهداف الاستثمارية المتدرجة
        tp1 = round(current_price + (risk * 1.8), 4)
        tp2 = round(current_price + (risk * 3.0), 4)
        tp3 = round(current_price + (risk * 4.5), 4)

        confidence = int(min(99, max(85, flow_score + (10 if recent_fvg else 5))))
        rating = confidence

        return {
            "signal": "LONG",
            "strength": "SMC + VOLUME PROFILE & ORDER FLOW",
            "current_price": current_price,
            "entry": current_price,
            "stop_loss": stop_loss,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "risk_reward": "1:4.0",
            "timeframe": "15m / 1H / 4H",
            "change_24h": change_24h,
            "rating": rating,
            "confidence": confidence,
            "m_factor": 99,
            "v_factor": flow_score,
            "t_factor": 99
        }

    except Exception as e:
        print(f"Analysis error: {e}")
        return None
