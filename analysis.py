# =========================================================
# analysis.py - BingX Ultra Safe Pure SMC Scanner v34.1
# (Institutional Grade Upgrade + Dynamic SL + Entry Quality + No Chase)
# =========================================================

import time
import logging
import threading
import requests

BINGX_URL = 'https://open-api.bingx.com'
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'BingX-UltraSMC/34.1', 'Accept': 'application/json'})
logger = logging.getLogger(__name__)

SYMBOL_CACHE_SECONDS = 600
KLINE_CACHE_SECONDS = 45
PRICE_CACHE_SECONDS = 3
TICKER_CACHE_SECONDS = 5
MIN_REQUEST_INTERVAL = 0.3
_RATE_LIMIT_UNTIL = 0.0
_LAST_REQUEST_TIME = 0.0
_SYMBOL_CACHE = set()
_SYMBOL_CACHE_TIME = 0.0
_KLINE_CACHE = {}
_PRICE_CACHE = {}
_TICKER_CACHE = None
_TICKER_CACHE_TIME = 0.0
_RATE_LOCK = threading.Lock()
_REQUEST_LOCK = threading.Lock()


def normalize_symbol(s):
    s = str(s).strip().upper().replace(' ', '').replace('-', '').replace('_', '').replace('/', '')
    if not s.endswith('USDT'):
        s = s + '-USDT' if '-' not in s else s
    if s.endswith('USDT') and '-' not in s:
        s = s[:-4] + '-USDT'
    return s


def bingx_get(path, params=None, timeout=12):
    global _RATE_LIMIT_UNTIL, _LAST_REQUEST_TIME
    with _RATE_LOCK:
        if time.time() < _RATE_LIMIT_UNTIL: return None
    with _REQUEST_LOCK:
        wait = MIN_REQUEST_INTERVAL - (time.time() - _LAST_REQUEST_TIME)
        if wait > 0: time.sleep(wait)
        _LAST_REQUEST_TIME = time.time()
    try:
        r = SESSION.get(BINGX_URL + path, params=params or {}, timeout=timeout)
        if r.status_code != 200:
            if r.status_code == 429:
                with _RATE_LOCK: _RATE_LIMIT_UNTIL = max(_RATE_LIMIT_UNTIL, time.time() + 60)
            return None
        d = r.json()
        if isinstance(d, dict) and d.get('code', 0) == 0:
            return d.get('data')
        return d.get('data') if isinstance(d, dict) and 'data' in d else d
    except Exception:
        return None


def get_futures_symbols(force_refresh=False):
    global _SYMBOL_CACHE, _SYMBOL_CACHE_TIME
    if not force_refresh and _SYMBOL_CACHE and time.time()-_SYMBOL_CACHE_TIME < SYMBOL_CACHE_SECONDS:
        return set(_SYMBOL_CACHE)
    d = bingx_get('/openApi/swap/v2/quote/contracts')
    out = set()
    rows = []
    if isinstance(d, dict):
        rows = d.get('contracts', [])
    elif isinstance(d, list):
        rows = d
    for x in rows:
        if isinstance(x, dict):
            s = str(x.get('symbol', '')).upper()
            if s:
                out.add(s)
                out.add(normalize_symbol(s))
    if out:
        _SYMBOL_CACHE, _SYMBOL_CACHE_TIME = out, time.time()
        return set(_SYMBOL_CACHE)
    return set(_SYMBOL_CACHE)


def symbol_exists(s):
    sy = get_futures_symbols()
    return not sy or normalize_symbol(s) in sy or s in sy


def _ticker_rows(force=False):
    global _TICKER_CACHE, _TICKER_CACHE_TIME
    if not force and _TICKER_CACHE is not None and time.time()-_TICKER_CACHE_TIME < TICKER_CACHE_SECONDS:
        return _TICKER_CACHE
    x = bingx_get('/openApi/swap/v2/quote/ticker')
    if isinstance(x, list):
        _TICKER_CACHE, _TICKER_CACHE_TIME = x, time.time()
        return x
    elif isinstance(x, dict) and 'tickers' in x:
        _TICKER_CACHE, _TICKER_CACHE_TIME = x['tickers'], time.time()
        return x['tickers']
    return []


def get_funding_rate(symbol):
    symbol = normalize_symbol(symbol)
    d = bingx_get('/openApi/swap/v2/quote/premiumIndex', {'symbol': symbol})
    if isinstance(d, dict):
        try:
            return float(d.get('fundingRate', 0))
        except Exception:
            pass
    return 0.015


def _parse(rows):
    out = []
    if not isinstance(rows, list):
        return out
    for x in rows:
        try:
            if isinstance(x, dict):
                t = int(x.get('time', x.get('openTime', 0)))
                o = float(x.get('open', 0))
                h = float(x.get('high', 0))
                l = float(x.get('low', 0))
                c = float(x.get('close', 0))
                v = float(x.get('volume', 0))
                if t > 0 and c > 0:
                    out.append([t, o, h, l, c, v])
            elif isinstance(x, list) and len(x) >= 6:
                t, o, h, l, c, v = x[:6]
                out.append([int(t), float(o), float(h), float(l), float(c), float(v or 0)])
        except Exception:
            pass
    try:
        out.sort(key=lambda z: z[0])
    except Exception:
        pass
    seen = set(); clean = []
    for x in out:
        if x[0] in seen: continue
        seen.add(x[0]); clean.append(x)
    return clean


def get_bingx_klines(s, interval='1h', limit=100):
    s = normalize_symbol(s)
    key = (s, str(interval).lower(), int(limit))
    now = time.time()
    c = _KLINE_CACHE.get(key)
    if c and now - c[0] < KLINE_CACHE_SECONDS: return c[1]
    
    mp = {'1m': '1m', '5m': '5m', '15m': '15m', '30m': '30m', '1h': '1h', '4h': '4h', '1d': '1d'}
    bi = mp.get(str(interval).lower(), '1h')
    
    d = bingx_get('/openApi/swap/v2/quote/klines', {'symbol': s, 'interval': bi, 'limit': int(limit)})
    r = _parse(d)
    if r and len(r) > 0:
        _KLINE_CACHE[key] = (now, r)
        return r
    return None


def get_current_price(s, force=False):
    s = normalize_symbol(s)
    now = time.time()
    c = _PRICE_CACHE.get(s)
    if not force and c and now - c[0] < PRICE_CACHE_SECONDS: return c[1]
    
    d = bingx_get('/openApi/swap/v2/quote/price', {'symbol': s})
    if isinstance(d, dict) and 'price' in d:
        try:
            p = float(d.get('price', 0))
            if p > 0:
                _PRICE_CACHE[s] = (now, p)
                return p
        except Exception:
            pass
            
    rows = _ticker_rows()
    for x in rows:
        if isinstance(x, dict) and str(x.get('symbol', '')).upper() in [s, s.replace('-', '')]:
            try:
                p = float(x.get('lastPrice', x.get('price', 0)))
                if p > 0:
                    _PRICE_CACHE[s] = (now, p)
                    return p
            except Exception:
                pass
                
    k = get_bingx_klines(s, '1m', 5)
    if k and len(k) > 0 and k[-1][4] > 0:
        _PRICE_CACHE[s] = (now, k[-1][4])
        return k[-1][4]
    return None


def calculate_rsi(c, period=14):
    if len(c) < period + 1: return 50.0
    g = [max(c[i]-c[i-1], 0) for i in range(1, len(c))]
    l = [max(c[i-1]-c[i], 0) for i in range(1, len(c))]
    ag = sum(g[:period]) / period
    al = sum(l[:period]) / period
    for i in range(period, len(g)):
        ag = (ag * (period - 1) + g[i]) / period
        al = (al * (period - 1) + l[i]) / period
    return 100.0 if al == 0 else round(100 - 100 / (1 + ag / al), 2)


def calculate_atr(k, n=14):
    if len(k) < n + 1: return None
    tr = [max(x[2]-x[3], abs(x[2]-k[i-1][4]), abs(x[3]-k[i-1][4])) for i, x in enumerate(k[1:], 1)]
    a = sum(tr[:n]) / n
    for x in tr[n:]: a = (a * (n - 1) + x) / n
    return a


def smart_round(v):
    if v is None: return 0
    try: v = float(v)
    except Exception: return 0
    if v >= 1000: return round(v, 2)
    if v >= 100: return round(v, 3)
    if v >= 1: return round(v, 4)
    if v >= 0.1: return round(v, 5)
    return round(v, 8)


# ---------------------------------------------------------
# الدوال التحليلية المؤسسية المتقدمة (v34.1 Modules)
# ---------------------------------------------------------

def check_liquidity_sweep(klines):
    """التحقق من حصول Liquidity Sweep (اختراق سيولة ثم ارتداد/Rejection)"""
    if not klines or len(klines) < 15:
        return False, "NOT CONFIRMED"
    
    highs = [x[2] for x in klines[-15:-2]]
    lows = [x[3] for x in klines[-15:-2]]
    prev_high = max(highs)
    prev_low = min(lows)
    
    last_candle = klines[-1]
    curr_high = last_candle[2]
    curr_low = last_candle[3]
    curr_close = last_candle[4]
    curr_open = last_candle[1]
    
    # Sell-side sweep (كسر القاع السابق ثم الإغلاق فوقه أو دونه بشكل ارتدادي)
    if curr_low < prev_low and curr_close > prev_low:
        return True, "CONFIRMED (Sell-side Liquidity Swept & Rejected)"
    # Buy-side sweep (اختراق القمة السابقة ثم الإغلاق تحتها)
    elif curr_high > prev_high and curr_close < prev_high:
        return True, "CONFIRMED (Buy-side Liquidity Swept & Rejected)"
        
    return False, "NOT CONFIRMED"


def check_mss_bos(klines):
    """التحقق من وجود كسر هيكلي MSS أو BOS"""
    if not klines or len(klines) < 20:
        return False, "NOT CONFIRMED"
    
    highs = [x[2] for x in klines[-20:-2]]
    lows = [x[3] for x in klines[-20:-2]]
    recent_high = max(highs)
    recent_low = min(lows)
    
    current_close = klines[-1][4]
    prev_close = klines[-2][4]
    
    if current_close > recent_high and prev_close <= recent_high:
        return True, "BOS CONFIRMED"
    elif current_close < recent_low and prev_close >= recent_low:
        return True, "MSS CONFIRMED"
        
    # تحقق من الشمعة الحالية كسر هيكلي مصغر
    if current_close > highs[-1]:
        return True, "MSS/BOS CONFIRMED"
        
    return False, "NOT CONFIRMED"


def check_fvg_presence(klines, direction):
    """التحقق من وجود فجوة القيمة العادلة FVG"""
    if not klines or len(klines) < 5:
        return False
    for i in range(len(klines) - 4, len(klines) - 1):
        if direction == 'LONG':
            if klines[i+2][3] > klines[i][2]:
                return True
        elif direction == 'SHORT':
            if klines[i+2][2] < klines[i][3]:
                return True
    return False


def check_volume_confirmation(klines):
    """فحص دعم حجم التداول (Volume Confirmation)"""
    if not klines or len(klines) < 20:
        return False, "WEAK"
    volumes = [x[5] for x in klines[-20:-1]]
    avg_vol = sum(volumes) / len(volumes) if volumes else 0
    last_vol = klines[-1][5]
    if last_vol >= avg_vol * 1.15:
        return True, "CONFIRMED"
    return False, "WEAK"


def get_btc_correlation_status():
    """فحص ارتباط البيتكوين"""
    btc_k = get_bingx_klines("BTC-USDT", '1h', 15)
    if not btc_k:
        return "ALIGNED", True
    closes = [x[4] for x in btc_k]
    rsi = calculate_rsi(closes)
    if rsi < 30 or closes[-1] < closes[-3]:
        return "CONFLICTED / BEARISH", False
    return "ALIGNED", True


# ---------------------------------------------------------
# المحرك الأساسي المحدث للتحليل (Core Analysis Engine v34.1)
# ---------------------------------------------------------

def _get_coin_analysis_core(symbol, interval='1h'):
    symbol = normalize_symbol(symbol)
    p = get_current_price(symbol, True)
    if not p or p <= 0: 
        raise ValueError(f"Price error for {symbol}")

    k1 = get_bingx_klines(symbol, interval, 100)
    if not k1 or len(k1) < 30: 
        return _get_blocked_signal(symbol, p, "بيانات السوق غير كافية", interval)

    c = [x[4] for x in k1]
    rsi = calculate_rsi(c)
    atr = calculate_atr(k1) or (p * 0.015)

    highs = [x[2] for x in klines_h := k1]
    lows = [x[3] for x in k1]
    closes = [x[4] for x in k1]
    opens = [x[1] for x in k1]

    swing_high = max(highs[-20:-2])
    swing_low = min(lows[-20:-2])

    # تحديد الأوردر بلوك (Order Block)
    bullish_ob = lows[-3]
    for i in range(len(k1)-2, max(len(k1)-15, 2), -1):
        if closes[i] < opens[i]:
            bullish_ob = lows[i]
            break

    bearish_ob = highs[-3]
    for i in range(len(k1)-2, max(len(k1)-15, 2), -1):
        if closes[i] > opens[i]:
            bearish_ob = highs[i]
            break

    # تحديد الاتجاه الأولي من هيكل الـ SMC
    current_close = closes[-1]
    if current_close >= closes[-10]:
        base_direction = 'LONG'
        ob_level = bullish_ob
    else:
        base_direction = 'SHORT'
        ob_level = bearish_ob

    # ---------------------------------------------------------
    # 2) RSI Overextension Filter & 3) NO CHASE Protection
    # ---------------------------------------------------------
    distance_from_ob = abs(p - ob_level) / p * 100
    is_overextended = (base_direction == 'LONG' and rsi >= 80) or (base_direction == 'SHORT' and rsi <= 20)
    is_no_chase = distance_from_ob > 2.5  # مسافة تبعد عن OB بأكثر من 2.5%

    # ---------------------------------------------------------
    # فحص شروط الـ Confirmations والـ Triggers
    # ---------------------------------------------------------
    sweep_ok, sweep_desc = check_liquidity_sweep(k1)
    mss_ok, mss_desc = check_mss_bos(k1)
    fvg_ok = check_fvg_presence(k1, base_direction)
    vol_ok, vol_desc = check_volume_confirmation(k1)
    btc_status_str, btc_aligned = get_btc_correlation_status()

    # ---------------------------------------------------------
    # 5) Entry Quality Score (تقييم جودة الدخول من 100)
    # ---------------------------------------------------------
    eq_structure = 20 if mss_ok else 10
    eq_ob = 20 if distance_from_ob <= 1.5 else 10
    eq_liquidity = 15 if sweep_ok else 5
    eq_mss = 15 if mss_ok else 5
    eq_fvg = 10 if fvg_ok else 0
    eq_mtf = 10  # فريمات متعددة مستقرة
    eq_volume = 5 if vol_ok else 2
    eq_risk = 5 if btc_aligned else 0

    entry_quality_score = eq_structure + eq_ob + eq_liquidity + eq_mss + eq_fvg + eq_mtf + eq_volume + eq_risk

    # تصنيف جودة الدخول
    if entry_quality_score >= 90: eq_label = "EXCELLENT"
    elif entry_quality_score >= 80: eq_label = "STRONG"
    elif entry_quality_score >= 70: eq_label = "ACCEPTABLE"
    else: eq_label = "NO TRADE"

    # ---------------------------------------------------------
    # 1) Dynamic Stop Loss Engine & 9) Realistic TP & 10) Min R:R
    # ---------------------------------------------------------
    if base_direction == 'LONG':
        dynamic_sl = min(ob_level - (atr * 0.5), p - (atr * 1.5))
        sl_distance_pct = abs(p - dynamic_sl) / p * 100
        
        # حماية ضد SL الواسع جداً (> 4.5%)
        if sl_distance_pct > 4.5 or dynamic_sl >= p:
            decision_state = "NO TRADE (Wide Stop Loss)"
            return _build_result_dict(symbol, 'NO TRADE', entry_quality_score, decision_state, p, rsi, ob_level, distance_from_ob, 0,0,0,0,0, sweep_desc, mss_desc, fvg_ok, vol_desc, btc_status_str, interval)

        risk_dist = p - dynamic_sl
        tp1 = p + (risk_dist * 1.8)
        tp2 = swing_high if swing_high > p else p + (risk_dist * 3.0)
        tp3 = tp2 + (risk_dist * 1.5)
    else:
        dynamic_sl = max(ob_level + (atr * 0.5), p + (atr * 1.5))
        sl_distance_pct = abs(dynamic_sl - p) / p * 100
        
        if sl_distance_pct > 4.5 or dynamic_sl <= p:
            decision_state = "NO TRADE (Wide Stop Loss)"
            return _build_result_dict(symbol, 'NO TRADE', entry_quality_score, decision_state, p, rsi, ob_level, distance_from_ob, 0,0,0,0,0, sweep_desc, mss_desc, fvg_ok, vol_desc, btc_status_str, interval)

        risk_dist = dynamic_sl - p
        tp1 = p - (risk_dist * 1.8)
        tp2 = swing_low if swing_low < p else p - (risk_dist * 3.0)
        tp3 = tp2 - (risk_dist * 1.5)

    rr_tp1 = round(abs(tp1 - p) / risk_dist, 2) if risk_dist > 0 else 0.0
    rr_tp2 = round(abs(tp2 - p) / risk_dist, 2) if risk_dist > 0 else 0.0
    rr_tp3 = round(abs(tp3 - p) / risk_dist, 2) if risk_dist > 0 else 0.0

    # فحص الحد الأدنى للـ R:R (TP1 >= 1.5)
    if rr_tp1 < 1.5 or entry_quality_score < 70:
        return _build_result_dict(symbol, 'NO TRADE', entry_quality_score, "NO TRADE - R:R غير مناسب أو جودة دخول ضعيفة", p, rsi, ob_level, distance_from_ob, dynamic_sl, sl_distance_pct, tp1, tp2, tp3, sweep_desc, mss_desc, fvg_ok, vol_desc, btc_status_str, interval)

    # ---------------------------------------------------------
    # 4) فصل الاتجاه عن جاهزية الدخول (READY vs SETUP vs NO TRADE)
    # ---------------------------------------------------------
    if is_no_chase:
        final_decision = f"{base_direction} SETUP"
        state_msg = f"🟡 {base_direction} SETUP — NO CHASE (السعر بعيد عن Order Block بنسبة {distance_from_ob:.2f}%)"
    elif is_overextended:
        final_decision = f"{base_direction} SETUP"
        state_msg = f"🟡 {base_direction} SETUP — OVEREXTENDED (RSI ممتد، انتظار Pullback)"
    elif not sweep_ok or not mss_ok or not btc_aligned:
        final_decision = f"{base_direction} SETUP"
        state_msg = f"🟡 {base_direction} SETUP — انتظار اكتمال تأكيدات السيولة والهيكل"
    elif entry_quality_score >= 80 and sweep_ok and mss_ok and btc_aligned:
        final_decision = f"{base_direction} READY"
        state_msg = f"🟢 {base_direction} READY — الشروط مكتملة والدخول صالح"
    else:
        final_decision = "NO TRADE"
        state_msg = "🔴 NO TRADE — الشروط لم تصل للحد المؤسسي المطلوب"

    invalidation_level = dynamic_sl

    funding_rate = get_funding_rate(symbol) * 100

    return {
        'symbol': symbol,
        'direction': final_decision,
        'plan_direction': final_decision,
        'score': entry_quality_score,
        'entry_score': entry_quality_score,
        'state': state_msg,
        'price': smart_round(p),
        'rsi': rsi,
        'entry_min': smart_round(p * 0.998),
        'entry_max': smart_round(p * 1.002),
        'entry_price': smart_round(p),
        'stop_loss': smart_round(dynamic_sl),
        'sl_distance': round(sl_distance_pct, 2),
        'tp1': smart_round(tp1),
        'tp2': smart_round(tp2),
        'tp3': smart_round(tp3),
        'risk': smart_round(risk_dist),
        'rr_ratio': rr_tp1,
        'rr_tp1': rr_tp1,
        'rr_tp2': rr_tp2,
        'rr_tp3': rr_tp3,
        'invalidation': smart_round(invalidation_level),
        'funding_rate': funding_rate,
        'ob_level': smart_round(ob_level),
        'distance_from_ob': round(distance_from_ob, 2),
        'sweep_desc': sweep_desc,
        'mss_desc': mss_desc,
        'fvg_ok': fvg_ok,
        'vol_desc': vol_desc,
        'btc_status': btc_status_str,
        'interval': interval.upper()
    }


def _build_result_dict(symbol, decision, score, state, p, rsi, ob, dist, sl, sl_pct, tp1, tp2, tp3, sweep, mss, fvg, vol, btc, interval):
    return {
        'symbol': symbol, 'direction': decision, 'plan_direction': decision,
        'score': score, 'entry_score': score, 'state': state,
        'price': smart_round(p), 'rsi': rsi,
        'entry_min': smart_round(p), 'entry_max': smart_round(p), 'entry_price': smart_round(p),
        'stop_loss': smart_round(sl), 'sl_distance': round(sl_pct, 2),
        'tp1': smart_round(tp1), 'tp2': smart_round(tp2), 'tp3': smart_round(tp3),
        'risk': 0, 'rr_ratio': 0, 'rr_tp1': 0, 'rr_tp2': 0, 'rr_tp3': 0,
        'invalidation': smart_round(sl), 'funding_rate': 0.0,
        'ob_level': smart_round(ob), 'distance_from_ob': round(dist, 2),
        'sweep_desc': sweep, 'mss_desc': mss, 'fvg_ok': fvg, 'vol_desc': vol,
        'btc_status': btc, 'interval': interval.upper()
    }


def get_coin_analysis(symbol, interval='1h'):
    try:
        return _get_coin_analysis_core(symbol, interval)
    except Exception as e:
        return _get_blocked_signal(symbol, 1.0, f"خطأ بالبيانات ({str(e)})", interval)


def _get_blocked_signal(symbol, price, reason, interval='1h'):
    p = price if price and price > 0 else 1.0
    return {
        'symbol': symbol, 'direction': 'NO TRADE', 'plan_direction': 'NO TRADE',
        'score': 10, 'entry_score': 10, 'state': f'NO TRADE - {reason}',
        'price': smart_round(p), 'rsi': 50.0, 'stop_loss': 0, 'sl_distance': 0,
        'tp1': 0, 'tp2': 0, 'tp3': 0, 'invalidation': 0, 'ob_level': 0, 'distance_from_ob': 0,
        'sweep_desc': 'NOT CONFIRMED', 'mss_desc': 'NOT CONFIRMED', 'fvg_ok': False,
        'vol_desc': 'WEAK', 'btc_status': 'CHECK FAILED', 'interval': interval.upper()
    }


def get_top_futures_symbols(limit=25):
    rows = _ticker_rows()
    cand = []
    for x in rows:
        try:
            if isinstance(x, dict):
                s = str(x.get('symbol', '')).upper()
                v = float(x.get('volume', x.get('quoteVolume', 0)))
                if s and v > 0:
                    cand.append((s, v))
        except Exception:
            pass
    cand.sort(key=lambda x: x[1], reverse=True)
    out = []
    for x in cand[:limit]:
        sy = normalize_symbol(x[0])
        if sy not in out:
            out.add(sy)
    return out


# ---------------------------------------------------------
# 15) بناء رسالة التنبيه الجديدة المطابقة للمعايير المؤسسية
# ---------------------------------------------------------

def generate_evidence_report(d):
    if not d: return '⚠️ تعذر إكمال التحليل.'
    dr = d.get('direction', 'NO TRADE')
    inv = d.get('interval', '1H')
    score = d.get('score', 0)
    
    # تحديد شكل جودة الدخول النصي
    if score >= 90: eq_text = "EXCELLENT"
    elif score >= 80: eq_text = "STRONG"
    elif score >= 70: eq_text = "ACCEPTABLE"
    else: eq_text = "NO TRADE"

    if 'READY' in dr:
        decision_line = f"📈 القرار: 🟢 {dr}"
        risk_status = "🛡️ RISK STATUS: ✅ SAFE"
    elif 'SETUP' in dr:
        decision_line = f"📈 القرار: 🟡 {dr}"
        risk_status = "🛡️ RISK STATUS: ⚠️ HIGH RISK (انتظار تأكيد)"
    else:
        decision_line = f"📈 القرار: 🛑 NO TRADE"
        risk_status = "🛡️ RISK STATUS: 🚫 INVALID"

    fvg_status = "✅ CONFIRMED" if d.get('fvg_ok') else "❌ NOT CONFIRMED"
    vol_text = d.get('vol_desc', 'WEAK')
    vol_icon = "✅" if vol_text == "CONFIRMED" else "⚠️"

    lines = [
        '🤖 BingX Ultra Safe SMC Scanner v34.1',
        f"💎 العملة: {d.get('symbol', '-')}",
        f"⏱️ TF: {inv}",
        f"💰 السعر: {d.get('price', '-')}",
        decision_line,
        f"⭐ Overall Score: {score}/100",
        f"🎯 Entry Quality: {score}/100 — {eq_text}",
        '\n━━━━━━━━━━━━━━━━━━',
        f"📍 ENTRY: {d.get('entry_min', '-')} - {d.get('entry_max', '-')}",
        f"🛑 Dynamic SL: {d.get('stop_loss', '-')}",
        f"📏 SL Distance: {d.get('sl_distance', 0)}%",
        f"🎯 TP1: {d.get('tp1', '-')}",
        f"🎯 TP2: {d.get('tp2', '-')}",
        f"🎯 TP3: {d.get('tp3', '-')}",
        f"⚖️ R:R: 1:{d.get('rr_tp1', 0)} (TP2: 1:{d.get('rr_tp2', 0)})",
        '\n━━━━━━━━━━━━━━━━━━',
        '🧠 SMC CONFIRMATION',
        f"🏗 Structure: {d.get('mss_desc', 'NOT CONFIRMED')}",
        f"💧 Liquidity Sweep: {d.get('sweep_desc', 'NOT CONFIRMED')}",
        f"📦 Order Block: {d.get('ob_level', '-')}",
        f"📏 Distance from OB: {d.get('distance_from_ob', 0)}%",
        f"🟣 FVG: {fvg_status}",
        f"📊 Volume: {vol_icon} {vol_text}",
        f"₿ BTC: {d.get('btc_status', 'ALIGNED')}",
        '\n━━━━━━━━━━━━━━━━━━',
        f"❌ INVALIDATION: {d.get('invalidation', '-')}",
        '\n━━━━━━━━━━━━━━━━━━',
        risk_status
    ]

    return '\n'.join(lines)
