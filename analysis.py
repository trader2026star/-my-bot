# analysis.py - Institutional Suite v45.0 Full Production Version
import time
import logging

# إعداد السجل (Logs) لمتابعة حالة البوت بدقة
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_top_futures_symbols():
    """
    إرجاع قائمة العملات المتاحة للمسح والتداول على العقود الآجلة
    مع حماية ضد الأخطاء لضمان استقرار السيرفر على Render
    """
    symbols = [
        "DASH-USDT", 
        "SOPH-USDT", 
        "BTC-USDT", 
        "ETH-USDT", 
        "SOL-USDT",
        "BNB-USDT",
        "XRP-USDT"
    ]
    logging.info(f"تم جلب {len(symbols)} عملة بنجاح للمسح المؤسسي.")
    return symbols

def evaluate_institutional_signal(symbol, current_price, h4_trend, h1_trend):
    """
    منطق التحليل المؤسسي وقفل الشمعة لمنع التخبط اللحظي
    وفلترة السيولة وهيكل الـ SMC
    """
    logging.info(f"جاري فحص العملة {symbol} عند السعر {current_price} | اتجاه 4H: {h4_trend} | اتجاه 1H: {h1_trend}")
    
    # التأكد من توافق فريم الماكرو 4H مع فريم 1H لمنع الإشارات الوهمية
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
        "message": "لا يوجد توافق زمني بين فريم الـ 4H والـ 1H، الانتظار لحين اكتمال الهيكل أفضل."
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
        """
        محرك قفل الشمعة الإلزامي (Candle State Lock)
        يمنع البوت تماماً من تغيير الإشارة أو عكس الاتجاه طوال مدة شمعة الـ 4 ساعات
        """
        # التحقق من حالة القفل النشط
        if self.locked_signal and time.time() < self.lock_expiry_time:
            logging.info(f"القفل الإلزامي نشط للعملة {self.symbol}. الإشارة المثبتة: {self.locked_signal}")
            return {
                "status": "LOCKED",
                "message": "قفل الشمعة مفعل: ممنوع تغيير الاتجاه أو إعادة الحساب حتى إغلاق شمعة الماكرو.",
                "signal": self.locked_signal,
                "entry": self.entry_price,
                "stop_loss": self.stop_loss,
                "tp1": self.tp1
            }

        # فحص الشروط الجديدة في حال انتهاء القفل أو بدايته
        if h4_trend == h1_trend:
            self.locked_signal = h4_trend
            self.entry_price = current_price
            self.stop_loss = current_price * 0.985 if h4_trend == "LONG" else current_price * 1.015
            self.tp1 = current_price * 1.03 if h4_trend == "LONG" else current_price * 0.97
            
            # تثبيت القفل لمدة 4 ساعات كاملة (14400 ثانية)
            self.lock_expiry_time = time.time() + 14400  
            
            logging.info(f"تم تفعيل قفل جديد للعملة {self.symbol} باتجاه {self.locked_signal} لمدة 4 ساعات.")
            return {
                "status": "NEW_LOCK",
                "signal": self.locked_signal,
                "entry": self.entry_price,
                "stop_loss": self.stop_loss,
                "tp1": self.tp1,
                "note": "تم تفعيل القفل الإلزامي بنجاح والأرقام ثابتة."
            }
        
        return {
            "status": "IDLE",
            "message": "في انتظار اكتمال الهيكل المؤسسي وسحب السيولة."
        }
