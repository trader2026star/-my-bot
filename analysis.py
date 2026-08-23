import requests

def scan_market(limit=5):
    """
    دالة لجلب بيانات السوق الحية من منصة Binance وفحص العملات الأكثر حركة وتداولاً.
    """
    url = "https://api.binance.com/api/v3/ticker/24hr"
    
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        
        # تصفية العملات مقابل USDT واختيار الأكثر نشاطاً أو ارتفاعاً
        usdt_pairs = []
        for item in data:
            symbol = item.get('symbol', '')
            if symbol.endswith('USDT') and not symbol.endswith(('DOWNUSDT', 'UPUSDT', 'BULLUSDT', 'BEARUSDT')):
                try:
                    price_change = float(item.get('priceChangePercent', 0))
                    volume = float(item.get('quoteVolume', 0))
                    last_price = float(item.get('lastPrice', 0))
                    
                    usdt_pairs.append({
                        "symbol": symbol.replace('USDT', '/USDT'),
                        "change": price_change,
                        "price": last_price,
                        "volume": volume
                    })
                except ValueError:
                    continue
        
        # ترتيب العملات حسب نسبة التغير أو حجم التداول لجلب الأقوى حالياً
        usdt_pairs.sort(key=lambda x: x['change'], reverse=True)
        
        results = []
        for pair in usdt_pairs[:limit]:
            # تحديد نوع العملية بناءً على اتجاه السعر (صاعد قوي كمثال)
            action = "شراء (LONG) 🚀" if pair['change'] > 0 else "متابعة (NEUTRAL)"
            entry = f"{pair['price']}"
            target = f"{pair['price'] * 1.03:.4f}" # هدف افتراضي +3%
            stop_loss = f"{pair['price'] * 0.98:.4f}" # وقف خسارة افتراضي -2%
            
            results.append({
                "symbol": pair['symbol'],
                "action": action,
                "entry": entry,
                "target": target,
                "stop_loss": stop_loss,
                "reason": f"تغير السعر خلال 24 ساعة بنسبة {pair['change']}% مع نشاط ملحوظ في السيولة."
            })
            
        return results

    except Exception as e:
        print(f"Error fetching Binance data: {e}")
        return []


def generate_evidence_report(data):
    """
    توليد التقرير المنسق لإرساله عبر تيليجرام.
    """
    report = (
        f"🚨 **تقرير تحليل السوق الحي** 🚨\n\n"
        f"🪙 **العملة:** `{data.get('symbol')}`\n"
        f"🎯 **الحالة:** `{data.get('action')}`\n"
        f"📥 **السعر الحالي / الدخول:** `{data.get('entry')}`\n"
        f"🎯 **الهدف المقترح:** `{data.get('target')}`\n"
        f"🛑 **وقف الخسارة:** `{data.get('stop_loss')}`\n\n"
        f"📊 **المؤشرات:**\n_{data.get('reason')}_\n\n"
        f"⚡ _مدعوم ببيانات Binance الفورية._"
    )
    return report
