import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional
import requests

BINANCE_BASE_URL = "https://data-api.binance.vision"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Binance-AI-Scanner/2.0", "Accept": "application/json"})

def format_number(val: float) -> str:
    if val is None:
        return "0"
    if val >= 1:
        return f"{val:.2f}"
    elif val >= 0.0001:
        return f"{val:.4f}"
    else:
        return f"{val:.8f}"

def binance_get(endpoint: str, params: Optional[dict] = None):
    try:
        res = SESSION.get(BINANCE_BASE_URL + endpoint, params=params or {}, timeout=10)
        res.raise_for_status()
        data = res.json()
        if isinstance(data, dict) and data.get("code"):
            return None
        return data
    except:
        return None

def get_usdt_symbols() -> List[str]:
    data = binance_get("/api/v3/exchangeInfo")
    if not data or "symbols" not in data:
        return []
    exc = {"USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "DAIUSDT", "EURUSDT", "TRYUSDT", "BRLUSDT", "GBPUSDT", "AUDUSDT", "USDPUSDT"}
    return [s["symbol"] for s in data["symbols"] if s.get("status") == "TRADING" and s.get("quoteAsset") == "USDT" and s["symbol"] not in exc]

def get_klines(symbol: str, limit: int = 50):
    data = binance_get("/api/v3/klines", {"symbol": symbol, "interval": "1h", "limit": limit})
    if not data or not isinstance(data, list):
        return []
    try:
        return [{"close": float(r[4]), "high": float(r[2]), "low": float(r[3]), "volume": float(r[5])} for r in data]
    except:
        return []

def calculate_rsi(closes: List[float], period: int = 14) -> float:
    if len(closes) <= period:
        return 50.0
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        diff = closes[i] - closes[i-1]
        if diff >= 0:
            gains += diff
        else:
            losses -= diff
    avg_gain = gains / period
    avg_loss = losses / period
    
    for i in range(period + 1, len(closes)):
        diff = closes[i] - closes[i-1]
        if diff >= 0:
            avg_gain = (avg_gain * (period - 1) + diff) / period
            avg_loss = (avg_loss * (period - 1)) / period
        else:
            avg_gain = (avg_gain * (period - 1)) / period
            avg_loss = (avg_loss * (period - 1) - diff) / period
            
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def analyze_symbol(symbol: str) -> Optional[Dict]:
    candles = get_klines(symbol, 40)
    if len(candles) < 25:
        return None
    
    closes = [c["close"] for c in candles]
    volumes = [c["volume"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    
    price = closes[-1]
    rsi_val = calculate_rsi(closes, 14)
    
    # قياس دخول السيولة (مقارنة فوليوم آخر شمعة بمتوسط آخر 10 شمعات)
    avg_volume = sum(volumes[-11:-1]) / 10 if len(volumes) >= 11 else volumes[-1]
    vol_ratio = volumes[-1] / avg_volume if avg_volume > 0 else 1.0
    
    recent_high = max(highs[-10:])
    recent_low = min(lows[-10:])
    price_range = (recent_high - recent_low) / recent_low
    
    # شروط الانفجار وتجميع السيولة (فوليوم عالي + تجميع ضيق + RSI مناسب)
    is_volume_spike = vol_ratio >= 1.6
    is_tight_range = price_range <= 0.035
    is_near_resistance = (recent_high - price) / recent_high <= 0.02
    
    reasons = []
    score = 50
    
    if is_volume_spike:
        reasons.append(f"🔥 دخول سيولة ضخمة (الفوليوم {vol_ratio:.1f}x من المتوسط)")
        score += 20
    if is_tight_range:
        reasons.append("🔍 تجميع سعري ضيق يسبق الانفجار")
        score += 15
    if is_near_resistance:
        reasons.append("🎯 تختبر منطقة المقاومة للاختراق")
        score += 15
        
    # إذا تحققت شروط السيولة والانفجار
    if is_volume_spike and (is_tight_range or is_near_resistance) and rsi_val < 70:
        return {
            "symbol": symbol,
            "direction": "LONG",
            "score": min(score, 98),
            "price": price,
            "rsi": rsi_val,
            "volume_ratio": vol_ratio,
            "entry_low": price * 0.995,
            "entry_high": price * 1.002,
            "stop": recent_low * 0.985,
            "tp1": recent_high * 1.02,
            "tp2": recent_high * 1.05,
            "tp3": recent_high * 1.09,
            "support": recent_low,
            "resistance": recent_high,
            "reasons": reasons,
            "is_ready": True
        }
    return None

def scan_market() -> List[Dict]:
    symbols = get_usdt_symbols()
    results = []
    
    # فحص سريع ومتوازي لكل العملات لضمان أعلى أداء
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_symbol = {executor.submit(analyze_symbol, s): s for s in symbols}
        for future in as_completed(future_to_symbol):
            res = future.result()
            if res:
                results.append(res)
                
    # ترتيب العملات حسب أقوى دخول سيولة وسكور
    results = sorted(results, key=lambda x: x["score"], reverse=True)
    return results
