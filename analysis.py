import ccxt
import pandas as pd
import numpy as np
import logging

# إعداد السجلات (Logging) للمتابعة الدقيقة
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SmartMoneyTradingAnalyst:
    def __init__(self, exchange_id='bingx', api_key='', secret_key=''):
        """
        تهيئة الاتصال بمنصة التداول عبر مكتبة CCXT لدعم العقود الآجلة (Swap)
        """
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

    # ==========================================
    # جلب بيانات الشموع الحية (OHLCV)
    # ==========================================
    def fetch_ohlcv_data(self, symbol='BTC/USDT:USDT', timeframe='1h', limit=150):
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            logger.error(f"خطأ أثناء جلب بيانات الشموع لـ {symbol} على فريم {timeframe}: {e}")
            return None

    # ==========================================
    # تحليل بنية السوق والاتجاه
    # ==========================================
    def analyze_market_structure(self, df):
        df['trend_ema_fast'] = df['close'].ewm(span=50, adjust=False).mean()
        df['trend_ema_slow'] = df['close'].ewm(span=200, adjust=False).mean()
        
        df['swing_high'] = df['high'].rolling(window=5).max()
        df['swing_low'] = df['low'].rolling(window=5).min()

        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        df['atr'] = np.max(ranges, axis=1).rolling(window=14).mean()

        return df

    # ==========================================
    # اتخاذ القرار الذكي وإدارة المخاطر (هدف واحد)
    # ==========================================
    def evaluate_strategy(self, symbol='BTC/USDT:USDT', account_balance=1000.0, risk_percentage=0.01):
        df = self.fetch_ohlcv_data(symbol, timeframe='1h', limit=150)
        if df is None or len(df) < 100:
            return {"Decision": "WAIT", "Reason": "البيانات المسترجعة غير كافية للتحليل الحي."}

        df = self.analyze_market_structure(df)
        
        last_closed = df.iloc[-2]
        current_price = df.iloc[-1]['close']
        current_atr = last_closed['atr']

        is_uptrend = last_closed['trend_ema_fast'] > last_closed['trend_ema_slow']
        is_downtrend = last_closed['trend_ema_fast'] < last_closed['trend_ema_slow']

        recent_swing_low = df['low'].iloc[-15:-2].min()
        recent_swing_high = df['high'].iloc[-15:-2].max()

        long_condition = is_uptrend and (current_price <= last_closed['trend_ema_fast'] * 1.015)
        short_condition = is_downtrend and (current_price >= last_closed['trend_ema_fast'] * 0.985)

        allowed_risk_usd = account_balance * risk_percentage

        if long_condition:
            stop_loss = min(recent_swing_low - (0.5 * current_atr), current_price - (2.5 * current_atr))
            risk_per_token = current_price - stop_loss
            
            if risk_per_token <= 0:
                return {"Decision": "WAIT", "Reason": "خطأ في حساب مسافة وقف الخسارة."}

            position_tokens = allowed_risk_usd / risk_per_token
            position_value_usdt = position_tokens * current_price
            take_profit = current_price + (3 * risk_per_token)  # هدف واحد (1:3)
            
            leverage = max(1, min(10, int(current_price / (risk_per_token * 2))))

            return {
                "Decision": "MARKET LONG 🟢",
                "Symbol": symbol,
                "Entry": round(current_price, 4),
                "Stop Loss": round(stop_loss, 4),
                "Take Profit": round(take_profit, 4),
                "Position Size (USDT)": round(position_value_usdt, 2),
                "Leverage": leverage,
                "Reason": f"اتجاه صاعد هيكلي مع ارتداد آمن من مناطق السيولة."
            }

        elif short_condition:
            stop_loss = max(recent_swing_high + (0.5 * current_atr), current_price + (2.5 * current_atr))
            risk_per_token = stop_loss - current_price
            
            if risk_per_token <= 0:
                return {"Decision": "WAIT", "Reason": "خطأ في حساب مسافة وقف الخسارة."}

            position_tokens = allowed_risk_usd / risk_per_token
            position_value_usdt = position_tokens * current_price
            take_profit = current_price - (3 * risk_per_token)  # هدف واحد (1:3)
            
            leverage = max(1, min(10, int(current_price / (risk_per_token * 2))))

            return {
                "Decision": "MARKET SHORT 🔴",
                "Symbol": symbol,
                "Entry": round(current_price, 4),
                "Stop Loss": round(stop_loss, 4),
                "Take Profit": round(take_profit, 4),
                "Position Size (USDT)": round(position_value_usdt, 2),
                "Leverage": leverage,
                "Reason": f"اتجاه هابط هيكلي مع رفض سعري عند قمة الهيكل."
            }

        return {
            "Decision": "WAIT ⏳",
            "Symbol": symbol,
            "Reason": "السوق في منطقة عرضية أو لم يلامس مناطق الهيكل المطلوبة."
        }
