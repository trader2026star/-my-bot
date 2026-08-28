# =========================================================
# analysis.py - BingX Futures AI Scanner v21.0
# ORDER BLOCK PRIMARY ENGINE
# 1D Context | 4H MTF OB | 1H Primary OB | 30m/15m Confirmation
# Robust price + klines + OB + ENTRY/WAIT
# =========================================================
import time
import logging
import threading
import requests

BINGX_URL = 'https://open-api.bingx.com'
SESSION = requests.Session()
SESSION.headers.update({'User-Agent':'BingX-OB-Scanner/21.0','Accept':'application/json'})
logger = logging.getLogger(__name__)

SYMBOL_CACHE_SECONDS=600
KLINE_CACHE_SECONDS=45
PRICE_CACHE_SECONDS=3
TICKER_CACHE_SECONDS=5
MIN_REQUEST_INTERVAL=0.45
_RATE_LIMIT_UNTIL=0.0
_LAST_REQUEST_TIME=0.0
_SYMBOL_CACHE=set(); _SYMBOL_CACHE_TIME=0.0
_KLINE_CACHE={}; _PRICE_CACHE={}; _TICKER_CACHE=None; _TICKER_CACHE_TIME=0.0
_RATE_LOCK=threading.Lock(); _REQUEST_LOCK=threading.Lock()


def normalize_symbol(s):
    s=str(s).strip().upper().replace(' ','').replace('-','').replace('_','').replace('/','')
    return s if s.endswith(('USDT','USDC')) else s+'USDT'

def bingx_symbol(s):
    s=normalize_symbol(s); return s[:-4]+'-'+s[-4:]

def _rows(d):
    if not isinstance(d,dict): return []
    x=d.get('data')
    if isinstance(x,list): return x
    if isinstance(x,dict): return [x]
    return []

def bingx_get(path,params=None,timeout=12):
    global _RATE_LIMIT_UNTIL,_LAST_REQUEST_TIME
    with _RATE_LOCK:
        if time.time() < _RATE_LIMIT_UNTIL: return None
    with _REQUEST_LOCK:
        wait=MIN_REQUEST_INTERVAL-(time.time()-_LAST_REQUEST_TIME)
        if wait>0: time.sleep(wait)
        _LAST_REQUEST_TIME=time.time()
    try:
        r=SESSION.get(BINGX_URL+path,params=params or {},timeout=timeout)
        if r.status_code!=200:
            logger.warning('BingX HTTP %s | %s',r.status_code,path); return None
        d=r.json()
        if not isinstance(d,dict): return None
        code=d.get('code')
        if code in (109429,109400):
            with _RATE_LOCK: _RATE_LIMIT_UNTIL=max(_RATE_LIMIT_UNTIL,time.time()+60)
            logger.warning('BingX rate limit %s | %s',code,path); return None
        if code not in (0,None):
            logger.warning('BingX API error %s | %s',code,path); return None
        return d
    except Exception as e:
        logger.warning('BingX request failed | %s | %s',path,e); return None

def _is_crypto_usdt_symbol(s):
    s=str(s).upper().replace('-','')
    if not s.endswith('USDT'): return False
    base=s[:-4]
    blocked=('SP500','NASDAQ','DJI','US30','DXY','GOLD','SILVER','XAU','XAG','OIL','BRENT','WTI','COPPER','PLATINUM','PALLADIUM')
    return not base.endswith('USD') and not any(x in base for x in blocked)

def get_futures_symbols(force_refresh=False):
    global _SYMBOL_CACHE,_SYMBOL_CACHE_TIME
    if not force_refresh and _SYMBOL_CACHE and time.time()-_SYMBOL_CACHE_TIME<SYMBOL_CACHE_SECONDS: return set(_SYMBOL_CACHE)
    d=bingx_get('/openApi/swap/v2/quote/contracts'); out=set()
    for x in _rows(d):
        if isinstance(x,dict):
            s=str(x.get('symbol','')).replace('-','').upper(); status=x.get('status')
            if _is_crypto_usdt_symbol(s) and status in (1,'1',None): out.add(s)
    if out: _SYMBOL_CACHE=out; _SYMBOL_CACHE_TIME=time.time()
    return set(_SYMBOL_CACHE)

def symbol_exists(s):
    sy=get_futures_symbols(); return not sy or normalize_symbol(s) in sy

def _price_value(x):
    if not isinstance(x,dict): return None
    for k in ('price','lastPrice','last','close','markPrice'):
        try:
            v=float(x.get(k));
            if v>0:return v
        except: pass
    return None

def _ticker_rows(force=False):
    global _TICKER_CACHE,_TICKER_CACHE_TIME
    if not force and _TICKER_CACHE is not None and time.time()-_TICKER_CACHE_TIME<TICKER_CACHE_SECONDS:return _TICKER_CACHE
    x=_rows(bingx_get('/openApi/swap/v2/quote/ticker'))
    if x:_TICKER_CACHE=x;_TICKER_CACHE_TIME=time.time()
    return x

def _parse(rows):
    out=[]
    for x in rows:
        try:
            if isinstance(x,dict):
                t=x.get('time',x.get('timestamp',x.get('openTime',0))); o=x.get('open');h=x.get('high');l=x.get('low');c=x.get('close');v=x.get('volume',x.get('vol',0))
            elif isinstance(x,list) and len(x)>=6:t,o,h,l,c,v=x[:6]
            else:continue
            if None in (o,h,l,c):continue
            out.append([t,float(o),float(h),float(l),float(c),float(v or 0)])
        except: pass
    try:out.sort(key=lambda z:z[0])
    except:pass
    # remove duplicate timestamps
    seen=set(); clean=[]
    for x in out:
        if x[0] in seen: continue
        seen.add(x[0]); clean.append(x)
    return clean

def get_bingx_klines(s,interval='1h',limit=200):
    s=normalize_symbol(s); key=(s,str(interval).lower(),int(limit)); now=time.time()
    c=_KLINE_CACHE.get(key)
    if c and now-c[0]<KLINE_CACHE_SECONDS:return c[1]
    params={'symbol':bingx_symbol(s),'interval':str(interval).lower(),'limit':int(limit)}
    best=[]
    for ep in ('/openApi/swap/v3/quote/klines','/openApi/swap/v2/quote/klines'):
        r=_parse(_rows(bingx_get(ep,params)))
        if len(r)>len(best):best=r
        if len(r)>=30:
            _KLINE_CACHE[key]=(now,r); return r
    if best:_KLINE_CACHE[key]=(now,best); return best
    logger.warning('Kline empty %s interval=%s',s,interval); return None

def get_current_price(s,force=False):
    s=normalize_symbol(s); now=time.time(); c=_PRICE_CACHE.get(s)
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
    if k:
        p=k[-1][4]
        if p>0:_PRICE_CACHE[s]=(now,p);return p
    return None

def ema(v,n):
    if len(v)<n:return None
    e=sum(v[:n])/n;m=2/(n+1)
    for x in v[n:]:e=(x-e)*m+e
    return e

def calculate_ema(v,n):return ema(v,n)

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
    base=sum(v[-n-4:-4])/n; recent=sum(v[-4:-1])/3
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

# ---------------- ORDER BLOCK ENGINE ----------------
def detect_order_blocks(k,lookback=120):
    if len(k)<35:return {'bullish':[],'bearish':[]}
    bull=[];bear=[];start=max(5,len(k)-lookback)
    for i in range(start,len(k)-2):
        b,d=k[i],k[i+1];rng=max(d[2]-d[3],1e-12);body=abs(d[4]-d[1]);disp=body/rng
        if disp<.30:continue
        left=k[max(0,i-12):i]
        if not left:continue
        ph=max(x[2] for x in left);pl=min(x[3] for x in left)
        bull_bos=d[4]>ph or (d[2]>ph and d[4]>=d[1]);bear_bos=d[4]<pl or (d[3]<pl and d[4]<=d[1])
        lo,hi=sorted((b[1],b[4]));move=abs(percentage_change(d[1],d[4]));strength=min(100,42+disp*38+min(move,8)*3)
        item={'type':'BULLISH','index':i,'low':lo,'high':hi,'mid':(lo+hi)/2,'strength':round(strength,1)}
        if _dir(b)=='BEARISH' and _dir(d)=='BULLISH' and bull_bos:bull.append(item)
        item={'type':'BEARISH','index':i,'low':lo,'high':hi,'mid':(lo+hi)/2,'strength':round(strength,1)}
        if _dir(b)=='BULLISH' and _dir(d)=='BEARISH' and bear_bos:bear.append(item)
    bull=sorted(bull,key=lambda x:(x['index'],x['strength']),reverse=True)[:15]
    bear=sorted(bear,key=lambda x:(x['index'],x['strength']),reverse=True)[:15]
    return {'bullish':bull,'bearish':bear}

def price_inside_ob(p,o,tolerance=.008):
    if not o:return False
    pad=max((o['high']-o['low'])*tolerance,0)
    return o['low']-pad<=p<=o['high']+pad

def ob_distance_percent(p,o):
    if not o or p<=0:return 999
    if price_inside_ob(p,o):return 0.0
    return ((o['low']-p)/p*100) if p<o['low'] else ((p-o['high'])/p*100)

def _ob_valid(k,o,d):
    if not o:return False
    # Invalidation uses candle close plus a small wick allowance.
    for x in k[o['index']+2:]:
        if d=='LONG' and x[4]<o['low']*0.997:return False
        if d=='SHORT' and x[4]>o['high']*1.003:return False
    return True

def find_active_order_block(k,d,p):
    if not k:return None
    obs=detect_order_blocks(k); candidates=obs['bullish'] if d=='LONG' else obs['bearish'];best=None
    for o in candidates:
        if not _ob_valid(k,o,d):continue
        dist=ob_distance_percent(p,o)
        if dist>8:continue
        age=len(k)-1-o['index']; rec=18 if age<=12 else 10 if age<=30 else 4
        # Prefer price proximity strongly; never let an old far OB beat a fresh nearby OB.
        score=o['strength']+rec+max(0,28-dist*3.2)
        if best is None or score>best[0]:best=(score,o)
    return best[1] if best else None

def detect_ob_retest(k,o,d):
    if not o:return False,[]
    touched=False;rejected=False;reasons=[]
    start=max(o['index']+2,len(k)-30)
    for x in k[start:]:
        if x[3]<=o['high']*1.001 and x[2]>=o['low']*.999:
            touched=True
            if d=='LONG' and x[4]>=o['mid']:rejected=True
            if d=='SHORT' and x[4]<=o['mid']:rejected=True
    if touched:reasons.append('السعر أعاد اختبار Order Block')
    if rejected:reasons.append('ظهر رفض من منطقة Order Block')
    return touched and rejected,reasons

# ---------------- CONFIRMATION ----------------
def detect_market_structure(k):
    if len(k)<30:return {'structure':'UNKNOWN','bos':'NONE','liquidity_zone':'NONE','reasons':[]}
    c=k[-1][4];prev=k[-2][4];rh=max(x[2] for x in k[-30:-5]);rl=min(x[3] for x in k[-30:-5]);bos='NONE';rs=[]
    if c>rh and prev<=rh:bos='BULLISH_BOS';st='BULLISH';rs.append('BOS صاعد مؤكد')
    elif c<rl and prev>=rl:bos='BEARISH_BOS';st='BEARISH';rs.append('BOS هابط مؤكد')
    else:
        e9=ema([x[4] for x in k],9);e20=ema([x[4] for x in k],20)
        st='BULLISH' if e9 and e20 and e9>e20 else 'BEARISH' if e9 and e20 and e9<e20 else 'MIXED';rs.append('لا يوجد BOS جديد مؤكد')
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
    c=[x[4] for x in k];v=[x[5] for x in k];n=min(30,len(c)//2);old=c[-2*n:-n];rec=c[-n:]
    dd=(min(rec)-max(old))/max(old)*100;rr=(max(rec)-min(rec))/min(rec)*100;ov=sum(v[-2*n:-n])/len(old);rv=sum(v[-10:])/10;score=(dd<=-4)+(rr<=20)+(rv>=ov*.65);rs=[]
    if dd<=-4:rs.append('هبوط سابق واضح')
    if rr<=20:rs.append('النطاق السعري بدأ يضيق')
    if score>=2:rs.append('الحجم ما زال موجوداً بعد الهبوط')
    return score>=2,score,rs

def smart_round(v):
    if v is None:return None
    try:v=float(v)
    except:return 0
    return round(v,2) if v>=1000 else round(v,3) if v>=100 else round(v,4) if v>=1 else round(v,5) if v>=.1 else round(v,6) if v>=.01 else round(v,8)

def _mtf(t4,t1,t30,t15,d):return sum(x==d for x in (t4,t1,t30,t15))

def get_coin_analysis(symbol):
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
    l=s=0;lines=[];reject=[]
    if bo:l+=38;lines.append('يوجد Bullish Order Block أساسي صالح على 1H');l+=10 if bo['strength']>=55 else 0;l+=15 if bor else 0;l+=10 if bd<=1.5 else 5 if bd<=3 else 0
    if so:s+=38;lines.append('يوجد Bearish Order Block أساسي صالح على 1H');s+=10 if so['strength']>=55 else 0;s+=15 if sor else 0;s+=10 if sd<=1.5 else 5 if sd<=3 else 0
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
    if vr>=1.1:(l if l>=s else s); l+=3 if l>=s else 0; s+=3 if s>l else 0;lines.append('الحجم يدعم الحركة')
    if t4=='LONG' and 35<=rsi<=72:l+=3
    elif t4=='LONG' and rsi>82: l-=4;reject.append('RSI مرتفع جداً')
    if t4=='SHORT' and 28<=rsi<=68:s+=3
    elif t4=='SHORT' and rsi<20:s-=4;reject.append('RSI منخفض جداً')
    supd=abs(p-sup)/p*100;resd=abs(res-p)/p*100;ch2=percentage_change(c[-3],p);ch6=percentage_change(c[-7],p);crash=ch2<=-8 or ch6<=-15;pump=ch2>=8 or ch6>=15
    if crash:l-=10;s-=10;reject.append('حركة هبوط سريعة')
    if pump:l-=6;s-=6;reject.append('حركة صعود سريعة؛ لا نطارد السعر')
    long_near=bool(bo) and bd<=1.5;short_near=bool(so) and sd<=1.5
    long_confirm=long_near and (bor or st['bos']=='BULLISH_BOS' or (_mtf(t4,t1,t30,t15,'LONG')>=2 and t15!='SHORT'))
    short_confirm=short_near and (sor or st['bos']=='BEARISH_BOS' or (_mtf(t4,t1,t30,t15,'SHORT')>=2 and t15!='LONG'))
    long_ok=bool(bo) and l>=62 and long_near and long_confirm and resd>.35 and not crash and not(rsi>=82 and not bor) and t15!='SHORT'
    short_ok=bool(so) and s>=62 and short_near and short_confirm and supd>.35 and not crash and not(rsi<=20 and not sor) and t15!='LONG'
    if long_ok and l>=s:direction='LONG';es=l;state='ENTRY READY - Bullish Order Block + Confirmation'
    elif short_ok and s>l:direction='SHORT';es=s;state='ENTRY READY - Bearish Order Block + Confirmation'
    elif bo and l>=48 and not crash:direction='WAIT';es=l;state='REVERSAL WATCH - Bullish OB قريب وننتظر التأكيد' if bd<=1.5 else 'REVERSAL WATCH - Bullish OB موجود لكن السعر بعيد'
    elif so and s>=48 and not crash:direction='WAIT';es=s;state='REVERSAL WATCH - Bearish OB قريب وننتظر التأكيد' if sd<=1.5 else 'REVERSAL WATCH - Bearish OB موجود لكن السعر بعيد'
    elif bottom and (bo4 or so4):direction='WAIT';es=max(l,s,45);state='ACCUMULATION WATCH - MTF Order Block قريب وننتظر تأكيد 1H'
    else:direction='NO TRADE';es=max(l,s,0);state='NO TRADE - لا يوجد Order Block صالح قريب'
    emin=emax=sl=tp1=tp2=tp3=None
    if direction=='LONG' and bo:
        emin,emax=bo['low'],bo['high'];sl=min(bo['low']-atr*.35,p-atr*.8);risk=max(p-sl,atr*.5);tp1=p+risk*1.25;tp2=p+risk*2;tp3=p+risk*3
        if res>p and (res-p)/p*100>=.35:tp1=min(tp1,res)
    elif direction=='SHORT' and so:
        emin,emax=so['low'],so['high'];sl=max(so['high']+atr*.35,p+atr*.8);risk=max(sl-p,atr*.5);tp1=p-risk*1.25;tp2=p-risk*2;tp3=p-risk*3
        if sup<p and (p-sup)/p*100>=.35:tp1=max(tp1,sup)
    # Never publish an entry whose TP1 is too close.
    if direction=='LONG' and sl and tp1 and (tp1-p)<(p-sl)*.70:direction='WAIT';state='REVERSAL WATCH - Bullish OB موجود لكن المقاومة قريبة';emin=emax=sl=tp1=tp2=tp3=None
    if direction=='SHORT' and sl and tp1 and (p-tp1)<(sl-p)*.70:direction='WAIT';state='REVERSAL WATCH - Bearish OB موجود لكن الدعم قريب';emin=emax=sl=tp1=tp2=tp3=None
    if direction=='LONG' and resd<=.12:direction='WAIT';state='REVERSAL WATCH - السعر قريب من المقاومة';emin=emax=sl=tp1=tp2=tp3=None
    if direction=='SHORT' and supd<=.12:direction='WAIT';state='REVERSAL WATCH - السعر قريب من الدعم';emin=emax=sl=tp1=tp2=tp3=None
    buy=60+min(vr*6,25) if liq=='INFLOW' else 40-min(vr*5,25) if liq=='OUTFLOW' else 50
    return {'symbol':symbol,'direction':direction,'score':int(max(0,min(100,es))),'entry_score':int(max(0,min(100,es))),'state':state,'price':smart_round(p),'rsi':rsi,'volume_ratio':vr,'volume_trend':vt,'liquidity_state':liq,'liquidity_score':liqs,'bottom_detected':bottom,'bottom_score':bs,'drawdown':0,'buy_pressure':round(max(5,min(95,buy)),1),'trend':'UP' if t4=='LONG' else 'DOWN' if t4=='SHORT' else 'NEUTRAL','trend_1d':td,'trend_4h':t4,'trend_1h':t1,'trend_30m':t30,'trend_15m':t15,'structure':st['structure'],'bos':st['bos'],'liquidity_zone':st['liquidity_zone'],'bullish_ob':bo,'bearish_ob':so,'bullish_ob_4h':bo4,'bearish_ob_4h':so4,'bullish_ob_distance':round(bd,2),'bearish_ob_distance':round(sd,2),'bullish_ob_retest':bor,'bearish_ob_retest':sor,'recent_change_2':round(ch2,2),'recent_change_6':round(ch6,2),'crash_detected':crash,'pump_detected':pump,'entry_min':smart_round(emin),'entry_max':smart_round(emax),'stop_loss':smart_round(sl),'tp1':smart_round(tp1),'tp2':smart_round(tp2),'tp3':smart_round(tp3),'support':smart_round(sup),'resistance':smart_round(res),'support_distance':round(supd,2),'resistance_distance':round(resd,2),'long_score':int(max(0,min(100,l))),'short_score':int(max(0,min(100,s))),'analysis_lines':lines,'liquidity_reasons':liqr,'bottom_reasons':br,'structure_reasons':st['reasons'],'bullish_retest_reasons':bor_r,'bearish_retest_reasons':sor_r,'rejection_reasons':list(dict.fromkeys(reject))}

def test_market_data(symbol='BTCUSDT'):
    symbol=normalize_symbol(symbol);p=get_current_price(symbol,True);a=get_bingx_klines(symbol,'1h',60);b=get_bingx_klines(symbol,'4h',60)
    return {'symbol':symbol,'price_ok':p is not None,'price':p,'1h_rows':len(a) if a else 0,'4h_rows':len(b) if b else 0,'ok':p is not None and bool(a) and len(a)>=30}

def get_top_futures_symbols(limit=30):
    sy=get_futures_symbols();rows=_ticker_rows();cand=[]
    for x in rows:
        try:
            s=str(x.get('symbol','')).replace('-','').upper();v=float(x.get('quoteVolume',x.get('volume',0)));ch=abs(float(x.get('priceChangePercent',0)))
            if s in sy and s.endswith('USDT') and v>0:cand.append((s,v*(1+min(ch/100,.3))))
        except:pass
    cand.sort(key=lambda x:x[1],reverse=True);return [x[0] for x in cand[:limit]] or list(sy)[:limit]

def _stage1_score(symbol):
    p=get_current_price(symbol);k=get_bingx_klines(symbol,'1h',120)
    if p is None or not k:return None
    obs=detect_order_blocks(k);cand=[]
    for o in obs['bullish']+obs['bearish']:
        d='LONG' if o['type']=='BULLISH' else 'SHORT'
        if not _ob_valid(k,o,d):continue
        dist=ob_distance_percent(p,o)
        if dist>8:continue
        ret,_=detect_ob_retest(k,o,d);trend=calculate_timeframe_trend(k);score=50+min(o['strength'],30)+(15 if ret else 0)+(8 if trend==d else 0)-dist*3
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
        state=x.get('state','');sr=4 if 'ENTRY READY' in state else 3 if 'REVERSAL WATCH' in state else 2 if 'ACCUMULATION' in state else 1;ret=int(x.get('bullish_ob_retest') or x.get('bearish_ob_retest'));dist=min(x.get('bullish_ob_distance',999),x.get('bearish_ob_distance',999));return (sr,ret,-dist,x.get('entry_score',0))
    res.sort(key=rank,reverse=True);return res[:limit]

def _ob_text(o):return 'غير موجود' if not o else f"{smart_round(o['low'])} - {smart_round(o['high'])}"

def generate_evidence_report(d):
    if not d:return '⚠️ تعذر إكمال التحليل.\nلم يتم استلام بيانات صالحة من محرك التحليل.'
    dr=d.get('direction','WAIT');emo='🟢' if dr=='LONG' else '🔴' if dr=='SHORT' else '🟡';liq='🟢 دخول سيولة محتمل' if d.get('liquidity_state')=='INFLOW' else '🔴 خروج سيولة محتمل' if d.get('liquidity_state')=='OUTFLOW' else '🟡 سيولة محايدة';bos='🟢 BULLISH' if d.get('bos')=='BULLISH_BOS' else '🔴 BEARISH' if d.get('bos')=='BEARISH_BOS' else '⚪ NONE'
    lines=['🤖 BingX AI Scanner',f"💎 العملة: {d.get('symbol','-')}",f"💰 السعر الحالي: {d.get('price','-')}",f"📈 الاتجاه النهائي: {emo} {dr}",f"⭐ Entry Score: {d.get('entry_score',0)}/100",f"\n🧠 الحالة: {d.get('state','-')}",'\n🏦 ORDER BLOCK = المحرك الأساسي',f"🟢 Bullish OB 1H: {_ob_text(d.get('bullish_ob'))}",f"🔴 Bearish OB 1H: {_ob_text(d.get('bearish_ob'))}",f"📊 Bullish OB 4H: {_ob_text(d.get('bullish_ob_4h'))}",f"📊 Bearish OB 4H: {_ob_text(d.get('bearish_ob_4h'))}",f"📏 Bullish OB Distance: {d.get('bullish_ob_distance',999)}%",f"📏 Bearish OB Distance: {d.get('bearish_ob_distance',999)}%",f"🔄 Bullish Retest: {'YES' if d.get('bullish_ob_retest') else 'NO'}",f"🔄 Bearish Retest: {'YES' if d.get('bearish_ob_retest') else 'NO'}",'\n📊 Context',f"1D: {d.get('trend_1d')}",f"4H: {d.get('trend_4h')}",'\n⏱️ Confirmation',f"1H: {d.get('trend_1h')}",f"30m: {d.get('trend_30m')}",f"15m: {d.get('trend_15m')}",'\n🏗️ Structure',f"{d.get('structure')} | BOS: {bos}",f'\n💧 Liquidity: {liq}',f"📊 Volume: {d.get('volume_ratio')}x",f"📈 Volume Trend: {d.get('volume_trend')}",f"💪 Buy Pressure: {d.get('buy_pressure')}%",f"📊 RSI: {d.get('rsi')}",f"\n🛡️ Support: {d.get('support')}",f"🔴 Resistance: {d.get('resistance')}"]
    if dr in ('LONG','SHORT'):lines += ['\n📍 منطقة الدخول',f"{d.get('entry_min')} - {d.get('entry_max')}",f"\n🛑 Stop Loss: {d.get('stop_loss')}",f"\n🎯 TP1: {d.get('tp1')}",f"🎯 TP2: {d.get('tp2')}",f"🎯 TP3: {d.get('tp3')}"]
    else:
        o=d.get('bullish_ob') if d.get('bullish_ob_distance',999)<=d.get('bearish_ob_distance',999) else d.get('bearish_ob')
        lines += ['\n📍 منطقة الدخول',_ob_text(o),'⏳ انتظار تأكيد السعر داخل/قرب Order Block','\n🛑 Stop Loss: غير محدد']
    lines += ['\n\n🔍 أسباب القرار']+[f'• {x}' for x in d.get('analysis_lines',[])[:10]]+[f'⚠️ {x}' for x in d.get('rejection_reasons',[])[:5]]+['\n🛡️ ORDER BLOCK هو العامل الأساسي.','⚠️ 1D = Context | 4H = MTF | 1H = Primary OB | 30m + 15m = Confirmation.','⚠️ الإشارة تحليلية وليست ضماناً للربح.']
    return '\n'.join(lines)
