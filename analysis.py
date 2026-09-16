import ccxt
import pandas as pd
import numpy as np
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SmartMoneyTradingAnalyst:
    def __init__(self, exchange_id='bingx', api_key='', secret_key=''):
        exchange_class = getattr(ccxt, exchange_id)
        self.exchange = exchange_class({
            'apiKey': api_key,
            'secret': secret_key,
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        })
        try:
            self.exchange.load_markets()
            logger.info(f"تم الاتصال بنجاح بمنصة {exchange_id.upper()} وتحميل أسواق الـ Swap.")
        except Exception as e:
            logger.error(f"فشل الاتصال بالمنصة: {e}")

    def fetch_ohlcv_data(self, symbol='BTC/USDT:USDT', timeframe='1h', limit=150):
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            if not ohlcv or len(ohlcv) < 50:
                return None
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            logger.error(f"خطأ أثناء جلب بيانات الشموع لـ {symbol}: {e}")
            return None

    def analyze_smc_structure(self, df):
        """كشف الهيكل المؤسسي ومناطق الطلب/العرض (Order Blocks & Market Structure)"""
        # حساب الـ ATR لقياس التذبذب ووضع الوقف الآمن
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        df['atr'] = np.max(ranges, axis=1).rolling(window=14).mean()

        # تحديد القمم والقيعان الهيكلية لآخر 14 شمعة (Swing High/Low)
        df['swing_high'] = df['high'].rolling(window=14).max()
        df['swing_low'] = df['low'].rolling(window=14).min()

        # تحديد مناطق الـ Order Blocks (شمعة الانعكاس المؤسسي)
        # بلوك شرائي: شمعة هابطة تليها شمعة صاعدة قوية تبتلعها
        df['bullish_ob'] = (df['close'].shift(1) < df['open'].shift(1)) & (df['close'] > df['high'].shift(1))
        # بلوك بيعي: شمعة صاعدة تليها شمعة هابطة قوية تكسرها
        df['bearish_ob'] = (df['close'].shift(1) > df['open'].shift(1)) & (df['close'] < df['low'].shift(1))

        # كسر الهيكل (BOS / Market Structure Shift)
        df['bos_bullish'] = df['close'] > df['swing_high'].shift(1)
        df['bos_bearish'] = df['close'] < df['swing_low'].shift(1)

        return df

    def evaluate_strategy(self, symbol='BTC/USDT:USDT', account_balance=1000.0, risk_percentage=0.01):
        df = self.fetch_ohlcv_data(symbol, timeframe='1h', limit=150)
        if df is None or len(df) < 100:
            return {"Decision": "WAIT", "Reason": "البيانات المسترجعة غير كافية للتحليل الحي."}

        df = self.analyze_smc_structure(df)
        
        last_closed = df.iloc[-2]
        current_price = df.iloc[-1]['close']
        current_atr = last_closed['atr']
        allowed_risk_usd = account_balance * risk_percentage

        recent_swing_low = df['low'].iloc[-20:-2].min()
        recent_swing_high = df['high'].iloc[-20:-2].max()

        # تقييم اتجاه السيولة وهل نحن في منطقة شراء (Bullish SMC) أم بيع (Bearish SMC)
        is_bullish_setup = last_closed['bos_bullish'] or last_closed['bullish_ob'] or (current_price > recent_swing_low + (current_atr * 2))
        is_bearish_setup = last_closed['bos_bearish'] or last_closed['bearish_ob'] or (current_price < recent_swing_high - (current_atr * 2))

        # إذا كانت الهيكلة تميل للصعود (أو كسر قمة) -> نسعي وراء صفقات الشراء المحمية
        if is_bullish_setup and not last_closed['bos_bearish']:
            stop_loss = min(recent_swing_low - (0.5 * current_atr), current_price - (2.0 * current_atr))
            risk_per_token = current_price - stop_loss
            
            if risk_per_token <= 0:
                risk_per_token = current_atr * 1.5
                stop_loss = current_price - risk_per_token

            position_tokens = allowed_risk_usd / risk_per_token
            position_value_usdt = position_tokens * current_price
            take_profit = current_price + (3 * risk_per_token)  # هدف 1:3 دقيق وصارم
            leverage = max(1, min(10, int(current_price / (risk_per_token * 2))))

            return {
                "Decision": "MARKET LONG 🟢 (SMC Structure)",
                "Symbol": symbol,
                "Entry": round(current_price, 4),
                "Stop Loss": round(stop_loss, 4),
                "Take Profit": round(take_profit, 4),
                "Position Size (USDT)": round(position_value_usdt, 2),
                "Leverage": leverage,
                "Reason": "تأكيد هيكلي صاعد (BOS/Order Block) مع حماية الوقف خلف القاع المؤسسي."
            }
        else:
            # صفقات البيع (Short) باستهداف الهيكل الهابط ومناطق الـ OB
            stop_loss = max(recent_swing_high + (0.5 * current_atr), current_price + (2.0 * current_atr))
            risk_per_token = stop_loss - current_price
            
            if risk_per_token <= 0:
                risk_per_token = current_atr * 1.5
                stop_loss = current_price + risk_per_token

            position_tokens = allowed_risk_usd / risk_per_token
            position_value_usdt = position_tokens * current_price
            take_profit = current_price - (3 * risk_per_token)  # هدف 1:3 دقيق وصارم
            leverage = max(1, min(10, int(current_price / (risk_per_token * 2))))

            return {
                "Decision": "MARKET SHORT 🔴 (SMC Structure)",
                "Symbol": symbol,
                "Entry": round(current_price, 4),
                "Stop Loss": round(stop_loss, 4),
                "Take Profit": round(take_profit, 4),
                "Position Size (USDT)": round(position_value_usdt, 2),
                "Leverage": leverage,
                "Reason": "تأكيد هيكلي هابط (BOS/Bearish OB) واصطياد السيولة البيعية."
            }
