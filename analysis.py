import time
from decimal import Decimal
from typing import Dict, List, Optional
import requests

BINANCE_BASE_URL = "https://data-api.binance.vision"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Binance-AI-Scanner/2.0",
    "Accept": "application/json",
})

def binance_get(endpoint: str, params: Optional[dict] = None):
    response = SESSION.get(
        BINANCE_BASE_URL + endpoint,
        params=params or {},
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict) and data.get("code"):
        raise RuntimeError(
            f"Binance API error {data.get('code')}: {data.get('msg')}"
        )
    return data

def get_usdt_symbols() -> List[str]:
    data = binance_get("/api/v3/exchangeInfo")
    excluded = {
        "USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "DAIUSDT", "EURUSDT",
        "TRYUSDT", "BRLUSDT", "GBPUSDT", "AUDUSDT", "USDPUSDT",
    }
    symbols = []
    for item in data.get("symbols", []):
        if item.get("status") != "TRADING":
            continue
        if item.get("quoteAsset") != "USDT":
            continue
        if item.get("isSpotTradingAllowed") is False:
            continue
        symbol = item.get("symbol")
        if symbol and symbol not in excluded:
            symbols.append(symbol)
    return symbols

def get_current_price(symbol: str) -> Decimal:
    data = binance_get("/api/v3/ticker/price", {"symbol": symbol})
    return Decimal(str(data["price"]))

def get_klines(symbol: str, interval: str = "1h", limit: int = 250):
    data = binance_get(
        "/api/v3/klines",
        {"symbol": symbol, "interval": interval, "limit": limit},
    )
    candles = []
    for row in data:
        candles.append({
            "time": int(row[0]),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
        })
    return candles

def ema(values: List[float], period: int) -> List[Optional[float]]:
    result = [None] * len(values)
    if len(values) < period:
        return result
    multiplier = 2 / (period + 1)
    previous = sum(values[:period]) / period
    result[period - 1] = previous
    for i in range(period, len(values)):
        previous = (values[i] - previous) * multiplier + previous
        result[i] = previous
    return result

def rsi(values: List[float], period: int = 14) -> List[Optional[float]]:
    result = [None] * len(values)
    if len(values) <= period:
        return result
    gains, losses = [], []
    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    if avg_loss == 0:
        result[period] = 100
    else:
        rs = avg_gain / avg_loss
        result[period] = 100 - (100 / (1 + rs))
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            result[i + 1] = 100
        else:
            rs = avg_gain / avg_loss
            result[i + 1] = 100 - (100 / (1 + rs))
    return result

def macd(values: List[float]):
    ema12 = ema(values, 12)
    ema26 = ema(values, 26)
    line = [None] * len(values)
    for i in range(len(values)):
        if ema12[i] is not None and ema26[i] is not None:
            line[i] = ema12[i] - ema26[i]
    valid = [x for x in line if x is not None]
    signal_valid = ema(valid, 9)
    signal = [None] * len(values)
    start = len(values) - len(valid)
    for i, value in enumerate(signal_valid):
        if value is not None:
            signal[start + i] = value
    return line, signal

def atr(candles: List[dict], period: int = 14) -> List[Optional[float]]:
    result = [None] * len(candles)
    if len(candles) <= period:
        return result
    true_ranges = [None]
    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low = candles[i]["low"]
        previous_close = candles[i - 1]["close"]
        true_range = max(high - low, abs(high - previous_close), abs(low - previous_close))
        true_ranges.append(true_range)
    first_atr = sum(true_ranges[1:period + 1]) / period
    result[period] = first_atr
    previous = first_atr
    for i in range(period + 1, len(candles)):
        previous = (previous * (period - 1) + true_ranges[i]) / period
        result[i] = previous
    return result

def get_support(candles: List[dict], lookback: int = 30):
    return min(candle["low"] for candle in candles[-lookback:])

def get_resistance(candles: List[dict], lookback: int = 30):
    return max(candle["high"] for candle in candles[-lookback:])

def early_breakout(candles: List[dict], lookback: int = 15):
    """التحقق مما إذا كانت العملة تخترق أول مقاومة في بداية الحركة"""
    if len(candles) < lookback + 2:
        return False
    previous = candles[-lookback - 1:-1]
    resistance = max(candle["high"] for candle in previous)
    last = candles[-1]
    # الشمعة الأخيرة تخترق المقاومة بحجم تداول قوي وقفل فوقها
    return last["close"] > resistance and last["volume"] > 0

def volume_surge(candles: List[dict], period: int = 20):
    """كشف انفجار حجم التداول الباكر (سيولة داخلة)"""
    if len(candles) < period + 1:
        return 0
    current = candles[-1]["volume"]
    previous = [candle["volume"] for candle in candles[-period - 1:-1]]
    average = sum(previous) / len(previous)
    return current / average if average > 0 else 0

def analyze_symbol(symbol: str) -> Optional[Dict]:
    symbol = symbol.upper().strip()
    if not symbol.endswith("USDT"):
        symbol += "USDT"

    try:
        candles_1h = get_klines(symbol, "1h", 150)
        candles_4h = get_klines(symbol, "10h", 100) # استخدام فريم مناسب لجودة البيانات
    except Exception:
        try:
            candles_4h = get_klines(symbol, "4h", 100)
        except Exception:
            return None

    if len(candles_1h) < 50:
        return None

    closes_1h = [candle["close"] for candle in candles_1h]
    
    ema20_1h = ema(closes_1h, 20)[-1]
    ema50_1h = ema(closes_1h, 50)[-1]
    rsi_1h = rsi(closes_1h, 14)[-1]
    macd_line, signal_line = macd(closes_1h)
    macd_1h, signal_1h = macd_line[-1], signal_line[-1]
    atr_1h = atr(candles_1h, 14)[-1]

    required = [ema20_1h, ema50_1h, rsi_1h, macd_1h, signal_1h, atr_1h]
    if any(value is None for value in required):
        return None

    price = closes_1h[-1]
    support = get_support(candles_1h, 30)
    resistance = get_resistance(candles_1h, 30)
    vol_ratio = volume_surge(candles_1h, 20)
    is_early_breakout = early_breakout(candles_1h, 15)

    long_score = 0
    long_reasons = []

    # استراتيجية بداية الانفجار الصاعد (Early Pump Strategy)
    if is_early_breakout:
        long_score += 35
        long_reasons.append("🚀 اختراق باكر لمقاومة سابقة (بداية انطلاق)")

    if vol_ratio >= 1.8:  # فوليوم قوي جداً يبين دخول سيولة مفاجئة
        long_score += 25
        long_reasons.append(f"🔥 انفجار حجم التداول ({vol_ratio:.1f}x المتوسط)")
    elif vol_ratio >= 1.2:
        long_score += 15
        long_reasons.append(f"📈 ارتفاع ملحوظ بالفوليوم ({vol_ratio:.1f}x)")

    if price > ema20_1h:
        long_score += 15
        long_reasons.append("السعر فوق EMA20 (زخم إيجابي)")

    if 45 <= rsi_1h <= 72:  # مؤشر RSI في بداية الصعود وليس في التشبع القاتل
        long_score += 15
        long_reasons.append(f"RSI في منطقة صعود باكر ({rsi_1h:.1f})")

    if macd_1h > signal_1h:
        long_score += 10
        long_reasons.append("تقاطع MACD إيجابي")

    direction = "LONG"
    score = long_score
    reasons = long_reasons

    # شرط صارم: يجب أن توفر العملة إشارة بداية ترند حقيقية (فوليوم واختراق)
    is_ready = (score >= 65 and is_early_breakout and vol_ratio >= 1.3)

    # حساب مناطق الدخول والأهداف بحسب استراتيجية بداية الحركة
    entry_low = max(support, price - atr_1h * 0.2)
    entry_high = price
    stop = price - atr_1h * 1.1  # وقف خسارة محكم تحت سعر الانطلاق
    risk = price - stop
    risk = risk if risk > 0 else atr_1h
    
    tp1 = price + risk * 1.5
    tp2 = price + risk * 2.5
    tp3 = price + risk * 4.0

    reward = abs(tp2 - price)
    rr = (reward / risk) if risk > 0 else 0

    return {
        "symbol": symbol,
        "direction": direction,
        "score": score,
        "price": price,
        "entry_low": entry_low,
        "entry_high": entry_high,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "rsi": rsi_1h,
        "volume_ratio": vol_ratio,
        "support": support,
        "resistance": resistance,
        "atr": atr_1h,
        "risk_reward": rr,
        "reasons": reasons,
        "is_ready": is_ready,
    }

def scan_market() -> List[Dict]:
    symbols = get_usdt_symbols()
    results = []
    for symbol in symbols:
        try:
            result = analyze_symbol(symbol)
            if result and result.get("is_ready"):
                results.append(result)
        except Exception:
            pass
        time.sleep(0.02)
    results.sort(key=lambda x: (x["score"], x.get("risk_reward", 0)), reverse=True)
    return results

def format_number(value: float) -> str:
    value = float(value)
    if value >= 1000:
        return f"{value:.2f}"
    if value >= 1:
        return f"{value:.4f}".rstrip("0").rstrip(".")
    if value >= 0.01:
        return f"{value:.6f}".rstrip("0").rstrip(".")
    if value >= 0.0001:
        return f"{value:.8f}".rstrip("0").rstrip(".")
    return f"{value:.10f}".rstrip("0").rstrip(".")
