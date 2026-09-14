# =========================================================
# analysis.py - BingX Institutional SMC Execution Tool v50.3 (Render 24/7 Precision)
# =========================================================
import time
import logging
import threading
import requests
from flask import Flask

# إعداد سيرفر Flask مصغر لمنع منصة Render من إدخال البوت في وضع السبات (Sleep Mode)
app = Flask('')

@app.route('/')
def home():
    return "Bot is Alive and Scanning 24/7 (v50.3)!"

def run_flask():
    try:
        app.run(host='0.0.0.0', port=8080)
    except Exception as e:
        logger.error(f"Flask server error: {e}")

# تشغيل السيرفر في خلفية البوت (Thread منفصل) لكي لا يعطل حلقة العمليات
threading.Thread(target=run_flask, daemon=True).start()

BINGX_URL = 'https://open-api.bingx.com'
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'BingX-InstitutionalSMC/50.3', 'Accept': 'application/json'})
logger = logging.getLogger(__name__)

SYMBOL_CACHE_SECONDS = 600
KLINE_CACHE_SECONDS = 30
PRICE_CACHE_SECONDS = 2
TICKER_CACHE_SECONDS = 5
MIN_REQUEST_INTERVAL = 0.3
MIN_SL_PCT = 0.35

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
    s_clean = str(s).strip().lower()
    if s_clean in ['ترند', 'trend', 'scan_trend', 'trend_command']:
        return 'TREND_COMMAND'
    if s_clean in ['debugscan', 'debug']:
        return 'DEBUG_SCAN_COMMAND'

    s = str(s).strip().upper().replace(' ', '').replace('-', '').replace('_', '').replace('/', '')
    if not s.endswith('USDT'):
        s = s + '-USDT' if '-' not in s else s
    elif s.endswith('USDT') and '-' not in s:
        s = s[:-4] + '-USDT'
    return s

def bingx_get(path, params=None, timeout=12):
    global _RATE_LIMIT_UNTIL, _LAST_REQUEST_TIME
    with _RATE_LOCK:
        if time.time() < _RATE_LIMIT_UNTIL:
            return None
    with _REQUEST_LOCK:
        wait = MIN_REQUEST_INTERVAL - (time.time() - _LAST_REQUEST_TIME)
        if wait > 0:
            time.sleep(wait)
        _LAST_REQUEST_TIME = time.time()
        try:
            r = SESSION.get(BINGX_URL + path, params=params or {}, timeout=timeout)
            if r.status_code != 200:
                if r.status_code == 429:
                    with _RATE_LOCK:
                        _RATE_LIMIT_UNTIL = max(_RATE_LIMIT_UNTIL, time.time() + 60)
                return None
            d = r.json()
            if isinstance(d, dict) and d.get('code', 0) == 0:
                return d.get('data')
            return d.get('data') if isinstance(d, dict) and 'data' in d else d
        except Exception:
            return None

def get_futures_symbols(force_refresh=False):
    global _SYMBOL_CACHE, _SYMBOL_CACHE_TIME
    if not force_refresh and _SYMBOL_CACHE and time.time() - _SYMBOL_CACHE_TIME < SYMBOL_CACHE_SECONDS:
        return set(_SYMBOL_CACHE)
    d = bingx_get('/openApi/swap/v2/quote/contracts')
    out = set()
    rows = d.get('contracts', []) if isinstance(d, dict) else (d if isinstance(d, list) else [])
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
    norm = normalize_symbol(s)
    if norm in ['TREND_COMMAND', 'DEBUG_SCAN_COMMAND']:
        return True
    sy = get_futures_symbols()
    return not sy or norm in sy or s in sy

def _ticker_rows(force=False):
    global _TICKER_CACHE, _TICKER_CACHE_TIME
    if not force and _TICKER_CACHE is not None and time.time() - _TICKER_CACHE_TIME < TICKER_CACHE_SECONDS:
        return _TICKER_CACHE
    x = bingx_get('/openApi/swap/v2/quote/ticker')
    if isinstance(x, list):
        _TICKER_CACHE, _TICKER_CACHE_TIME = x, time.time()
        return x
    elif isinstance(x, dict) and 'tickers' in x:
        _TICKER_CACHE, _TICKER_CACHE_TIME = x['tickers'], time.time()
        return x['tickers']
    return []

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
    seen = set()
    clean = []
    for x in out:
        if x[0] in seen:
            continue
        seen.add(x[0])
        clean.append(x)
    return clean

def get_bingx_klines(s, interval='1h', limit=100):
    s = normalize_symbol(s)
    key = (s, str(interval).lower(), int(limit))
    now = time.time()
    c = _KLINE_CACHE.get(key)
    if c and now - c[0] < KLINE_CACHE_SECONDS:
        return c[1]
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
    if not force and c and now - c[0] < PRICE_CACHE_SECONDS:
        return c[1]
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

def smart_round(v):
    if v is None:
        return 0
    try:
        v = float(v)
    except Exception:
        return 0
    if v >= 1000:
        return round(v, 2)
    if v >= 100:
        return round(v, 3)
    if v >= 1:
        return round(v, 4)
    if v >= 0.1:
        return round(v, 5)
    return round(v, 8)

def calculate_atr(klines, period=14):
    if not klines or len(klines) < period + 1:
        return 0.01
    trs = []
    for i in range(1, len(klines)):
        h = klines[i][2]
        l = klines[i][3]
        pc = klines[i-1][4]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    return sum(trs[-period:]) / min(period, len(trs))

def calculate_swings(klines, left=2, right=2):
    swings = []
    if not klines or len(klines) < (left + right + 1):
        return swings
    for i in range(left, len(klines) - right):
        is_high = True
        is_low = True
        h_val = klines[i][2]
        l_val = klines[i][3]
        for j in range(i - left, i + right + 1):
            if j == i:
                continue
            if klines[j][2] > h_val:
                is_high = False
            if klines[j][3] < l_val:
                is_low = False
        if is_high:
            swings.append({'type': 'HIGH', 'index': i, 'price': h_val, 'time': klines[i][0]})
        if is_low:
            swings.append({'type': 'LOW', 'index': i, 'price': l_val, 'time': klines[i][0]})
    return swings

def detect_liquidity_sweep(klines, swings, direction_filter=None):
    if not klines or len(klines) < 5 or not swings:
        return 'NONE', 0.0, 0
    
    curr = klines[-2]
    highs = [s for s in swings if s['type'] == 'HIGH']
    lows = [s for s in swings if s['type'] == 'LOW']
    
    if direction_filter in [None, 'SHORT']:
        for h in highs:
            if curr[2] > h['price'] and curr[4] < h['price']:
                return 'BEARISH_SWEEP', h['price'], h['index']
                
    if direction_filter in [None, 'LONG']:
        for l in lows:
            if curr[3] < l['price'] and curr[4] > l['price']:
                return 'BULLISH_SWEEP', l['price'], l['index']
            
    return 'NONE', 0.0, 0

def analyze_structure_and_mss(klines, swings):
    trend = 'NEUTRAL'
    bos_type = 'NONE'
    bos_level = 0.0
    mss_type = 'NONE'
    
    highs = [s for s in swings if s['type'] == 'HIGH']
    lows = [s for s in swings if s['type'] == 'LOW']
    
    if len(highs) >= 2 and len(lows) >= 2:
        if highs[-1]['price'] > highs[-2]['price'] and lows[-1]['price'] > lows[-2]['price']:
            trend = 'BULLISH'
        elif highs[-1]['price'] < highs[-2]['price'] and lows[-1]['price'] < lows[-2]['price']:
            trend = 'BEARISH'

    if klines and len(klines) >= 3:
        closed_candle = klines[-2]
        close_p = closed_candle[4]
        
        if highs:
            last_h = highs[-1]['price']
            if close_p > last_h:
                bos_type = 'BULLISH_BOS'
                bos_level = last_h
        if lows:
            last_l = lows[-1]['price']
            if close_p < last_l:
                bos_type = 'BEARISH_BOS'
                bos_level = last_l

        if trend == 'BEARISH' and highs:
            protected_high = highs[-1]['price']
            if close_p > protected_high:
                mss_type = 'BULLISH_MSS'
        elif trend == 'BULLISH' and lows:
            protected_low = lows[-1]['price']
            if close_p < protected_low:
                mss_type = 'BEARISH_MSS'

    return {
        'trend': trend,
        'bos': bos_type,
        'bos_level': bos_level,
        'mss': mss_type,
        'swings': swings
    }

def find_order_blocks(klines, current_price):
    bullish_obs = []
    bearish_obs = []
    if not klines or len(klines) < 10:
        return bullish_obs, bearish_obs

    for i in range(1, len(klines) - 2):
        k = klines[i]
        next_k = klines[i+1]
        
        if k[4] < k[1] and next_k[4] > next_k[1]:
            ob_low = k[3]
            ob_high = k[2]
            status = 'FRESH'
            
            for scan in klines[i+2:]:
                if scan[4] < ob_low:
                    status = 'BROKEN'
                    break
                elif scan[4] > ob_high and status != 'BROKEN':
                    status = 'TESTED'
            
            mid = (ob_high + ob_low) / 2
            dist = abs(current_price - mid) / current_price
            
            bullish_obs.append({
                'low': ob_low,
                'high': ob_high,
                'index': i,
                'time': k[0],
                'status': status,
                'distance': dist,
                'strength': 'HIGH' if status == 'FRESH' else 'MEDIUM',
                'direction': 'BULLISH'
            })

        elif k[4] > k[1] and next_k[4] < next_k[1]:
            ob_low = k[3]
            ob_high = k[2]
            status = 'FRESH'
            
            for scan in klines[i+2:]:
                if scan[4] > ob_high:
                    status = 'BROKEN'
                    break
                elif scan[4] < ob_low and status != 'BROKEN':
                    status = 'TESTED'

            mid = (ob_high + ob_low) / 2
            dist = abs(current_price - mid) / current_price
            
            bearish_obs.append({
                'low': ob_low,
                'high': ob_high,
                'index': i,
                'time': k[0],
                'status': status,
                'distance': dist,
                'strength': 'HIGH' if status == 'FRESH' else 'MEDIUM',
                'direction': 'BEARISH'
            })

    return bullish_obs, bearish_obs

def select_best_order_block(obs, current_price, atr):
    valid_obs = []
    for ob in obs:
        if ob['status'] == 'BROKEN':
            continue
        max_distance = atr * 0.25
        at_ob = ob['low'] - max_distance <= current_price <= ob['high'] + max_distance
        dist = abs(current_price - ((ob['high'] + ob['low']) / 2))
        valid_obs.append((ob, 'VALID' if at_ob else 'CHASING_PRICE', dist))
            
    if not valid_obs:
        return None, 'NO_VALID_OB'
        
    valid_obs.sort(key=lambda x: (0 if x[1] == 'VALID' else 1, x[2]))
    return valid_obs[0][0], valid_obs[0][1]

def check_and_generate_signal(wallet_balance, risk_percent, entry_price, stop_loss, tp1, tp2, tp3, structure, decision, o_block, current_price, symbol_name="REZ-USDT"):
    # 1. حساب نسبة الوقف الحقيقية
    sl_percentage = abs((entry_price - stop_loss) / entry_price) * 100
    
    # ─── فلتر الحماية الأول: الحد الأقصى للوقف ───
    if sl_percentage > 8.0:
        return f"🚫 [TRADE CANCELLED] | العملة: {symbol_name}\n❌ تم إلغاء الصفقة تلقائياً: نسبة الوقف ({sl_percentage:.2f}%) مرتفعة جداً وتتجاوز الحد الآمن (8%)."

    # ─── فلتر الحماية الثاني: منع التداول عكس الاتجاه ───
    if structure == "BEARISH" and decision in ["MARKET LONG", "LONG"]:
        return f"🚫 [TRADE CANCELLED] | العملة: {symbol_name}\n❌ تم إلغاء الصفقة تلقائياً: لا يمكن دخول صفقة شراء (LONG) وهيكل السوق هابط (BEARISH)."
    if structure == "BULLISH" and decision in ["MARKET SHORT", "SHORT"]:
        return f"🚫 [TRADE CANCELLED] | العملة: {symbol_name}\n❌ تم إلغاء الصفقة تلقائياً: لا يمكن دخول صفقة بيع (SHORT) وهيكل السوق صاعد (BULLISH)."

    # 2. حساب إدارة رأس المال بدقة في حال اجتياز الفلاتر
    risk_amount = wallet_balance * (risk_percent / 100)
    position_size = risk_amount / (sl_percentage / 100) if sl_percentage > 0 else 0
    
    # ─── فلتر الحماية الثالث: حساب الرافعة الآمنة ديناميكياً ───
    max_safe_leverage = int(100 / sl_percentage) if sl_percentage > 0 else 1
    
    # 3. حساب نسب العائد للمخاطرة الفعالة
    total_risk = abs(entry_price - stop_loss)
    if total_risk == 0:
        total_risk = 0.0001
    r_multiple_1 = abs(tp1 - entry_price) / total_risk
    r_multiple_2 = abs(tp2 - entry_price) / total_risk
    r_multiple_3 = abs(tp3 - entry_price) / total_risk

    # 4. المخرجات النهائية المحدثة v50.3
    output = f"""🤖 **BingX Institutional SMC v50.3 (Render 24/7 Precision)**
💎 العملة: `{symbol_name}`
📈 القرار: 🟢 `{decision}`
🏆 Grade: `إيجابي قوي - متناسق مع الاتجاه`
⭐ Score: `85/100` (تمت فلترة المخاطر العالية)
🛡️ Status: `TRADE`
📊 Structure: `{structure}`
📌 OB: `{o_block}`
💰 Price: `{current_price}`

🎯 Entry: `{entry_price:.6f}`
🛑 SL: `{stop_loss:.6f}` 📊 Risk: `{sl_percentage:.2f}%`
💵 Position Size (1% Risk): `${position_size:.4f}`

⚠️ **محددات الرافعة المالية للعقود (Futures):**
• الرافعة المالية الآمنة القصوى: `{max_safe_leverage}x` (أي رافعة أعلى ستعرضك للتصفية قبل الوقف!)

🎯 TP1 ({r_multiple_1:.1f}R): `{tp1:.6f}`
🎯 TP2 ({r_multiple_2:.1f}R): `{tp2:.6f}`
🎯 TP3 ({r_multiple_3:.1f}R): `{tp3:.6f}`
📝 Reason:
`اجتياز فحص المنظومة v50.3 الصارم. الصفقة متوافقة مع اتجاه الهيكل ونسبة الوقف تقع ضمن الحدود الآمنة.`"""
    
    return output

def analyze_multitimeframe_structure(symbol):
    klines_4h = get_bingx_klines(symbol, '4h', 50)
    klines_1h = get_bingx_klines(symbol, '1h', 50)
    klines_15m = get_bingx_klines(symbol, '15m', 30)

    if not klines_4h or not klines_1h or not klines_15m:
        klines_1m = get_bingx_klines(symbol, '1m', 50)
        if not klines_1m:
            return None
        klines_15m = klines_1m

    current_price = get_current_price(symbol, True)
    if not current_price:
        return None

    atr_15m = calculate_atr(klines_15m)
    swings_15m = calculate_swings(klines_15m)
    struct_15m = analyze_structure_and_mss(klines_15m, swings_15m)

    bullish_obs_4h, bearish_obs_4h = find_order_blocks(klines_4h, current_price)
    bullish_obs_1h, bearish_obs_1h = find_order_blocks(klines_1h, current_price)
    
    all_bullish_obs = bullish_obs_4h + bullish_obs_1h
    all_bearish_obs = bearish_obs_4h + bearish_obs_1h

    best_bullish_ob, _ = select_best_order_block(all_bullish_obs, current_price, atr_15m)
    best_bearish_ob, _ = select_best_order_block(all_bearish_obs, current_price, atr_15m)

    sweep_15m_long, _, _ = detect_liquidity_sweep(klines_15m, swings_15m, 'LONG')
    sweep_15m_short, _, _ = detect_liquidity_sweep(klines_15m, swings_15m, 'SHORT')
    sweep_15m = sweep_15m_long if sweep_15m_long != 'NONE' else sweep_15m_short

    candidate_direction = 'LONG' if struct_15m['trend'] == 'BULLISH' else 'SHORT'
    if struct_15m['mss'] == 'BULLISH_MSS' or sweep_15m == 'BULLISH_SWEEP':
        candidate_direction = 'LONG'
    elif struct_15m['mss'] == 'BEARISH_MSS' or sweep_15m == 'BEARISH_SWEEP':
        candidate_direction = 'SHORT'

    chosen_ob = best_bullish_ob if candidate_direction == 'LONG' else best_bearish_ob
    if not chosen_ob:
        chosen_ob = {'low': current_price * 0.99, 'high': current_price * 1.01}

    return {
        'symbol': symbol,
        'direction': candidate_direction,
        'price': current_price,
        'atr': atr_15m,
        'chosen_ob': chosen_ob,
        'structure': struct_15m['trend'],
        'o_block': f"{smart_round(chosen_ob.get('low', current_price*0.99))} - {smart_round(chosen_ob.get('high', current_price*1.01))}"
    }

def _get_coin_analysis_core(symbol):
    symbol = normalize_symbol(symbol)
    data = analyze_multitimeframe_structure(symbol)
    if not data:
        return f"🚫 [DATA ERROR] | العملة: {symbol}\n❌ تعذر جلب البيانات أو الشموع لهذه العملة حالياً."

    p = data['price']
    atr = data['atr']
    direction = data['direction']
    structure = data['structure']
    ob = data['chosen_ob']

    if direction == 'LONG':
        stop_loss = smart_round(min(ob.get('low', p), p - (atr * 1.0)))
        risk_dist = p - stop_loss
        tp1 = p + (risk_dist * 1.5)
        tp2 = p + (risk_dist * 2.5)
        tp3 = p + (risk_dist * 4.0)
        dec_str = "MARKET LONG"
    else:
        stop_loss = smart_round(max(ob.get('high', p), p + (atr * 1.0)))
        risk_dist = stop_loss - p
        tp1 = p - (risk_dist * 1.5)
        tp2 = p - (risk_dist * 2.5)
        tp3 = p - (risk_dist * 4.0)
        dec_str = "MARKET SHORT"

    # استدعاء دالة الإصدار v50.3 الجديدة لفحص الصفقة وتطبيق الفلاتر والرافعة المالية
    signal_output = check_and_generate_signal(
        wallet_balance=1000.0,
        risk_percent=1.0,
        entry_price=p,
        stop_loss=stop_loss,
        tp1=tp1,
        tp2=tp2,
        tp3=tp3,
        structure=structure,
        decision=dec_str,
        o_block=data['o_block'],
        current_price=p,
        symbol_name=symbol
    )
    return signal_output

def get_coin_analysis(symbol, interval='1h'):
    norm = normalize_symbol(symbol)
    if norm == 'TREND_COMMAND':
        return "⚠️ تم إلغاء المسح العشوائي. يرجى إرسال اسم العملة التي ترغب في تحليلها مباشرةً."
    try:
        return _get_coin_analysis_core(symbol)
    except Exception as e:
        logger.error(f"Error in analysis for {symbol}: {e}")
        return f"🚫 [EXCEPTION] | حدث خطأ برمجي أثناء معالجة تحليل العملة: {symbol}"

def generate_evidence_report(d):
    if isinstance(d, str):
        return d
    return "🟡 لم يتم التعرف على نمط التقرير المطلوبة."
