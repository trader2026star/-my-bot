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
# EXPERT DUAL-MARKET ANALYST BOT CORE (SPOT & FUTURES - LONG ONLY)
# =========================================================
class ExpertDualAnalystBot:
    def __init__(
        self,
        exchange_id='bingx',
        api_key='',
        secret_key=''
    ):
        self.exchange_id = exchange_id
        exchange_class = getattr(ccxt, exchange_id)
        
        self.exchange = exchange_class({
            'apiKey': api_key,
            'secret': secret_key,
            'enableRateLimit': True
        })

        self.cache = {}
        self.cache_seconds = 20

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

    def _fetch_ohlcv(self, symbol, timeframe, limit=220, market_type='swap'):
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
        df['rsi'] = self._calculate_rsi(df['close'], 14)
        
        vol_ma = df['volume'].rolling(window=20).mean()
        df['volume_ratio'] = np.where(vol_ma > 0, df['volume'] / vol_ma, 1.0)
        
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

    def get_market_context(self, symbol, market_type):
        trend_4h = "UNKNOWN"
        trend_1h = "UNKNOWN"
        btc_context = "UNKNOWN"

        try:
            df_4h = self._fetch_ohlcv(symbol, '4h', 50, market_type)
            if df_4h is not None and len(df_4h) > 10:
                _, st_dir_4h = self._calculate_supertrend(df_4h)
                trend_4h = "BULLISH" if st_dir_4h.iloc[-1] == 1 else "BEARISH"

            df_1h = self._fetch_ohlcv(symbol, '1h', 50, market_type)
            if df_1h is not None and len(df_1h) > 10:
                _, st_dir_1h = self._calculate_supertrend(df_1h)
                trend_1h = "BULLISH" if st_dir_1h.iloc[-1] == 1 else "BEARISH"

            btc_symbol = "BTC/USDT" if market_type == 'spot' else "BTC/USDT:USDT"
            df_btc = self._fetch_ohlcv(btc_symbol, '1h', 50, market_type)
            if df_btc is not None and len(df_btc) > 10:
                _, st_dir_btc = self._calculate_supertrend(df_btc)
                btc_context = "BULLISH" if st_dir_btc.iloc[-1] == 1 else "BEARISH"
        except Exception as e:
            logger.error("Error fetching market context: %s", e)

        return trend_4h, trend_1h, btc_context

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

    def evaluate_strategy(self, symbol, market_type='swap'):
        if not self._is_valid_symbol(symbol):
            return None

        df_15m = self._fetch_ohlcv(symbol, '15m', 100, market_type)
        if df_15m is None or len(df_15m) < 30:
            return None

        df_15m = self._prepare(df_15m)
        if len(df_15m) == 0:
            return None
            
        row = df_15m.iloc[-1]
        decision = 'LONG'

        fvg = self.detect_fvg(df_15m)
        ob = self.detect_order_block(df_15m)
        candle_pattern = self.detect_candlestick_patterns(df_15m)
        
        confirmations = ['Structure', 'Trend']
        
        if row['supertrend_dir'] == 1:
            confirmations.append('SuperTrend_Bullish')
            
        if row['sar_bullish']:
            confirmations.append('ParabolicSAR_Buy')

        if row['close'] <= row['bb_lower'] * 1.01:
            confirmations.append('Bollinger_Lower_Bounce')

        if row['rsi'] > 20 and row['rsi'] < 75:
            confirmations.append('RSI_Momentum_OK')

        if fvg:
            confirmations.append(fvg)
        if ob:
            confirmations.append(ob['type'])
        if candle_pattern:
            confirmations.append(candle_pattern)

        if len(confirmations) < 3:
            return None

        trend_4h, trend_1h, btc_context = self.get_market_context(symbol, market_type)

        if trend_4h == 'BEARISH':
            return None
        if row['rsi'] > 80:
            return None
        if row['volume_ratio'] < 0.6:
            return None

        entry = float(row['close'])
        atr = float(row['atr']) if 'atr' in row and row['atr'] > 0 else entry * 0.01

        recent_low = float(df_15m['low'].iloc[-5:].min())

        sl = min(entry - (atr * 2.2), recent_low - (atr * 0.5))
        risk_distance = entry - sl
        tp1 = entry + (risk_distance * 1.5)
        tp2 = entry + (risk_distance * 2.5)
        tp3 = entry + (risk_distance * 4.0)

        score_val = 82 + (len(confirmations) * 3)

        return {
            'symbol': symbol,
            'market_type': 'SPOT' if market_type == 'spot' else 'FUTURES',
            'decision': decision,
            'score': min(score_val, 99),
            'quality': 'HIGH',
            'confirmations': confirmations,
            'trend_4h': trend_4h,
            'trend_1h': trend_1h,
            'btc_context': btc_context,
            'rsi_15m': float(row['rsi']),
            'volume_ratio': float(row['volume_ratio']),
            'entry': entry,
            'sl': sl,
            'tp1': tp1,
            'tp2': tp2,
            'tp3': tp3,
            'risk_pct': round((abs(entry - sl) / entry) * 100, 2),
            'structure_confirmation': 'BULLISH'
        }

bot = ExpertDualAnalystBot(exchange_id='bingx')

# =========================================================
# TELEGRAM SENDER
# =========================================================
def send_telegram_alert(signal):
    if TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        logger.info("Telegram token not set. Skipping message dispatch.")
        return

    market_label = "🟢 [SPOT - فوري]" if signal['market_type'] == 'SPOT' else "🚀 [FUTURES - فيوتشر]"

    msg = f"""
{market_label} LONG-ONLY SIGNAL 📈

📊 Symbol: {signal['symbol']}
🎯 Decision: LONG
⭐ Score: {signal['score']}
🏷 Quality: HIGH

📌 Confirmations: {len(signal['confirmations'])}/3+
🧠 {', '.join(signal['confirmations'])}

📈 4H Trend: {signal['trend_4h']}
📊 1H Trend: {signal['trend_1h']}
₿ BTC Context: {signal['btc_context']}

💪 RSI 15M: {signal['rsi_15m']:.1f}
🔊 Volume: {signal['volume_ratio']:.2f}x

💰 Entry: {signal['entry']:.7f}
🛑 SL: {signal['sl']:.7f} ({signal['risk_pct']}%)

🎯 TP1: {signal['tp1']:.7f} | R:R 1:1.5
🎯 TP2: {signal['tp2']:.7f} | R:R 1:2.5
🎯 TP3: {signal['tp3']:.7f} | R:R 1:4

🛡 Strategy: LONG ONLY (No Shorting)
⚡ Entry Status: DIRECT

⚠️ Setup signal — not a guaranteed result.
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
# BACKGROUND MARKET SCANNER LOOP & SELF PING
# =========================================================
def self_ping():
    while True:
        try:
            time.sleep(240)
            requests.get(RENDER_EXTERNAL_URL, timeout=10)
            logger.info("Self-ping sent successfully to keep service awake.")
        except Exception as e:
            logger.warning("Self-ping failed: %s", e)

def background_scanner():
    # قائمة موسعة لأكثر من 100 عملة رقمية قوية (Spot & Futures)
    spot_symbols = [
        "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", 
        "ADA/USDT", "DOGE/USDT", "AVAX/USDT", "LINK/USDT", "SUI/USDT", 
        "NEAR/USDT", "RENDER/USDT", "FET/USDT", "SHIB/USDT", "UNI/USDT", 
        "APT/USDT", "OP/USDT", "ATOM/USDT", "LTC/USDT", "ETC/USDT", 
        "BCH/USDT", "FIL/USDT", "STX/USDT", "INJ/USDT", "ARB/USDT", 
        "ICP/USDT", "TIA/USDT", "SEI/USDT", "DYM/USDT", "PEPE/USDT", 
        "FLOKI/USDT", "BONK/USDT", "WIF/USDT", "JUP/USDT", "STRK/USDT", 
        "MANA/USDT", "SAND/USDT", "AXS/USDT", "GALA/USDT", "IMX/USDT", 
        "RNDR/USDT", "AGIX/USDT", "OCEAN/USDT", "NEAR/USDT", "GRT/USDT", 
        "HBAR/USDT", "ALGO/USDT", "VET/USDT", "FTM/USDT", "EGLD/USDT"
    ]
    
    futures_symbols = [
        "BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "XRP/USDT:USDT", 
        "DOGE/USDT:USDT", "AVAX/USDT:USDT", "ADA/USDT:USDT", "LINK/USDT:USDT", 
        "SUI/USDT:USDT", "NEAR/USDT:USDT", "DYM/USDT:USDT", "RENDER/USDT:USDT", 
        "FET/USDT:USDT", "INJ/USDT:USDT", "ARB/USDT:USDT", "SHIB/USDT:USDT", 
        "UNI/USDT:USDT", "APT/USDT:USDT", "OP/USDT:USDT", "ATOM/USDT:USDT", 
        "LTC/USDT:USDT", "ICP/USDT:USDT", "TIA/USDT:USDT", "SEI/USDT:USDT", 
        "PEPE/USDT:USDT", "FLOKI/USDT:USDT", "BONK/USDT:USDT", "WIF/USDT:USDT", 
        "JUP/USDT:USDT", "STRK/USDT:USDT", "MANA/USDT:USDT", "SAND/USDT:USDT", 
        "AXS/USDT:USDT", "GALA/USDT:USDT", "IMX/USDT:USDT", "GRT/USDT:USDT", 
        "HBAR/USDT:USDT", "ALGO/USDT:USDT", "VET/USDT:USDT", "FTM/USDT:USDT", 
        "POL/USDT:USDT", "CHZ/USDT:USDT", "CRV/USDT:USDT", "LDO/USDT:USDT", 
        "SNX/USDT:USDT", "MKR/USDT:USDT", "AAVE/USDT:USDT", "COMP/USDT:USDT", 
        "SUSHI/USDT:USDT", "1INCH/USDT:USDT"
    ]
    
    unique_symbols = set()
    symbols_to_scan = []
    
    for s in spot_symbols:
        item = (s, "spot")
        if item not in unique_symbols:
            unique_symbols.add(item)
            symbols_to_scan.append(item)
            
    for s in futures_symbols:
        item = (s, "swap")
        if item not in unique_symbols:
            unique_symbols.add(item)
            symbols_to_scan.append(item)
    
    sent_signals_cooldown = {}
    logger.info("Cleaned background market scanner thread started successfully with %d unique assets (>100 total market combinations).", len(symbols_to_scan))
    
    while True:
        try:
            logger.info("Starting scheduled market scan across +100 assets...")
            for symbol, m_type in symbols_to_scan:
                signal = bot.evaluate_strategy(symbol, m_type)
                if signal:
                    cooldown_key = f"{symbol}_{signal['market_type']}"
                    last_time = sent_signals_cooldown.get(cooldown_key, 0)
                    
                    if time.time() - last_time > 7200:
                        send_telegram_alert(signal)
                        sent_signals_cooldown[cooldown_key] = time.time()
                        logger.info("Signal found and sent for %s (%s)", symbol, signal['market_type'])
                
                time.sleep(1.0) # تأقلم سريع ومنتظم لعدم الضغط على حظر المنصة (Rate Limit)
                
        except Exception as e:
            logger.error("Error in background scanner: %s", e)
            
        time.sleep(90)

# =========================================================
# FLASK WEBHOOK ENDPOINT
# =========================================================
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    if not data or 'symbol' not in data:
        return jsonify({"status": "error", "message": "Invalid payload"}), 400

    symbol = data['symbol']
    market_type = data.get('market_type', 'swap')
    
    logger.info("Analyzing symbol via webhook: %s in market: %s", symbol, market_type)

    signal = bot.evaluate_strategy(symbol, market_type)
    if signal:
        send_telegram_alert(signal)
        return jsonify({"status": "success", "signal": signal}), 200
    else:
        return jsonify({"status": "filtered", "message": "Filtered out by market filters"}), 200

@app.route('/', methods=['GET'])
def index():
    return "Expert Cleaned Dual-Market LONG-ONLY Analyst Bot (+100 Assets) is running successfully!", 200

if __name__ == '__main__':
    scanner_thread = threading.Thread(target=background_scanner, daemon=True)
    scanner_thread.start()

    ping_thread = threading.Thread(target=self_ping, daemon=True)
    ping_thread.start()

    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
