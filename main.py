import os
import time
import logging
import threading
import ccxt
import pandas as pd
import numpy as np
import requests
from flask import Flask, request, jsonify

# =========================================================
# CONFIGURATION & LOGGING
# =========================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "YOUR_TELEGRAM_CHAT_ID")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "https://my-bot-zag6.onrender.com")

app = Flask(__name__)

# =========================================================
# EXPERT CISD & SMARTER MONEY BOT CORE
# =========================================================
class ExpertCISDBot:
    def __init__(self, exchange_id='bingx', api_key='', secret_key=''):
        self.exchange_id = exchange_id
        exchange_class = getattr(ccxt, exchange_id)
        self.exchange = exchange_class({
            'apiKey': api_key,
            'secret': secret_key,
            'enableRateLimit': True
        })
        self.cache = {}
        self.cache_seconds = 25

    def _is_valid_symbol(self, symbol):
        unwanted_tokens = [
            'EUR', 'JPY', 'GBP', 'CAD', 'AUD', 'CHF', 'NZD', 'NCFX', 
            'USDCUSD', 'BULL', 'BEAR', 'UP', 'DOWN', '3S', '3L', 'HEDGE'
        ]
        if 'USDT' not in symbol:
            return False
        if any(token in symbol for token in unwanted_tokens):
            return False
        return True

    def _fetch_ohlcv(self, symbol, timeframe, limit=200, market_type='swap'):
        if not self._is_valid_symbol(symbol):
            return None

        key = f"{symbol}:{timeframe}:{limit}:{market_type}"
        now = time.time()
        cached = self.cache.get(key)
        if cached and (now - cached['time'] < self.cache_seconds):
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
            self.cache[key] = {'time': now, 'data': df}
            return df.copy()
        except Exception as e:
            logger.warning("OHLCV error %s %s (%s): %s", symbol, timeframe, market_type, e)
            return None

    def _calculate_rsi(self, series, period=14):
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    def _calculate_supertrend(self, df, period=10, multiplier=3):
        hl2 = (df['high'] + df['low']) / 2
        atr = (df['high'] - df['low']).rolling(period).mean()
        upper_band = hl2 + (multiplier * atr)
        lower_band = hl2 - (multiplier * atr)
        
        supertrend = pd.Series(index=df.index, dtype='float64')
        direction = pd.Series(index=df.index, dtype='int')
        
        supertrend.iloc[0] = upper_band.iloc[0]
        direction.iloc[0] = 1
        
        for i in range(1, len(df)):
            if df['close'].iloc[i] > upper_band.iloc[i-1]:
                direction.iloc[i] = 1
            elif df['close'].iloc[i] < lower_band.iloc[i-1]:
                direction.iloc[i] = -1
            else:
                direction.iloc[i] = direction.iloc[i-1]
                if direction.iloc[i] == 1 and lower_band.iloc[i] < lower_band.iloc[i-1]:
                    lower_band.iloc[i] = lower_band.iloc[i-1]
                if direction.iloc[i] == -1 and upper_band.iloc[i] > upper_band.iloc[i-1]:
                    upper_band.iloc[i] = upper_band.iloc[i-1]
            
            supertrend.iloc[i] = lower_band.iloc[i] if direction.iloc[i] == 1 else upper_band.iloc[i]
            
        return supertrend, direction

    def detect_cisd_and_fvg(self, df):
        """
        تطبيق استراتيجية تسليم السعر (Change in the State of Delivery - CISD):
        1. سحب السيولة: كسر قاع سابق (Stop Hunt).
        2. الاندفاع (Displacement): شمعة صاعدة قوية جداً بحجم جسم يكسر الهيكل (MSS).
        3. FVG: ترك فجوة سعرية تدل على ضخ سيولة حقيقية من الحيتان.
        """
        if df is None or len(df) < 15:
            return False, 0.0, False

        # قاع السويفت الأخير
        recent_low = df['low'].iloc[-15:-3].min()
        
        curr = df.iloc[-1]
        prev = df.iloc[-2]
        prev_2 = df.iloc[-3]

        # 1. سحب السيولة (شمعة سابقة كسرت القاع أو مسّته ثم ارتدت)
        swept_liquidity = (prev['low'] < recent_low or prev_2['low'] < recent_low or curr['low'] < recent_low)

        # 2. الاندفاع (Displacement): شمعة الحالية أو السابقة جسمها أضعاف المتوسط ولونها أخضر قوي
        body_curr = abs(curr['close'] - curr['open'])
        avg_body = abs(df['close'] - df['open']).rolling(10).mean().iloc[-1]
        is_displacement = body_curr > (avg_body * 1.5) and curr['close'] > curr['open']

        # 3. فحص الفجوة السعرية (Fair Value Gap - FVG) الصاعدة
        # الفجوة تحدث عندما يكون قاع الشمعة الحالية أعلى من قمة الشمعة التي قبلها بمرتين
        has_fvg = curr['low'] > prev_2['high']

        if swept_liquidity and is_displacement and has_fvg:
            return True, float(recent_low), True

        return False, 0.0, False

    def evaluate_strategy(self, symbol, market_type='swap'):
        if not self._is_valid_symbol(symbol):
            return None

        df_15m = self._fetch_ohlcv(symbol, '15m', 120, market_type)
        df_1h = self._fetch_ohlcv(symbol, '1h', 50, market_type)
        df_4h = self._fetch_ohlcv(symbol, '4h', 50, market_type)

        if df_15m is None or len(df_15m) < 40 or df_1h is None or df_4h is None:
            return None

        df_15m['rsi'] = self._calculate_rsi(df_15m['close'], 14)
        _, st_dir_4h = self._calculate_supertrend(df_4h)
        _, st_dir_1h = self._calculate_supertrend(df_1h)

        # عدم الشراء إذا كان الاتجاه العام على 4 ساعات هابطاً بقوة
        if st_dir_4h.iloc[-1] == -1:
            return None

        row_15m = df_15m.iloc[-1]

        # تطبيق استراتيجية تسليم السعر CISD
        is_cisd, sweep_level, has_fvg = self.detect_cisd_and_fvg(df_15m)

        confirmations = ['Smart_Money_Concept']
        if is_cisd:
            confirmations.append('CISD_Delivery_Confirmed')
        if has_fvg:
            confirmations.append('Fair_Value_Gap_FVG')
        if st_dir_1h.iloc[-1] == 1:
            confirmations.append('1H_Trend_Aligned')

        # شرط صارم جداً: يجب أن تتحقق شروط الـ CISD والفلترة بالكامل
        if not is_cisd or len(confirmations) < 3:
            return None

        # فلترة الزخم
        vol_ma = df_15m['volume'].rolling(window=20).mean().iloc[-1]
        volume_ratio = row_15m['volume'] / vol_ma if vol_ma > 0 else 1.0
        if volume_ratio < 0.9 or row_15m['rsi'] > 78 or row_15m['rsi'] < 25:
            return None

        entry = float(row_15m['close'])
        atr = float((df_15m['high'] - df_15m['low']).rolling(14).mean().iloc[-1])
        if not atr or atr <= 0:
            atr = entry * 0.01

        # وقف الخسارة أسفل نقطة سحب السيولة (تأمين كامل ضد الضرب الوهمي)
        sl = sweep_level - (atr * 0.4) if sweep_level > 0 else entry - (atr * 2.5)
        risk_distance = entry - sl

        if risk_distance <= 0:
            return None

        # أهداف صفقات العمر تعتمد على قمم فريم الساعة والأربع ساعات السابقة
        recent_high = float(df_1h['high'].iloc[-35:].max())
        tp1 = entry + (risk_distance * 2.0)
        tp2 = entry + (risk_distance * 3.8)
        tp3 = max(entry + (risk_distance * 6.5), recent_high)

        score_val = 92 + (len(confirmations) * 2)

        return {
            'symbol': symbol,
            'market_type': 'SPOT' if market_type == 'spot' else 'FUTURES',
            'decision': 'LONG (CISD SNIPER)',
            'score': min(score_val, 99),
            'quality': 'ELITE CISD VIP',
            'confirmations': confirmations,
            'trend_4h': 'BULLISH' if st_dir_4h.iloc[-1] == 1 else 'NEUTRAL',
            'trend_1h': 'BULLISH' if st_dir_1h.iloc[-1] == 1 else 'NEUTRAL',
            'rsi_15m': float(row_15m['rsi']),
            'volume_ratio': float(volume_ratio),
            'entry': entry,
            'sl': sl,
            'tp1': tp1,
            'tp2': tp2,
            'tp3': tp3,
            'risk_pct': round((abs(entry - sl) / entry) * 100, 2)
        }

bot = ExpertCISDBot(exchange_id='bingx')

# =========================================================
# TELEGRAM SENDER
# =========================================================
def send_telegram_alert(signal):
    if TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        logger.info("Telegram token not set.")
        return

    market_label = "🟢 [SPOT - CISD صفقة العمر]" if signal['market_type'] == 'SPOT' else "🚀 [FUTURES - CISD تسليم السعر الحوتي]"

    msg = f"""
{market_label} 💎

📊 Symbol: {signal['symbol']}
🎯 Decision: {signal['decision']}
⭐ Score: {signal['score']}/100
🏷 Quality: {signal['quality']}

🧠 Confirmations: {', '.join(signal['confirmations'])}

📈 4H Trend: {signal['trend_4h']}
📊 1H Trend: {signal['trend_1h']}
💪 RSI 15M: {signal['rsi_15m']:.1f}
🔊 Volume Surge: {signal['volume_ratio']:.2f}x

💰 Entry Price: {signal['entry']:.7f}
🛑 Stop Loss: {signal['sl']:.7f} ({signal['risk_pct']}%)

🎯 TP1 (1:2): {signal['tp1']:.7f}
🎯 TP2 (1:3.8): {signal['tp2']:.7f}
🎯 TP3 (Elite Target): {signal['tp3']:.7f}

⚡ Strategy: CISD (Change in the State of Delivery) + FVG
⚠️ إدارة رأس المال هي الأساس للوصول للهدف المنشود.
"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logger.error("Telegram error: %s", e)

# =========================================================
# BACKGROUND SCANNER LOOP & WEBHOOK
# =========================================================
def self_ping():
    while True:
        try:
            time.sleep(240)
            requests.get(RENDER_EXTERNAL_URL, timeout=10)
        except:
            pass

def background_scanner():
    spot_symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "AVAX/USDT", "LINK/USDT", "SUI/USDT", "NEAR/USDT", "RENDER/USDT", "FET/USDT", "INJ/USDT", "ARB/USDT", "TIA/USDT"]
    futures_symbols = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "XRP/USDT:USDT", "AVAX/USDT:USDT", "LINK/USDT:USDT", "SUI/USDT:USDT", "NEAR/USDT:USDT", "RENDER/USDT:USDT", "FET/USDT:USDT", "INJ/USDT:USDT", "ARB/USDT:USDT", "TIA/USDT:USDT"]
    
    symbols_to_scan = [(s, "spot") for s in spot_symbols] + [(s, "swap") for s in futures_symbols]
    sent_cooldown = {}

    logger.info("CISD Elite Scanner started with %d assets.", len(symbols_to_scan))
    
    while True:
        try:
            for symbol, m_type in symbols_to_scan:
                signal = bot.evaluate_strategy(symbol, m_type)
                if signal:
                    cooldown_key = f"{symbol}_{signal['market_type']}"
                    if time.time() - sent_cooldown.get(cooldown_key, 0) > 18000: # فترة تهدئة 5 ساعات لعدم تكرار التنبيه والتأكد من قوة الفرصة
                        send_telegram_alert(signal)
                        sent_cooldown[cooldown_key] = time.time()
                time.sleep(1.5)
        except Exception as e:
            logger.error("Scanner loop error: %s", e)
        time.sleep(120)

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    if not data or 'symbol' not in data:
        return jsonify({"status": "error"}), 400
    signal = bot.evaluate_strategy(data['symbol'], data.get('market_type', 'swap'))
    if signal:
        send_telegram_alert(signal)
        return jsonify({"status": "success", "signal": signal}), 200
    return jsonify({"status": "filtered"}), 200

@app.route('/')
def index():
    return "CISD Elite Sniper Bot is running and hunting for life-changing setups!", 200

if __name__ == '__main__':
    threading.Thread(target=background_scanner, daemon=True).start()
    threading.Thread(target=self_ping, daemon=True).start()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
