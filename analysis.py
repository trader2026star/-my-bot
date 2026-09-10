# analysis.py - Institutional Suite v45.0 Ultimate Production Version
import time
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_top_futures_symbols():
    """إرجاع قائمة العملات المتاحة للمسح والتداول"""
    return [
        "DASH-USDT", 
        "SOPH-USDT", 
        "BTC-USDT", 
        "ETH-USDT", 
        "SOL-USDT",
        "BNB-USDT",
        "XRP-USDT"
    ]

def get_coin_analysis(symbol, current_price=0.0, h4_trend="LONG", h1_trend="LONG"):
    """دالة التحليل الأساسية المطلوبة بواسطة main.py لمنع أي خطأ استيراد"""
    return evaluate_institutional_signal(symbol, current_price, h4_trend, h1_trend)

def analyze_coin(symbol, current_price=0.0, h4_trend="LONG", h1_trend="LONG"):
    """دالة بديلة لاحتواء أي استيراد مختلف في main.py"""
    return evaluate_institutional_signal(symbol, current_price, h4_trend, h1_trend)

def evaluate_institutional_signal(symbol, current_price, h4_trend, h1_trend):
    """منطق التحليل المؤسسي وقفل الشمعة لمنع التخبط اللحظي"""
    if h4_trend == h1_trend:
        return {
            "status": "APPROVED",
            "signal": h4_trend,
            "entry": current_price,
            "tp1": current_price * 1.03 if h4_trend == "LONG" else current_price * 0.97,
            "stop_loss": current_price * 0.985 if h4_trend == "LONG" else current_price * 1.015,
            "message": f"توافق مؤسسي صارم على {symbol} - الاتجاه: {h4_trend}"
        }
    
    return {
        "status": "WAITING",
        "signal": "NEUTRAL",
        "message": "لا يوجد توافق زمني بين فريم الـ 4H والـ 1H، الانتظار أفضل."
    }

class InstitutionalEngine:
    def __init__(self, symbol):
        self.symbol = symbol
        self.locked_signal = None
        self.lock_expiry_time = 0
        self.entry_price = 0.0
        self.stop_loss = 0.0
        self.tp1 = 0.0

    def process_candle_lock(self, current_candle_time, h4_trend, h1_trend, current_price):
        if self.locked_signal and time.time() < self.lock_expiry_time:
            return {
                "status": "LOCKED",
                "message": "قفل الشمعة مفعل: ممنوع تغيير الاتجاه حتى إغلاق شمعة الماكرو.",
                "signal": self.locked_signal,
                "entry": self.entry_price,
                "stop_loss": self.stop_loss,
                "tp1": self.tp1
            }

        if h4_trend == h1_trend:
            self.locked_signal = h4_trend
            self.entry_price = current_price
            self.stop_loss = current_price * 0.985 if h4_trend == "LONG" else current_price * 1.015
            self.tp1 = current_price * 1.03 if h4_trend == "LONG" else current_price * 0.97
            self.lock_expiry_time = time.time() + 14400  # 4 ساعات
            
            return {
                "status": "NEW_LOCK",
                "signal": self.locked_signal,
                "entry": self.entry_price,
                "stop_loss": self.stop_loss,
                "tp1": self.tp1,
                "note": "تم تفعيل القفل الإلزامي بنجاح."
            }
        
        return {
            "status": "IDLE",
            "message": "في انتظار اكتمال الهيكل المؤسسي."
        }
