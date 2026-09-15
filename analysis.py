import ccxt
import pandas as pd
import numpy as np
import logging
import os
from flask import Flask

# إعداد السجلات (Logging) لمتابعة حالة البوت وعمليات الجلب والتحليل بدقة
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 🌐 إنشاء تطبيق Flask في البداية لتلبية متطلبات منصة Render لفتح المنفذ (Port) فوراً
app = Flask(__name__)

@app.route('/')
def home():
    return "Crypto Trading Bot is Running Successfully with Flask & Render."

class CryptoTradingBot:
    def __init__(self, exchange_id='bingx', api_key='', secret_key=''):
        """
        تهيئة اتصال المنصة باستخدام مكتبة CCXT مع تنظيف آمن للمفاتيح لمنع خطأ latin-1
        """
        if api_key and any(ord(c) > 127 for c in api_key):
            api_key = ""
        if secret_key and any(ord(c) > 127 for c in secret_key):
            secret_key = ""

        exchange_class = getattr(ccxt, exchange_id)
        
        self.exchange = exchange_class({
            'apiKey': api_key,
            'secret': secret_key,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'swap', # التداول العقود الآجلة (Futures / Swap)
            }
        })
        
        try:
            self.exchange.load_markets()
            logger.info(f"تم الاتصال بنجاح بمنصة {exchange_id.upper()} وتحميل الأسواق.")
        except Exception as e:
            logger.error(f"فشل الاتصال بالمنصة: {e}")

    def fetch_ohlcv_data(self, symbol='BTC/USDT:USDT', timeframe='4h', limit=100):
        """
        1. سحب بيانات الشموع الحية الحقيقية (OHLCV) من المنصة
        """
        try:
            logger.info(f"جاري سحب بيانات الشموع للزوج {symbol} على الفريم {timeframe}...")
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            logger.error(f"خطأ أثناء جلب بيانات الشموع لـ {symbol}: {e}")
            return None

    def calculate_indicators(self, df):
        """
        2. حساب المؤشرات الرياضية الحتمية (EMA 20, EMA 50, RSI 14, ATR 14)
        """
        df['ema_20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['ema_50'] = df['close'].ewm(span=50, adjust=False).mean()

        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / (loss + 1e-10)
        df['rsi'] = 100 - (100 / (1 + rs))

        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = np.max(ranges, axis=1)
        df['atr'] = true_range.rolling(window=14).mean()

        return df

    def evaluate_strategy(self, symbol='BTC/USDT:USDT', account_balance=1000.0, risk_percentage=0.01):
        """
        3 & 4. تنفيذ استراتيجية الدخول الصارمة وحساب إدارة المخاطر والرافعة المالية
        """
        df = self.fetch_ohlcv_data(symbol, timeframe='4h', limit=100)
        if df is None or len(df) < 60:
            logger.warning("البيانات المسترجعة غير كافية لإجراء التحليل الرياضي.")
            return {"Decision": "WAIT", "Reason": "بيانات غير كافية"}

        df = self.calculate_indicators(df)

        last_row = df.iloc[-2]
        current_price = df.iloc[-1]['close']

        logger.info(f"تحليل {symbol} -> السعر الحالي: {current_price} | EMA20: {last_row['ema_20']:.4f} | EMA50: {last_row['ema_50']:.4f} | RSI: {last_row['rsi']:.2f} | ATR: {last_row['atr']:.4f}")

        long_condition = (last_row['ema_20'] > last_row['ema_50']) and (last_row['rsi'] < 40)
        short_condition = (last_row['ema_20'] < last_row['ema_50']) and (last_row['rsi'] > 60)

        if long_condition:
            stop_loss = current_price - (2 * last_row['atr'])
            take_profit = current_price + (4 * last_row['atr'])
            risk_per_token = current_price - stop_loss
            
            allowed_risk_amount = account_balance * risk_percentage
            position_size_tokens = allowed_risk_amount / risk_per_token if risk_per_token > 0 else 0
            position_size_usdt = position_size_tokens * current_price

            calculated_leverage = int(current_price / (risk_per_token * 2)) if risk_per_token > 0 else 1
            safe_leverage = max(1, min(10, calculated_leverage))

            return {
                "Decision": "MARKET LONG",
                "Symbol": symbol,
                "Entry Price": current_price,
                "Stop Loss": round(stop_loss, 4),
                "Take Profit": round(take_profit, 4),
                "Position Size (Tokens)": round(position_size_tokens, 4),
                "Position Size (USDT)": round(position_size_usdt, 2),
                "Safe Leverage": safe_leverage
            }

        elif short_condition:
            stop_loss = current_price + (2 * last_row['atr'])
            take_profit = current_price - (4 * last_row['atr'])
            risk_per_token = stop_loss - current_price
            
            allowed_risk_amount = account_balance * risk_percentage
            position_size_tokens = allowed_risk_amount / risk_per_token if risk_per_token > 0 else 0
            position_size_usdt = position_size_tokens * current_price

            calculated_leverage = int(current_price / (risk_per_token * 2)) if risk_per_token > 0 else 1
            safe_leverage = max(1, min(10, calculated_leverage))

            return {
                "Decision": "MARKET SHORT",
                "Symbol": symbol,
                "Entry Price": current_price,
                "Stop Loss": round(stop_loss, 4),
                "Take Profit": round(take_profit, 4),
                "Position Size (Tokens)": round(position_size_tokens, 4),
                "Position Size (USDT)": round(position_size_usdt, 2),
                "Safe Leverage": safe_leverage
            }

        return {
            "Decision": "WAIT",
            "Symbol": symbol,
            "Reason": "الشروط الرياضية الحتمية لم تتحقق بالكامل (لا توجد فرصة آمنة حالياً)"
        }

# ==========================================
# تشغيل البوت وخادم الويب لمنصة Render
# ==========================================
if __name__ == "__main__":
    API_KEY = os.getenv("API_KEY", "")
    SECRET_KEY = os.getenv("SECRET_KEY", "")

    bot = CryptoTradingBot(exchange_id='bingx', api_key=API_KEY, secret_key=SECRET_KEY)

    target_symbol = 'BTC/USDT:USDT'
    virtual_account_balance = 1000.0 

    signal_result = bot.evaluate_strategy(symbol=target_symbol, account_balance=virtual_account_balance, risk_percentage=0.01)

    print("\n==========================================")
    print("       تقرير التحليل الرياضي الحتمي للبوت     ")
    print("==========================================")
    for key, value in signal_result.items():
        print(f"• {key}: {value}")
    print("==========================================")

    # تشغيل سيرفر الويب على المنفذ المطلوب لضمان نجاح النشر على Render
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
