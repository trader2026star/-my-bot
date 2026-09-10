# analysis.py - Institutional Version v45.0

def get_top_futures_symbols():
    """
    إرجاع قائمة العملات المتاحة للمسح والتداول على العقود الآجلة
    """
    return [
        "DASH-USDT", 
        "SOPH-USDT", 
        "BTC-USDT", 
        "ETH-USDT", 
        "SOL-USDT"
    ]

def evaluate_institutional_signal(symbol, current_price, h4_trend, h1_trend):
    """
    منطق التحليل المؤسسي وقفل الشمعة لمنع التخبط اللحظي
    """
    # التأكد من توافق فريم الماكرو 4H مع فريم 1H
    if h4_trend == h1_trend:
        return {
            "status": "APPROVED",
            "signal": h4_trend,
            "message": f"توافق مؤسسي على {symbol} - الاتجاه: {h4_trend}"
        }
    
    return {
        "status": "WAITING",
        "signal": "NEUTRAL",
        "message": "لا يوجد توافق زمني، الانتظار أفضل."
    }
