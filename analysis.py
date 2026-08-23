import requests

def scan_market(limit=5):
    """
    جلب الأسعار الحقيقية والمباشرة لأشهر العملات الرقمية من بينانس.
    """
    # قائمة بأهم العملات الحية في السوق لجلب أسعارها الحقيقية بدقة وسرعة
    symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT"]
    
    results = []
    
    for sym in symbols[:limit]:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={sym}"
        try:
            response = requests.get(url, timeout=5)
            data = response.json()
            
            if "price" in data:
                price = float(data["price"])
                formatted_symbol = sym.replace("USDT", "/USDT")
                
                # افتراضات منطقية للهدف ووقف الخسارة بناءً على السعر الحقيقي الحالي
                target = round(price * 1.025, 4)  # هدف +2.5%
                stop_loss = round(price * 0.985, 4) # وقف خسارة -1.5%
                
                results.append({
                    "symbol": formatted_symbol,
                    "action": "مراقبة / صفقة محتملة 🚀",
                    "entry": f"{price}",
                    "target": f"{target}",
                    "stop_loss": f"{stop_loss}",
                    "reason": "السعر مستمد مباشرة وبشكل حي من منصة Binance اللحظية."
                })
        except Exception as e:
            print(f"Error fetching {sym}: {e}")
            continue
            
    return results


def generate_evidence_report(data):
    """
    توليد التقرير المنسق لإرساله عبر تيليجرام.
    """
    report = (
        f"📊 **تقرير الأسعار الحية من السوق** 📊\n\n"
        f"🪙 **العملة:** `{data.get('symbol')}`\n"
        f"🎯 **الحالة:** `{data.get('action')}`\n"
        f"📥 **السعر الحقيقي الفوري:** `{data.get('entry')}`\n"
        f"🎯 **الهدف المقترح:** `{data.get('target')}`\n"
        f"🛑 **وقف الخسارة:** `{data.get('stop_loss')}`\n\n"
        f"📈 **التحليل الفني:**\n_{data.get('reason')}_\n\n"
        f"⚡ _البيانات دقيقة ومحدثة مباشرة._"
    )
    return report
