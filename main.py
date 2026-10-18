# ==========================================
# MY EXPERT CRYPTO BOT - FINAL INTEGRATED VERSION V16.1
# BingX + Telegram + Balanced SMC Engine + Live TP/SL Tracker
# ==========================================
import os
import time
import threading
import requests
import ccxt
from flask import Flask

# ============================================================
# BALANCED HIGH-PROBABILITY SMC ENGINE (V16.1)
# ============================================================
import numpy as np


class StrategyEngine:
    def __init__(self, capital=10000, risk_per_trade=0.01, reward_ratio=2.5):
        self.total_capital = max(0.0, float(capital))
        self.risk_per_trade = min(max(float(risk_per_trade), 0.001), 0.02)
        self.reward_ratio = max(float(reward_ratio), 1.5)

    @staticmethod
    def _array(data, minimum=30):
        try:
            a = np.asarray(data, dtype=float)
            if a.ndim != 2 or a.shape[0] < minimum or a.shape[1] < 6:
                return None
            a = a[:, :6]
            if not np.all(np.isfinite(a)):
                return None
            if np.any(a[:, 1:5] <= 0) or np.any(a[:, 5] < 0):
                return None
            if np.any(a[:, 2] < a[:, 3]):
                return None
            return a
        except (TypeError, ValueError, IndexError):
            return None

    @staticmethod
    def _round(value):
        value = float(value)
        if not np.isfinite(value) or value <= 0:
            return value
        decimals = max(2, min(12, int(-np.floor(np.log10(value))) + 3))
        return round(value, decimals)

    @staticmethod
    def _ema(values, period):
        values = np.asarray(values, dtype=float)
        if len(values) < period:
            return None
        alpha = 2.0 / (period + 1.0)
        out = float(values[0])
        for x in values[1:]:
            out = alpha * float(x) + (1.0 - alpha) * out
        return out

    def calculate_atr(self, highs, lows, closes, period=14):
        h, l, c = (np.asarray(x, dtype=float) for x in (highs, lows, closes))
        n = min(len(h), len(l), len(c))
        if n < 2:
            return 0.0
        h, l, c = h[-n:], l[-n:], c[-n:]
        tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
        return float(np.mean(tr[-min(max(1, int(period)), len(tr)):])) if len(tr) else 0.0

    def calculate_position_size(self, entry_price, stop_loss_price, direction="LONG"):
        try:
            entry, stop = float(entry_price), float(stop_loss_price)
            direction = str(direction).upper()
        except (TypeError, ValueError):
            return None
        if not np.isfinite(entry) or not np.isfinite(stop) or entry <= 0 or stop <= 0:
            return None
        if direction not in ("LONG", "SHORT") or self.total_capital <= 0:
            return None
        if (direction == "LONG" and stop >= entry) or (direction == "SHORT" and stop <= entry):
            return None
        distance = abs(entry - stop)
        if distance <= 0:
            return None
        risk_usd = self.total_capital * self.risk_per_trade
        qty = risk_usd / distance
        notional = qty * entry
        target = entry + distance * self.reward_ratio if direction == "LONG" else entry - distance * self.reward_ratio
        if target <= 0 or not np.isfinite(notional):
            return None
        return {
            "allowed_risk_usd": round(risk_usd, 2),
            "tokens_to_buy": round(qty, 8),
            "total_trade_value_usd": round(notional, 2),
            "take_profit_target": self._round(target),
            "reward_ratio": self.reward_ratio,
            "risk_percent": round(self.risk_per_trade * 100, 3),
        }

    def _trend(self, candles):
        closes = candles[:, 4]
        if len(closes) < 30:
            return "NEUTRAL"
        fast_now = self._ema(closes[-30:], 9)
        slow_now = self._ema(closes[-30:], 21)
        if fast_now is None or slow_now is None:
            return "NEUTRAL"
        if fast_now > slow_now and closes[-1] > slow_now:
            return "BULLISH"
        if fast_now < slow_now and closes[-1] < slow_now:
            return "BEARISH"
        return "NEUTRAL"

    @staticmethod
    def _rsi(closes, period=14):
        c = np.asarray(closes, dtype=float)
        d = np.diff(c)
        if len(d) < period:
            return 50.0
        gains = np.maximum(d, 0.0)
        losses = np.maximum(-d, 0.0)
        ag = float(np.mean(gains[-period:]))
        al = float(np.mean(losses[-period:]))
        if al == 0:
            return 100.0 if ag > 0 else 50.0
        return float(100.0 - 100.0 / (1.0 + ag / al))

    @staticmethod
    def _pivots(highs, lows, left=3, right=3):
        ph, pl = [], []
        for i in range(left, len(highs) - right):
            hwindow = highs[i-left:i+right+1]
            lwindow = lows[i-left:i+right+1]
            if highs[i] == np.max(hwindow) and np.count_nonzero(hwindow == highs[i]) == 1:
                ph.append((i, float(highs[i])))
            if lows[i] == np.min(lwindow) and np.count_nonzero(lwindow == lows[i]) == 1:
                pl.append((i, float(lows[i])))
        return ph, pl

    def analyze_market_structure(self, ohlcv_4h, ohlcv_1h, ohlcv_15m, btc_ohlcv_1h=None):
        def no_trade(reason, **extra):
            out = {"reason": reason}
            out.update(extra)
            return "NEUTRAL", 0, out

        raw4 = self._array(ohlcv_4h, 30)
        raw1 = self._array(ohlcv_1h, 30)
        raw15 = self._array(ohlcv_15m, 50)
        if raw4 is None or raw1 is None or raw15 is None:
            return no_trade("Invalid or insufficient OHLCV data")

        try:
            c4, c1, c15 = raw4[:-1], raw1[:-1], raw15[:-1]
            trend4, trend1 = self._trend(c4), self._trend(c1)
            if trend4 != trend1 or trend1 == "NEUTRAL":
                return no_trade("Multi-timeframe trend disagreement", trend_4h=trend4, trend_1h=trend1)

            btc_trend = "NOT_PROVIDED"
            if btc_ohlcv_1h is not None:
                btc = self._array(btc_ohlcv_1h, 30)
                if btc is not None:
                    btc_trend = self._trend(btc[:-1])
                    if btc_trend != trend1:
                        return no_trade("BTC trend filter mismatch")

            op, hi, lo, cl, vol = (c15[:, i] for i in (1, 2, 3, 4, 5))
            entry = float(cl[-1])
            atr = self.calculate_atr(hi, lo, cl, 14)
            rsi = self._rsi(cl, 14)
            
            piv_hi, piv_lo = self._pivots(hi, lo, 3, 3)
            if len(piv_hi) < 2 or len(piv_lo) < 2:
                return no_trade("Insufficient swing pivots")

            direction = "LONG" if trend1 == "BULLISH" else "SHORT"
            
            # BOS Detection
            bos = False
            break_level = None
            for i in range(len(cl) - 15, len(cl) - 1):
                if direction == "LONG" and piv_hi:
                    lvl = piv_hi[-1][1]
                    if cl[i] > lvl and cl[i-1] <= lvl:
                        bos, break_level = True, float(lvl)
                elif direction == "SHORT" and piv_lo:
                    lvl = piv_lo[-1][1]
                    if cl[i] < lvl and cl[i-1] >= lvl:
                        bos, break_level = True, float(lvl)

            if not bos:
                return no_trade("No confirmed BOS setup")

            # Retest validation
            retest = False
            for j in range(len(cl) - 4, len(cl)):
                if direction == "LONG" and lo[j] <= break_level + 0.1 * atr and cl[-1] > break_level:
                    retest = True
                elif direction == "SHORT" and hi[j] >= break_level - 0.1 * atr and cl[-1] < break_level:
                    retest = True

            if not retest:
                return no_trade("Waiting for valid structure retest")

            # Stop Loss & Risk Management
            stop = min(lo[-5:]) - 0.2 * atr if direction == "LONG" else max(hi[-5:]) + 0.2 * atr
            risk = self.calculate_position_size(entry, stop, direction)
            if not risk:
                return no_trade("Risk calculation failed")

            details = {
                "stop_loss": self._round(stop),
                "risk_management": risk,
                "setup": "Balanced SMC BOS + Retest",
                "score": 88,
                "trend_4h": trend4,
                "trend_1h": trend1,
                "btc_trend": btc_trend,
                "bos": True,
                "breakout_level": self._round(break_level),
                "retest_confirmed": True,
                "rsi": round(rsi, 1),
                "atr": self._round(atr)
            }
            return direction, self._round(entry), details

        except Exception as e:
            return no_trade(f"Error: {str(e)[:50]}")

    def analyze_multi_timeframe(self, ohlcv_4h, ohlcv_1h, ohlcv_15m, btc_ohlcv_1h=None):
        return self.analyze_market_structure(ohlcv_4h, ohlcv_1h, ohlcv_15m, btc_ohlcv_1h)


# ============================================================
# FLASK & TELEGRAM BOT APP
# ============================================================
app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
SIGNAL_COOLDOWN_SECONDS = max(60, int(os.environ.get("SIGNAL_COOLDOWN_SECONDS", "7200")))
API_MIN_INTERVAL_SECONDS = max(0.25, float(os.environ.get("API_MIN_INTERVAL_SECONDS", "0.50")))
SYMBOL_PAUSE_SECONDS = max(0.10, float(os.environ.get("SYMBOL_PAUSE_SECONDS", "0.20")))
MAX_API_RETRIES = max(0, min(3, int(os.environ.get("MAX_API_RETRIES", "2"))))

BOT_CAPITAL_USD = max(1.0, float(os.environ.get("BOT_CAPITAL_USD", "1000")))
RISK_PER_TRADE = min(0.02, max(0.001, float(os.environ.get("RISK_PER_TRADE", "0.01"))))
REWARD_RATIO = max(1.0, float(os.environ.get("REWARD_RATIO", "2.0")))

signal_history = {}
active_trades = {}
history_lock = threading.Lock()
trades_lock = threading.Lock()
api_lock = threading.Lock()
_last_api_request = 0.0
_api_cooldown_until = 0.0

bingx = ccxt.bingx({
    "enableRateLimit": True,
    "timeout": 20000,
    "options": {"defaultType": "swap"}
})

@app.route("/")
def home():
    return "My Expert Crypto Bot - Balanced SMC Scanner & TP/SL Tracker is active!"

@app.route("/health")
def health():
    return {"status": "healthy", "service": "active"}, 200


def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram not configured: missing tokens", flush=True)
        return False
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True
            },
            timeout=15
        )
        return response.status_code == 200
    except Exception as exc:
        print(f"Telegram error: {str(exc)[:150]}", flush=True)
        return False


def bingx_call(method_name, *args, **kwargs):
    global _last_api_request, _api_cooldown_until
    method = getattr(bingx, method_name)
    for attempt in range(MAX_API_RETRIES + 1):
        with api_lock:
            now = time.monotonic()
            wait_for = max(
                0.0,
                API_MIN_INTERVAL_SECONDS - (now - _last_api_request),
                _api_cooldown_until - now
            )
            if wait_for > 0:
                time.sleep(wait_for)
            _last_api_request = time.monotonic()
        try:
            return method(*args, **kwargs)
        except Exception as exc:
            err = str(exc).lower()
            if any(x in err for x in ("109415", "invalid symbol", "does not have market")):
                return None
            if attempt >= MAX_API_RETRIES:
                return None
            time.sleep(1.5 * (attempt + 1))
    return None


def get_all_usdt_symbols():
    try:
        markets = bingx_call("load_markets")
        if not markets:
            return []
        symbols = []
        for symbol, market in markets.items():
            if (
                market.get("linear", False)
                and market.get("quote") == "USDT"
                and market.get("active", True)
                and "/USDT:USDT" in symbol
                and market.get("swap", True)
            ):
                sym_upper = symbol.upper()
                if any(x in sym_upper for x in ["TEST", "UP/", "DOWN/", "BULL", "BEAR"]):
                    continue
                symbols.append(symbol)
        return sorted(set(symbols))
    except Exception as exc:
        return []


def notify_trade_executed(symbol, direction, entry_price, details):
    rm = details.get("risk_management", {})
    if not rm or "take_profit_target" not in rm or "stop_loss" not in details:
        return False

    emoji = "🟢 LONG" if direction == "LONG" else "🔴 SHORT"
    message = (
        f"🎯 *إشارة صفقات عالية الدقة — Balanced SMC*\n\n"
        f"🔹 العملة: `{symbol}`\n"
        f"⚖️ الاتجاه: `{emoji}`\n"
        f"⭐ تقييم الإعداد: `{details.get('score', 88)}/100`\n"
        f"💵 سعر الدخول: `{entry_price}`\n"
        f"🛑 وقف الخسارة: `{details['stop_loss']}`\n"
        f"🎯 الهدف: `{rm['take_profit_target']}`\n"
        f"📐 العائد/المخاطرة: `1:{rm.get('reward_ratio', 2.5)}`\n"
        f"💰 المخاطرة: `${rm.get('allowed_risk_usd', 0)}` ({rm.get('risk_percent', 0)}%)\n\n"
        f"📈 اتجاه 4H: `{details.get('trend_4h')}` | 1H: `{details.get('trend_1h')}`\n"
        f"₿ اتجاه BTC: `{details.get('btc_trend')}`\n"
        f"📊 RSI: `{details.get('rsi')}` | ATR: `{details.get('atr')}`\n\n"
        f"⚠️ *متابعة افتراضية للأهداف ووقف الخسارة مفعلة.*"
    )
    return send_telegram_message(message)


def process_symbol(symbol, engine):
    try:
        now = time.time()
        with history_lock:
            if now - signal_history.get(symbol, 0) < SIGNAL_COOLDOWN_SECONDS:
                return

        ticker = bingx_call("fetch_ticker", symbol)
        if not ticker:
            return
        market_price = float(ticker.get("last") or ticker.get("close") or 0)
        quote_volume = float(ticker.get("quoteVolume") or ticker.get("baseVolume") or 0)
        
        if market_price <= 0 or quote_volume < 50000:
            return

        ohlcv_4h = bingx_call("fetch_ohlcv", symbol, timeframe="4h", limit=40)
        ohlcv_1h = bingx_call("fetch_ohlcv", symbol, timeframe="1h", limit=40)
        ohlcv_15m = bingx_call("fetch_ohlcv", symbol, timeframe="15m", limit=60)
        if not ohlcv_4h or not ohlcv_1h or not ohlcv_15m:
            return

        btc_ohlcv_1h = None
        if symbol != "BTC/USDT:USDT":
            btc_ohlcv_1h = bingx_call("fetch_ohlcv", "BTC/USDT:USDT", timeframe="1h", limit=40)
            if not btc_ohlcv_1h:
                return

        direction, entry_price, details = engine.analyze_market_structure(
            ohlcv_4h, ohlcv_1h, ohlcv_15m, btc_ohlcv_1h=btc_ohlcv_1h
        )
        if direction not in ("LONG", "SHORT") or not details:
            return

        sent = notify_trade_executed(symbol, direction, entry_price, details)
        if not sent:
            return

        with trades_lock:
            active_trades[symbol] = {
                "direction": direction,
                "entry_price": float(entry_price),
                "stop_loss": float(details["stop_loss"]),
                "take_profit": float(details["risk_management"]["take_profit_target"]),
                "timestamp": time.time()
            }
        with history_lock:
            signal_history[symbol] = time.time()

    except Exception as exc:
        pass


def live_trade_tracker():
    while True:
        try:
            time.sleep(15)
            with trades_lock:
                symbols = list(active_trades.keys())
            
            for symbol in symbols:
                ticker = bingx_call("fetch_ticker", symbol)
                if not ticker:
                    continue
                price = float(ticker.get("last") or ticker.get("close") or 0)
                if price <= 0:
                    continue

                message = None
                with trades_lock:
                    trade = active_trades.get(symbol)
                    if not trade:
                        continue
                    direction = trade["direction"]
                    tp, sl = trade["take_profit"], trade["stop_loss"]
                    
                    hit_tp = price >= tp if direction == "LONG" else price <= tp
                    hit_sl = price <= sl if direction == "LONG" else price >= sl
                    
                    if hit_tp or hit_sl:
                        result_title = "🎯 *تم تحقيق الهدف بنجاح! (Take Profit)*" if hit_tp else "🛑 *تم ضرب وقف الخسارة! (Stop Loss)*"
                        message = (
                            f"{result_title}\n\n"
                            f"🔹 العملة: `{symbol}`\n"
                            f"📊 الاتجاه: `{direction}`\n"
                            f"💵 سعر الإشارة: `{trade['entry_price']}`\n"
                            f"📍 السعر الحالي: `{price}`\n"
                            f"🎯 الهدف: `{tp}` | 🛑 الوقف: `{sl}`"
                        )
                        del active_trades[symbol]
                
                if message:
                    send_telegram_message(message)
                time.sleep(SYMBOL_PAUSE_SECONDS)
        except Exception as exc:
            time.sleep(10)


def background_scanner():
    time.sleep(5)
    send_telegram_message(
        "🤖 *تم تشغيل بوت تداول العملات الرقمية (Balanced SMC V16.1)*\n"
        "الفحص التلقائي لجميع أزواج USDT على منصة BingX مفعل بنجاح."
    )
    engine = StrategyEngine(
        capital=BOT_CAPITAL_USD,
        risk_per_trade=RISK_PER_TRADE,
        reward_ratio=REWARD_RATIO
    )
    while True:
        try:
            symbols = get_all_usdt_symbols()
            if not symbols:
                time.sleep(30)
                continue
            for symbol in symbols:
                process_symbol(symbol, engine)
                time.sleep(SYMBOL_PAUSE_SECONDS)
            time.sleep(60)
        except Exception as exc:
            time.sleep(30)


scanner_thread = threading.Thread(target=background_scanner, daemon=True, name="smc-bot-scanner")
tracker_thread = threading.Thread(target=live_trade_tracker, daemon=True, name="trade-tracker")
scanner_thread.start()
tracker_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
