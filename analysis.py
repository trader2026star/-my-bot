import requests

BINANCE_URL = "https://api.binance.com"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "CryptoZeroReversal/7.0"})

def api_get(path, params=None, timeout=10):
    try:
        r = SESSION.get(BINANCE_URL + path, params=params, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"Binance API error {path}: {e}")
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

# قائمة ضخمة وشاملة لأكثر من 80 عملة نشطة ومتنوعة في السوق لتفادي حظر exchangeInfo نهائياً
def get_usdt_symbols():
    return [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "TAOUSDT", "SEIUSDT", "ETCUSDT", 
        "DEXEUSDT", "AVAXUSDT", "SUIUSDT", "ADAUSDT", "XRPUSDT", "PEPEUSDT", 
        "RENDERUSDT", "NEARUSDT", "LINKUSDT", "DOGEUSDT", "FETUSDT", "ARBUSDT",
        "OPUSDT", "INJUSDT", "TIAUSDT", "ATOMUSDT", "MATICUSDT", "BNBUSDT",
        "SHIBUSDT", "WIFUSDT", "FLOKIUSDT", "BONKUSDT", "NEARUSDT", "APTUSDT",
        "POLUSDT", "ICPUSDT", "FILUSDT", "LDOUSDT", "FTMUSDT", "STXUSDT",
        "IMXUSDT", "RUNEUSDT", "NEARUSDT", "GRTUSDT", "UNIUSDT", "ATOMUSDT",
        "CRVUSDT", "AAVEUSDT", "SNXUSDT", "MKRUSDT", "DYDXUSDT", "GMXUSDT",
        "PENDLEUSDT", "IOSTUSDT", "CHZUSDT", "ENJUSDT", "SANDUSDT", "MANAUSDT",
        "AXSUSDT", "GALAUSDT", "THETAUSDT", "FTTUSDT", "ZECUSDT", "DASHUSDT",
        "BCHUSDT", "LTCUSDT", "XLMUSDT", "ALGOUSDT", "VETUSDT", "HBARUSDT",
        "EGLDUSDT", "KASUSDT", "JUPUSDT", "PYTHUSDT", "MANTAUSDT", "PORTALUSDT",
        "STRKUSDT", "AEVOUSDT", "BOMEUSDT", "SCAUSDT", "WLDUSDT", "TNSRUSDT"
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
        trend = "STRONG_UP"
    elif strong_down:
        trend = "STRONG_DOWN"
    elif e9 > e20:
        trend = "UP"
    elif e9 < e20:
        trend = "DOWN"
    else:
        trend = "SIDEWAYS"

    support = min(lows[-30:])
    resistance = max(highs[-30:])
    res_dist = (resistance - price) / price * 100
    sup_dist = (price - support) / price * 100

    location_high = max(highs[-20:])
    location_low = min(lows[-20:])
    location = ((price - location_low) / (location_high - location_low) * 100
                if location_high > location_low else 50)
    change20 = (price / closes[-21] - 1) * 100 if closes[-21] else 0

    accumulation = 0
    distribution = 0
    if pressure >= 52: accumulation += 30
    if pressure <= 48: distribution += 30
    if vol_ratio >= 1 and pressure >= 52: accumulation += 20
    if vol_ratio >= 1 and pressure <= 48: distribution += 20
    if change20 > -6 and location < 70 and pressure >= 52: accumulation += 20
    if change20 < 6 and location > 30 and pressure <= 48: distribution += 20
    accumulation = min(accumulation, 100)
    distribution = min(distribution, 100)

    long_score = 0
    short_score = 0
    if strong_up: long_score += 35
    elif trend == "UP": long_score += 25
    elif trend == "SIDEWAYS": long_score += 5
    if strong_down: short_score += 35
    elif trend == "DOWN": short_score += 25
    elif trend == "SIDEWAYS": short_score += 5

    if 50 <= rr <= 70: long_score += 15
    elif 55 <= rr <= 75: long_score += 8
    if 30 <= rr <= 50: short_score += 15
    elif 25 <= rr <= 45: short_score += 8
    if pressure >= 55: long_score += 20
    elif pressure >= 52: long_score += 12
    if pressure <= 45: short_score += 20
    elif pressure <= 48: short_score += 12
    if vol_ratio >= 1.5:
        long_score += 15; short_score += 15
    elif vol_ratio >= 1:
        long_score += 8; short_score += 8
    if accumulation >= 60: long_score += 15
    if distribution >= 55: short_score += 15
    if res_dist <= 3 and long_score >= short_score: long_score += 10
    if sup_dist <= 3 and short_score >= long_score: short_score += 10

    long_score = min(100, long_score)
    short_score = min(100, short_score)

    if long_score >= 70 and long_score >= short_score + 5:
        action = "🟢 LONG"; score = long_score
        status = "🔥 قبل الاختراق" if vol_ratio >= 1.2 and res_dist <= 5 else "🟢 تجميع + مراقبة دخول السيولة"
    elif short_score >= 70 and short_score >= long_score + 5:
        action = "🔴 SHORT"; score = short_score; status = "🔴 تصريف + خروج سيولة"
    else:
        action = "🟡 WAIT"; score = max(long_score, short_score)
        status = "🟢 تجميع + مراقبة دخول السيولة" if accumulation >= 60 else "⚪ حركة عادية"

    out = {
        "symbol": symbol, "action": action, "score": f"{score}/100", "status": status,
        "price": fmt(price), "rsi": f"{rr:.1f}", "volume": f"{vol_ratio:.2f}x",
        "buy_pressure": f"{pressure:.1f}%", "trend": trend,
        "support": fmt(support), "resistance": fmt(resistance), "analysis_lines": []
    }

    if action == "🟢 LONG":
        entry_low = price * 0.9944
        sl = support * 0.994
        risk = max(price - sl, price * 0.02)
        out.update(entry_range=f"{fmt(entry_low)} - {fmt(price)}", stop_loss=fmt(sl),
                   tp1=fmt(price + risk*1.5), tp2=fmt(price + risk*2.4), tp3=fmt(price + risk*3.75))
    elif action == "🔴 SHORT":
        entry_high = price * 1.0144
        sl = resistance * 1.013
        risk = max(sl - price, price * 0.01)
        out.update(entry_range=f"{fmt(price)} - {fmt(entry_high)}", stop_loss=fmt(sl),
                   tp1=fmt(max(price-risk*1.5, 0)), tp2=fmt(max(price-risk*2.4, 0)), tp3=fmt(max(price-risk*3.75, 0)))

    lines = []
    if strong_up: lines.append("• الترند صاعد بقوة: EMA9 > EMA20 > EMA50")
    elif strong_down: lines.append("• الترند هابط بقوة: EMA9 < EMA20 < EMA50")
    elif trend == "UP": lines.append("• الترند العام صاعد")
    elif trend == "DOWN": lines.append("• الترند العام هابط")
    if action == "🟢 LONG" or accumulation >= 60:
        lines.append(f"• تجميع محتمل قبل الحركة — قوة التجميع {max(60, accumulation)}/100")
    elif action == "🔴 SHORT" or distribution >= 55:
        lines.append(f"• علامات تصريف وخروج سيولة — قوة {max(55, distribution)}/100")
    if res_dist <= 5 and action == "🟢 LONG": lines.append("• السعر قريب من مقاومة مع تحسن الحجم والسيولة")
    if pressure > 52: lines.append("• ضغط شراء أعلى من المتوسط")
    elif pressure < 48: lines.append("• ضغط البيع أعلى من ضغط الشراء")
    if vol_ratio >= 1.2: lines.append(f"• الحجم أعلى من متوسطه بحوالي {vol_ratio:.2f}x")
    elif vol_ratio > .8: lines.append("• الحجم بدأ في الارتفاع")
    if 45 <= rr <= 70: lines.append("• RSI في منطقة تسمح باستمرار الحركة بدون تشبع شديد")
    elif rr < 30 and action == "🟡 WAIT": lines.append("• RSI منخفض لكن لا توجد إشارة انعكاس مؤكدة")
    if pressure > 52: lines.append("• تدفق السيولة يميل للمشترين")
    elif pressure < 48: lines.append("• تدفق السيولة يميل للبائعين")
    if action == "🟡 WAIT" and strong_down and rr < 30: lines.append("• ⚠️ العملة منهارة وممتدة هبوطياً — لا نطارد الهبوط")
    out["analysis_lines"] = lines
    return out

def get_coin_analysis(symbol_input):
    symbol = symbol_input.upper().strip()
    if not symbol.endswith("USDT"): symbol += "USDT"
    return analyze_symbol(symbol)

def scan_market(limit=10):
    results = []
    # فحص جميع العملات في القائمة الكبيرة بدقة فائقة
    for symbol in get_usdt_symbols():
        try:
            data = analyze_symbol(symbol)
            if data and data["action"] != "🟡 WAIT": 
                results.append(data)
        except Exception as e:
            pass
    results.sort(key=lambda x: int(x["score"].split("/")[0]), reverse=True)
    return results if limit is None else results[:limit]

def generate_evidence_report(data):
    if not data: return "⚠️ عذراً، لم يتم العثور على بيانات لهذه العملة أو الرمز غير صحيح."
    report = (
        "🤖 **Binance AI Scanner**\n\n"
        f"💎 **العملة:** `{data['symbol']}`\n"
        f"📈 **الاتجاه:** `{data['action']}`\n"
        f"⭐ **Score:** `{data['score']}`\n"
        f"🧠 **الحالة:** `{data['status']}`\n\n"
        f"💰 **السعر:** `{data['price']}`\n"
        f"📊 **RSI:** `{data['rsi']}`\n"
        f"📊 **Volume:** `{data['volume']}`\n"
        f"💧 **Buy Pressure:** `{data['buy_pressure']}`\n"
        f"📈 **Trend:** `{data['trend']}`\n\n"
    )
    if data['action'] != "🟡 WAIT":
        report += (f"📍 **منطقة الدخول**\n`{data['entry_range']}`\n\n"
                   f"🛑 **Stop Loss**\n`{data['stop_loss']}`\n\n"
                   f"🎯 **الأهداف**\nTP1: `{data['tp1']}`\nTP2: `{data['tp2']}`\nTP3: `{data['tp3']}`\n\n")
    report += (f"🛡️ **الدعم والمقاومة**\nSupport: `{data['support']}`\nResistance: `{data['resistance']}`\n\n"
               "🔍 **التحليل**\n" + "\n".join(data['analysis_lines']) + "\n\n")
    report += "🟡 **الحالة:** انتظار تأكيد — لا تطارد السعر" if data['action'] == "🟡 WAIT" else "✅ **الصفقة:** جاهزة للمراقبة/الدخول حسب تأكيد السعر"
    return report
