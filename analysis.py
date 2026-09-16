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

    def analyze_ote_and_structure(self, df):
        """حساب مناطق الـ OTE (Optimal Trade Entry) وتصحيح الفيبوناتشي مع السيولة والـ ATR"""
        df['trend_ema'] = df['close'].ewm(span=50, adjust=False).mean()
        
        # حساب نطاق الحركة للـ ATR
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        df['atr'] = np.max(ranges, axis=1).rolling(window=14).mean()

        # إيجاد أعلى قمة وأدنى قاع في آخر 20 شمعة لقياس موجة الاندفاع (Impulse Wave)
        df['impulse_high'] = df['high'].rolling(window=20).max()
        df['impulse_low'] = df['low'].rolling(window=20).min()

        # مستويات الـ OTE (من 62% إلى 79% تصحيح من الموجة)
        diff = df['impulse_high'] - df['impulse_low']
        df['ote_long_zone'] = df['impulse_high'] - (diff * 0.786) # الحد الأدنى لمنطقة الديسكونت
        df['ote_long_max'] = df['impulse_high'] - (diff * 0.618)
        
        df['ote_short_zone'] = df['impulse_low'] + (diff * 0.786)
        df['ote_short_min'] = df['impulse_low'] + (diff * 0.618)

        return df

    def evaluate_strategy(self, symbol='BTC/USDT:USDT', account_balance=1000.0, risk_percentage=0.01):
        df = self.fetch_ohlcv_data(symbol, timeframe='1h', limit=150)
        if df is None or len(df) < 100:
            return {"Decision": "WAIT", "Reason": "البيانات المسترجعة غير كافية للتحليل الحي."}

        df = self.analyze_ote_and_structure(df)
        
        last_closed = df.iloc[-2]
        current_price = df.iloc[-1]['close']
        current_atr = last_closed['atr']
        allowed_risk_usd = account_balance * risk_percentage

        # شروط الـ OTE للصعود (Long): السعر يصحح لمنطقة الديسكونت (الـ OTE) مع ارتداد إيجابي
        in_long_ote = (current_price >= last_closed['ote_long_zone']) and (current_price <= last_closed['ote_long_max'])
        is_bullish_bias = current_price > last_closed['trend_ema']

        # شروط الـ OTE للهبوط (Short): السعر يصعد لمنطقة البريميوم (الـ OTE الهابطة) مع رفض
        in_short_ote = (current_price <= last_closed['ote_short_zone']) and (current_price >= last_closed['ote_short_min'])
        is_bearish_bias = current_price < last_closed['trend_ema']

        recent_swing_low = df['low'].iloc[-15:-2].min()
        recent_swing_high = df['high'].iloc[-15:-2].max()

        if in_long_ote and is_bullish_bias:
            stop_loss = min(recent_swing_low - (0.5 * current_atr), current_price - (2.0 * current_atr))
            risk_per_token = current_price - stop_loss
            
            if risk_per_token <= 0:
                return {"Decision": "WAIT", "Reason": "خطأ في حساب مسافة وقف الخسارة."}

            position_tokens = allowed_risk_usd / risk_per_token
            position_value_usdt = position_tokens * current_price
            take_profit = current_price + (3 * risk_per_token)  # هدف 1:3 احترافي
            leverage = max(1, min(10, int(current_price / (risk_per_token * 2))))

            return {
                "Decision": "MARKET LONG 🟢 (OTE/Discount)",
                "Symbol": symbol,
                "Entry": round(current_price, 4),
                "Stop Loss": round(stop_loss, 4),
                "Take Profit": round(take_profit, 4),
                "Position Size (USDT)": round(position_value_usdt, 2),
                "Leverage": leverage,
                "Reason": "ارتداد من منطقة الـ OTE التصحيحية (Discount) مع توافق الاتجاه الصاعد."
            }

        elif in_short_ote and is_bearish_bias:
            stop_loss = max(recent_swing_high + (0.5 * current_atr), current_price + (2.0 * current_atr))
            risk_per_token = stop_loss - current_price
            
            if risk_per_token <= 0:
                return {"Decision": "WAIT", "Reason": "خطأ في حساب مسافة وقف الخسارة."}

            position_tokens = allowed_risk_usd / risk_per_token
            position_value_usdt = position_tokens * current_price
            take_profit = current_price - (3 * risk_per_token)  # هدف 1:3 احترافي
            leverage = max(1, min(10, int(current_price / (risk_per_token * 2))))

            return {
                "Decision": "MARKET SHORT 🔴 (OTE/Premium)",
                "Symbol": symbol,
                "Entry": round(current_price, 4),
                "Stop Loss": round(stop_loss, 4),
                "Take Profit": round(take_profit, 4),
                "Position Size (USDT)": round(position_value_usdt, 2),
                "Leverage": leverage,
                "Reason": "رفض سعري من منطقة الـ OTE البيعية (Premium) مع توافق الاتجاه الهابط."
            }

        return {
            "Decision": "WAIT ⏳",
            "Symbol": symbol,
            "Reason": "السعر لم يصل بعد لمستويات الـ OTE المطلوبة (ننتظر التصحيح)."
        }
