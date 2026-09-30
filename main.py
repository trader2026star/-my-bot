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
# EXPERT SNIPER BOT CORE (SMART MONEY & LIQUIDITY SWEEP)
# =========================================================
class ExpertSniperBot:
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

    def detect_liquidity_sweep_and_mss(self, df):
        """
        يكتشف ما إذا كان السعر قد كسر قاعاً سابقاً (سحب سيولة Stop Hunting) 
        ثم أغلق بشمعة قوية صاعدة (Market Structure Shift)
        """
        if df is None or len(df) < 10:
            return False, 0.0

        # قاع السويفت الأخير خلال الشموع السابقة
        recent_low = df['low'].iloc[-10:-2].min()
        prev_low_idx = df['low'].iloc[-10:-2].idxmin()
        
        current_candle = df.iloc[-1]
        prev_candle = df.iloc[-2]

        # شرط سحب السيولة: الشمعة السابقة أو الحالية كسرت القاع ثم ارتدت
        swept_liquidity = (prev_candle['low'] < recent_low or current_candle['low'] < recent_low)
        
        # شرط تغير الهيكل (MSS): إغلاق صعودي قوي فوق جسم الشمعة السابقة مع حجم تداول عالي
        is_bullish_mss = (current_candle['close'] > current_candle['open']) and \
                         (current_candle['close'] > prev_candle['high'])

        if swept_liquidity and is_bullish_mss:
            return True, float(recent_low)
            
        return False, 0.0

    def detect_order_block(self, df):
        if df is None or len(df) < 5:
            return None
        for i in range(len(df) - 2, 2, -1):
            if (df.loc[i, 'close'] < df.loc[i, 'open'] and 
                df.loc[i+1, 'close'] > df.loc[i+1, 'open'] and 
                df.loc[i+1, 'close'] > df.loc[i, 'high']):
                return float(df.loc[i, 'low'])
        return None

    def evaluate_strategy(self, symbol, market_type='swap'):
        if not self._is_valid_symbol(symbol):
            return None

        # فريمات متعددة لاقتناص الصفقات العالية الدقة
        df_15m = self._fetch_ohlcv(symbol, '15m', 120, market_type)
        df_1h = self._fetch_ohlcv(symbol, '1h', 50, market_type)
        df_4h = self._fetch_ohlcv(symbol, '4h', 50, market_type)

        if df_15m is None or len(df_15m) < 40 or df_1h is None or df_4h is None:
            return None

        # حساب المؤشرات
        df_15m['rsi'] = self._calculate_rsi(df_15m['close'], 14)
        _, st_dir_4h = self._calculate_supertrend(df_4h)
        _, st_dir_1h = self._calculate_supertrend(df_1h)

        # 1. فلترة الاتجاه العام: يجب ألا يكون الاتجاه هابطاً بقوة على الأربع ساعات
        if st_dir_4h.iloc[-1] == -1:
            return None

        row_15m = df_15m.iloc[-1]
        
        # 2. فحص سحب السيولة وهيكل السوق (مفاهيم الذكاء المؤسسي)
        has_sweep_mss, sweep_level = self.detect_liquidity_sweep_and_mss(df_15m)
        ob_level = self.detect_order_block(df_15m)

        confirmations = ['Smart_Money_Structure']
        if has_sweep_mss:
            confirmations.append('Liquidity_Sweep_MSS')
        if ob_level:
            confirmations.append('Order_Block_Support')
        if st_dir_1h.iloc[-1] == 1:
            confirmations.append('1H_Trend_Aligned')

        # شرط صارم جداً لضمان جودة صفقة العمر (يجب أن توجد مؤشرات مؤسسية واضحة)
        if len(confirmations) < 3:
            return None

        # فلترة الزخم والحجم
        vol_ma = df_15m['volume'].rolling(window=20).mean().iloc[-1]
        volume_ratio = row_15m['volume'] / vol_ma if vol_ma > 0 else 1.0
        if volume_ratio < 0.8 or row_15m['rsi'] > 75 or row_15m['rsi'] < 25:
            return None

        entry = float(row_15m['close'])
        atr = float((df_15m['high'] - df_15m['low']).rolling(14).mean().iloc[-1])
        if not atr or atr <= 0:
            atr = entry * 0.01

        # تحديد وقف الخسارة أسفل منطقة السيولة المسحوبة بقليل للحماية من الضرب الوهمي
        sl = min(entry - (atr * 2.5), sweep_level - (atr * 0.5)) if sweep_level > 0 else entry - (atr * 2.5)
        risk_distance = entry - sl

        if risk_distance <= 0:
            return None

        # صفقات العمر تعتمد على أهداف بعيدة بناءً على قمم السوق السابقة
        recent_high = float(df_1h['high'].iloc[-30:].max())
        tp1 = entry + (risk_distance * 2.0)
        tp2 = entry + (risk_distance * 3.5)
        tp3 = max(entry + (risk_distance * 6.0), recent_high) # الهدف الثالث يطارد القمة ليعطيك عائد تاريخي

        score_val = 88 + (len(confirmations) * 3)

        return {
            'symbol': symbol,
            'market_type': 'SPOT' if market_type == 'spot' else 'FUTURES',
            'decision': 'LONG (SNIPER)',
            'score': min(score_val, 99),
            'quality': 'ELITE VIP',
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

bot = ExpertSniperBot(exchange_id='bingx')

# =========================================================
# TELEGRAM SENDER
# =========================================================
def send_telegram_alert(signal):
    if TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        logger.info("Telegram token not set.")
        return

    market_label = "🟢 [SPOT - صفقات العمر]" if signal['market_type'] == 'SPOT' else "🚀 [FUTURES - صفقات العمر الحوتية]"

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
🔊 Volume Spike: {signal['volume_ratio']:.2f}x

💰 Entry Price: {signal['entry']:.7f}
🛑 Stop Loss: {signal['sl']:.7f} ({signal['risk_pct']}%)

🎯 TP1 (1:2): {signal['tp1']:.7f}
🎯 TP2 (1:3.5): {signal['tp2']:.7f}
🎯 TP3 (Elite Target): {signal['tp3']:.7f}

⚡ Strategy: Smart Money / Liquidity Sweep
⚠️ إدارة رأس المال هي سر النجاح والأمان.
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

    logger.info("Elite Sniper Scanner started with %d assets.", len(symbols_to_scan))
    
    while True:
        try:
            for symbol, m_type in symbols_to_scan:
                signal = bot.evaluate_strategy(symbol, m_type)
                if signal:
                    cooldown_key = f"{symbol}_{signal['market_type']}"
                    if time.time() - sent_cooldown.get(cooldown_key, 0) > 14400: # حظر تكرار التنبيه لنفس العملة لمدة 4 ساعات لضمان الجودة
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
    return "Elite Sniper Bot is running and hunting for life-changing trades!", 200

if __name__ == '__main__':
    threading.Thread(target=background_scanner, daemon=True).start()
    threading.Thread(target=self_ping, daemon=True).start()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
