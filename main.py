import os
import time
import requests
import pandas as pd
import numpy as np
from binance.um_futures import UMFutures

# بيانات التيليجرام والمنصة (تأكد إنها متظبطة في الـ Environment Variables على Render)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

client = UMFutures()

# قائمة العملات السريعة والمميزة إضافية (التي تتميز بالحركة القوية والسريعة للتداول اليومي)
SELECTED_WATCHLIST = [
    "SOLUSDT", "XRPUSDT", "DOGEUSDT", "PEPEUSDT", "SUIUSDT", 
    "NEARUSDT", "AVAXUSDT", "RENDERUSDT", "FETUSDT", "INJUSDT"
]

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials missing!")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Error sending telegram message: {e}")

def get_active_symbols():
    """دمج العملات الأكثر نشاطاً في السوق اليوم مع القائمة السريعة المحددة"""
    symbols_set = set(SELECTED_WATCHLIST)
    try:
        ticker_info = client.ticker_24hr_price_change()
        df = pd.DataFrame(ticker_info)
        df['quoteVolume'] = df['quoteVolume'].astype(float)
        
        # اختيار أعلى 15 عملة في الفوليوم اليومي
        usdt_pairs = df[df['symbol'].str.endswith('USDT')].copy()
        top_volume_coins = usdt_pairs.sort_values(by='quoteVolume', ascending=False).head(15)['symbol'].tolist()
        
        # دمج القائمتين لضمان عدم تفويت أي فرصة سريعة
        for sym in top_volume_coins:
            symbols_set.add(sym)
            
    except Exception as e:
        print(f"Error fetching top volume symbols: {e}")
        
    return list(symbols_set)

def analyze_market():
    symbols = get_active_symbols()
    print(f"Scanning {len(symbols)} active & watchlist symbols...")
    
    for symbol in symbols:
        try:
            # جلب الشمعات (فريم 1 ساعة للحركة السريعة والمدروسة)
            klines = client.klines(symbol=symbol, interval='1h', limit=50)
            df = pd.DataFrame(klines, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_asset_volume', 'n_trades',
                'taker_buy_base', 'taker_buy_quote', 'ignore'
            ])
            df['close'] = df['close'].astype(float)
            df['high'] = df['high'].astype(float)
            df['low'] = df['low'].astype(float)
            
            # حساب مؤشر القوة النسبية RSI
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            df['rsi'] = 100 - (100 / (1 + rs))
            
            current_price = df['close'].iloc[-1]
            current_rsi = df['rsi'].iloc[-1]
            
            # إشارة شراء (Long): تشبع بيعي RSI < 35 (فرصة ارتداد صاعد)
            if current_rsi < 35:
                tp = current_price * 1.015  # هدف سريع 1.5%
                sl = current_price * 0.990  # ستوب لص 1%
                msg = (
                    f"🟢 **فرصة صعود (LONG)** 🟢\n"
                    f"💎 العملة: `{symbol}`\n"
                    f"💵 السعر الحالي: `{current_price}`\n"
                    f"📊 مؤشر RSI: `{current_rsi:.2f}` (تشبع بيعي)\n"
                    f"🎯 الهدف المقترح: `{tp:.4f}`\n"
                    f"🛑 وقف الخسارة: `{sl:.4f}`\n"
                    f"💡 *مخصص برأس مال 3$ وهدف سريع*"
                )
                send_telegram_message(msg)
                time.sleep(2)

            # إشارة بيع (Short): تشبع شرائي RSI > 65 (فرصة هبوط وانعكاس)
            elif current_rsi > 65:
                tp = current_price * 0.985  # هدف هبوط سريع 1.5%
                sl = current_price * 1.010  # ستوب لص 1%
                msg = (
                    f"🔴 **فرصة هبوط (SHORT)** 🔴\n"
                    f"💎 العملة: `{symbol}`\n"
                    f"💵 السعر الحالي: `{current_price}`\n"
                    f"📊 مؤشر RSI: `{current_rsi:.2f}` (تشبع شرائي)\n"
                    f"🎯 الهدف المقترح: `{tp:.4f}`\n"
                    f"🛑 وقف الخسارة: `{sl:.4f}`\n"
                    f"💡 *مخصص برأس مال 3$ وهدف سريع*"
                )
                send_telegram_message(msg)
                time.sleep(2)
                
        except Exception as e:
            print(f"Error analyzing {symbol}: {e}")
            continue

if __name__ == "__main__":
    print("Bot started with Enhanced Watchlist & Auto-Scanner for Long/Short...")
    while True:
        analyze_market()
        # فحص السوق كل 15 دقيقة
        time.sleep(900)
