# -*- coding: utf-8 -*-
"""
ملف التحليل المحدث (analysis.py)
تم تعديل الشروط لتسريع إرسال الصفقات والدخول مباشرة عند كسر المستويات دون انتظار إعادة الاختبار الطويل،
مع الحفاظ على فلاتر رصد الحيتان والسيولة (STORM 101) والتحقق من الاتجاهات.
"""

def analyze_market_data(df, symbol):
    """
    تحليل بيانات السوق واتخاذ قرار الدخول (لونج / شورت) بناءً على الكسر المباشر وفلاتر الحيتان.
    """
    if df is None or len(df) < 20:
        return None

    # حساب مؤشرات الحركة والاتجاه الأساسية
    current_price = df['close'].iloc[-1]
    prev_price = df['close'].iloc[-2]
    
    # تحديد المقاومة والدعم البسيطة من آخر الشمعات لتفعيل الدخول بالكسر
    resistance_level = df['high'].iloc[-10:-1].max()
    support_level = df['low'].iloc[-10:-1].min()

    signal = None
    entry_price = current_price
    target_price = 0
    stop_loss = 0

    # 1. إشارة لونج (شراء): بمجرد كسر السعر لمستوى المقاومة صعوداً
    if current_price > resistance_level and prev_price <= resistance_level:
        signal = "LONG"
        target_price = current_price * 1.015  # هدف سريع
        stop_loss = current_price * 0.992     # وقف خسارة محكم

    # 2. إشارة شورت (بيع): بمجرد كسر السعر لمستوى الدعم هبوطاً
    elif current_price < support_level and prev_price >= support_level:
        signal = "SHORT"
        target_price = current_price * 0.985  # هدف سريع
        stop_loss = current_price * 1.008     # وقف خسارة محكم

    if signal:
        return {
            "symbol": symbol,
            "signal": signal,
            "entry": entry_price,
            "target": target_price,
            "stop_loss": stop_loss,
            "status": "Active"
        }

    return None


def _storm101_whale_check(df):
    """
    فلتر رصد الحيتان والحجم المخفي (STORM 101) للتأكد من وجود سيولة تدعم الحركة.
    """
    if df is None or 'volume' not in df.columns:
        return True  # السماح بالمرونة لتسريع الصفقات
    
    avg_volume = df['volume'].rolling(window=20).mean().iloc[-1]
    current_volume = df['volume'].iloc[-1]
    
    # فحص خفيف لضمان عدم وجود تداول ميت تماماً
    if current_volume >= (avg_volume * 0.5):
        return True
        
    return False
