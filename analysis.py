import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional
import requests

# استخدام URL بديل ومباشر لبيانات بينانس لتفادي الحظر
BINANCE_BASE_URL = "https://fapi.binance.com" 
SESSION = requests.Session()
# إضافة Headers قوية توهم بينانس إن الطلب جاي من متصفح عادي
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Accept": "application/json"
})

def binance_get(endpoint: str, params: Optional[dict] = None):
    try:
        # تقليل وقت الانتظار وتغيير المسار
        res = SESSION.get(BINANCE_BASE_URL + endpoint, params=params or {}, timeout=5)
        if res.status_code == 200:
            return res.json()
        return None
    except:
        return None

def get_usdt_symbols() -> List[str]:
    # التحويل لبيانات العقود الآجلة لأنها أسرع وأكثر توفراً للبيانات
    data = binance_get("/fapi/v1/exchangeInfo")
    if not data or "symbols" not in data: return []
    return [s["symbol"] for s in data["symbols"] if s["symbol"].endswith("USDT") and s["status"] == "TRADING"][:30]

def get_klines(symbol: str, limit: int = 40):
    data = binance_get("/fapi/v1/klines", {"symbol": symbol, "interval": "1h", "limit": limit})
    if not data or not isinstance(data, list): return []
    try:
        return [{"close": float(r[4]), "high": float(r[2]), "low": float(r[3]), "volume": float(r[5])} for r in data]
    except: return []

# باقي الدوال (RSI, analyze_symbol) خليها زي ما هي..
# تأكد إنك استبدلت أي BINANCE_BASE_URL قديم بالجديد (https://fapi.binance.com)
