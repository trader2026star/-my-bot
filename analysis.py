import logging
import ccxt
import pandas as pd
import numpy as np

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

    def fetch_ohlcv_data(self, symbol, timeframe='4h', limit=100):
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            logger.error(f"خطأ في جلب بيانات {symbol}: {e}")
            return None

    def calculate_atr(self, df, period=14):
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = np.max(ranges, axis=1)
        return true_range.rolling(period).mean()

    def calculate_rsi(self, df, period=14):
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    def get_market_trend(self, timeframe='4h'):
        try:
            btc_df = self.fetch_ohlcv_data('BTC/USDT:USDT', timeframe=timeframe, limit=60)
            if btc_df is not None and len(btc_df) >= 50:
                btc_close = btc_df['close'].iloc[-1]
                btc_sma50 = btc_df['close'].rolling(window=50).mean().iloc[-1]
                return "BULLISH" if btc_close > btc_sma50 else "BEARISH"
        except Exception:
            pass
        return "NEUTRAL"

    def evaluate_strategy(self, symbol, account_balance=1000.0, risk_percentage=0.01):
        df = self.fetch_ohlcv_data(symbol, timeframe='4h', limit=100)
        
        if df is None or len(df) < 50:
            return {
                "Decision": "NO TRADE ⏳",
                "Reason": "INSUFFICIENT DATA / ERROR",
                "Score": 50,
                "Quality": "WEAK"
            }

        close = df['close'].iloc[-1]
        volume_recent = df['volume'].iloc[-5:].mean()
        
        # فلتر السيولة
        if volume_recent * close < 50000:
            return {
                "Decision": "NO TRADE ⏳",
                "Reason": "LOW LIQUIDITY / VOLUME",
                "Score": 40,
                "Quality": "WEAK"
            }

        # حساب المؤشرات وهيكل السوق
        sma_fast = df['close'].rolling(window=9).mean().iloc[-1]
        sma_slow = df['close'].rolling(window=21).mean().iloc[-1]
        sma_trend = df['close'].rolling(window=50).mean().iloc[-1]
        atr = self.calculate_atr(df).iloc[-1]
        rsi_series = self.calculate_rsi(df)
        current_rsi = rsi_series.iloc[-1] if not rsi_series.empty else 50

        if pd.isna(atr) or atr == 0:
            atr = close * 0.01

        # تحديد مستويات هيكل السوق والـ Order Blocks (OB) الحقيقية
        recent_low = df['low'].iloc[-6:-1].min()
        recent_high = df['high'].iloc[-6:-1].max()
        
        # اكتشاف تقريبي للـ OB (الشمعة المعاكسة الأخيرة قبل الحركة القوية)
        bullish_ob_low = df[['open', 'close']].iloc[-4].min() # منطقة الـ Bullish OB
        bearish_ob_high = df[['open', 'close']].iloc[-4].max() # منطقة الـ Bearish OB

        # شروط هيكل السوق (MSS)
        bullish_mss = (df['close'].iloc[-1] > df['high'].iloc[-3]) and (sma_fast > sma_slow)
        bearish_mss = (df['close'].iloc[-1] > df['low'].iloc[-3] == False) and (sma_fast < sma_slow) # تم ضبطها بدقة للـ Short

        is_bullish = bullish_mss and (close > sma_trend) and (current_rsi < 68)
        is_bearish = bearish_mss and (close < sma_trend) and (current_rsi > 32)

        btc_trend = self.get_market_trend(timeframe='4h')

        if is_bullish and btc_trend == "BEARISH":
            return {
                "Decision": "NO TRADE ⏳",
                "Reason": "BLOCKED BY BTC BEARISH TREND",
                "Score": 48,
                "Quality": "WEAK"
            }

        if not is_bullish and not is_bearish:
            reason_text = "OVERBOUGHT / OVERSOLD RSI" if (current_rsi >= 68 or current_rsi <= 32) else "NO SMC STRUCTURE / CONSOLIDATION"
            return {
                "Decision": "NO TRADE ⏳",
                "Reason": reason_text,
                "Score": 52,
                "Quality": "WEAK"
            }

        # === التحقق من عدم مطاردة السعر (Price Chasing & OB Zone Check) ===
        entry = round(close, 5 if close < 1 else 2)
        
        if is_bullish:
            # منع الدخول لو السعر صعد وابتعد تماماً عن منطقة الـ OB (تجنب الـ Chasing)
            if entry > (bullish_ob_high + (4 * atr)):
                return {
                    "Decision": "NO TRADE ⏳",
                    "Reason": "PRICE CHASED / TOO FAR FROM OB",
                    "Score": 50,
                    "Quality": "WEAK"
                }
            
            decision = "MARKET LONG 🟢"
            reason = "SMC Bullish MSS + Order Block Alignment"
            
            # وقف الخسارة الهيكلي الحقيقي تحت الـ OB أو الـ Swing Low مع بفر صغير
            stop_loss = round(min(recent_low, bullish_ob_low) - (0.2 * atr), 5 if close < 1 else 2)
            
            risk = entry - stop_loss
            if risk <= 0: 
                risk = atr
                stop_loss = entry - risk

            tp1 = round(entry + (1.8 * risk), 5 if close < 1 else 2)
            tp2 = round(entry + (3.2 * risk), 5 if close < 1 else 2)
            leverage = 1

        else:
            # منع الدخول لو السعر هبط وابتعد عن الـ Bearish OB
            if entry < (bearish_ob_high - (4 * atr)):
                return {
                    "Decision": "NO TRADE ⏳",
                    "Reason": "PRICE CHASED / TOO FAR FROM OB",
                    "Score": 50,
                    "Quality": "WEAK"
                }

            decision = "MARKET SHORT 🔴"
            reason = "SMC Bearish MSS + Order Block Alignment"
            
            # وقف الخسارة الهيكلي الحقيقي فوق الـ OB أو الـ Swing High مع بفر صغير
            stop_loss = round(max(recent_high, bearish_ob_high) + (0.2 * atr), 5 if close < 1 else 2)
            
            risk = stop_loss - entry
            if risk <= 0: 
                risk = atr
                stop_loss = entry + risk

            tp1 = round(entry - (1.8 * risk), 5 if close < 1 else 2)
            tp2 = round(entry - (3.2 * risk), 5 if close < 1 else 2)
            leverage = 2

        # === فلتر التأكد من أن الـ SL ليس واسعاً بشكل مبالغ فيه ===
        sl_percentage_distance = abs(entry - stop_loss) / entry
        if sl_percentage_distance > 0.08:  # لو الـ SL أوسع من 8% من السعر
            return {
                "Decision": "NO TRADE ⏳",
                "Reason": "SL TOO WIDE / STRUCTURAL INVALIDATION RISK",
                "Score": 50,
                "Quality": "WEAK"
            }

        # حساب نسبة العائد للمخاطرة الفعلية
        reward_tp1 = abs(tp1 - entry)
        rr_ratio = reward_tp1 / risk if risk > 0 else 0

        if rr_ratio < 1.3:
            return {
                "Decision": "NO TRADE ⏳",
                "Reason": "LOW RISK-TO-REWARD RATIO (<1.3)",
                "Score": 58,
                "Quality": "WEAK"
            }

        # === نظام تجميع المؤكدات الحقيقي (Multi-Confluence Scoring System) ===
        confluences_count = 0

        # 1. تأكيد هيكل السوق
        if (is_bullish and bullish_mss) or (is_bearish and bearish_mss):
            confluences_count += 1

        # 2. توافق اتجاه السوق العام (BTC Trend)
        if (is_bullish and btc_trend == "BULLISH") or (is_bearish and btc_trend == "BEARISH"):
            confluences_count += 1

        # 3. نظافة الزخم وعدم التشبع (RSI Optimal Zone)
        if 40 <= current_rsi <= 60:
            confluences_count += 1

        # 4. تأكيد الفوليوم (Volume Expansion vs Average)
        avg_volume_20 = df['volume'].rolling(window=20).mean().iloc[-1]
        if volume_recent > avg_volume_20:
            confluences_count += 1

        # 5. نسبة العائد للمخاطرة (Strong R:R)
        if rr_ratio >= 2.0:
            confluences_count += 1

        # اشتراط الحد الأدنى للمؤكدات (على الأقل 3 مؤكدات صحيحة من أصل 5)
        if confluences_count < 3:
            return {
                "Decision": "NO TRADE ⏳",
                "Reason": f"INSUFFICIENT CONFLUENCES ({confluences_count}/5)",
                "Score": 55,
                "Quality": "WEAK"
            }

        # تدرج السكور بناءً على عدد المؤكدات الحقيقية المجتمعة
        base_score = 65
        score = base_score + (confluences_count * 7)
        score = min(95, score)
        
        quality = "🟢 STRONG" if score >= 80 else "🟡 MODERATE"

        # حساب حجم العقد المالي لإدارة المخاطر بناءً على مسافة الـ SL الجديدة
        risk_amount = account_balance * risk_percentage
        risk_per_unit = risk
        
        if risk_per_unit > 0:
            position_size = round((risk_amount / risk_per_unit) * entry / leverage, 2)
        else:
            position_size = round(account_balance * 0.2, 2)

        position_size = max(10.0, min(position_size, account_balance * leverage * 2))

        return {
            "Decision": decision,
            "Entry": entry,
            "Stop Loss": stop_loss,
            "TP1": tp1,
            "TP2": tp2,
            "Score": score,
            "Quality": quality,
            "Position Size (USDT)": position_size,
            "Leverage": leverage,
            "Reason": reason
        }
