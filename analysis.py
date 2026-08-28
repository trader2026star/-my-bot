# =========================================================
# analysis.py - BingX Futures AI Scanner v18.0
# ORDER BLOCK PRIMARY: 1H OB -> Retest/BOS -> Liquidity -> MTF
# FIX: robust BingX data/price + practical OB detection + scoring
# =========================================================
import time, logging, threading, requests

BINGX_URL = 'https://open-api.bingx.com'
SESSION = requests.Session()
SESSION.headers.update({'User-Agent':'CryptoZeroReversal-BingX-OB-Scanner/18.0','Accept':'application/json'})
logger = logging.getLogger(__name__)

SYMBOL_CACHE_SECONDS=600; KLINE_CACHE_SECONDS=60; PRICE_CACHE_SECONDS=3; TICKER_CACHE_SECONDS=5
_SYMBOL_CACHE=set(); _SYMBOL_CACHE_TIME=0
_KLINE_CACHE={}; _PRICE_CACHE={}; _TICKER_CACHE=None; _TICKER_CACHE_TIME=0
_RATE_LIMIT_UNTIL=0; _RATE_LOCK=threading.Lock(); _REQUEST_LOCK=threading.Lock(); _LAST_REQUEST_TIME=0.0
MIN_REQUEST_INTERVAL=1.05


def bingx_get(path, params=None, timeout=12):
    global _RATE_LIMIT_UNTIL, _LAST_REQUEST_TIME
    with _RATE_LOCK:
        if time.time() < _RATE_LIMIT_UNTIL:
            return None
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
            with _RATE_LOCK: _RATE_LIMIT_UNTIL=max(_RATE_LIMIT_UNTIL,time.time()+90)
            return None
        if code not in (0,None):
            logger.warning('BingX API ERROR code=%s | %s',code,path); return None
        return d
    except Exception as e:
        logger.warning('BingX REQUEST FAILED | %s | %s',path,e); return None


def normalize_symbol(s):
    s=str(s).strip().upper().replace(' ','').replace('-','').replace('_','').replace('/','')
    return s if s.endswith(('USDT','USDC')) else s+'USDT'


def bingx_symbol(s):
    s=normalize_symbol(s); return s[:-4]+'-'+s[-4:]


def _rows(d):
    if not isinstance(d,dict): return []
    x=d.get('data')
    return x if isinstance(x,list) else ([x] if isinstance(x,dict) else [])


def _is_crypto_usdt_symbol(s):
    s=str(s).upper().replace('-','')
    if not s.endswith('USDT'): return False
    base=s[:-4]
    blocked=('SP500','NASDAQ','DJI','US30','DXY','GOLD','SILVER','XAU','XAG','OIL','BRENT','WTI','COPPER','PLATINUM','PALLADIUM')
    if base.endswith('USD') or any(x in base for x in blocked): return False
    return True


def get_futures_symbols(force_refresh=False):
    global _SYMBOL_CACHE,_SYMBOL_CACHE_TIME
    if not force_refresh and _SYMBOL_CACHE and time.time()-_SYMBOL_CACHE_TIME<SYMBOL_CACHE_SECONDS:
        return set(_SYMBOL_CACHE)
    d=bingx_get('/openApi/swap/v2/quote/contracts'); out=set()
    for x in _rows(d):
        if isinstance(x,dict):
            s=str(x.get('symbol','')).replace('-','').upper()
            if _is_crypto_usdt_symbol(s) and x.get('status') in (1,'1',None): out.add(s)
    if out: _SYMBOL_CACHE=out; _SYMBOL_CACHE_TIME=time.time()
    return set(_SYMBOL_CACHE)


def symbol_exists(s):
    s=normalize_symbol(s); sy=get_futures_symbols(); return not sy or s in sy


def _price_row(x):
    if not isinstance(x,dict): return None
    for k in ('price','lastPrice','last','close','markPrice'):
        try:
            v=float(x.get(k));
            if v>0: return v
        except Exception: pass
    return None


def _ticker_rows(force=False):
    global _TICKER_CACHE,_TICKER_CACHE_TIME
    if not force and _TICKER_CACHE is not None and time.time()-_TICKER_CACHE_TIME<TICKER_CACHE_SECONDS:
        return _TICKER_CACHE
    x=_rows(bingx_get('/openApi/swap/v2/quote/ticker'))
    if x: _TICKER_CACHE=x; _TICKER_CACHE_TIME=time.time()
    return x


def get_current_price(s,force=False):
    s=normalize_symbol(s); now=time.time(); c=_PRICE_CACHE.get(s)
    if not force and c and now-c[0]<PRICE_CACHE_SECONDS: return c[1]
    for x in _ticker_rows(force):
        if isinstance(x,dict) and str(x.get('symbol','')).replace('-','').upper()==s:
            p=_price_row(x)
            if p: _PRICE_CACHE[s]=(now,p); return p
    for ep in ('/openApi/swap/v2/quote/price','/openApi/swap/v1/ticker/price','/openApi/swap/v3/quote/price'):
        for x in _rows(bingx_get(ep,{'symbol':bingx_symbol(s)})):
            p=_price_row(x)
            if p: _PRICE_CACHE[s]=(now,p); return p
    k=get_bingx_klines(s,'1h',60)
    if k:
        try:
            p=float(k[-1][4]);
            if p>0: _PRICE_CACHE[s]=(now,p); return p
        except Exception: pass
    return None


def _parse(rows):
    out=[]
    for x in rows:
        try:
            if isinstance(x,dict):
                t=x.get('time') or x.get('timestamp') or x.get('openTime') or 0
                o=x.get('open'); h=x.get('high'); l=x.get('low'); c=x.get('close'); v=x.get('volume',x.get('vol',0))
            elif isinstance(x,list) and len(x)>=6: t,o,h,l,c,v=x[:6]
            else: continue
            if None in (o,h,l,c): continue
            out.append([t,float(o),float(h),float(l),float(c),float(v or 0)])
        except Exception: pass
    try: out.sort(key=lambda z:z[0])
    except Exception: pass
    return out


def get_bingx_klines(s,interval='1h',limit=200):
    s=normalize_symbol(s); key=(s,interval,int(limit)); now=time.time(); c=_KLINE_CACHE.get(key)
    if c and now-c[0]<KLINE_CACHE_SECONDS: return c[1]
    best=[]; p={'symbol':bingx_symbol(s),'interval':str(interval).lower(),'limit':int(limit)}
    for ep in ('/openApi/swap/v3/quote/klines','/openApi/swap/v2/quote/klines'):
        r=_parse(_rows(bingx_get(ep,p))); best=max(best,r,key=len)
        if len(r)>=30: _KLINE_CACHE[key]=(now,r); return r
    if best: _KLINE_CACHE[key]=(now,best); return best
    return None


def calculate_ema(v,n):
    if len(v)<n:return None
    e=sum(v[:n])/n; m=2/(n+1)
    for x in v[n:]: e=(x-e)*m+e
    return e


def calculate_rsi(c,period=14):
    if len(c)<period+1:return 50.0
    g=[max(c[i]-c[i-1],0) for i in range(1,len(c))]; l=[max(c[i-1]-c[i],0) for i in range(1,len(c))]
    ag=sum(g[:period])/period; al=sum(l[:period])/period
    for i in range(period,len(g)):
        ag=(ag*(period-1)+g[i])/period; al=(al*(period-1)+l[i])/period
    return 100.0 if al==0 else round(100-100/(1+ag/al),2)


def calculate_atr(k,n=14):
    if len(k)<n+1:return None
    tr=[max(x[2]-x[3],abs(x[2]-k[i-1][4]),abs(x[3]-k[i-1][4])) for i,x in enumerate(k[1:],1)]
    a=sum(tr[:n])/n
    for x in tr[n:]: a=(a*(n-1)+x)/n
    return a


def calculate_volume_ratio(v,n=20):
    if len(v)<n+4:return 1.0
    a=sum(v[-4:-1])/3; b=sum(v[-n-4:-4])/n
    return round(max(.05,min(5,a/b)),2) if b>0 else 1.0


def calculate_volume_trend(v,short_period=5,long_period=20):
    if len(v)<long_period+short_period+1:return 'NEUTRAL'
    a=sum(v[-short_period-1:-1])/short_period; b=sum(v[-long_period-short_period-1:-short_period-1])/long_period
    return 'RISING' if b and a/b>=1.12 else 'FALLING' if b and a/b<=.88 else 'NEUTRAL'


def percentage_change(a,b): return 0 if not a else (b-a)/a*100


def calculate_support_resistance(k):
    if not k:return 0,0
    p=k[-1][4]; h=[x[2] for x in k[-80:]]; l=[x[3] for x in k[-80:]]
    s=[x for x in l if x<p]; r=[x for x in h if x>p]
    return (max(s) if s else min(l)),(min(r) if r else max(h))


def _dir(k): return 'BULLISH' if k[4]>k[1] else 'BEARISH' if k[4]<k[1] else 'NEUTRAL'

# v18: OB is detected from displacement candles and the last opposite candle.
# The old version required a close beyond a very small 5-candle extreme, which
# produced too few blocks. Here BOS is confirmed against a wider local swing.
def detect_order_blocks(k,lookback=120):
    if len(k)<30:return {'bullish':[],'bearish':[]}
    bull=[]; bear=[]; start=max(5,len(k)-lookback)
    for i in range(start,len(k)-2):
        b=k[i]; d=k[i+1]; rng=max(d[2]-d[3],1e-12); body=abs(d[4]-d[1]);
        displacement=body/rng
        if displacement<0.45: continue
        left=k[max(0,i-12):i]
        ph=max(x[2] for x in left); pl=min(x[3] for x in left)
        # Allow wick/small-close BOS so valid OBs are not discarded too early.
        bull_bos=d[4]>ph or d[2]>ph and d[4]>=d[1]
        bear_bos=d[4]<pl or d[3]<pl and d[4]<=d[1]
        if _dir(b)=='BEARISH' and _dir(d)=='BULLISH' and bull_bos:
            lo,hi=sorted((b[1],b[4])); strength=min(100,40+displacement*35+min(max(percentage_change(d[1],d[4]),0),6)*4)
            bull.append({'type':'BULLISH','index':i,'low':lo,'high':hi,'mid':(lo+hi)/2,'strength':round(strength,1)})
        if _dir(b)=='BULLISH' and _dir(d)=='BEARISH' and bear_bos:
            lo,hi=sorted((b[1],b[4])); strength=min(100,40+displacement*35+min(max(-percentage_change(d[1],d[4]),0),6)*4)
            bear.append({'type':'BEARISH','index':i,'low':lo,'high':hi,'mid':(lo+hi)/2,'strength':round(strength,1)})
    return {'bullish':sorted(bull,key=lambda x:(x['index'],x['strength']),reverse=True)[:12], 'bearish':sorted(bear,key=lambda x:(x['index'],x['strength']),reverse=True)[:12]}


def price_inside_ob(p,o,tolerance=.005):
    if not o:return False
    m=max((o['high']-o['low'])*tolerance,0)
    return o['low']-m<=p<=o['high']+m


def ob_distance_percent(p,o):
    if not o or p<=0:return 999
    if price_inside_ob(p,o):return 0
    return ((o['low']-p)/p*100) if p<o['low'] else ((p-o['high'])/p*100)


def _ob_valid(k,o,d):
    if not o:return False
    # Do not invalidate an OB merely because of an intrabar wick.
    for x in k[o['index']+2:]:
        if d=='LONG' and x[4]<o['low']*(1-0.001): return False
        if d=='SHORT' and x[4]>o['high']*(1+0.001): return False
    return True


def find_active_order_block(k,d,p):
    obs=detect_order_blocks(k); cs=obs['bullish' if d=='LONG' else 'bearish']; best=None
    for o in cs:
        if not _ob_valid(k,o,d):continue
        dist=ob_distance_percent(p,o)
        if dist>12:continue
        rec=12 if o['index']>=len(k)-15 else 7 if o['index']>=len(k)-35 else 2
        proximity=max(0,20-dist*2.5)
        score=o['strength']+rec+proximity
        if best is None or score>best[0]:best=(score,o)
    return best[1] if best else None


def detect_ob_retest(k,o,d):
    if not o:return False,[]
    touched=False; rejected=False; reasons=[]
    start=max(o['index']+2,len(k)-18)
    for x in k[start:]:
        if x[3]<=o['high'] and x[2]>=o['low']:
            touched=True
            if d=='LONG' and x[4]>=o['mid']:rejected=True
            if d=='SHORT' and x[4]<=o['mid']:rejected=True
    if touched: reasons.append('السعر أعاد اختبار Order Block')
    if rejected: reasons.append('ظهر رفض من منطقة Order Block')
    return touched and rejected,reasons


def detect_market_structure(k):
    if len(k)<25:return {'structure':'UNKNOWN','bos':'NONE','liquidity_zone':'NONE','reasons':[]}
    c=k[-1][4]; prev=k[-2][4]; rh=max(x[2] for x in k[-30:-5]); rl=min(x[3] for x in k[-30:-5]); bos='NONE'; st='MIXED'; rs=[]
    if c>rh and prev<=rh:bos='BULLISH_BOS';st='BULLISH';rs.append('BOS صاعد مؤكد')
    elif c<rl and prev>=rl:bos='BEARISH_BOS';st='BEARISH';rs.append('BOS هابط مؤكد')
    else:
        hh=max(x[2] for x in k[-10:]);ll=min(x[3] for x in k[-10:]); st='BULLISH' if c>=hh*.997 else 'BEARISH' if c<=ll*1.003 else 'MIXED';rs.append('لا يوجد BOS جديد مؤكد')
    hh=max(x[2] for x in k[-10:]);ll=min(x[3] for x in k[-10:]); zone='LOW_LIQUIDITY' if abs(c-ll)/c*100<=.6 else 'HIGH_LIQUIDITY' if abs(hh-c)/c*100<=.6 else 'NONE'
    return {'structure':st,'bos':bos,'liquidity_zone':zone,'reasons':rs}


def detect_liquidity_flow(k):
    if len(k)<25:return 'NEUTRAL',0,[]
    r=k[:-1]; bull=sum(x[5] for x in r[-15:] if x[4]>x[1]); bear=sum(x[5] for x in r[-15:] if x[4]<x[1]); tot=bull+bear; share=bull/tot if tot else .5
    vr=calculate_volume_ratio([x[5] for x in r]); rc=percentage_change(r[-6][4],r[-1][4]); rv=sum(x[5] for x in r[-5:])/5; pv=sum(x[5] for x in r[-15:-5])/10; sc=0; rs=[]
    if share>=.56 and vr>=.85:sc+=2;rs.append('ضغط الشراء أعلى من البيع')
    if rv>pv*1.05 and rc>=-2:sc+=1;rs.append('الحجم يتحسن مع استقرار السعر')
    if share<=.44 and vr>=.85:sc-=2;rs.append('ضغط البيع أعلى من الشراء')
    if rv>pv*1.05 and rc<=-2:sc-=1;rs.append('ارتفاع الحجم مع ضغط بيعي')
    return ('INFLOW',sc,rs) if sc>=2 else ('OUTFLOW',sc,rs) if sc<=-2 else ('NEUTRAL',sc,rs)


def calculate_timeframe_trend(k):
    if not k:return 'UNKNOWN'
    c=[x[4] for x in k]; a=calculate_ema(c,9); b=calculate_ema(c,20); d=calculate_ema(c,50)
    if None in (a,b,d):return 'UNKNOWN'
    return 'LONG' if a>b>d and c[-1]>b else 'SHORT' if a<b<d and c[-1]<b else 'NEUTRAL'


def detect_bottom_accumulation(k):
    if len(k)<40:return False,0,[]
    c=[x[4] for x in k];v=[x[5] for x in k]; n=min(30,len(c)//2); old=c[-2*n:-n]; rec=c[-n:]
    dd=(min(rec)-max(old))/max(old)*100; rr=(max(rec)-min(rec))/min(rec)*100
    score=(1 if dd<=-4 else 0)+(1 if rr<=18 else 0)+(1 if sum(v[-10:])/10>=sum(v[-2*n:-n])/len(old)*.65 else 0); rs=[]
    if dd<=-4:rs.append('هبوط سابق واضح')
    if rr<=18:rs.append('النطاق السعري بدأ يضيق')
    if score>=2:rs.append('الحجم ما زال موجوداً بعد الهبوط')
    return score>=2,score,rs


def smart_round(v):
    try:v=float(v)
    except:return 0
    if v>=1000:return round(v,2)
    if v>=100:return round(v,3)
    if v>=1:return round(v,4)
    if v>=.1:return round(v,5)
    if v>=.01:return round(v,6)
    return round(v,8)


def get_coin_analysis(symbol):
    symbol=normalize_symbol(symbol)
    if not symbol_exists(symbol):return None
    k1=get_bingx_klines(symbol,'1h',200); p=get_current_price(symbol,True)
    if p is None and k1:
        try:p=float(k1[-1][4])
        except Exception:p=None
    if p is None:return None
    if not k1 or len(k1)<30:return {'symbol':symbol,'direction':'NO TRADE','score':0,'entry_score':0,'state':'NO TRADE - بيانات 1H غير مكتملة','price':smart_round(p)}
    k4=get_bingx_klines(symbol,'4h',160); kd=get_bingx_klines(symbol,'1d',120); k30=get_bingx_klines(symbol,'30m',160); k15=get_bingx_klines(symbol,'15m',160)
    t1=calculate_timeframe_trend(k1);t4=calculate_timeframe_trend(k4);td=calculate_timeframe_trend(kd);t30=calculate_timeframe_trend(k30);t15=calculate_timeframe_trend(k15)
    c=[x[4] for x in k1];v=[x[5] for x in k1]; rsi=calculate_rsi(c);atr=calculate_atr(k1) or p*.01;vr=calculate_volume_ratio(v);vt=calculate_volume_trend(v);sup,res=calculate_support_resistance(k1)
    st=detect_market_structure(k1);liq,liqs,liqr=detect_liquidity_flow(k1);bottom,bs,br=detect_bottom_accumulation(k1)
    bo=find_active_order_block(k1,'LONG',p);so=find_active_order_block(k1,'SHORT',p);bo4=find_active_order_block(k4,'LONG',p) if k4 else None;so4=find_active_order_block(k4,'SHORT',p) if k4 else None
    bor,bor_r=detect_ob_retest(k1,bo,'LONG');sor,sor_r=detect_ob_retest(k1,so,'SHORT');bd=ob_distance_percent(p,bo) if bo else 999;sd=ob_distance_percent(p,so) if so else 999
    l=s=0;lines=[];reject=[]
    if bo:l+=35;lines.append('يوجد Bullish Order Block فعال على 1H');l+=10 if bo['strength']>=55 else 0;l+=20 if bor else 0
    if so:s+=35;lines.append('يوجد Bearish Order Block فعال على 1H');s+=10 if so['strength']>=55 else 0;s+=20 if sor else 0
    if t4=='LONG':l+=15+(15 if bo4 else 0)
    elif t4=='SHORT':s+=15+(15 if so4 else 0)
    if t1=='LONG':l+=7
    elif t1=='SHORT':s+=7
    if t30=='LONG':l+=5
    elif t30=='SHORT':s+=5
    if t15=='LONG':l+=5
    elif t15=='SHORT':s+=5
    if st['bos']=='BULLISH_BOS':l+=12;lines.append('BOS صاعد يؤكد Bullish OB')
    elif st['bos']=='BEARISH_BOS':s+=12;lines.append('BOS هابط يؤكد Bearish OB')
    if liq=='INFLOW':l+=8;lines.append('السيولة تميل للشراء')
    elif liq=='OUTFLOW':s+=8;lines.append('السيولة تميل للبيع')
    if vr>=1.15:
        if l>=s:l+=5
        else:s+=5
        lines.append('الحجم يدعم الحركة')
    if t4=='LONG' and 38<=rsi<=68:l+=4
    elif t4=='SHORT' and 32<=rsi<=65:s+=4
    supd=abs(p-sup)/p*100;resd=abs(res-p)/p*100
    ch2=percentage_change(c[-3],p);ch6=percentage_change(c[-7],p);crash=ch2<=-8 or ch6<=-15;pump=ch2>=8 or ch6>=15
    if crash:l-=10;s-=10;reject.append('حركة هبوط سريعة')
    if pump:l-=8;s-=8;reject.append('حركة صعود سريعة؛ لا نطارد السعر')
    lc=bor or (st['bos']=='BULLISH_BOS' and t1=='LONG'); sc=sor or (st['bos']=='BEARISH_BOS' and t1=='SHORT')
    # v18: do not require retest as the only confirmation. A fresh OB plus
    # aligned lower timeframes can stay in WAIT; ENTRY needs retest or BOS.
    long_ready=bool(bo) and l>=70 and lc and t15!='SHORT' and not crash and resd>.20
    short_ready=bool(so) and s>=70 and sc and t15!='LONG' and not crash and supd>.20
    if long_ready and l>=s: direction='LONG';es=l;state='ENTRY READY - Bullish Order Block + Confirmation'
    elif short_ready and s>l: direction='SHORT';es=s;state='ENTRY READY - Bearish Order Block + Confirmation'
    elif bo and l>=55 and resd>.20 and not crash: direction='WAIT';es=l;state='REVERSAL WATCH - Bullish OB موجود وننتظر Retest/BOS'
    elif so and s>=55 and supd>.20 and not crash: direction='WAIT';es=s;state='REVERSAL WATCH - Bearish OB موجود وننتظر Retest/BOS'
    elif bottom: direction='WAIT';es=max(l,45);state='ACCUMULATION WATCH - تجميع محتمل وننتظر Order Block/BOS'
    else: direction='NO TRADE';es=max(l,s,0);state='NO TRADE - Order Block غير مكتمل التأكيد'
    emin=emax=sl=tp1=tp2=tp3=None
    if direction=='LONG' and bo:
        emin,emax=bo['low'],bo['high'];sl=min(bo['low']-atr*.35,p-atr*.8);risk=max(p-sl,atr*.5);tp1=p+risk*1.2;tp2=p+risk*2;tp3=p+risk*3
        if res>p:tp1=min(tp1,res)
    elif direction=='SHORT' and so:
        emin,emax=so['low'],so['high'];sl=max(so['high']+atr*.35,p+atr*.8);risk=max(sl-p,atr*.5);tp1=p-risk*1.2;tp2=p-risk*2;tp3=p-risk*3
        if sup<p:tp1=max(tp1,sup)
    if direction=='LONG' and (resd<=.12 or sl is None or sl>=p): direction='WAIT';state='REVERSAL WATCH - السعر قريب من المقاومة';emin=emax=sl=tp1=tp2=tp3=None
    if direction=='SHORT' and (supd<=.12 or sl is None or sl<=p): direction='WAIT';state='REVERSAL WATCH - السعر قريب من الدعم';emin=emax=sl=tp1=tp2=tp3=None
    buy=60+min(vr*6,25) if liq=='INFLOW' else 40-min(vr*5,25) if liq=='OUTFLOW' else 50
    return {'symbol':symbol,'direction':direction,'score':int(max(0,min(100,es))),'entry_score':int(max(0,min(100,es))),'state':state,'price':smart_round(p),'rsi':rsi,'volume_ratio':vr,'volume_trend':vt,'liquidity_state':liq,'liquidity_score':liqs,'bottom_detected':bottom,'bottom_score':bs,'drawdown':0,'buy_pressure':round(max(5,min(95,buy)),1),'trend':'UP' if t4=='LONG' else 'DOWN' if t4=='SHORT' else 'NEUTRAL','trend_1d':td,'trend_4h':t4,'trend_1h':t1,'trend_30m':t30,'trend_15m':t15,'structure':st['structure'],'bos':st['bos'],'liquidity_zone':st['liquidity_zone'],'bullish_ob':bo,'bearish_ob':so,'bullish_ob_4h':bo4,'bearish_ob_4h':so4,'bullish_ob_distance':round(bd,2),'bearish_ob_distance':round(sd,2),'bullish_ob_retest':bor,'bearish_ob_retest':sor,'recent_change_2':round(ch2,2),'recent_change_6':round(ch6,2),'crash_detected':crash,'pump_detected':pump,'entry_min':smart_round(emin) if emin is not None else None,'entry_max':smart_round(emax) if emax is not None else None,'stop_loss':smart_round(sl) if sl is not None else None,'tp1':smart_round(tp1) if tp1 is not None else None,'tp2':smart_round(tp2) if tp2 is not None else None,'tp3':smart_round(tp3) if tp3 is not None else None,'support':smart_round(sup),'resistance':smart_round(res),'support_distance':round(supd,2),'resistance_distance':round(resd,2),'long_score':int(max(0,min(100,l))),'short_score':int(max(0,min(100,s))),'analysis_lines':lines,'liquidity_reasons':liqr,'bottom_reasons':br,'structure_reasons':st['reasons'],'bullish_retest_reasons':bor_r,'bearish_retest_reasons':sor_r,'rejection_reasons':list(dict.fromkeys(reject))}


def test_market_data(symbol='BTCUSDT'):
    symbol=normalize_symbol(symbol);p=get_current_price(symbol,True);a=get_bingx_klines(symbol,'1h',60);b=get_bingx_klines(symbol,'4h',60)
    return {'symbol':symbol,'price_ok':p is not None,'price':p,'1h_rows':len(a) if a else 0,'4h_rows':len(b) if b else 0,'ok':p is not None and bool(a) and len(a)>=30}


def get_top_futures_symbols(limit=30):
    sy=get_futures_symbols()
    if not sy:return []
    rows=_ticker_rows(); cand=[]
    for x in rows:
        try:
            s=str(x.get('symbol','')).replace('-','').upper();v=float(x.get('quoteVolume',x.get('volume',0)));ch=abs(float(x.get('priceChangePercent',0)))
            if s in sy and s.endswith('USDT') and v>0:cand.append((s,v*(1+min(ch/100,.3))))
        except Exception:pass
    cand.sort(key=lambda x:x[1],reverse=True);return [x[0] for x in cand[:limit]] or list(sy)[:limit]


def _stage1_score(symbol):
    p=get_current_price(symbol); k=get_bingx_klines(symbol,'1h',100)
    if p is None or not k:return None
    o=detect_order_blocks(k); best=max(o['bullish']+o['bearish'],key=lambda x:x['strength'],default=None)
    if not best:return None
    d='LONG' if best['type']=='BULLISH' else 'SHORT';dist=ob_distance_percent(p,best);ret,_=detect_ob_retest(k,best,d)
    t=calculate_timeframe_trend(k); score=45+min(best['strength'],30)+(20 if ret else 0)+(10 if t==d else 0)-min(dist*3,36)
    return symbol,score,d,ret


def scan_market(limit=5):
    uni=get_top_futures_symbols(30);stage=[x for s in uni if (x:=_stage1_score(s))];stage.sort(key=lambda x:x[1],reverse=True);res=[]
    for s,*_ in stage[:10]:
        try:
            d=get_coin_analysis(s)
            if d and d.get('direction') in ('LONG','SHORT','WAIT') and not d.get('crash_detected'):res.append(d)
        except Exception:logger.exception('FULL ANALYSIS FAILED | %s',s)
    def rank(x):
        return (3 if 'ENTRY READY' in x.get('state','') else 2 if 'REVERSAL WATCH' in x.get('state','') else 1 if 'ACCUMULATION WATCH' in x.get('state','') else 0,x.get('entry_score',0),x.get('bullish_ob_retest',False) or x.get('bearish_ob_retest',False))
    res.sort(key=rank,reverse=True);return res[:limit]


def _ob_text(o): return 'غير موجود' if not o else f"{smart_round(o['low'])} - {smart_round(o['high'])}"


def generate_evidence_report(d):
    if not d:return '⚠️ تعذر إكمال التحليل.\nلم يتم استلام بيانات صالحة من محرك التحليل.'
    dr=d.get('direction','WAIT'); emo='🟢' if dr=='LONG' else '🔴' if dr=='SHORT' else '🟡'
    liq='🟢 دخول سيولة محتمل' if d.get('liquidity_state')=='INFLOW' else '🔴 خروج سيولة محتمل' if d.get('liquidity_state')=='OUTFLOW' else '🟡 سيولة محايدة'
    bos='🟢 BULLISH' if d.get('bos')=='BULLISH_BOS' else '🔴 BEARISH' if d.get('bos')=='BEARISH_BOS' else '⚪ NONE'
    lines=[f"🤖 BingX AI Scanner\n\n💎 العملة: {d.get('symbol','-')}\n💰 السعر الحالي: {d.get('price','-')}\n📈 الاتجاه النهائي: {emo} {dr}\n⭐ Entry Score: {d.get('entry_score',0)}/100\n\n🧠 الحالة: {d.get('state','-')}\n\n🏦 ORDER BLOCK = المحرك الأساسي\n🟢 Bullish OB 1H: {_ob_text(d.get('bullish_ob'))}\n🔴 Bearish OB 1H: {_ob_text(d.get('bearish_ob'))}\n📊 Bullish OB 4H: {_ob_text(d.get('bullish_ob_4h'))}\n📊 Bearish OB 4H: {_ob_text(d.get('bearish_ob_4h'))}\n🔄 Bullish Retest: {'YES' if d.get('bullish_ob_retest') else 'NO'}\n🔄 Bearish Retest: {'YES' if d.get('bearish_ob_retest') else 'NO'}\n\n📊 Context\n1D: {d.get('trend_1d')}\n4H: {d.get('trend_4h')}\n\n⏱️ Confirmation\n1H: {d.get('trend_1h')}\n30m: {d.get('trend_30m')}\n15m: {d.get('trend_15m')}\n\n🏗️ Structure\n{d.get('structure')} | BOS: {bos}\n\n💧 Liquidity: {liq}\n📊 Volume: {d.get('volume_ratio')}x\n📈 Volume Trend: {d.get('volume_trend')}\n💪 Buy Pressure: {d.get('buy_pressure')}%\n📊 RSI: {d.get('rsi')}\n\n🛡️ Support: {d.get('support')}\n🔴 Resistance: {d.get('resistance')}\n"]
    if dr in ('LONG','SHORT'):
        lines += [f"\n📍 منطقة الدخول\n{d.get('entry_min')} - {d.get('entry_max')}\n\n🛑 Stop Loss: {d.get('stop_loss')}\n\n🎯 TP1: {d.get('tp1')}\n🎯 TP2: {d.get('tp2')}\n🎯 TP3: {d.get('tp3')}"]
    else: lines += ['\n📍 منطقة الدخول\n⏳ انتظار Retest / BOS\n\n🛑 Stop Loss: غير محدد']
    lines += ['\n\n🔍 أسباب القرار']+[f'• {x}' for x in d.get('analysis_lines',[])[:10]]+['\n🛡️ ORDER BLOCK هو العامل الأساسي.','⚠️ 1D = Context | 4H = MTF | 1H = Primary OB | 30m + 15m = Confirmation.','⚠️ الإشارة تحليلية وليست ضماناً للربح.']
    return '\n'.join(lines)
