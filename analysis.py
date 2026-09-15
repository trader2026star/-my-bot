import ccxt
import pandas as pd
import numpy as np
import logging
import os
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler

# إعداد السجلات (Logging)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 🌐 إنشاء تطبيق الويب لإرضاء منصة Render وفتح المنفذ المطلوبة
app = Flask(__name__)

@app.route('/')
def home():
    return "Crypto Trading Bot with Telegram & Render is Active."

class CryptoTradingBot:
    def __init__(self, exchange_id='bingx', api_key='', secret_key=''):
        if api_key and any(ord(c) > 127 for c in api_key):
            api_key = ""
        if secret_key and any(ord(c) > 127 for c in secret_key):
            secret_key = ""

        exchange_class = getattr(ccxt, exchange_id)
        self.exchange = exchange_class({
            'apiKey': api_key,
            'secret': secret_key,
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        })
        try:
            self.exchange.load_markets()
            logger.info(f"تم الاتصال بنجاح بمنصة {exchange_id.upper()} وتحميل الأسواق.")
        except Exception as e:
            logger.error(f"فشل الاتصال بالمنصة: {e}")

    def fetch_ohlcv_data(self, symbol='BTC/USDT:USDT', timeframe='4h', limit=100):
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            logger.error(f"خطأ أثناء جلب بيانات الشموع لـ {symbol}: {e}")
            return None

    def calculate_indicators(self, df):
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
        df['atr'] = np.max(ranges, axis=1).rolling(window=14).mean()

        return df

    def evaluate_strategy(self, symbol='BTC/USDT:USDT', account_balance=1000.0, risk_percentage=0.01):
        df = self.fetch_ohlcv_data(symbol, timeframe='4h', limit=100)
        if df is None or len(df) < 60:
            return {"Decision": "WAIT", "Reason": "البيانات المسترجعة غير كافية للتحليل."}

        df = self.calculate_indicators(df)
        last_row = df.iloc[-2]
        current_price = df.iloc[-1]['close']

        long_condition = (last_row['ema_20'] > last_row['ema_50']) and (last_row['rsi'] < 40)
        short_condition = (last_row['ema_20'] < last_row['ema_50']) and (last_row['rsi'] > 60)

        if long_condition:
            stop_loss = current_price - (2 * last_row['atr'])
            take_profit = current_price + (4 * last_row['atr'])
            risk_per_token = current_price - stop_loss
            allowed_risk = account_balance * risk_percentage
            pos_tokens = allowed_risk / risk_per_token if risk_per_token > 0 else 0
            leverage = max(1, min(10, int(current_price / (risk_per_token * 2)) if risk_per_token > 0 else 1))

            return {
                "Decision": "MARKET LONG 🟢",
                "Symbol": symbol,
                "Entry": current_price,
                "SL": round(stop_loss, 4),
                "TP": round(take_profit, 4),
                "Size USDT": round(pos_tokens * current_price, 2),
                "Leverage": leverage
            }

        elif short_condition:
            stop_loss = current_price + (2 * last_row['atr'])
            take_profit = current_price - (4 * last_row['atr'])
            risk_per_token = stop_loss - current_price
            allowed_risk = account_balance * risk_percentage
            pos_tokens = allowed_risk / risk_per_token if risk_per_token > 0 else 0
            leverage = max(1, min(10, int(current_price / (risk_per_token * 2)) if risk_per_token > 0 else 1))

            return {
                "Decision": "MARKET SHORT 🔴",
                "Symbol": symbol,
                "Entry": current_price,
                "SL": round(stop_loss, 4),
                "TP": round(take_profit, 4),
                "Size USDT": round(pos_tokens * current_price, 2),
                "Leverage": leverage
            }

        return {
            "Decision": "WAIT ⏳",
            "Symbol": symbol,
            "Reason": "الشروط الرياضية الحتمية لم تتحقق بالكامل (لا توجد فرصة آمنة حالياً)"
        }

# تهيئة البوت العام
bot_engine = CryptoTradingBot(exchange_id='bingx', api_key=os.getenv("API_KEY", ""), secret_key=os.getenv("SECRET_KEY", ""))

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """الرد على أمر البدء"""
    await update.message.reply_text(
        "مرحباً بك! أنا بوت التداول الآلي والتحليل الرياضي (SMC/EMA/RSI).\n"
        "أرسل الأمر /analyze لفحص زوج BTC/USDT حالياً."
    )

async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تنفيذ التحليل الفوري عند إرسال الأمر من تيليجرام"""
    await update.message.reply_text("جاري جلب البيانات الفورية وإجراء التحليل الرياضي الحتمي على فريم 4H...")
    
    result = bot_engine.evaluate_strategy(symbol='BTC/USDT:USDT', account_balance=1000.0, risk_percentage=0.01)
    
    report = "📊 *تقرير التحليل الرياضي الحتمي*\n\n"
    for key, value in result.items():
        report += f"• *{key}*: `{value}`\n"
        
    await update.message.reply_text(report, parse_mode='Markdown')

def run_telegram_bot():
    """تشغيل مستمع تيليجرام"""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        logger.warning("مفتاح تيليجرام (TELEGRAM_BOT_TOKEN) غير متوفر في متغيرات البيئة.")
        return
    
    app_tg = ApplicationBuilder().token(token).build()
    app_tg.add_handler(CommandHandler("start", start_command))
    app_tg.add_handler(CommandHandler("analyze", analyze_command))
    
    logger.info("تم البدء بالاستماع لرسائل تيليجرام بنجاح...")
    app_tg.run_polling()

if __name__ == "__main__":
    # تشغيل بوت تيليجرام في خلفية السكربت أو بالتوازي مع الويب
    import threading
    tg_thread = threading.Thread(target=run_telegram_bot)
    tg_thread.daemon = True
    tg_thread.start()

    # تشغيل سيرفر الويب لالتقاط المنفذ المطلوب من Render
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
