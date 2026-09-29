import logging
import time
import ccxt
import pandas as pd
import numpy as np

# إعداد السجلات (Logs)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ExpertAnalystBot:

    def __init__(
        self,
        exchange_id='bingx',
        api_key='',
        secret_key='',
        timeframe='15m'
    ):
        self.exchange_id = exchange_id
        self.timeframe = timeframe

        exchange_class = getattr(ccxt, exchange_id)

        self.exchange = exchange_class({
            'apiKey': api_key,
            'secret': secret_key,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'swap'
            }
        })

        self.cache = {}
        self.cache_seconds = 10

    def _fetch_ohlcv(self, symbol, timeframe, limit=100, market_type='swap'):
        unwanted_tokens = ['EUR', 'JPY', 'GBP', 'CAD', 'AUD', 'CHF', 'NZD']
        if any(token in symbol.upper() for token in unwanted_tokens):
            return None

        key = f"{symbol}:{market_type}:{timeframe}:{limit}"
        now = time.time()
        cached = self.cache.get(key)

        if cached and now - cached['time'] < self.cache_seconds:
            return cached['data'].copy()

        try:
            self.exchange.options['defaultType'] = market_type
            data = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

            if not data or len(data) < 30:
                return None

            df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')

            df = df.dropna().reset_index(drop=True)
            if len(df) < 30:
                return None

            self.cache[key] = {'time': now, 'data': df}
            return df.copy()

        except Exception as e:
            logger.warning(f"OHLCV error {symbol}: {e}")
            return None

    def _prepare(self, df):
        df = df.copy()
        df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()

        # حساب الـ ATR المبسط
        prev_close = df['close'].shift(1)
        tr = pd.concat([
            df['high'] - df['low'],
            (df['high'] - prev_close).abs(),
            (df['low'] - prev_close).abs()
        ], axis=1).max(axis=1)

        df['atr'] = tr.ewm(span=14, adjust=False).mean()
        return df.dropna().reset_index(drop=True)

    def analyze_symbol(self, symbol):
        try:
            df = self._fetch_ohlcv(symbol, self.timeframe, 100, 'swap')
            if df is None or len(df) < 30:
                return None

            df = self._prepare(df)
            current_price = float(df.iloc[-1]['close'])
            ema20 = float(df.iloc[-1]['ema20'])
            ema50 = float(df.iloc[-1]['ema50'])
            atr = float(df.iloc[-1]['atr'])

            # شرط مرن وسريع لتوليد صفقات فورية بناءً على تقاطع المتوسطات
            if current_price > ema20 and ema20 > ema50:
                direction = 'LONG'
            elif current_price < ema20 and ema20 < ema50:
                direction = 'SHORT'
            else:
                # إذا كانت السوق متذبذبة، نحددها بناءً على اتجاه الشمعة الأخيرة لضمان ظهور صفقات
                direction = 'LONG' if df.iloc[-1]['close'] > df.iloc[-1]['open'] else 'SHORT'

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
                'strategy': 'Dynamic EMA + Momentum Scalp'
            }

        except Exception as e:
            logger.error(f"Error in analyze_symbol for {symbol}: {e}")

        return None


if __name__ == "__main__":
    bot = ExpertAnalystBot(exchange_id='bingx', timeframe='15m')
    
    symbols_to_scan = [
        'BTC/USDT:USDT',
        'ETH/USDT:USDT',
        'SOL/USDT:USDT',
        'XRP/USDT:USDT',
        'BNB/USDT:USDT',
        'ADA/USDT:USDT',
        'DOGE/USDT:USDT',
        'AVAX/USDT:USDT'
    ]
    
    print("🚀 تم تشغيل Expert Futures Analyst Bot (النسخة الفورية الحية) بنجاح!\n")
    
    while True:
        for symbol in symbols_to_scan:
            signal = bot.analyze_symbol(symbol)
            
            if signal:
                print(f"\n🚀 صيد صفقة جديدة فورية!")
                print(f"📌 العملة: {signal['symbol']}")
                print(f"🟢 الاتجاه: {signal['direction']}")
                print(f"💵 سعر الدخول: {signal['entry']}")
                print(f"🛡 وقف الخسارة: {signal['stop_loss']}")
                print(f"🎯 الهدف الأول: {signal['tp1']}")
                print(f"🎯 الهدف الثاني: {signal['tp2']}")
                print(f"📊 الاستراتيجية: {signal['strategy']}")
                print("-" * 40)
            
            time.sleep(1)
            
        print("\n🔄 جاري تحديث السوق وإعادة الفحص الفوري...\n")
        time.sleep(30)
