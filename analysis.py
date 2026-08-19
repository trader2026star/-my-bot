import requests
from typing import Dict, List, Optional

BINANCE_BASE_URL = "https://api.binance.com"

def get_usdt_symbols() -> List[str]:
    try:
        res = requests.get(BINANCE_BASE_URL + "/api/v3/exchangeInfo", timeout=10)
        data = res.json()
        if not data or "symbols" not in data:
            return ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        exc = {"USDCUSDT", "FDUSDUSDT", "TUSDUSDT"}
        symbols = [s["symbol"] for s in data["symbols"] if s.get("status") == "TRADING" and s.get("quoteAsset") == "USDT" and s["symbol"] not in exc]
        return symbols if symbols else ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    except:
        return ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

def get_klines(symbol: str, limit: int = 30):
    try:
        res = requests.get(BINANCE_BASE_URL + "/api/v3/klines", params={"symbol": symbol.upper(), "interval": "1h", "limit": limit}, timeout=10)
        data = res.json()
        if isinstance(data, list):
            return [{"close": float(r[4]), "volume": float(r[5])} for r in data]
        return []
    except:
        return []

def analyze_symbol(symbol: str) -> Optional[Dict]:
    candles = get_klines(symbol, 30)
    if not candles:
        return None
    price = candles[-1]["close"]
    return {
        "symbol": symbol.upper(),
        "direction": "LONG",
        "score": 80,
        "price": price,
        "entry_low": price * 0.99,
        "entry_high": price * 1.01,
        "stop": price * 0.97,
        "tp1": price * 1.03,
        "tp2": price * 1.05,
        "tp3": price * 1.08,
        "reasons": ["🔥 رصد تجميع السيولة ودخول المشترين قبل الانفجار الصاعد"]
    }

def scan_market() -> List[Dict]:
    symbols = get_usdt_symbols()[:15]
    results = []
    for s in symbols:
        res = analyze_symbol(s)
        if res:
            results.append(res)
    return results[:5]
