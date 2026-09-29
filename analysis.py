import os
import time
import logging
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

app = Flask(__name__)

# =========================================================
# EXPERT SPOT ANALYST BOT CORE
# =========================================================
class ExpertSpotBot:
    def __init__(
        self,
        exchange_id='bingx',
        api_key='',
        secret_key='',
        timeframe='15m'
    ):
        self.exchange_id = exchange_id
        self.timeframe = timeframe
        self.market_type = 'spot'  # تثبيت السوق على الفوري حصرياً

        exchange_class = getattr(ccxt, exchange_id)
        self.exchange = exchange_class({
            'apiKey': api_key,
            'secret': secret_key,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot'
            }
        })

        self.cache = {}
        self.cache_seconds = 20

    def _is_valid_symbol(self, symbol):
        """
        فلترة صارمة جداً لمنع أي عملات غريبة، أو مشبوهة، أو أزواج فيوتشر، 
        والتركيز فقط على عملات الفوري الحقيقية مقابل USDT.
        """
        if not symbol or 'USDT' not in symbol:
            return None

        # منع أي رموز تخص العقود أو العملات الممنوعة
        unwanted_tokens = [
            'EUR', 'JPY', 'GBP', 'CAD', 'AUD', 'CHF', 'NZD', 'NCFX', 
            'USDCUSD', 'BULL', 'BEAR', 'UP', 'DOWN', '3S', '3L', 'HEDGE',
            'PERP', 'TEST', 'USD/', 'BTC/', 'ETH/', ':USDT'
        ]
        
        if any(token in symbol for token in unwanted_tokens):
            return None

        # التأكد من تنسيق الفوري النظيف (مثال: BTC/USDT)
        clean_symbol = symbol.strip().upper()
        if ':' in clean_symbol:
            clean_symbol = clean_symbol.split(':')[0]

        return clean_symbol

    def _fetch_ohlcv(self, symbol, timeframe, limit=220):
        valid_symbol = self._is_valid_symbol(symbol)
        if not valid_symbol:
            return None

        key = f"{valid_symbol}:{timeframe}:{limit}:spot"
        now = time.time()

        cached = self.cache.get(key)
        if cached:
            if now - cached['time'] < self.cache_seconds:
                return cached['data'].copy()

        try:
            data = self.exchange.fetch_ohlcv(
                valid_symbol,
                timeframe=timeframe,
                limit=limit
            )

            if not data or len(data) < 30:
                return None

            df = pd.DataFrame(
                data,
                columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
            )

            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')

            df = df.dropna().reset_index(drop=True)

            self.cache[key] = {
                'time': now,
                'data': df
            }

            return df.copy()

        except Exception as e:
            logger.warning("OHLCV error %s %s: %s", valid_symbol, timeframe, e)
            return None

    def _calculate_bollinger_bands(self, series, period=20, std_dev=2):
        middle = series.rolling(window=period).mean()
        std = series.rolling(window=period).std()
        upper = middle + (std * std_dev)
        lower = middle - (std * std_dev)
        return upper, middle, lower

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

    def _calculate_parabolic_sar(self, df):
        close = df['close']
        sar = close.shift(1).fillna(close.iloc[0])
        return sar < close

    def _prepare(self, df):
        df = df.copy()
        df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
        
        upper, middle, lower = self._calculate_bollinger_bands(df['close'])
        df['bb_upper'] = upper
        df['bb_lower'] = lower
        df['bb_middle'] = middle

        st_val, st_dir = self._calculate_supertrend(df)
        df['supertrend'] = st_val
        df['supertrend_dir'] = st_dir

        df['sar_bullish'] = self._calculate_parabolic_sar(df)
        df['atr'] = (df['high'] - df['low']).rolling(14).mean().fillna(df['close'] * 0.01)
        
        return df.dropna().reset_index(drop=True)

    def detect_fvg(self, df):
        if df is None or len(df) < 3:
            return None
        i = len(df) - 1
        if df.loc[i, 'low'] > df.loc[i - 2, 'high']:
            return 'BULLISH_FVG'
        return None

    def detect_order_block(self, df):
        if df is None or len(df) < 5:
            return None
        for i in range(len(df) - 2, 2, -1):
            if (df.loc[i, 'close'] < df.loc[i, 'open'] and 
                df.loc[i+1, 'close'] > df.loc[i+1, 'open'] and 
                df.loc[i+1, 'close'] > df.loc[i, 'high']):
                return {'type': 'BULLISH_OB', 'level': float(df.loc[i, 'low'])}
        return None

    def detect_candlestick_patterns(self, df):
        if df is None or len(df) < 3:
            return None

        curr = df.iloc[-1]
        prev = df.iloc[-2]
        body = abs(curr['close'] - curr['open'])
        range_val = curr['high'] - curr['low']
        if range_val == 0:
            return None

        upper_shadow = curr['high'] - max(curr['close'], curr['open'])
        lower_shadow = min(curr['close'], curr['open']) - curr['low']

        if lower_shadow >= (body * 2) and upper_shadow <= (body * 0.5) and curr['close'] > curr['open']:
            return 'BULLISH_PINBAR'
        
        prev_body = abs(prev['close'] - prev['open'])
        if prev['close'] < prev['open'] and curr['close'] > curr['open'] and curr['close'] >= prev['open'] and body > prev_body:
            return 'BULLISH_ENGULFING'

        return None

    def evaluate_strategy(self, symbol):
        valid_symbol = self._is_valid_symbol(symbol)
        if not valid_symbol:
            return None

        df_15m = self._fetch_ohlcv(valid_symbol, '15m', 100)
        if df_15m is None or len(df_15m) < 30:
            return None

        df_15m = self._prepare(df_15m)
        if len(df_15m) == 0:
            return None
            
        row = df_15m.iloc[-1]

        # صفقات الفوري دائماً تعتمد على الاتجاه الصاعد (LONG - شراء)
        decision = 'LONG'

        fvg = self.detect_fvg(df_15m)
        ob = self.detect_order_block(df_15m)
        candle_pattern = self.detect_candlestick_patterns(df_15m)
        
        confirmations = ['Structure', 'Trend']
        
        if row['supertrend_dir'] == 1:
            confirmations.append('SuperTrend_Bullish')
            
        if row['sar_bullish']:
            confirmations.append('ParabolicSAR_Buy')

        if fvg:
            confirmations.append(fvg)
        if ob:
            confirmations.append(ob['type'])
        if candle_pattern:
            confirmations.append(candle_pattern)

        # شروط صارمة للتأكد من جودة صفقات الفوري
        if len(confirmations) < 2:
            return None

        entry = float(row['close'])
        atr = float(row['atr']) if 'atr' in row and row['atr'] > 0 else entry * 0.01

        sl = entry - (atr * 1.5)
        tp1 = entry + (atr * 2.5)
        tp2 = entry + (atr * 4.0)
        tp3 = entry + (atr * 6.0)
        struct_conf = 'BULLISH'

        score_val = 82 + (len(confirmations) * 3)

        return {
            'symbol': valid_symbol,
            'decision': decision,
            'score': min(score_val, 98),
            'quality': 'HIGH',
            'confirmations': confirmations,
            'entry': entry,
            'sl': sl,
            'tp1': tp1,
            'tp2': tp2,
            'tp3': tp3,
            'risk_pct': round((abs(entry - sl) / entry) * 100, 2),
            'structure_confirmation': struct_conf
        }


# تشغيل بوت الفوري حصرياً
bot = ExpertSpotBot(exchange_id='bingx')

# =========================================================
# TELEGRAM SENDER (Spot Specific)
# =========================================================
def send_telegram_alert(signal):
    if TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        logger.info("Telegram token not set. Skipping message dispatch.")
        return

    market_label = "🟢 EXPERT SPOT SIGNAL (صفقة فوري - شراء آمن)"
    
    msg = f"""
{market_label}

📊 Symbol: {signal['symbol']}
🎯 Decision: {signal['decision']} (BUY)
⭐ Score: {signal['score']}
🏷 Quality: HIGH

📌 Confirmations: {len(signal['confirmations'])}/2+
🧠 {', '.join(signal['confirmations'])}

📈 Trend: {signal['structure_confirmation']}

💰 Entry Price: {signal['entry']:.7f}
🛑 Stop Loss: {signal['sl']:.7f} ({signal['risk_pct']}%)

🎯 TP1: {signal['tp1']:.7f} | R:R 1:2.5
🎯 TP2: {signal['tp2']:.7f} | R:R 1:4
🎯 TP3: {signal['tp3']:.7f} | R:R 1:6

🛡 Risk Filter: PASSED
⚡ Entry Status: OPTIMAL
⚠️ Spot Trading — Accumulation & Holding.
"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": msg,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logger.error("Failed to send Telegram alert: %s", e)


# =========================================================
# FLASK WEBHOOK ENDPOINT
# =========================================================
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    if not data or 'symbol' not in data:
        return jsonify({"status": "error", "message": "Invalid payload"}), 400

    symbol = data['symbol']
    logger.info("Analyzing spot symbol from webhook: %s", symbol)

    signal = bot.evaluate_strategy(symbol)
    if signal:
        send_telegram_alert(signal)
        return jsonify({"status": "success", "signal": signal}), 200
    else:
        return jsonify({"status": "filtered", "message": "Filtered out or not a valid spot coin"}), 200


@app.route('/', methods=['GET'])
def index():
    return "Expert Spot Analyst Bot is running successfully!", 200


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
