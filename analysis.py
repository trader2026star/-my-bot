# ملف التحليلات وتوليد التقارير المتوافق مع main.py

def scan_market(limit=5):
    """
    دالة لفحص السوق وجلب العملات أو الصفقات المطابقة.
    يمكنك ربطها بـ API (مثل Binance أو غيره لاحقاً).
    حالياً تعيد أمثلة توضيحية لضمان عمل البوت بنجاح.
    """
    # مثال توضيحي لبيانات صفقات تجريبية تتوافق مع التقرير
    mock_results = [
        {
            "symbol": "BTC/USDT",
            "action": "شراء (LONG)",
            "entry": "64,500",
            "target": "67,000",
            "stop_loss": "63,200",
            "reason": "اختراق مقاومة قوية مع حجم تداول عالي على الإطار الزمني 4 ساعات."
        },
        {
            "symbol": "ETH/USDT",
            "action": "بيع (SHORT)",
            "entry": "3,500",
            "target": "3,350",
            "stop_loss": "3,580",
            "reason": "ارتداد من خط اتجاه هابط رئيسي وتشبع شراء على مؤشر RSI."
        }
    ]
    
    return mock_results[:limit]


def generate_evidence_report(data):
    """
    دالة لتوليد تقرير احترافي ومنسق بالشكل المطلوب إرساله عبر تيليجرام.
    """
    report = (
        f"🚨 **تقرير تحليل فني جديد** 🚨\n\n"
        f"🪙 **العملة:** `{data.get('symbol')}`\n"
        f"🎯 **العملية:** `{data.get('action')}`\n"
        f"📥 **منطقة الدخول:** `{data.get('entry')}`\n"
        f"🎯 **الهدف:** `{data.get('target')}`\n"
        f"🛑 **وقف الخسارة:** `{data.get('stop_loss')}`\n\n"
        f"📊 **السبب الفني:**\n_{data.get('reason')}_\n\n"
        f"⚡ _تم الفحص بواسطة بوت التداول الآلي._"
    )
    return report
