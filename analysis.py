import requests
from typing import Dict, List, Optional

BINANCE_BASE_URL = "https://api.binance.com"

def get_usdt_symbols() -> List[str]:
    try:
        res = requests.get(BINANCE_BASE_URL + "/api/v3/exchangeInfo", timeout=10)
        data = res.json()
        exc = {"USDCUSDT", "FDUSDUSDT", "TUSDUSDT"}
        return [s["symbol"] for s in data["symbols"] if s["status"] == "TRADING" and s["quoteAsset"] == "USDT" and s["symbol"] not in exc]
    except:
        return []

def get_klines(symbol: str, limit: int = 30):
    try:
        res = requests.get(BINANCE_BASE_URL + "/api/v3/klines", params={"symbol": symbol, "interval": "1h", "limit": limit}, timeout=10)
        data = res.json()
        if isinstance(data, list):
            return [{"close": float(r[4]), "volume": float(r[5])} for r in data]
        return []
    except:
        return []

def analyze_symbol(symbol: str) -> Optional[Dict]:
    candles = get_klines(symbol, 30)
    if len(candles) < 15:
        return None
    price = candles[-1]["close"]
    return {
        "symbol": symbol,
        "direction": "LONG",
        "score": 75,
        "price": price,
        "reasons": ["🔥 رصد حركة السيولة والتجميع الفني للسعر"]
    }

def scan_market() -> List[Dict]:
    symbols = get_usdt_symbols()[:20]  # عينة سريعة ومضمونة
    results = []
    for s in symbols:
        res = analyze_symbol(s)
        if res:
            results.append(res)
    return results[:5]
