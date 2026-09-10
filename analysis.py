# BingX Institutional Engine v45.0 - Strict State Lock Architecture
import time

class InstitutionalEngine:
    def __init__(self, symbol):
        self.symbol = symbol
        self.locked_signal = None
        self.lock_expiry_time = 0
        self.entry_price = 0.0
        self.tp1 = 0.0
        self.stop_loss = 0.0

    def evaluate_market(self, current_candle_time, h4_trend, h1_trend, current_price, ob_zone):
        # قاعدة 1: لو الشمعة الحالية لسه سارية وفي قفل مفعل، ممنوع تغيير القرار نهائياً
        if self.locked_signal and time.time() < self.lock_expiry_time:
            return {
                "status": "LOCKED",
                "message": "القفل الإلزامي مفعل: ممنوع إعادة الحساب أو تغيير الإشارة وسط الشمعة.",
                "signal": self.locked_signal,
                "entry": self.entry_price,
                "tp1": self.tp1,
                "sl": self.stop_loss
            }

        # قاعدة 2: فلترة الهيكل المؤسسية وتوافق فريم الماكرو (4H مع 1H)
        if h4_trend == h1_trend and current_price in ob_zone:
            self.locked_signal = h4_trend  # LONG أو SHORT
            self.entry_price = current_price
            # تثبيت عمر الشمعة الحالية (4 ساعات = 14400 ثانية)
            self.lock_expiry_time = time.time() + 14400 
            
            return {
                "status": "NEW_LOCK_ESTABLISHED",
                "signal": self.locked_signal,
                "note": "تم تفعيل قفل الشمعة بنجاح، الأرقام ثابتة حتى إغلاق شمعة الـ 4H."
            }
        
        return {
            "status": "WAITING_FOR_SETUP",
            "message": "لا يوجد توافق مؤسسي أو سحب سيولة واضح، الانتظار أفضل."
        }
