import time
from decimal import Decimal
from typing import Dict, List, Optional
import requests

BINANCE_BASE_URL = "https://data-api.binance.vision"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Binance-AI-Scanner/2.0", "Accept": "application/json"})

def binance_get(endpoint: str, params: Optional[dict] = None):
    res = SESSION.get(BINANCE_BASE_URL + endpoint, params=params or {}, timeout=15)
    res.raise_for_status()
    data = res.json()
    if isinstance(data, dict) and data.get("code"):
        raise RuntimeError(f"API Error {data.get('code')}")
    return data

def get_usdt_symbols() -> List[str]:
    data = binance_get("/api/v3/exchangeInfo")
    exc = {"USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "DAIUSDT", "EURUSDT", "TRYUSDT", "BRLUSDT", "GBPUSDT", "AUDUSDT", "USDPUSDT"}
    return [s["symbol"] for s in data.get("symbols", []) if s.get("status") == "TRADING" and s.get("quoteAsset") == "USDT" and s["symbol"] not in exc]

def get_klines(symbol: str, limit: int = 60):
    data = binance_get("/api/v3/klines", {"symbol": symbol, "interval": "1h", "limit": limit})
    return [{"close": float(r[4]), "high": float(r[2]), "low": float(r[3]), "volume": float(r[5])} for r in data]

def rsi(values: List[float], period: int = 14) -> List[Optional[float]]:
    res = [None] * len(values)
    if len(values) <= period: return res
    gains, losses = [], []
    for i in range(1, len(values)):
        diff = values[i] - values[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        ag = (ag * (period - 1) + gains[i]) / period
        al = (al * (period - 1) + losses[i]) / period
        rs = ag / (al if al != 0 else 0.001)
        res[i+1] = 100 - (100 / (1 + rs))
    return res

def analyze_symbol(symbol: str) -> Optional[Dict]:
    try:
        candles = get_klines(symbol, 60)
        if len(candles) < 30: return None
        closes = [c["close"] for c in candles]
        
        r = rsi(closes, 14)[-1]
        if r is None or r > 60: return None
        
        recent = candles[-10:]
        highs = [c["high"] for c in recent]
        lows = [c["low"] for c in recent]
        vols = [c["volume"] for c in recent]
        
        pr_range = (max(highs) - min(lows)) / min(lows)
        vol_up = vols[-1] > vols[-2] > vols[-3]
        res_val = max(highs)
        price = closes[-1]
        near_res = (res_val - price) / res_val < 0.015
        
        if pr_range < 0.025 and vol_up and near_res:
            return {
                "symbol": symbol,
                "price": price,
                "resistance": res_val,
                "reasons": ["🔍 رصد تجميع سعري ضيق", "🚀 فوليوم متصاعد قبل الانفجار", "🎯 قريبة جداً من المقاومة"],
                "is_ready": True
            }
    except:
        pass
    return None

def scan_market() -> List[Dict]:
    results = []
    for s in get_usdt_symbols():
        res = analyze_symbol(s)
        if res: results.append(res)
        time.sleep(0.02)
    return results
