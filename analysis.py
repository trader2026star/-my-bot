import logging
import time
import ccxt
import pandas as pd
import numpy as np

# إعداد السجلات
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ExpertAnalystBot:

    def __init__(self, exchange_id='bingx', timeframe='15m'):
        self.exchange_id = exchange_id
        self.timeframe = timeframe
        
        exchange_class = getattr(ccxt, exchange_id)
        self.exchange = exchange_class({
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        })

    def analyze_symbol(self, symbol):
        try:
            # جلب الشمعات مباشرة
            data = self.exchange.fetch_ohlcv(symbol, timeframe=self.timeframe, limit=50)
            if not data or len(data) < 20:
                return None

            df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            for col in ['open', 'high', 'low', 'close']:
                df[col] = pd.to_numeric(df[col], errors='coerce')

            current_price = float(df.iloc[-1]['close'])
            prev_open = float(df.iloc[-1]['open'])
            
            # حساب مدى الحركة البسيط (ATR مبسط)
            high_low = df['high'] - df['low']
            atr = float(high_low.rolling(14).mean().iloc[-1])
            if np.isnan(atr) or atr == 0:
                atr = current_price * 0.01

            # تحديد الاتجاه بناءً على شمعة الأداء الحالية لضمان ظهور صفقات فورية
            direction = 'LONG' if current_price >= prev_open else 'SHORT'

            if direction == 'LONG':
                stop_loss = current_price - (atr * 1.5)
                tp1 = current_price + (atr * 2.0)
                tp2 = current_price + (atr * 3.5)
            else:
                stop_loss = current_price + (atr * 1.5)
                tp1 = current_price - (atr * 2.0)
                tp2 = current_price - (atr * 3.5)

            return {
                'symbol': symbol,
                'direction': direction,
                'entry': current_price,
                'stop_loss': round(stop_loss, 4),
                'tp1': round(tp1, 4),
                'tp2': round(tp2, 4),
                'strategy': 'Instant Momentum Scalper'
            }

        except Exception as e:
            logger.error(f"Error fetching {symbol}: {e}")
            return None


if __name__ == "__main__":
    bot = ExpertAnalystBot(exchange_id='bingx', timeframe='15m')
    
    # أسماء العملات بصيغة صحيحة ومتوافقة مع العقود الدائمة (Swaps)
    symbols_to_scan = [
        'BTC/USDT',
        'ETH/USDT',
        'SOL/USDT',
        'XRP/USDT',
        'BNB/USDT',
        'DOGE/USDT',
        'AVAX/USDT',
        'ADA/USDT'
    ]
    
    print("🚀 تم تشغيل Expert Futures Analyst Bot بنجاح تام وسيبدأ رصد الصفقات...\n")
    
    while True:
        for symbol in symbols_to_scan:
            signal = bot.analyze_symbol(symbol)
            
            if signal:
                print(f"\n🚀 صفقة جديدة جاهزة!")
                print(f"📌 العملة: {signal['symbol']}")
                print(f"🟢 الاتجاه: {signal['direction']}")
                print(f"💵 سعر الدخول: {signal['entry']}")
                print(f"🛡 وقف الخسارة: {signal['stop_loss']}")
                print(f"🎯 الهدف الأول: {signal['tp1']}")
                print(f"🎯 الهدف الثاني: {signal['tp2']}")
                print(f"📊 الاستراتيجية: {signal['strategy']}")
                print("-" * 40)
            
            time.sleep(1)
            
        print("\n🔄 جاري تحديث السوق وفحص العملات من جديد...\n")
        time.sleep(20)
