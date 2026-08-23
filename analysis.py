import requests

BINANCE_URL = "https://api.binance.com"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "CryptoZeroReversal/7.0"})

def api_get(path, params=None, timeout=10):
    try:
        r = SESSION.get(BINANCE_URL + path, params=params, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None

def ema(values, period):
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    value = sum(values[:period]) / period
    for price in values[period:]:
        value = price * k + value * (1 - k)
    return value

def rsi(values, period=14):
    if len(values) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(values)):
        d = values[i] - values[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        ag = (ag * (period - 1) + gains[i]) / period
        al = (al * (period - 1) + losses[i]) / period
    if al == 0:
        return 100.0
    return 100 - (100 / (1 + ag / al))

def fmt(x):
    if x is None:
        return "-"
    if x >= 1000:
        return f"{x:,.2f}"
    if x >= 1:
        return f"{x:.4f}"
    if x >= 0.1:
        return f"{x:.5f}"
    if x >= 0.01:
        return f"{x:.6f}"
    return f"{x:.8f}"

def get_klines(symbol, interval="15m", limit=120):
    return api_get("/api/v3/klines", {"symbol": symbol, "interval": interval, "limit": limit})

def get_usdt_symbols():
    return [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "TAOUSDT", "SEIUSDT", "ETCUSDT", 
        "AVAXUSDT", "SUIUSDT", "ADAUSDT", "XRPUSDT", "PEPEUSDT", "RENDERUSDT", 
        "NEARUSDT", "LINKUSDT", "DOGEUSDT", "FETUSDT", "ARBUSDT", "OPUSDT"
    ]

def analyze_symbol(symbol):
    k = get_klines(symbol)
    if not k or len(k) < 60:
        return None

    closes = [float(x[4]) for x in k]
    highs = [float(x[2]) for x in k]
    lows = [float(x[3]) for x in k]
    vols = [float(x[5]) for x in k]

    price = closes[-1]
    e9, e20, e50 = ema(closes, 9), ema(closes, 20), ema(closes, 50)
    rr = rsi(closes)
    if None in (e9, e20, e50, rr):
        return None

    avg_vol = sum(vols[-21:-1]) / 20
    vol_ratio = vols[-1] / avg_vol if avg_vol else 0

    buy = sell = 0.0
    for x in k[-20:]:
        o, h, l, c, v = map(float, x[1:6])
        rng = max(h - l, 1e-12)
        buy += v * max(c - l, 0) / rng
        sell += v * max(h - c, 0) / rng
    total = buy + sell
    pressure = buy / total * 100 if total else 50.0

    strong_up = e9 > e20 > e50
    strong_down = e9 < e20 < e50
    if strong_up:
        trend = "صاعد قوي"
    elif strong_down:
        trend = "هابط قوي"
    elif e9 > e20:
        trend = "صاعد"
    elif e9 < e20:
        trend = "هابط"
    else:
        trend = "جانبي"

    support = min(lows[-30:])
    resistance = max(highs[-30:])

    long_score = 50
    short_score = 50
    if strong_up: long_score += 25
    if strong_down: short_score += 25
    if 50 <= rr <= 70: long_score += 15
    if 30 <= rr <= 50: short_score += 15
    if pressure >= 52: long_score += 10
    if pressure <= 48: short_score += 10

    if long_score >= short_score:
        action = "صعود (LONG)"
        score = min(long_score, 100)
        status = "تجميع وإيجابية"
    else:
        action = "هبوط (SHORT)"
        score = min(short_score, 100)
        status = "تصريف وسلبية"

    out = {
        "symbol": symbol, "action": action, "score": f"{score}/100", "status": status,
        "price": fmt(price), "rsi": f"{rr:.1f}", "volume": f"{vol_ratio:.2f}x",
        "buy_pressure": f"{pressure:.1f}%", "trend": trend,
        "support": fmt(support), "resistance": fmt(resistance)
    }

    if "LONG" in action:
        risk = max(price - support, price * 0.015)
        out.update(
            entry_range=f"{fmt(price * 0.995)} - {fmt(price)}",
            stop_loss=fmt(support * 0.99),
            tp1=fmt(price + risk * 1.5),
            tp2=fmt(price + risk * 2.5),
            tp3=fmt(price + risk * 3.5)
        )
    else:
        risk = max(resistance - price, price * 0.015)
        out.update(
            entry_range=f"{fmt(price)} - {fmt(price * 1.005)}",
            stop_loss=fmt(resistance * 1.01),
            tp1=fmt(max(price - risk * 1.5, 0)),
            tp2=fmt(max(price - risk * 2.5, 0)),
            tp3=fmt(max(price - risk * 3.5, 0))
        )
    return out

def get_coin_analysis(symbol_input):
    symbol = symbol_input.upper().strip()
    if not symbol.endswith("USDT"): symbol += "USDT"
    return analyze_symbol(symbol)

def scan_market(limit=5):
    results = []
    for symbol in get_usdt_symbols():
        data = analyze_symbol(symbol)
        if data:
            results.append(data)
    results.sort(key=lambda x: int(x["score"].split("/")[0]), reverse=True)
    return results[:limit]

def generate_evidence_report(data):
    if not data:
        return "عذراً، لم يتم العثور على بيانات لهذه العملة."
    
    report = (
        f"تقرير تحليل العملة: {data['symbol']}\n"
        f"الاتجاه المقترح: {data['action']}\n"
        f"التقييم: {data['score']}\n"
        f"الحالة: {data['status']}\n\n"
        f"السعر الحالي: {data['price']}\n"
        f"مؤشر القوة RSI: {data['rsi']}\n"
        f"حجم التداول: {data['volume']}\n"
        f"ضغط الشراء: {data['buy_pressure']}\n"
        f"الاتجاه العام: {data['trend']}\n\n"
        f"منطقة الدخول: {data['entry_range']}\n"
        f"وقف الخسارة: {data['stop_loss']}\n"
        f"الهدف الأول: {data['tp1']}\n"
        f"الهدف الثاني: {data['tp2']}\n"
        f"الهدف الثالث: {data['tp3']}\n\n"
        f"الدعم القريب: {data['support']}\n"
        f"المقاومة القريبة: {data['resistance']}"
    )
    return report
