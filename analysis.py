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
    response = SESSION.get(BINANCE_BASE_URL + endpoint, params=params or {}, timeout=15)
    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict) and data.get("code"):
        raise RuntimeError(f"Binance API error {data.get('code')}: {data.get('msg')}")
    return data

def get_usdt_symbols() -> List[str]:
    data = binance_get("/api/v3/exchangeInfo")
    excluded = {"USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "DAIUSDT", "EURUSDT", "TRYUSDT", "BRLUSDT", "GBPUSDT", "AUDUSDT", "USDPUSDT"}
    return [item["symbol"] for item in data.get("symbols", []) if item.get("status") == "TRADING" and item.get("quoteAsset") == "USDT" and item.get("symbol") not in excluded]

def get_klines(symbol: str, interval: str = "1h", limit: int = 100):
    data = binance_get("/api/v3/klines", {"symbol": symbol, "interval": interval, "limit": limit})
    return [{"close": float(row[4]), "high": float(row[2]), "low": float(row[3]), "volume": float(row[5])} for row in data]

def rsi(values: List[float], period: int = 14) -> List[Optional[float]]:
    result = [None] * len(values)
    if len(values) <= period: return result
    gains, losses = [], []
    for i in range(1, len(values)):
        diff = values[i] - values[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rs = avg_gain / (avg_loss if avg_loss != 0 else 0.001)
        result[i+1] = 100 - (100 / (1 + rs))
    return result

def is_accumulation_phase(candles: List[dict], lookback: int = 10):
    if len(candles) < lookback + 5: return False
    recent = candles[-lookback:]
    highs = [c["high"] for c in recent]
    lows = [c["low"] for c in recent]
    volumes = [c["volume"] for c in recent]
    
    price_range = (max(highs) - min(lows)) / min(lows)
    volume_increasing = volumes[-1] > volumes[-2] > volumes[-3]
    resistance = max(highs)
    price = candles[-1]["close"]
    near_resistance = (resistance - price) / resistance < 0.015
    
    return price_range < 0.025 and volume_increasing and near_resistance

def analyze_symbol(symbol: str) -> Optional[Dict]:
    try:
        candles = get_klines(symbol, "1h", 60)
        if len(candles) < 30: return None
        closes = [c["close"] for c in candles]
        
        rsi_val = rsi(closes, 14)[-1]
        if rsi_val is None or rsi_val > 60: return None
        
        if not is_accumulation_phase(candles): return None
        
        price = closes[-1]
        resistance = max(c["high"] for c in candles[-20:])
        
        return {
            "symbol": symbol,
            "price": price,
            "resistance": resistance,
            "reasons": ["🔍 رصد تجميع سعري ضيق", "🚀 فوليوم متصاعد قبل الانفجار", "🎯 قريبة جداً من المقاومة"],
            "is_ready": True
        }
    except: return None

def scan_market() -> List[Dict]:
    symbols = get_usdt_symbols()
    results = []
    for symbol in symbols:
        res = analyze_symbol(symbol)
        if res: results.append(res)
        time.sleep(0.02)
    return results
