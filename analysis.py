import ccxt

# تهيئة الاتصال بـ بينانس بطريقة احترافية
exchange = ccxt.binance({
    'enableRateLimit': True,
    'options': {'defaultType': 'future'}
})

def get_market_data(symbol):
    try:
        # جلب بيانات الشموع (OHLCV)
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=20)
        if not ohlcv: return None
        
        # تحويل البيانات لشكل مبسط
        last_candle = ohlcv[-1]
        return {
            "price": last_candle[4],
            "volume": last_candle[5]
        }
    except Exception as e:
        return None

# استخدم الدالة دي في البوت بتاعك لجلب البيانات لأي عملة
# مثال: data = get_market_data("SOL/USDT")
