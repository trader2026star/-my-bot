import ccxt

def get_market_movers():
    exchange = ccxt.binance()
    # جلب بيانات السوق (تغيير السعر في آخر 24 ساعة)
    tickers = exchange.fetch_tickers()
    
    # فلترة العملات اللي سعرها زاد بأكثر من 5% (مثال)
    gainers = []
    for symbol, data in tickers.items():
        if '/USDT' in symbol and data['percentage'] and data['percentage'] > 5:
            gainers.append(f"{symbol}: {data['percentage']}%")
            if len(gainers) >= 5: break # جيب أول 5 عملات فقط
            
    return "\n".join(gainers) if gainers else "لا توجد عملات صاعدة بقوة الآن."
