# جزء إرسال رسالة التنبيه أو الاستعلام
entry_info = details.get('entry_zone', {})
risk_mgmt = details.get('risk_management', {})

message = (
    f"🟢 *نوع المركز: LONG*\n"
    f"🔹 العملة: `{symbol}`\n"
    f"━━━━━━━━━━━━━━━━━━━\n"
    f"📍 *الدخول المثالي:* `{entry_info.get('ideal_entry', entry_price)}`\n"
    f"📍 *الدخول البديل:* `{entry_info.get('alternative_entry', entry_price)}`\n"
    f"🛑 *وقف الخسارة:* `{details.get('stop_loss')}`\n"
    f"━━━━━━━━━━━━━━━━━━━\n"
    f"🎯 *جني الأرباح (TP1):* `{risk_mgmt.get('take_profit_1')}`\n"
    f"  • TP2: `{risk_mgmt.get('take_profit_2')}`\n"
    f"  • TP3: `{risk_mgmt.get('take_profit_3')}`\n"
    f"━━━━━━━━━━━━━━━━━━━\n"
    f"💡 *ملاحظة:* {details.get('reason')}"
)
