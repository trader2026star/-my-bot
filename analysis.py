# =========================================================
# analysis.py - BingX Futures AI Scanner v25.0
# ORDER BLOCK PRIMARY + ICT CONFLUENCE ENGINE
# 1D Context | 4H MTF OB | 1H Primary OB | 30m/15m Confirmation
#
# v23:
# - ORDER BLOCK remains the PRIMARY engine
# - ICT confluence: Liquidity Sweep + MSS/BOS + FVG + Displacement
# - Premium / Discount zones
# - WAIT keeps complete Entry / SL / TP trade plan
# - ICT confirms/refines OB; it does NOT replace OB
# =========================================================

import time
import logging
import threading
import requests

BINGX_URL = 'https://open-api.bingx.com'
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'BingX-OB-ICT-Scanner/25.0', 'Accept': 'application/json'})
logger = logging.getLogger(__name__)

SYMBOL_CACHE_SECONDS = 600
KLINE_CACHE_SECONDS = 45
PRICE_CACHE_SECONDS = 3
TICKER_CACHE_SECONDS = 5
MIN_REQUEST_INTERVAL = 0.45
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
    return s if s.endswith(('USDT', 'USDC')) else s + 'USDT'


def bingx_symbol(s):
    s = normalize_symbol(s)
    return s[:-4] + '-' + s[-4:]


def _rows(d):
    if not isinstance(d, dict): return []
    x = d.get('data')
    if isinstance(x, list): return x
    if isinstance(x, dict): return [x]
    return []


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
            logger.warning('BingX HTTP %s | %s', r.status_code, path); return None
        d = r.json()
        if not isinstance(d, dict): return None
        code = d.get('code')
        if code in (109429, 109400):
            with _RATE_LOCK: _RATE_LIMIT_UNTIL = max(_RATE_LIMIT_UNTIL, time.time() + 60)
            logger.warning('BingX rate limit %s | %s', code, path); return None
        if code not in (0, None):
            logger.warning('BingX API error %s | %s', code, path); return None
        return d
    except Exception as e:
        logger.warning('BingX request failed | %s | %s', path, e); return None


def _is_crypto_usdt_symbol(s):
    s = str(s).upper().replace('-', '')
    if not s.endswith('USDT'): return False
    base = s[:-4]
    blocked = ('SP500','NASDAQ','DJI','US30','DXY','GOLD','SILVER','XAU','XAG','OIL','BRENT','WTI','COPPER','PLATINUM','PALLADIUM')
    return not base.endswith('USD') and not any(x in base for x in blocked)


def get_futures_symbols(force_refresh=False):
    global _SYMBOL_CACHE, _SYMBOL_CACHE_TIME
    if not force_refresh and _SYMBOL_CACHE and time.time()-_SYMBOL_CACHE_TIME < SYMBOL_CACHE_SECONDS:
        return set(_SYMBOL_CACHE)
    d = bingx_get('/openApi/swap/v2/quote/contracts'); out=set()
    for x in _rows(d):
        if isinstance(x, dict):
            s=str(x.get('symbol','')).replace('-','').upper(); status=x.get('status')
            if _is_crypto_usdt_symbol(s) and status in (1,'1',None): out.add(s)
    if out: _SYMBOL_CACHE, _SYMBOL_CACHE_TIME = out, time.time()
    return set(_SYMBOL_CACHE)


def symbol_exists(s):
    sy=get_futures_symbols(); return not sy or normalize_symbol(s) in sy


def _price_value(x):
    if not isinstance(x,dict): return None
    for k in ('price','lastPrice','last','close','markPrice'):
        try:
            v=float(x.get(k));
            if v>0:return v
        except Exception: pass
    return None


def _ticker_rows(force=False):
    global _TICKER_CACHE,_TICKER_CACHE_TIME
    if not force and _TICKER_CACHE is not None and time.time()-_TICKER_CACHE_TIME<TICKER_CACHE_SECONDS:return _TICKER_CACHE
    x=_rows(bingx_get('/openApi/swap/v2/quote/ticker'))
    if x:_TICKER_CACHE,_TICKER_CACHE_TIME=x,time.time()
    return x


def _parse(rows):
    out=[]
    for x in rows:
        try:
            if isinstance(x,dict):
                t=x.get('time',x.get('timestamp',x.get('openTime',0))); o=x.get('open'); h=x.get('high'); l=x.get('low'); c=x.get('close'); v=x.get('volume',x.get('vol',0))
            elif isinstance(x,list) and len(x)>=6:t,o,h,l,c,v=x[:6]
            else:continue
            if None in (o,h,l,c):continue
            out.append([t,float(o),float(h),float(l),float(c),float(v or 0)])
        except Exception:pass
    try:out.sort(key=lambda z:z[0])
    except Exception:pass
    seen=set(); clean=[]
    for x in out:
        if x[0] in seen:continue
        seen.add(x[0]);clean.append(x)
    return clean


def get_bingx_klines(s,interval='1h',limit=200):
    s=normalize_symbol(s); key=(s,str(interval).lower(),int(limit)); now=time.time(); c=_KLINE_CACHE.get(key)
    if c and now-c[0]<KLINE_CACHE_SECONDS:return c[1]
    params={'symbol':bingx_symbol(s),'interval':str(interval).lower(),'limit':int(limit)};best=[]
    for ep in ('/openApi/swap/v3/quote/klines','/openApi/swap/v2/quote/klines'):
        r=_parse(_rows(bingx_get(ep,params)))
        if len(r)>len(best):best=r
        if len(r)>=30:_KLINE_CACHE[key]=(now,r);return r
    if best:_KLINE_CACHE[key]=(now,best);return best
    return None


def get_current_price(s,force=False):
    s=normalize_symbol(s);now=time.time();c=_PRICE_CACHE.get(s)
    if not force and c and now-c[0]<PRICE_CACHE_SECONDS:return c[1]
    for x in _ticker_rows(force):
        if str(x.get('symbol','')).replace('-','').upper()==s:
            p=_price_value(x)
            if p:_PRICE_CACHE[s]=(now,p);return p
    for ep in ('/openApi/swap/v2/quote/price','/openApi/swap/v1/ticker/price','/openApi/swap/v3/quote/price'):
        for x in _rows(bingx_get(ep,{'symbol':bingx_symbol(s)})):
            p=_price_value(x)
            if p:_PRICE_CACHE[s]=(now,p);return p
    k=get_bingx_klines(s,'1m',5) or get_bingx_klines(s,'1h',5)
    if k and k[-1][4]>0:_PRICE_CACHE[s]=(now,k[-1][4]);return k[-1][4]
    return None


def ema(v,n):
    if len(v)<n:return None
    e=sum(v[:n])/n;m=2/(n+1)
    for x in v[n:]:e=(x-e)*m+e
    return e
calculate_ema=ema


def calculate_rsi(c,period=14):
    if len(c)<period+1:return 50.0
    g=[max(c[i]-c[i-1],0) for i in range(1,len(c))];l=[max(c[i-1]-c[i],0) for i in range(1,len(c))]
    ag=sum(g[:period])/period;al=sum(l[:period])/period
    for i in range(period,len(g)):
        ag=(ag*(period-1)+g[i])/period;al=(al*(period-1)+l[i])/period
    return 100.0 if al==0 else round(100-100/(1+ag/al),2)


def calculate_atr(k,n=14):
    if len(k)<n+1:return None
    tr=[max(x[2]-x[3],abs(x[2]-k[i-1][4]),abs(x[3]-k[i-1][4])) for i,x in enumerate(k[1:],1)]
    a=sum(tr[:n])/n
    for x in tr[n:]:a=(a*(n-1)+x)/n
    return a


def calculate_volume_ratio(v,n=20):
    if len(v)<n+4:return 1.0
    base=sum(v[-n-4:-4])/n;recent=sum(v[-4:-1])/3
    return round(max(.05,min(5,recent/base)),2) if base>0 else 1.0


def calculate_volume_trend(v,short_period=5,long_period=20):
    if len(v)<long_period+short_period+1:return 'NEUTRAL'
    a=sum(v[-short_period-1:-1])/short_period;b=sum(v[-long_period-short_period-1:-short_period-1])/long_period
    return 'RISING' if b and a/b>=1.12 else 'FALLING' if b and a/b<=.88 else 'NEUTRAL'


def percentage_change(a,b):return ((b-a)/a*100) if a else 0


def calculate_support_resistance(k):
    if not k:return 0,0
    p=k[-1][4]; highs=[x[2] for x in k[-80:]];lows=[x[3] for x in k[-80:]]
    below=[x for x in lows if x<p];above=[x for x in highs if x>p]
    return (max(below) if below else min(lows)),(min(above) if above else max(highs))


def _dir(x):return 'BULLISH' if x[4]>x[1] else 'BEARISH' if x[4]<x[1] else 'NEUTRAL'

# =========================================================
# ORDER BLOCK PRIMARY ENGINE
# =========================================================
def detect_order_blocks(k,lookback=120):
    if len(k)<35:return {'bullish':[],'bearish':[]}
    bull=[];bear=[];start=max(5,len(k)-lookback)
    for i in range(start,len(k)-2):
        b,d=k[i],k[i+1];rng=max(d[2]-d[3],1e-12);disp=abs(d[4]-d[1])/rng
        if disp<.30:continue
        left=k[max(0,i-12):i]
        if not left:continue
        ph=max(x[2] for x in left);pl=min(x[3] for x in left)
        bull_bos=d[4]>ph or (d[2]>ph and d[4]>=d[1]);bear_bos=d[4]<pl or (d[3]<pl and d[4]<=d[1])
        lo,hi=sorted((b[1],b[4]));move=abs(percentage_change(d[1],d[4]));strength=min(100,42+disp*38+min(move,8)*3)
        if _dir(b)=='BEARISH' and _dir(d)=='BULLISH' and bull_bos:bull.append({'type':'BULLISH','index':i,'low':lo,'high':hi,'mid':(lo+hi)/2,'strength':round(strength,1)})
        if _dir(b)=='BULLISH' and _dir(d)=='BEARISH' and bear_bos:bear.append({'type':'BEARISH','index':i,'low':lo,'high':hi,'mid':(lo+hi)/2,'strength':round(strength,1)})
    bull=sorted(bull,key=lambda x:(x['index'],x['strength']),reverse=True)[:15];bear=sorted(bear,key=lambda x:(x['index'],x['strength']),reverse=True)[:15]
    return {'bullish':bull,'bearish':bear}


def price_inside_ob(p,o,tolerance=.008):
    if not o:return False
    pad=max((o['high']-o['low'])*tolerance,0);return o['low']-pad<=p<=o['high']+pad


def ob_distance_percent(p,o):
    if not o or p<=0:return 999
    if price_inside_ob(p,o):return 0.0
    return ((o['low']-p)/p*100) if p<o['low'] else ((p-o['high'])/p*100)


def _ob_valid(k,o,d):
    if not o:return False
    for x in k[o['index']+2:]:
        if d=='LONG' and x[4]<o['low']*.997:return False
        if d=='SHORT' and x[4]>o['high']*1.003:return False
    return True


def find_active_order_block(k,d,p):
    if not k:return None
    candidates=detect_order_blocks(k)['bullish' if d=='LONG' else 'bearish'];best=None
    for o in candidates:
        if not _ob_valid(k,o,d):continue
        dist=ob_distance_percent(p,o)
        if dist>8:continue
        age=len(k)-1-o['index'];rec=18 if age<=12 else 10 if age<=30 else 4
        score=o['strength']+rec+max(0,28-dist*3.2)
        if best is None or score>best[0]:best=(score,o)
    return best[1] if best else None


def detect_ob_retest(k,o,d):
    if not o:return False,[]
    touched=rejected=False;reasons=[];start=max(o['index']+2,len(k)-30)
    for x in k[start:]:
        if x[3]<=o['high']*1.001 and x[2]>=o['low']*.999:
            touched=True
            if d=='LONG' and x[4]>=o['mid']:rejected=True
            if d=='SHORT' and x[4]<=o['mid']:rejected=True
    if touched:reasons.append('السعر أعاد اختبار Order Block')
    if rejected:reasons.append('ظهر رفض من منطقة Order Block')
    return touched and rejected,reasons

# =========================================================
# ICT ENGINE
# =========================================================
def _swing_high(k,i,left=2,right=2):
    if i<left or i+right>=len(k):return False
    h=k[i][2];return all(h>=k[j][2] for j in range(i-left,i+right+1) if j!=i)

def _swing_low(k,i,left=2,right=2):
    if i<left or i+right>=len(k):return False
    l=k[i][3];return all(l<=k[j][3] for j in range(i-left,i+right+1) if j!=i)


def ict_liquidity_sweep(k,lookback=40):
    if len(k)<12:return {'bullish':False,'bearish':False,'type':'NONE','level':None,'reasons':[]}
    end=len(k)-1;start=max(3,end-lookback); highs=[];lows=[]
    for i in range(start,end-2):
        if _swing_high(k,i):highs.append((k[i][2],i))
        if _swing_low(k,i):lows.append((k[i][3],i))
    last=k[-1];prev=k[-2];bull=bear=False;level=None;reasons=[]
    if lows:
        lvl=max(v for v,i in lows if i<end) if any(i<end for _,i in lows) else None
        if lvl and last[3]<lvl and last[4]>lvl and last[4]>=last[1]:bull=True;level=lvl;reasons.append('ICT Bullish Liquidity Sweep أسفل قاع سابق')
    if highs:
        lvl=min(v for v,i in highs if i<end) if any(i<end for _,i in highs) else None
        if lvl and last[2]>lvl and last[4]<lvl and last[4]<=last[1]:bear=True;level=lvl;reasons.append('ICT Bearish Liquidity Sweep أعلى قمة سابقة')
    typ='BULLISH_SWEEP' if bull and not bear else 'BEARISH_SWEEP' if bear and not bull else 'BOTH' if bull and bear else 'NONE'
    return {'bullish':bull,'bearish':bear,'type':typ,'level':level,'reasons':reasons}


def detect_ict_mss_bos(k,lookback=35):
    if len(k)<15:return {'mss':'NONE','bos':'NONE','direction':'NONE','level':None,'reasons':[]}
    c=k[-1][4];prev=k[-2][4];start=max(2,len(k)-lookback);sh=[];sl=[]
    for i in range(start,len(k)-2):
        if _swing_high(k,i):sh.append((k[i][2],i))
        if _swing_low(k,i):sl.append((k[i][3],i))
    last_h=sh[-1][0] if sh else max(x[2] for x in k[-20:-2]);last_l=sl[-1][0] if sl else min(x[3] for x in k[-20:-2])
    # BOS: continuation through structure. MSS: displacement through opposite structure after liquidity event.
    bos='NONE';mss='NONE';direction='NONE';level=None;reasons=[]
    if c>last_h and prev<=last_h:bos='BULLISH_BOS';direction='LONG';level=last_h;reasons.append('ICT Bullish BOS')
    elif c<last_l and prev>=last_l:bos='BEARISH_BOS';direction='SHORT';level=last_l;reasons.append('ICT Bearish BOS')
    prior=k[-6][4]
    if c>last_h and prior<=last_h:mss='BULLISH_MSS';direction='LONG';level=last_h;reasons.append('ICT Bullish MSS')
    elif c<last_l and prior>=last_l:mss='BEARISH_MSS';direction='SHORT';level=last_l;reasons.append('ICT Bearish MSS')
    trigger_index = len(k)-1 if (mss!='NONE' or bos!='NONE') else None
    trigger_high = k[trigger_index][2] if trigger_index is not None else None
    trigger_low = k[trigger_index][3] if trigger_index is not None else None
    return {'mss':mss,'bos':bos,'direction':direction,'level':level,'trigger_index':trigger_index,'trigger_high':trigger_high,'trigger_low':trigger_low,'reasons':reasons}


def detect_fvg(k,lookback=60):
    bull=[];bear=[]
    if len(k)<5:return {'bullish':[],'bearish':[],'nearest_bullish':None,'nearest_bearish':None}
    start=max(1,len(k)-lookback)
    for i in range(start,len(k)-1):
        a=k[i-1];c=k[i+1]
        if c[3]>a[2]:bull.append({'index':i,'low':a[2],'high':c[3],'mid':(a[2]+c[3])/2,'size':c[3]-a[2]})
        if c[2]<a[3]:bear.append({'index':i,'low':c[2],'high':a[3],'mid':(c[2]+a[3])/2,'size':a[3]-c[2]})
    p=k[-1][4]
    def near(arr):
        valid=[x for x in arr if x['high']>=p*.92 and x['low']<=p*1.08]
        return min(valid,key=lambda x:abs(p-x['mid'])) if valid else None
    return {'bullish':bull[-20:],'bearish':bear[-20:],'nearest_bullish':near(bull),'nearest_bearish':near(bear)}


def detect_displacement(k,period=20):
    if len(k)<period+2:return {'direction':'NONE','score':0,'ratio':0,'reasons':[]}
    x=k[-1];rng=max(x[2]-x[3],1e-12);body=abs(x[4]-x[1]);ratio=body/rng;atr=calculate_atr(k[:-1],14) or rng
    move=body/atr if atr else 0;direction='NONE';score=0;reasons=[]
    if ratio>=.65 and move>=1.15:
        direction='LONG' if x[4]>x[1] else 'SHORT';score=min(100,round(50+ratio*25+move*10));reasons.append('Displacement قوي')
    return {'direction':direction,'score':score,'ratio':round(ratio,2),'move_atr':round(move,2),'reasons':reasons}


def calculate_premium_discount(k,lookback=80):
    if not k:return {'range_high':None,'range_low':None,'equilibrium':None,'zone':'UNKNOWN','position':50.0}
    z=k[-lookback:];hi=max(x[2] for x in z);lo=min(x[3] for x in z);eq=(hi+lo)/2;p=k[-1][4];span=max(hi-lo,1e-12);pos=(p-lo)/span*100
    zone='DISCOUNT' if pos<45 else 'PREMIUM' if pos>55 else 'EQUILIBRIUM'
    return {'range_high':hi,'range_low':lo,'equilibrium':eq,'zone':zone,'position':round(pos,1)}


def ict_confluence(k,d):
    sweep=ict_liquidity_sweep(k);ms=detect_ict_mss_bos(k);fvg=detect_fvg(k);disp=detect_displacement(k);pd=calculate_premium_discount(k)
    score=0;reasons=[]
    if d=='LONG':
        if sweep['bullish']:score+=22;reasons+=sweep['reasons']
        if ms['mss']=='BULLISH_MSS':score+=18;reasons+=ms['reasons']
        elif ms['bos']=='BULLISH_BOS':score+=14;reasons+=ms['reasons']
        if disp['direction']=='LONG':score+=14;reasons+=disp['reasons']
        if fvg['nearest_bullish']:score+=8;reasons.append('Bullish FVG قريب من السعر')
        if pd['zone']=='DISCOUNT':score+=16;reasons.append('السعر في Discount')
        elif pd['zone']=='PREMIUM':score-=8;reasons.append('السعر في Premium؛ LONG أقل جودة')
    elif d=='SHORT':
        if sweep['bearish']:score+=22;reasons+=sweep['reasons']
        if ms['mss']=='BEARISH_MSS':score+=18;reasons+=ms['reasons']
        elif ms['bos']=='BEARISH_BOS':score+=14;reasons+=ms['reasons']
        if disp['direction']=='SHORT':score+=14;reasons+=disp['reasons']
        if fvg['nearest_bearish']:score+=8;reasons.append('Bearish FVG قريب من السعر')
        if pd['zone']=='PREMIUM':score+=16;reasons.append('السعر في Premium')
        elif pd['zone']=='DISCOUNT':score-=8;reasons.append('السعر في Discount؛ SHORT أقل جودة')
    return {'score':max(0,min(100,score)),'sweep':sweep,'mss_bos':ms,'fvg':fvg,'displacement':disp,'premium_discount':pd,'reasons':reasons}

# =========================================================
# LEGACY STRUCTURE / LIQUIDITY
# =========================================================
def detect_market_structure(k):
    if len(k)<30:return {'structure':'UNKNOWN','bos':'NONE','liquidity_zone':'NONE','reasons':[]}
    c=k[-1][4];prev=k[-2][4];rh=max(x[2] for x in k[-30:-5]);rl=min(x[3] for x in k[-30:-5]);bos='NONE';rs=[]
    if c>rh and prev<=rh:bos='BULLISH_BOS';st='BULLISH';rs.append('BOS صاعد مؤكد')
    elif c<rl and prev>=rl:bos='BEARISH_BOS';st='BEARISH';rs.append('BOS هابط مؤكد')
    else:
        e9=ema([x[4] for x in k],9);e20=ema([x[4] for x in k],20);st='BULLISH' if e9 and e20 and e9>e20 else 'BEARISH' if e9 and e20 and e9<e20 else 'MIXED';rs.append('لا يوجد BOS جديد مؤكد')
    hh=max(x[2] for x in k[-10:]);ll=min(x[3] for x in k[-10:]);zone='LOW_LIQUIDITY' if abs(c-ll)/c*100<=.6 else 'HIGH_LIQUIDITY' if abs(hh-c)/c*100<=.6 else 'NONE'
    return {'structure':st,'bos':bos,'liquidity_zone':zone,'reasons':rs}


def detect_liquidity_flow(k):
    if len(k)<25:return 'NEUTRAL',0,[]
    r=k[:-1];bull=sum(x[5] for x in r[-15:] if x[4]>x[1]);bear=sum(x[5] for x in r[-15:] if x[4]<x[1]);tot=bull+bear;share=bull/tot if tot else .5;vr=calculate_volume_ratio([x[5] for x in r]);score=0;rs=[]
    if share>=.56 and vr>=.85:score+=2;rs.append('ضغط الشراء أعلى من البيع')
    if share<=.44 and vr>=.85:score-=2;rs.append('ضغط البيع أعلى من الشراء')
    rv=sum(x[5] for x in r[-5:])/5;pv=sum(x[5] for x in r[-15:-5])/10;rc=percentage_change(r[-6][4],r[-1][4])
    if rv>pv*1.05 and rc>=-2:score+=1;rs.append('الحجم يتحسن مع استقرار السعر')
    if rv>pv*1.05 and rc<=-2:score-=1;rs.append('ارتفاع الحجم مع ضغط بيعي')
    return ('INFLOW',score,rs) if score>=2 else ('OUTFLOW',score,rs) if score<=-2 else ('NEUTRAL',score,rs)


def calculate_timeframe_trend(k):
    if not k:return 'UNKNOWN'
    c=[x[4] for x in k];a=ema(c,9);b=ema(c,20);d=ema(c,50)
    if None in (a,b,d):return 'UNKNOWN'
    return 'LONG' if a>b>d and c[-1]>b else 'SHORT' if a<b<d and c[-1]<b else 'NEUTRAL'


def detect_bottom_accumulation(k):
    if len(k)<40:return False,0,[]
    c=[x[4] for x in k];v=[x[5] for x in k];n=min(30,len(c)//2);old=c[-2*n:-n];rec=c[-n:];dd=(min(rec)-max(old))/max(old)*100;rr=(max(rec)-min(rec))/min(rec)*100;ov=sum(v[-2*n:-n])/len(old);rv=sum(v[-10:])/10;score=(dd<=-4)+(rr<=20)+(rv>=ov*.65);rs=[]
    if dd<=-4:rs.append('هبوط سابق واضح')
    if rr<=20:rs.append('النطاق السعري بدأ يضيق')
    if score>=2:rs.append('الحجم ما زال موجوداً بعد الهبوط')
    return score>=2,score,rs


def smart_round(v):
    if v is None:return None
    try:v=float(v)
    except Exception:return 0
    if v>=1000:return round(v,2)
    if v>=100:return round(v,3)
    if v>=1:return round(v,4)
    if v>=.1:return round(v,5)
    if v>=.01:return round(v,6)
    return round(v,8)


def _mtf(t4,t1,t30,t15,d):return sum(x==d for x in (t4,t1,t30,t15))


def determine_plan_direction(direction,long_score,short_score,bullish_ob,bearish_ob,bullish_distance,bearish_distance, t4=None,t1=None,t30=None,t15=None, ict_long_score=0, ict_short_score=0):
    # v24: never create a plan that directly contradicts MTF/structure.
    if direction in ('LONG','SHORT'):
        return direction
    long_mtf = sum(x=='LONG' for x in (t4,t1,t30,t15) if x)
    short_mtf = sum(x=='SHORT' for x in (t4,t1,t30,t15) if x)
    if bullish_ob and not bearish_ob:
        if t15=='SHORT' or (t4=='SHORT' and t1=='SHORT'):
            return None
        return 'LONG'
    if bearish_ob and not bullish_ob:
        if t15=='LONG' or (t4=='LONG' and t1=='LONG'):
            return None
        return 'SHORT'
    if bullish_ob and bearish_ob:
        if long_mtf > short_mtf and t15 != 'SHORT' and ict_long_score >= ict_short_score:
            return 'LONG'
        if short_mtf > long_mtf and t15 != 'LONG' and ict_short_score >= ict_long_score:
            return 'SHORT'
        if t15=='LONG' and t15!='SHORT' and ict_long_score>=ict_short_score:
            return 'LONG'
        if t15=='SHORT' and ict_short_score>=ict_long_score:
            return 'SHORT'
        return None
    return None


def calculate_trade_plan(plan_direction, price, atr, ob, support, resistance, structure=None):
    """Calculate trade levels ONLY for a confirmed MARKET setup.
    SL is placed 2 pips beyond the MSS candle; if MSS is absent, the BOS
    trigger candle is used because the entry gate explicitly allows MSS OR BOS.
    """
    empty={'entry_min':None,'entry_max':None,'entry_price':None,'stop_loss':None,'tp1':None,'tp2':None,'tp3':None,'risk':None}
    try:
        if plan_direction not in ('LONG','SHORT') or not price or not ob:
            return empty
        structure=structure or {}
        if structure.get('mss')=='NONE' and structure.get('bos')=='NONE':
            return empty
        emin=ob['low']; emax=ob['high']
        entry=(emin+emax)/2 if emin<=price<=emax else emin if price<emin else emax
        # Crypto-safe pip convention: 1 pip = 0.01% of current price.
        pip=max(price*0.0001, 1e-12)
        buffer=2.0*pip
        trigger_high=structure.get('trigger_high')
        trigger_low=structure.get('trigger_low')
        if plan_direction=='LONG':
            if trigger_low is None: return empty
            sl=trigger_low-buffer
            if sl>=entry: return empty
            risk=entry-sl
            tp1=entry+risk*1.25; tp2=entry+risk*2; tp3=entry+risk*3
            if resistance and resistance>entry and (resistance-entry)/risk>=.85: tp1=min(tp1,resistance)
            tp1=max(tp1,entry+risk*.75); tp2=max(tp2,tp1+risk*.35); tp3=max(tp3,tp2+risk*.5)
        else:
            if trigger_high is None: return empty
            sl=trigger_high+buffer
            if sl<=entry: return empty
            risk=sl-entry
            tp1=entry-risk*1.25; tp2=entry-risk*2; tp3=entry-risk*3
            if support and support<entry and (entry-support)/risk>=.85: tp1=max(tp1,support)
            tp1=min(tp1,entry-risk*.75); tp2=min(tp2,tp1-risk*.35); tp3=min(tp3,tp2-risk*.5)
        return {'entry_min':emin,'entry_max':emax,'entry_price':entry,'stop_loss':sl,'tp1':tp1,'tp2':tp2,'tp3':tp3,'risk':risk}
    except Exception:
        return empty

def strong_entry_filter(direction, price, ob, ob4, ob_distance, retest, t4, t1, t30, t15, ict, score, room_distance, crash, pump):
    """v25.0 INSTITUTIONAL ENTRY GATE. OB is primary; ICT validates the trigger."""
    reasons=[]
    if not ob:
        return False,['Order Block غير موجود']
    if ob_distance > 0.75:
        return False,['السعر بعيد عن 1H Order Block (>0.75%)']
    if ob.get('strength',0) < 62:
        return False,['قوة Order Block أقل من 62']
    if crash or pump:
        return False,['حركة حادة/مطاردة سعر ممنوعة']

    ms=ict.get('mss_bos',{}); disp=ict.get('displacement',{}); sweep=ict.get('sweep',{}); pd=ict.get('premium_discount',{})
    if direction=='LONG':
        structure_ok=ms.get('mss')=='BULLISH_MSS' or ms.get('bos')=='BULLISH_BOS'
        displacement_ok=disp.get('direction')=='LONG' and disp.get('score',0)>=65
        sweep_ok=bool(sweep.get('bullish'))
        mtf4_ok=t4=='LONG'
        low_ok=(t30=='LONG' or t15=='LONG') and t30!='SHORT' and t15!='SHORT'
        pd_ok=pd.get('zone')=='DISCOUNT'
    else:
        structure_ok=ms.get('mss')=='BEARISH_MSS' or ms.get('bos')=='BEARISH_BOS'
        displacement_ok=disp.get('direction')=='SHORT' and disp.get('score',0)>=65
        sweep_ok=bool(sweep.get('bearish'))
        mtf4_ok=t4=='SHORT'
        low_ok=(t30=='SHORT' or t15=='SHORT') and t30!='LONG' and t15!='LONG'
        pd_ok=pd.get('zone')=='PREMIUM'

    ict_score=ict.get('score',0)
    reasons += [] if structure_ok else ['لا يوجد MSS/BOS حديث في اتجاه الصفقة']
    reasons += [] if displacement_ok else ['لا يوجد Displacement قوي وحديث']
    reasons += [] if sweep_ok else ['لا يوجد Liquidity Sweep واضح']
    reasons += [] if retest else ['لا يوجد Retest/رفض واضح من Order Block']
    reasons += [] if mtf4_ok else ['4H لا يؤكد اتجاه الصفقة']
    reasons += [] if low_ok else ['30m/15m لا يؤكدان الاتجاه أو أحدهما يعاكس']
    reasons += [] if room_distance > 0.50 else ['المساحة أمام الدعم/المقاومة ضيقة']
    reasons += [] if ict_score >= 45 else ['ICT Confluence أقل من 45']
    reasons += [] if score >= 78 else ['Opportunity Score أقل من 78']

    # Preferred institutional sequence: Sweep + MSS/BOS + Displacement + Retest.
    full_trigger = sweep_ok and structure_ok and displacement_ok and retest
    valid_trigger = full_trigger or (retest and structure_ok and displacement_ok and ict_score>=50)
    # Premium/discount is a quality boost, not mandatory when the full trigger exists.
    quality = (pd_ok or full_trigger)
    ok = mtf4_ok and low_ok and structure_ok and displacement_ok and valid_trigger and quality and room_distance>0.50 and ict_score>=45 and score>=78
    return ok,reasons

# =========================================================
# MAIN ANALYSIS
# =========================================================
def _get_coin_analysis_impl(symbol):
    symbol=normalize_symbol(symbol)
    if not symbol_exists(symbol):return None
    k1=get_bingx_klines(symbol,'1h',220);p=get_current_price(symbol,True)
    if p is None and k1:p=k1[-1][4]
    if p is None:return None
    if not k1 or len(k1)<50:return {'symbol':symbol,'direction':'NO TRADE','score':0,'entry_score':0,'state':'NO TRADE - بيانات 1H غير مكتملة','price':smart_round(p)}
    k4=get_bingx_klines(symbol,'4h',180);kd=get_bingx_klines(symbol,'1d',120);k30=get_bingx_klines(symbol,'30m',180);k15=get_bingx_klines(symbol,'15m',180)
    t1=calculate_timeframe_trend(k1);t4=calculate_timeframe_trend(k4);td=calculate_timeframe_trend(kd);t30=calculate_timeframe_trend(k30);t15=calculate_timeframe_trend(k15)
    c=[x[4] for x in k1];v=[x[5] for x in k1];rsi=calculate_rsi(c);atr=calculate_atr(k1) or p*.01;vr=calculate_volume_ratio(v);vt=calculate_volume_trend(v);sup,res=calculate_support_resistance(k1);st=detect_market_structure(k1);liq,liqs,liqr=detect_liquidity_flow(k1);bottom,bs,br=detect_bottom_accumulation(k1)
    bo=find_active_order_block(k1,'LONG',p);so=find_active_order_block(k1,'SHORT',p);bo4=find_active_order_block(k4,'LONG',p) if k4 else None;so4=find_active_order_block(k4,'SHORT',p) if k4 else None
    bor,bor_r=detect_ob_retest(k1,bo,'LONG');sor,sor_r=detect_ob_retest(k1,so,'SHORT');bd=ob_distance_percent(p,bo);sd=ob_distance_percent(p,so)
    ict_long=ict_confluence(k1,'LONG');ict_short=ict_confluence(k1,'SHORT')
    # 15m ICT confirmation is used as secondary confirmation, not primary OB selection.
    ict15_long=ict_confluence(k15,'LONG') if k15 else {'score':0,'sweep':{},'mss_bos':{},'fvg':{},'displacement':{},'premium_discount':{},'reasons':[]}
    ict15_short=ict_confluence(k15,'SHORT') if k15 else {'score':0,'sweep':{},'mss_bos':{},'fvg':{},'displacement':{},'premium_discount':{},'reasons':[]}
    l=s=0;lines=[];reject=[]
    if bo:
        l+=38+(10 if bo['strength']>=55 else 0)+(15 if bor else 0)+(10 if bd<=1.5 else 5 if bd<=3 else 0);lines.append('يوجد Bullish Order Block أساسي صالح على 1H')
    if so:
        s+=38+(10 if so['strength']>=55 else 0)+(15 if sor else 0)+(10 if sd<=1.5 else 5 if sd<=3 else 0);lines.append('يوجد Bearish Order Block أساسي صالح على 1H')
    if t4=='LONG':l+=8+(7 if bo4 else 0);lines.append('4H يدعم Bullish OB' if bo4 else '4H يميل للصعود')
    elif t4=='SHORT':s+=8+(7 if so4 else 0);lines.append('4H يدعم Bearish OB' if so4 else '4H يميل للهبوط')
    if t1=='LONG':l+=6
    elif t1=='SHORT':s+=6
    if t30=='LONG':l+=4
    elif t30=='SHORT':s+=4
    if t15=='LONG':l+=4
    elif t15=='SHORT':s+=4
    if st['bos']=='BULLISH_BOS':l+=10;lines.append('BOS صاعد يدعم Bullish OB')
    elif st['bos']=='BEARISH_BOS':s+=10;lines.append('BOS هابط يدعم Bearish OB')
    if liq=='INFLOW':l+=6;lines.append('السيولة تميل للشراء')
    elif liq=='OUTFLOW':s+=6;lines.append('السيولة تميل للبيع')
    if vr>=1.1:(l if l>=s else s).__class__; l+=3 if l>=s else 0;s+=3 if s>l else 0;lines.append('الحجم يدعم الحركة')
    if t4=='LONG' and 35<=rsi<=72:l+=3
    elif t4=='LONG' and rsi>82:l-=4;reject.append('RSI مرتفع جداً')
    if t4=='SHORT' and 28<=rsi<=68:s+=3
    elif t4=='SHORT' and rsi<20:s-=4;reject.append('RSI منخفض جداً')
    supd=abs(p-sup)/p*100;resd=abs(res-p)/p*100;ch2=percentage_change(c[-3],p);ch6=percentage_change(c[-7],p);crash=ch2<=-8 or ch6<=-15;pump=ch2>=8 or ch6>=15
    if crash:l-=10;s-=10;reject.append('حركة هبوط سريعة')
    if pump:l-=6;s-=6;reject.append('حركة صعود سريعة؛ لا نطارد السعر')
    # ICT is additive and deliberately capped so OB stays primary.
    l_ict=min(22,round(ict_long['score']*.22));s_ict=min(22,round(ict_short['score']*.22));l+=l_ict;s+=s_ict

    # v25: Opportunity Score must reflect REAL entry readiness.
    # A high raw score from OB/volume/MTF alone must never produce 90-100
    # while the institutional trigger is missing. This keeps scoring honest.
    def _readiness_cap(direction, raw, ob, dist, retest, t4, t1, t30, t15, ict, room, crash, pump):
        cap=100
        if not ob: return 0
        if dist>0.75: cap=min(cap,72)
        if dist>1.50: cap=min(cap,60)
        ms=ict.get('mss_bos',{})
        disp=ict.get('displacement',{})
        sweep=ict.get('sweep',{})
        structure_ok=(ms.get('mss')==('BULLISH_MSS' if direction=='LONG' else 'BEARISH_MSS') or
                      ms.get('bos')==('BULLISH_BOS' if direction=='LONG' else 'BEARISH_BOS'))
        disp_ok=(disp.get('direction')==direction and disp.get('score',0)>=65)
        sweep_ok=bool(sweep.get('bullish' if direction=='LONG' else 'bearish'))
        mtf_ok=(t4==direction)
        confirm_ok=((t30==direction or t15==direction) and t30!=('SHORT' if direction=='LONG' else 'LONG') and t15!=('SHORT' if direction=='LONG' else 'LONG'))
        pd_zone=ict.get('premium_discount',{}).get('zone')
        pd_bad=(direction=='LONG' and pd_zone=='PREMIUM') or (direction=='SHORT' and pd_zone=='DISCOUNT')
        if not structure_ok: cap=min(cap,68)
        if not disp_ok: cap=min(cap,68)
        if not (sweep_ok or retest): cap=min(cap,64)
        if not mtf_ok: cap=min(cap,62)
        if not confirm_ok: cap=min(cap,65)
        if pd_bad: cap=min(cap,72)
        if room<=0.50: cap=min(cap,58)
        if crash or pump: cap=min(cap,50)
        return int(max(0,min(100,raw,cap)))

    l=_readiness_cap('LONG',l,bo,bd,bor,t4,t1,t30,t15,ict_long,resd,crash,pump)
    s=_readiness_cap('SHORT',s,so,sd,sor,t4,t1,t30,t15,ict_short,supd,crash,pump)
    if l_ict:lines.append(f'ICT Bullish Confluence +{l_ict}')
    if s_ict:lines.append(f'ICT Bearish Confluence +{s_ict}')
    if ict_long['sweep'].get('bullish'):lines.append('Liquidity Sweep صاعد')
    if ict_short['sweep'].get('bearish'):lines.append('Liquidity Sweep هابط')
    long_near=bool(bo) and bd<=1.5;short_near=bool(so) and sd<=1.5
    long_ict_confirm=ict_long['score']>=25 or ict15_long['score']>=20
    short_ict_confirm=ict_short['score']>=25 or ict15_short['score']>=20
    long_confirm=long_near and (bor or st['bos']=='BULLISH_BOS' or long_ict_confirm or (_mtf(t4,t1,t30,t15,'LONG')>=2 and t15!='SHORT'))
    short_confirm=short_near and (sor or st['bos']=='BEARISH_BOS' or short_ict_confirm or (_mtf(t4,t1,t30,t15,'SHORT')>=2 and t15!='LONG'))
    # Require OB + proximity + confirmation. ICT improves confirmation but never creates a trade without OB.
    # v25.0 STRONG ENTRY GATE: tighten ENTRY READY while keeping OB primary.
    long_ok, long_rejects = strong_entry_filter('LONG', p, bo, bo4, bd, bor, t4, t1, t30, t15, ict_long, l, resd, crash, pump)
    short_ok, short_rejects = strong_entry_filter('SHORT', p, so, so4, sd, sor, t4, t1, t30, t15, ict_short, s, supd, crash, pump)
    if not long_ok and l >= 62: reject.extend(long_rejects[:6])
    if not short_ok and s >= 62: reject.extend(short_rejects[:6])
    if long_ok and l>=s:direction='LONG';es=l;state='ENTRY READY - Strong Bullish OB + ICT MSS/BOS + Sweep/Retest + Displacement + MTF'
    elif short_ok and s>l:direction='SHORT';es=s;state='ENTRY READY - Strong Bearish OB + ICT MSS/BOS + Sweep/Retest + Displacement + MTF'
    elif bo and l>=48 and not crash:direction='WAIT';es=l;state='REVERSAL WATCH - Bullish OB قريب وننتظر ICT/confirmation' if bd<=1.5 else 'REVERSAL WATCH - Bullish OB موجود لكن السعر بعيد'
    elif so and s>=48 and not crash:direction='WAIT';es=s;state='REVERSAL WATCH - Bearish OB قريب وننتظر ICT/confirmation' if sd<=1.5 else 'REVERSAL WATCH - Bearish OB موجود لكن السعر بعيد'
    elif bottom and (bo4 or so4):direction='WAIT';es=max(l,s,45);state='ACCUMULATION WATCH - MTF Order Block قريب وننتظر تأكيد 1H'
    else:direction='NO TRADE';es=max(l,s,0);state='NO TRADE - لا يوجد Order Block صالح قريب'
    plan_direction=determine_plan_direction(direction,l,s,bo,so,bd,sd,t4,t1,t30,t15,ict_long['score'],ict_short['score']);plan_ob=bo if plan_direction=='LONG' else so if plan_direction=='SHORT' else None
    selected_ict=ict_long if plan_direction=='LONG' else ict_short if plan_direction=='SHORT' else {}
    selected_ms=selected_ict.get('mss_bos',{}) if isinstance(selected_ict,dict) else {}
    selected_structure_ok=(selected_ms.get('mss') not in (None,'NONE') or selected_ms.get('bos') not in (None,'NONE'))
    if direction in ('LONG','SHORT') and not selected_structure_ok:
        direction='WAIT'; plan_direction=None; plan_ob=None; es=0; state='WAIT - لا يوجد MSS/BOS مؤكد في اتجاه الصفقة'
    plan=calculate_trade_plan(plan_direction,p,atr,plan_ob,sup,res, st);emin=plan['entry_min'];emax=plan['entry_max'];entry_price=plan['entry_price'];sl=plan['stop_loss'];tp1=plan['tp1'];tp2=plan['tp2'];tp3=plan['tp3'];risk=plan['risk']
    if direction=='WAIT' and plan_direction is None:
        state='WAIT - لا توجد جهة خطة متوافقة مع MTF/ICT حالياً'
    if plan_direction=='LONG' and sl and tp1 and tp1-entry_price<(entry_price-sl)*.70:direction='WAIT';state='REVERSAL WATCH - Bullish OB موجود لكن المقاومة قريبة'
    if plan_direction=='SHORT' and sl and tp1 and entry_price-tp1<(sl-entry_price)*.70:direction='WAIT';state='REVERSAL WATCH - Bearish OB موجود لكن الدعم قريب'
    if plan_direction=='LONG' and resd<=.12:direction='WAIT';state='REVERSAL WATCH - السعر قريب من المقاومة'
    if plan_direction=='SHORT' and supd<=.12:direction='WAIT';state='REVERSAL WATCH - السعر قريب من الدعم'
    buy=60+min(vr*6,25) if liq=='INFLOW' else 40-min(vr*5,25) if liq=='OUTFLOW' else 50
    return {'symbol':symbol,'direction':direction,'plan_direction':plan_direction,'score':int(max(0,min(100,es))),'entry_score':int(max(0,min(100,es))),'state':state,'price':smart_round(p),'rsi':rsi,'volume_ratio':vr,'volume_trend':vt,'liquidity_state':liq,'liquidity_score':liqs,'bottom_detected':bottom,'bottom_score':bs,'drawdown':0,'buy_pressure':round(max(5,min(95,buy)),1),'trend':'UP' if t4=='LONG' else 'DOWN' if t4=='SHORT' else 'NEUTRAL','trend_1d':td,'trend_4h':t4,'trend_1h':t1,'trend_30m':t30,'trend_15m':t15,'structure':st['structure'],'bos':st['bos'],'liquidity_zone':st['liquidity_zone'],'bullish_ob':bo,'bearish_ob':so,'bullish_ob_4h':bo4,'bearish_ob_4h':so4,'bullish_ob_distance':round(bd,2),'bearish_ob_distance':round(sd,2),'bullish_ob_retest':bor,'bearish_ob_retest':sor,'recent_change_2':round(ch2,2),'recent_change_6':round(ch6,2),'crash_detected':crash,'pump_detected':pump,
        # ICT fields
        'ict_long_score':ict_long['score'],'ict_short_score':ict_short['score'],'ict_score':max(ict_long['score'],ict_short['score']),'liquidity_sweep':ict_long['sweep']['type'] if l>=s else ict_short['sweep']['type'],'bullish_liquidity_sweep':ict_long['sweep']['bullish'],'bearish_liquidity_sweep':ict_short['sweep']['bearish'],'ict_mss':ict_long['mss_bos']['mss'] if l>=s else ict_short['mss_bos']['mss'],'ict_bos':ict_long['mss_bos']['bos'] if l>=s else ict_short['mss_bos']['bos'],'ict_fvg_bullish':ict_long['fvg']['nearest_bullish'],'ict_fvg_bearish':ict_short['fvg']['nearest_bearish'],'ict_displacement_long':ict_long['displacement'],'ict_displacement_short':ict_short['displacement'],'premium_discount':ict_long['premium_discount'] if l>=s else ict_short['premium_discount'],'ict_long_reasons':ict_long['reasons'],'ict_short_reasons':ict_short['reasons'],'ict15_long_score':ict15_long['score'],'ict15_short_score':ict15_short['score'],'entry_gate':'PASSED' if direction in ('LONG','SHORT') and selected_structure_ok else 'WAIT','entry_gate_requirements':'OB + proximity + MSS/BOS + Displacement + Sweep/Retest + 4H + 30m/15m + room',
         'score_semantics':'Opportunity Score = setup quality; ENTRY READY requires the independent institutional hard gate.',
        'entry_min':smart_round(emin),'entry_max':smart_round(emax),'entry_price':smart_round(entry_price),'stop_loss':smart_round(sl),'tp1':smart_round(tp1),'tp2':smart_round(tp2),'tp3':smart_round(tp3),'risk':smart_round(risk),'support':smart_round(sup),'resistance':smart_round(res),'support_distance':round(supd,2),'resistance_distance':round(resd,2),'long_score':int(max(0,min(100,l))),'short_score':int(max(0,min(100,s))),'analysis_lines':lines,'liquidity_reasons':liqr,'bottom_reasons':br,'structure_reasons':st['reasons'],'bullish_retest_reasons':bor_r,'bearish_retest_reasons':sor_r,'rejection_reasons':list(dict.fromkeys(reject))}


def get_coin_analysis(symbol):
    """Safe analysis entry point. Any missing/invalid OB/FVG/MSS/ICT value
    becomes a normal WAIT result instead of crashing the analysis engine."""
    symbol=normalize_symbol(symbol)
    try:
        result=_get_coin_analysis_impl(symbol)
        if not isinstance(result,dict):
            return {'symbol':symbol,'direction':'WAIT','plan_direction':None,'entry_gate':'WAIT'}
        result.setdefault('direction','WAIT')
        result.setdefault('plan_direction',None)
        result.setdefault('entry_gate','WAIT')
        return result
    except Exception as exc:
        logging.exception('Analysis engine protected failure for %s: %s', symbol, exc)
        return {'symbol':symbol,'direction':'WAIT','plan_direction':None,'entry_gate':'WAIT',
                'ict_mss':'NONE','ict_bos':'NONE','state':'WAIT - protected indicator failure'}


def test_market_data(symbol='BTCUSDT'):
    symbol=normalize_symbol(symbol);p=get_current_price(symbol,True);a=get_bingx_klines(symbol,'1h',60);b=get_bingx_klines(symbol,'4h',60)
    return {'symbol':symbol,'price_ok':p is not None,'price':p,'1h_rows':len(a) if a else 0,'4h_rows':len(b) if b else 0,'ok':p is not None and bool(a) and len(a)>=30}


def get_top_futures_symbols(limit=30):
    sy=get_futures_symbols();rows=_ticker_rows();cand=[]
    for x in rows:
        try:
            s=str(x.get('symbol','')).replace('-','').upper();v=float(x.get('quoteVolume',x.get('volume',0)));ch=abs(float(x.get('priceChangePercent',0)))
            if s in sy and s.endswith('USDT') and v>0:cand.append((s,v*(1+min(ch/100,.3))))
        except Exception:pass
    cand.sort(key=lambda x:x[1],reverse=True);return [x[0] for x in cand[:limit]] or list(sy)[:limit]


def _stage1_score(symbol):
    p=get_current_price(symbol);k=get_bingx_klines(symbol,'1h',120)
    if p is None or not k:return None
    obs=detect_order_blocks(k);cand=[];trend=calculate_timeframe_trend(k)
    for o in obs['bullish']+obs['bearish']:
        d='LONG' if o['type']=='BULLISH' else 'SHORT'
        if not _ob_valid(k,o,d):continue
        dist=ob_distance_percent(p,o)
        if dist>8:continue
        ret,_=detect_ob_retest(k,o,d);ict=ict_confluence(k,d)
        score=50+min(o['strength'],30)+(15 if ret else 0)+(8 if trend==d else 0)+min(12,ict['score']*.12)-dist*3
        cand.append((symbol,score,d,ret))
    return max(cand,key=lambda x:x[1]) if cand else None


def scan_market(limit=5):
    stage=[]
    for s in get_top_futures_symbols(30):
        try:
            x=_stage1_score(s)
            if x:stage.append(x)
        except Exception:logger.exception('STAGE1 FAILED | %s',s)
    stage.sort(key=lambda x:x[1],reverse=True);res=[]
    for s,*_ in stage[:15]:
        try:
            d=get_coin_analysis(s)
            if not d or d.get('direction') not in ('LONG','SHORT','WAIT') or d.get('crash_detected'):continue
            if d.get('bullish_ob') or d.get('bearish_ob') or d.get('bullish_ob_4h') or d.get('bearish_ob_4h'):res.append(d)
        except Exception:logger.exception('FULL ANALYSIS FAILED | %s',s)
    def rank(x):
        state=x.get('state','');sr=4 if 'ENTRY READY' in state else 3 if 'REVERSAL WATCH' in state else 2 if 'ACCUMULATION' in state else 1;ret=int(x.get('bullish_ob_retest') or x.get('bearish_ob_retest'));dist=min(x.get('bullish_ob_distance',999),x.get('bearish_ob_distance',999));return sr,ret,-dist,x.get('ict_score',0),x.get('entry_score',0)
    res.sort(key=rank,reverse=True);return res[:limit]


def _ob_text(o):return 'غير موجود' if not o else f"{smart_round(o['low'])} - {smart_round(o['high'])}"

def _fvg_text(f):return 'غير موجود' if not f else f"{smart_round(f['low'])} - {smart_round(f['high'])}"

def _plan_direction_text(d):return '🟢 LONG' if d=='LONG' else '🔴 SHORT' if d=='SHORT' else '⚪ غير محدد'


def generate_evidence_report(d):
    # STRICT OUTPUT GATE: never expose a trade plan, prices, reasons or WAIT execution.
    # Only a confirmed MARKET setup may produce the detailed report.
    if not d:
        return '🟡 انتهى الفحص. لم يتم العثور حالياً على فرصة دخول فوري كاملة الشروط على هذه العملة.'
    dr=d.get('direction')
    pd=d.get('plan_direction')
    mss=str(d.get('ict_mss','NONE'))
    ict_bos=str(d.get('ict_bos','NONE'))
    market_confirmed=(dr in ('LONG','SHORT') and pd==dr and (mss!='NONE' or ict_bos!='NONE') and d.get('entry_gate')=='PASSED')
    if not market_confirmed:
        return '🟡 انتهى الفحص. لم يتم العثور حالياً على فرصة دخول فوري كاملة الشروط على هذه العملة.'
    emo='🟢' if dr=='LONG' else '🔴';liq='🟢 دخول سيولة محتمل' if d.get('liquidity_state')=='INFLOW' else '🔴 خروج سيولة محتمل' if d.get('liquidity_state')=='OUTFLOW' else '🟡 سيولة محايدة';bos='🟢 BULLISH' if d.get('bos')=='BULLISH_BOS' else '🔴 BEARISH' if d.get('bos')=='BEARISH_BOS' else '⚪ NONE'
    lines=['🤖 BingX AI Scanner v25.0',f"💎 العملة: {d.get('symbol','-')}",f"💰 السعر الحالي: {d.get('price','-')}",f"📈 الاتجاه النهائي: {emo} {dr}",f"⭐ Entry Score: {d.get('entry_score',0)}/100",f"\n🧠 الحالة: {d.get('state','-')}",'\n🏦 ORDER BLOCK = المحرك الأساسي',f"🟢 Bullish OB 1H: {_ob_text(d.get('bullish_ob'))}",f"🔴 Bearish OB 1H: {_ob_text(d.get('bearish_ob'))}",f"📊 Bullish OB 4H: {_ob_text(d.get('bullish_ob_4h'))}",f"📊 Bearish OB 4H: {_ob_text(d.get('bearish_ob_4h'))}",f"📏 Bullish OB Distance: {d.get('bullish_ob_distance',999)}%",f"📏 Bearish OB Distance: {d.get('bearish_ob_distance',999)}%",f"🔄 Bullish Retest: {'YES' if d.get('bullish_ob_retest') else 'NO'}",f"🔄 Bearish Retest: {'YES' if d.get('bearish_ob_retest') else 'NO'}",'\n📊 ICT CONFLUENCE','💧 Liquidity Sweep: '+str(d.get('liquidity_sweep','NONE')),f"🧱 MSS: {d.get('ict_mss','NONE')}",f"🏗️ ICT BOS: {d.get('ict_bos','NONE')}",f"🕳️ Bullish FVG: {_fvg_text(d.get('ict_fvg_bullish'))}",f"🕳️ Bearish FVG: {_fvg_text(d.get('ict_fvg_bearish'))}",f"💥 ICT Score: {d.get('ict_score',0)}/100",f"💎 Premium/Discount: {d.get('premium_discount',{}).get('zone','UNKNOWN')}",'\n📊 Context',f"1D: {d.get('trend_1d')}",f"4H: {d.get('trend_4h')}",'\n⏱️ Confirmation',f"1H: {d.get('trend_1h')}",f"30m: {d.get('trend_30m')}",f"15m: {d.get('trend_15m')}",'\n🏗️ Structure',f"{d.get('structure')} | BOS: {bos}",f'\n💧 Liquidity: {liq}',f"📊 Volume: {d.get('volume_ratio')}x",f"📈 Volume Trend: {d.get('volume_trend')}",f"💪 Buy Pressure: {d.get('buy_pressure')}%",f"📊 RSI: {d.get('rsi')}",f"\n🛡️ Support: {d.get('support')}",f"🔴 Resistance: {d.get('resistance')}"]
    if pd in ('LONG','SHORT'):
        lines += ['\n━━━━━━━━━━━━━━━━━━','📋 خطة الصفقة',f"🧭 اتجاه الخطة: {_plan_direction_text(pd)}",'\n📍 منطقة الدخول:',f"{d.get('entry_min')} - {d.get('entry_max')}",f"💰 سعر الدخول المرجعي: {d.get('entry_price')}",f"\n🎯 TP1: {d.get('tp1')}",f"🎯 TP2: {d.get('tp2')}",f"🎯 TP3: {d.get('tp3')}",f"\n🛑 Stop Loss: {d.get('stop_loss')}"]
        lines += ['\n🟢 التنفيذ: دخول فوري (MARKET)','✅ شروط الدخول الحالية مكتملة: OB + MSS/BOS + ICT + MTF.']
    lines += ['\n\n🔍 أسباب القرار']+[f'• {x}' for x in d.get('analysis_lines',[])[:10]]+[f'⚠️ {x}' for x in d.get('rejection_reasons',[])[:5]]
    lines += ['\n🛡️ ORDER BLOCK هو العامل الأساسي.','⚙️ ICT Strong Filter = Liquidity Sweep + MSS/BOS + Displacement + MTF + FVG/Premium-Discount.','⚠️ 1D = Context | 4H = MTF | 1H = Primary OB | 30m + 15m = Confirmation.','⚠️ الإشارة تحليلية وليست ضماناً للربح.']
    return '\n'.join(lines)
