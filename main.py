import ccxt
import pandas as pd
import numpy as np
import logging
import os
from flask import Flask

# 1. إعداد نظام السجلات (Logging) للمتابعة الدقيقة
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 🌐 2. إنشاء تطبيق الويب (Flask) لإرضاء منصة Render وفتح المنفذ المطلوب
app = Flask(__name__)

@app.route('/')
def home():
    """صفحة رئيسية للتأكد أن السيرفر يعمل على Render"""
    # تنفيذ تحليل فوري عند زيارة الرابط للاختبار
    analysis = bot_engine.evaluate_strategy(symbol='BTC/USDT:USDT', account_balance=1000.0, risk_percentage=0.01)
    return f"Deterministic Crypto Trading Bot is Active! <br><br> Latest Analysis Status: {analysis}"


class DeterministicTradingBot:
    def __init__(self, exchange_id='bingx', api_key='', secret_key=''):
        """
        تهيئة الاتصال بمنصة التداول (BingX أو Binance) عبر مكتبة CCXT
        """
        exchange_class = getattr(ccxt, exchange_id)
        self.exchange = exchange_class({
            'apiKey': api_key,
            'secret': secret_key,
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}  # التعامل مع عقود الهامش والـ Futures
        })
        try:
            self.exchange.load_markets()
            logger.info(f"تم الاتصال بنجاح بمنصة {exchange_id.upper()} وتحميل أسواق الـ Swap.")
        except Exception as e:
            logger.error(f"فشل الاتصال بالمنصة: {e}")

    # ==========================================
    # الخطوة 1: جلب بيانات الشموع الحية (OHLCV)
    # ==========================================
    def fetch_ohlcv_data(self, symbol='BTC/USDT:USDT', timeframe='4h', limit=100):
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            logger.error(f"خطأ أثناء جلب بيانات الشموع لـ {symbol} على فريم {timeframe}: {e}")
            return None

    # ==========================================
    # الخطوة 2: حساب المؤشرات الرياضية الحتمية
    # ==========================================
    def calculate_indicators(self, df):
        # المتوسطات المتحركة الأسية (EMA 20 & EMA 50)
        df['ema_20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['ema_50'] = df['close'].ewm(span=50, adjust=False).mean()

        # مؤشر القوة النسبية (RSI 14)
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / (loss + 1e-10)
        df['rsi'] = 100 - (100 / (1 + rs))

        # متوسط المدى الحقيقي (ATR 14) لقياس التذبذب
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        df['atr'] = np.max(ranges, axis=1).rolling(window=14).mean()

        return df

    # ==========================================
    # الخطوة 3 & 4: اتخاذ القرار وإدارة المخاطر الصارمة
    # ==========================================
    def evaluate_strategy(self, symbol='BTC/USDT:USDT', account_balance=1000.0, risk_percentage=0.01):
        df_4h = self.fetch_ohlcv_data(symbol, timeframe='4h', limit=100)
        if df_4h is None or len(df_4h) < 60:
            return {"Decision": "WAIT", "Reason": "البيانات المسترجعة غير كافية للتحليل."}

        df_4h = self.calculate_indicators(df_4h)
        
        last_closed = df_4h.iloc[-2]
        current_price = df_4h.iloc[-1]['close']
        current_atr = last_closed['atr']

        ema_20 = last_closed['ema_20']
        ema_50 = last_closed['ema_50']
        rsi_val = last_closed['rsi']

        # الشروط الرياضية الحتمية للاتجاه
        long_condition = (ema_20 > ema_50) and (rsi_val < 40)
        short_condition = (ema_20 < ema_50) and (rsi_val > 60)

        # إدارة المخاطر: 1% من إجمالي المحفظة
        allowed_risk_usd = account_balance * risk_percentage

        if long_condition:
            stop_loss = current_price - (2 * current_atr)
            risk_per_token = current_price - stop_loss
            
            if risk_per_token <= 0:
                return {"Decision": "WAIT", "Reason": "خطأ في حساب مسافة وقف الخسارة."}

            position_tokens = allowed_risk_usd / risk_per_token
            position_value_usdt = position_tokens * current_price
            take_profit = current_price + (4 * current_atr)  # نسبة Risk:Reward = 1:2
            
            # سقف الرافعة المالية بحيث لا تتجاوز 10x تحت أي ظرف
            leverage = max(1, min(10, int(current_price / (risk_per_token * 2))))

            return {
                "Decision": "MARKET LONG 🟢",
                "Symbol": symbol,
                "Entry": round(current_price, 4),
                "Stop Loss": round(stop_loss, 4),
                "Take Profit": round(take_profit, 4),
                "Position Size (USDT)": round(position_value_usdt, 2),
                "Leverage": leverage,
                "Reason": f"EMA20 ({ema_20:.2f}) > EMA50 ({ema_50:.2f}) و RSI ({rsi_val:.2f}) < 40"
            }

        elif short_condition:
            stop_loss = current_price + (2 * current_atr)
            risk_per_token = stop_loss - current_price
            
            if risk_per_token <= 0:
                return {"Decision": "WAIT", "Reason": "خطأ في حساب مسافة وقف الخسارة."}

            position_tokens = allowed_risk_usd / risk_per_token
            position_value_usdt = position_tokens * current_price
            take_profit = current_price - (4 * current_atr)  # نسبة Risk:Reward = 1:2
            
            # سقف الرافعة المالية بحيث لا تتجاوز 10x
            leverage = max(1, min(10, int(current_price / (risk_per_token * 2))))

            return {
                "Decision": "MARKET SHORT 🔴",
                "Symbol": symbol,
                "Entry": round(current_price, 4),
                "Stop Loss": round(stop_loss, 4),
                "Take Profit": round(take_profit, 4),
                "Position Size (USDT)": round(position_value_usdt, 2),
                "Leverage": leverage,
                "Reason": f"EMA20 ({ema_20:.2f}) < EMA50 ({ema_50:.2f}) و RSI ({rsi_val:.2f}) > 60"
            }

        return {
            "Decision": "WAIT ⏳",
            "Symbol": symbol,
            "Reason": "الشروط الحتمية لم تتحقق بالكامل (السوق في حالة حيادية)."
        }

# ==========================================
# تهيئة محرك البوت وسحب المفاتيح بأمان
# ==========================================
API_KEY = os.getenv("API_KEY", "")
SECRET_KEY = os.getenv("SECRET_KEY", "")

bot_engine = DeterministicTradingBot(exchange_id='bingx', api_key=API_KEY, secret_key=SECRET_KEY)

# ==========================================
# تشغيل السيرفر الرئيسي وخادم الويب لـ Render
# ==========================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
