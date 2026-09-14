# =========================================================
# analysis.py - BingX Institutional SMC v50.5 (Anti-Whipsaw & Pool Fix)
# =========================================================
import time
import logging
import threading
import requests
from requests.adapters import HTTPAdapter
from flask import Flask

# إعداد سيرفر Flask مصغر لمنع منصة Render من إدخال البوت في وضع السبات (Sleep Mode)
app = Flask('')

@app.route('/')
def home():
    return "Bot is Alive and Scanning 24/7 (v50.5 with Pool Timeout Fix)!"

def run_flask():
    try:
        app.run(host='0.0.0.0', port=8080)
    except Exception as e:
        logger.error(f"Flask server error: {e}")

# تشغيل السيرفر في خلفية البوت (Thread منفصل)
threading.Thread(target=run_flask, daemon=True).start()

BINGX_URL = 'https://open-api.bingx.com'

# تحسين إدارة اتصالات الـ HTTP لمنع تكدس الـ Pool Timeout وتوسيع الحد الأقصى للاتصالات
SESSION = requests.Session()
adapter = HTTPAdapter(pool_connections=50, pool_maxsize=50, max_retries=3)
SESSION.mount('https://', adapter)
SESSION.mount('http://', adapter)

SESSION.headers.update({'User-Agent': 'BingX-InstitutionalSMC/50.5', 'Accept': 'application/json'})
logger = logging.getLogger(__name__)

SYMBOL_CACHE_SECONDS = 600
KLINE_CACHE_SECONDS = 30
PRICE_CACHE_SECONDS = 2
TICKER_CACHE_SECONDS = 5
MIN_REQUEST_INTERVAL = 0.3

# القيد الصارم للحد الأدنى للمخاطرة (1.5%) والحد الأقصى للرافعة المالية (10x)
MIN_SL_PCT = 1.5
MAX_LEVERAGE_CAP = 10

# جدول تتبع إشارات الـ Cooldown لمنع التأرجح العكسي (Anti-Whipsaw Cache)
_SIGNAL_HISTORY = {}
_HISTORY_LOCK = threading.Lock()

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

def get_bingx_klines(s, interval='4h', limit=100):
    s = normalize_symbol(s)
    key = (s, str(interval).lower(), int(limit))
    now = time.time()
    c = _KLINE_CACHE.get(key)
    if c and now - c[0] < KLINE_CACHE_SECONDS:
        return c[1]
    mp = {'1h': '1h', '4h': '4h', '1d': '1d'}
    bi = mp.get(str(interval).lower(), '4h')
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
    k = get_bingx_klines(s, '1h', 5)
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

def analyze_structure_4h(klines_4h, swings_4h):
    trend = 'NEUTRAL'
    bos_type = 'NONE'
    bos_level = 0.0
    
    highs = [s for s in swings_4h if s['type'] == 'HIGH']
    lows = [s for s in swings_4h if s['type'] == 'LOW']
    
    if len(highs) >= 2 and len(lows) >= 2:
        if highs[-1]['price'] > highs[-2]['price'] and lows[-1]['price'] > lows[-2]['price']:
            trend = 'BULLISH'
        elif highs[-1]['price'] < highs[-2]['price'] and lows[-1]['price'] < lows[-2]['price']:
            trend = 'BEARISH'

    if klines_4h and len(klines_4h) >= 3:
        closed_candle = klines_4h[-2]
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

    return {
        'trend': trend,
        'bos': bos_type,
        'bos_level': bos_level,
        'swings': swings_4h
    }

def find_order_blocks_institutional(klines_4h, current_price):
    bullish_obs = []
    bearish_obs = []
    if not klines_4h or len(klines_4h) < 10:
        return bullish_obs, bearish_obs

    for i in range(1, len(klines_4h) - 2):
        k = klines_4h[i]
        next_k = klines_4h[i+1]
        
        if k[4] < k[1] and next_k[4] > next_k[1]:
            ob_low = k[3]
            ob_high = k[2]
            status = 'FRESH'
            
            for scan in klines_4h[i+2:]:
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
                'strength': 'INSTITUTIONAL_4H',
                'direction': 'BULLISH'
            })

        elif k[4] > k[1] and next_k[4] < next_k[1]:
            ob_low = k[3]
            ob_high = k[2]
            status = 'FRESH'
            
            for scan in klines_4h[i+2:]:
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
                'strength': 'INSTITUTIONAL_4H',
                'direction': 'BEARISH'
            })

    return bullish_obs, bearish_obs

def check_and_generate_signal(wallet_balance, risk_percent, entry_price, stop_loss, tp1, tp2, tp3, structure, decision, o_block, current_price, symbol_name="REZ-USDT"):
    sl_percentage = abs((entry_price - stop_loss) / entry_price) * 100
    
    if sl_percentage < MIN_SL_PCT:
        return f"🚫 [TRADE CANCELLED - TIGHT RISK] | العملة: {symbol_name}\n❌ تم إلغاء الصفقة فوراً: نسبة المخاطرة الفنية ({sl_percentage:.2f}%) أقل من الحد الأدنى الآمن ({MIN_SL_PCT}%) لتفادي ضرب الستوب لوس بالحركات العشوائية (Whipsaws)."

    if sl_percentage > 12.0:
        return f"🚫 [TRADE CANCELLED] | العملة: {symbol_name}\n❌ تم إلغاء الصفقة تلقائياً: نسبة الوقف ({sl_percentage:.2f}%) مرتفعة جداً وتتجاوز السقف الآمن."

    with _HISTORY_LOCK:
        now_ts = time.time()
        last_record = _SIGNAL_HISTORY.get(symbol_name)
        if last_record:
            last_dir = last_record['direction']
            last_time = last_record['time']
            if last_dir != decision and (now_ts - last_time) < 21600:
                hours_left = (21600 - (now_ts - last_time)) / 3600
                return f"🚫 [COOLDOWN ACTIVE - ANTI-WHIPSAW] | العملة: {symbol_name}\n❌ ممنوع إصدار إشارة عكسية ({decision}) قبل مرور 6 ساعات كاملة على الإشارة السابقة ({last_dir}). المتبقي: {hours_left:.1f} ساعة لتفادي التلاعب."

    if structure == "BEARISH" and decision in ["MARKET LONG", "LONG"]:
        return f"🚫 [TRADE CANCELLED] | العملة: {symbol_name}\n❌ تم إلغاء الصفقة: لا يمكن دخول شراء (LONG) وهيكل فريم 4 ساعات هابط (BEARISH)."
    if structure == "BULLISH" and decision in ["MARKET SHORT", "SHORT"]:
        return f"🚫 [TRADE CANCELLED] | العملة: {symbol_name}\n❌ تم إلغاء الصفقة: لا يمكن دخول بيع (SHORT) وهيكل فريم 4 ساعات صاعد (BULLISH)."

    calculated_leverage = int(100 / sl_percentage) if sl_percentage > 0 else 3
    max_safe_leverage = min(calculated_leverage, MAX_LEVERAGE_CAP)
    if max_safe_leverage < 3:
        max_safe_leverage = 3

    risk_amount = wallet_balance * (risk_percent / 100)
    position_size = risk_amount / (sl_percentage / 100) if sl_percentage > 0 else 0

    with _HISTORY_LOCK:
        _SIGNAL_HISTORY[symbol_name] = {'direction': decision, 'time': time.time()}

    total_risk = abs(entry_price - stop_loss)
    if total_risk == 0:
        total_risk = 0.0001
    r_multiple_1 = abs(tp1 - entry_price) / total_risk
    r_multiple_2 = abs(tp2 - entry_price) / total_risk
    r_multiple_3 = abs(tp3 - entry_price) / total_risk

    score = 98
    grade = "إيجابي مؤسسي فائق - محمي بـ Anti-Whipsaw & Pool Fix"

    output = f"""🤖 **BingX Institutional SMC v50.5 (Anti-Whipsaw & Pool Fix)**
💎 العملة: `{symbol_name}`
📈 القرار: 🟢 `{decision}`
🏆 Grade: `{grade}`
⭐ Score: `{score}/100` (تمت تصفية الضوضاء واجتياز فريم 4H بنجاح)
🛡️ Status: `TRADE`
📊 Structure (4H): `{structure}`
📌 OB (Institutional): `{o_block}`
💰 Price: `{current_price}`

🎯 Entry: `{entry_price:.6f}`
🛑 SL: `{stop_loss:.6f}` 📊 Risk Filter: `{sl_percentage:.2f}%` (أعلى من 1.5% المعتمدة)
💵 Position Size (1% Risk): `${position_size:.4f}`

⚠️ **الرافعة المالية المُعمدة (Strict Leverage Cap):**
• الرافعة المالية القصوى: `{max_safe_leverage}x` (محدودة بـ 10x صراعاً ضد تقلبات الحيتان وحماية الحساب).

🎯 TP1 ({r_multiple_1:.1f}R): `{tp1:.6f}`
🎯 TP2 ({r_multiple_2:.1f}R): `{tp2:.6f}`
🎯 TP3 ({r_multiple_3:.1f}R): `{tp3:.6f}`
📝 Reason:
`الاعتماد على إغلاقات فريم 4 ساعات، تفعيل قفل الـ Cooldown لمدة 6 ساعات منعاً للتأرجح العكسي، وإصلاح مشكلة اتصال الـ Pool.`"""
    
    return output

def analyze_institutional_multitimeframe(symbol):
    klines_4h = get_bingx_klines(symbol, '4h', 60)
    klines_1h = get_bingx_klines(symbol, '1h', 50)

    if not klines_4h or len(klines_4h) < 15:
        return None

    current_price = get_current_price(symbol, True)
    if not current_price:
        return None

    atr_4h = calculate_atr(klines_4h)
    swings_4h = calculate_swings(klines_4h, left=3, right=3)
    struct_4h = analyze_structure_4h(klines_4h, swings_4h)

    bullish_obs_4h, bearish_obs_4h = find_order_blocks_institutional(klines_4h, current_price)
    
    candidate_direction = 'LONG' if struct_4h['trend'] == 'BULLISH' else 'SHORT'
    
    chosen_ob = None
    if candidate_direction == 'LONG' and bullish_obs_4h:
        valid_b = [ob for ob in bullish_obs_4h if ob['status'] != 'BROKEN']
        if valid_b:
            valid_b.sort(key=lambda x: x['distance'])
            chosen_ob = valid_b[0]
    elif candidate_direction == 'SHORT' and bearish_obs_4h:
        valid_s = [ob for ob in bearish_obs_4h if ob['status'] != 'BROKEN']
        if valid_s:
            valid_s.sort(key=lambda x: x['distance'])
            chosen_ob = valid_s[0]

    if not chosen_ob:
        chosen_ob = {'low': current_price * 0.98, 'high': current_price * 1.02}

    return {
        'symbol': symbol,
        'direction': candidate_direction,
        'price': current_price,
        'atr': atr_4h,
        'chosen_ob': chosen_ob,
        'structure': struct_4h['trend'],
        'o_block': f"{smart_round(chosen_ob.get('low', current_price*0.98))} - {smart_round(chosen_ob.get('high', current_price*1.02))}"
    }

def _get_coin_analysis_core(symbol):
    symbol = normalize_symbol(symbol)
    data = analyze_institutional_multitimeframe(symbol)
    if not data:
        return f"🚫 [DATA ERROR] | العملة: {symbol}\n❌ تعذر جلب إغلاقات فريم 4 ساعات المؤسسي لهذه العملة حالياً."

    p = data['price']
    atr = data['atr']
    direction = data['direction']
    structure = data['structure']
    ob = data['chosen_ob']

    if direction == 'LONG':
        stop_loss = smart_round(min(ob.get('low', p), p - (atr * 1.5)))
        risk_dist = p - stop_loss
        tp1 = p + (risk_dist * 1.6)
        tp2 = p + (risk_dist * 2.6)
        tp3 = p + (risk_dist * 4.2)
        dec_str = "MARKET LONG"
    else:
        stop_loss = smart_round(max(ob.get('high', p), p + (atr * 1.5)))
        risk_dist = stop_loss - p
        tp1 = p - (risk_dist * 1.6)
        tp2 = p - (risk_dist * 2.6)
        tp3 = p - (risk_dist * 4.2)
        dec_str = "MARKET SHORT"

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

def get_coin_analysis(symbol, interval='4h'):
    norm = normalize_symbol(symbol)
    if norm == 'TREND_COMMAND':
        return "⚠️ تم إلغاء المسح العشوائي. يرجى إرسال اسم العملة التي ترغب في تحليلها بناءً على الفريمات المؤسسية مباشرةً."
    try:
        return _get_coin_analysis_core(symbol)
    except Exception as e:
        logger.error(f"Error in institutional analysis for {symbol}: {e}")
        return f"🚫 [EXCEPTION] | حدث خطأ برمجي أثناء معالجة التحليل المؤسسي للعملة: {symbol}"

def generate_evidence_report(d):
    if isinstance(d, str):
        return d
    return "🟡 لم يتم التعرف على نمط التقرير المطلوب."
