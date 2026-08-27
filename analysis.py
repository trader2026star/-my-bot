import time
import logging
import threading
import requests

BINGX_URL = "https://open-api.bingx.com"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "CryptoZeroReversal-BingX-Scanner/8.0", "Accept": "application/json"})
logger = logging.getLogger(__name__)
REQUEST_TIMEOUT = 12

_SYMBOL_CACHE = set(); _SYMBOL_CACHE_TIME = 0
SYMBOL_CACHE_SECONDS = 600
_KLINE_CACHE = {}; _KLINE_CACHE_TIME = {}
KLINE_CACHE_SECONDS = 45
_REQUEST_LOCK = threading.Lock(); _LAST_REQUEST_TIME = 0.0
MIN_REQUEST_INTERVAL = 0.45
_RATE_LIMIT_UNTIL = 0

# Coins that are useful for the daily-trend scanner. They are only a priority list;
# the scanner still discovers ALL available BingX USDT contracts.
PRIORITY_SYMBOLS = {
    "BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","DOGEUSDT","ADAUSDT",
    "SUIUSDT","LINKUSDT","AVAXUSDT","LTCUSDT","DOTUSDT","TRXUSDT","PEPEUSDT",
    "SHIBUSDT","UNIUSDT","WIFUSDT","BONKUSDT","FLOKIUSDT","SEIUSDT","NEARUSDT",
    "APTUSDT","ARBUSDT","OPUSDT","INJUSDT","TIAUSDT","ATOMUSDT","FILUSDT",
    "AAVEUSDT","MKRUSDT","CRVUSDT","COMPUSDT","JUPUSDT","RAYUSDT","WLDUSDT",
    "ONDOUSDT","ENAUSDT","PENDLEUSDT","STXUSDT","IMXUSDT","GALAUSDT","SANDUSDT",
    "MANAUSDT","AXSUSDT","APEUSDT","FETUSDT","TAOUSDT","RENDERUSDT","HBARUSDT",
    "ALGOUSDT","VETUSDT","ICPUSDT","ETCUSDT","BCHUSDT","XLMUSDT","KASUSDT",
    "HEIUSDT","ACTUSDT","CHIPUSDT","MAGUSDT","SOLOUSDT","NITUSDT","STARUSDT",
}

def _throttle():
    global _LAST_REQUEST_TIME
    with _REQUEST_LOCK:
        wait = MIN_REQUEST_INTERVAL - (time.time() - _LAST_REQUEST_TIME)
        if wait > 0: time.sleep(wait)
        _LAST_REQUEST_TIME = time.time()

def bingx_get(path, params=None):
    global _RATE_LIMIT_UNTIL
    if time.time() < _RATE_LIMIT_UNTIL: return None
    _throttle()
    try:
        r = SESSION.get(BINGX_URL + path, params=params or {}, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            logger.warning("BingX HTTP %s: %s", r.status_code, r.text[:300]); return None
        data = r.json()
        if not isinstance(data, dict): return None
        code = data.get("code")
        if code in (109429, 109400):
            _RATE_LIMIT_UNTIL = time.time() + 60
            logger.warning("BingX rate limit; cooldown 60s"); return None
        if code not in (0, None):
            logger.warning("BingX API error %s: %s", code, str(data)[:400]); return None
        return data
    except requests.RequestException as e:
        logger.warning("BingX request error: %s", e); return None
    except Exception as e:
        logger.exception("Unexpected BingX error: %s", e); return None

def normalize_symbol(symbol):
    if not symbol: return ""
    s = str(symbol).upper().strip()
    for c in " /-_": s = s.replace(c, "")
    return s if s.endswith("USDT") else s + "USDT"

def bingx_symbol(symbol):
    s = normalize_symbol(symbol)
    return f"{s[:-4]}-USDT" if s.endswith("USDT") and s[:-4] else s

def _extract_rows(data):
    if not data: return []
    rows = data.get("data")
    if isinstance(rows, dict):
        rows = rows.get("data", rows.get("rows", [rows]))
    return rows if isinstance(rows, list) else []

def get_futures_symbols():
    global _SYMBOL_CACHE, _SYMBOL_CACHE_TIME
    now = time.time()
    if _SYMBOL_CACHE and now - _SYMBOL_CACHE_TIME < SYMBOL_CACHE_SECONDS:
        return list(_SYMBOL_CACHE)
    symbols = set()
    for endpoint in ("/openApi/swap/v2/quote/contracts", "/openApi/swap/v2/quote/ticker"):
        rows = _extract_rows(bingx_get(endpoint))
        for item in rows:
            if not isinstance(item, dict): continue
            s = item.get("symbol") or item.get("pair") or item.get("contract")
            if s:
                s = normalize_symbol(str(s).replace("-", ""))
                if s.endswith("USDT"): symbols.add(s)
        if symbols: break
    if not symbols:
        logger.warning("BingX symbol discovery failed; using fallback list")
        symbols = set(PRIORITY_SYMBOLS)
    _SYMBOL_CACHE = symbols; _SYMBOL_CACHE_TIME = time.time()
    logger.info("Loaded %s BingX USDT futures symbols", len(symbols))
    return list(symbols)

def _interval_to_bingx(interval):
    return {"1m":"1m","3m":"3m","5m":"5m","15m":"15m","30m":"30m","1h":"1h","2h":"2h","4h":"4h","6h":"6h","8h":"8h","12h":"12h","1d":"1d","3d":"3d","1w":"1w"}.get(str(interval).lower(), interval)

def get_klines(symbol, interval="1h", limit=120):
    api_symbol = bingx_symbol(symbol); interval = _interval_to_bingx(interval)
    key = (api_symbol, interval, int(limit)); now = time.time()
    if key in _KLINE_CACHE and now - _KLINE_CACHE_TIME.get(key, 0) < KLINE_CACHE_SECONDS:
        return _KLINE_CACHE[key]
    data = bingx_get("/openApi/swap/v2/quote/klines", {"symbol":api_symbol,"interval":interval,"limit":int(limit)})
    rows = _extract_rows(data); result=[]
    for row in rows:
        try:
            if isinstance(row, dict):
                ts=row.get("time") or row.get("timestamp") or row.get("openTime")
                o=row.get("open") or row.get("o"); h=row.get("high") or row.get("h"); l=row.get("low") or row.get("l"); c=row.get("close") or row.get("c"); v=row.get("volume") or row.get("v") or 0
            elif isinstance(row,(list,tuple)) and len(row)>=6:
                ts,o,h,l,c,v=row[:6]
            else: continue
            if None in (o,h,l,c): continue
            result.append({"time":float(ts or 0),"open":float(o),"high":float(h),"low":float(l),"close":float(c),"volume":float(v or 0)})
        except Exception: continue
    result.sort(key=lambda x:x["time"])
    if result:
        _KLINE_CACHE[key]=result; _KLINE_CACHE_TIME[key]=time.time()
    return result

def get_current_price(symbol):
    data=bingx_get("/openApi/swap/v2/quote/ticker", {"symbol":bingx_symbol(symbol)})
    for item in _extract_rows(data):
        if isinstance(item,dict):
            for key in ("lastPrice","last","price","markPrice"):
                try:
                    p=float(item.get(key));
                    if p>0:return p
                except Exception: pass
    k=get_klines(symbol,"1m",3)
    return k[-1]["close"] if k else None

def calculate_ema(values, period):
    if not values:return []
    period=max(1,int(period))
    if len(values)<period:return [None]*len(values)
    out=[None]*(period-1); prev=sum(values[:period])/period; out.append(prev); m=2/(period+1)
    for v in values[period:]: prev=(v-prev)*m+prev; out.append(prev)
    return out

def calculate_rsi(values, period=14):
    if len(values)<period+1:return None
    gains=[];losses=[]
    for i in range(1,len(values)):
        d=values[i]-values[i-1]; gains.append(max(d,0)); losses.append(max(-d,0))
    ag=sum(gains[:period])/period; al=sum(losses[:period])/period
    for i in range(period,len(gains)):
        ag=((ag*(period-1))+gains[i])/period; al=((al*(period-1))+losses[i])/period
    if al==0:return 100.0
    return 100-(100/(1+ag/al))

def calculate_atr(klines, period=14):
    if len(klines)<period+1:return None
    trs=[]
    for i in range(1,len(klines)):
        x=klines[i];p=klines[i-1];trs.append(max(x["high"]-x["low"],abs(x["high"]-p["close"]),abs(x["low"]-p["close"])))
    return sum(trs[-period:])/len(trs[-period:])

def calculate_volume_ratio(klines, period=20):
    if len(klines)<2:return 0
    prev=[x["volume"] for x in klines[-(period+1):-1]]
    if not prev:return 0
    avg=sum(prev)/len(prev); return klines[-1]["volume"]/avg if avg>0 else 0

def calculate_volume_trend(klines, period=5):
    if len(klines)<period*2:return "NEUTRAL"
    a=sum(x["volume"] for x in klines[-period:])/period; b=sum(x["volume"] for x in klines[-period*2:-period])/period
    if b<=0:return "NEUTRAL"
    r=a/b
    return "RISING" if r>=1.05 else "FALLING" if r<=.95 else "STABLE"

def calculate_support_resistance(klines, lookback=80):
    if not klines:return None,None
    d=klines[-min(lookback,len(klines)):]; return min(x["low"] for x in d),max(x["high"] for x in d)

def calculate_timeframe_trend(klines):
    if len(klines)<60:return "NEUTRAL"
    c=[x["close"] for x in klines]; e9=calculate_ema(c,9)[-1];e20=calculate_ema(c,20)[-1];e50=calculate_ema(c,50)[-1];p=c[-1]
    if e9>e20 and e20>e50 and p>e20:return "LONG"
    if e9<e20 and e20<e50 and p<e20:return "SHORT"
    if e9>e20 and p>e20:return "LONG"
    if e9<e20 and p<e20:return "SHORT"
    return "NEUTRAL"

def detect_market_structure(klines):
    if len(klines)<40:return "MIXED","NONE"
    r=klines[-20:];p=klines[-40:-20];rh=max(x["high"] for x in r);rl=min(x["low"] for x in r);ph=max(x["high"] for x in p);pl=min(x["low"] for x in p);close=klines[-1]["close"]
    if close>ph:return "BULLISH","BULLISH"
    if close<pl:return "BEARISH","BEARISH"
    if rh>ph and rl>pl:return "BULLISH","NONE"
    if rh<ph and rl<pl:return "BEARISH","NONE"
    return "MIXED","NONE"

def detect_liquidity_flow(klines):
    if len(klines)<20:return "NEUTRAL",50
    r=klines[-12:];bv=sum(x["volume"] for x in r if x["close"]>x["open"]);sv=sum(x["volume"] for x in r if x["close"]<x["open"]);total=bv+sv
    if total<=0:return "NEUTRAL",50
    bp=bv/total*100;vr=calculate_volume_ratio(klines)
    if bv>sv*1.12 and vr>=.90:return "INFLOW",round(bp)
    if sv>bv*1.12 and vr>=.90:return "OUTFLOW",round(bp)
    return "NEUTRAL",round(bp)

def detect_bottom_accumulation(klines):
    base={"found":False,"score":0,"drawdown":0,"recent_range":0,"volume_ratio":0,"volume_trend":"NEUTRAL","reason":[]}
    if len(klines)<40:return base
    closes=[x["close"] for x in klines];cur=closes[-1];ph=max(closes[-40:-5])
    if ph<=0:return base
    dd=(cur/ph-1)*100;r=klines[-10:];hi=max(x["high"] for x in r);lo=min(x["low"] for x in r);rr=(hi-lo)/lo*100 if lo>0 else 0;vr=calculate_volume_ratio(klines);vt=calculate_volume_trend(klines);score=0;re=[]
    if dd<=-4:score+=1;re.append("هبوط سابق واضح")
    if dd<=-8:score+=1
    if rr<=18:score+=1;re.append("النطاق السعري بدأ يضيق")
    if vr>=.80:score+=1;re.append("الحجم ما زال موجوداً بعد الهبوط")
    if vt in ("RISING","STABLE"):score+=1
    rej=0
    for x in r[-6:]:
        body=max(abs(x["close"]-x["open"]),x["high"]-x["low"],1e-12);lw=min(x["open"],x["close"])-x["low"]
        if lw>=body*.60:rej+=1
    if rej>=1:score+=1;re.append("رفض سعري من الأسفل")
    base.update(found=score>=3,score=score,drawdown=dd,recent_range=rr,volume_ratio=vr,volume_trend=vt,reason=re);return base

def calculate_recent_move(klines,n):
    if len(klines)<=n:return 0
    old=klines[-n-1]["close"];new=klines[-1]["close"];return (new/old-1)*100 if old>0 else 0

def ema_state(klines):
    if len(klines)<20:return "MIXED"
    c=[x["close"] for x in klines];a=calculate_ema(c,9)[-1];b=calculate_ema(c,20)[-1]
    return "BULLISH" if a>b else "BEARISH" if a<b else "MIXED"

def get_coin_analysis(symbol):
    symbol=normalize_symbol(symbol)
    if not symbol:return None
    ks={tf:get_klines(symbol,tf,n) for tf,n in (("1d",100),("4h",120),("1h",120),("30m",100),("15m",100))}
    if any(len(ks[tf])<m for tf,m in (("1d",60),("4h",60),("1h",60),("30m",40),("15m",40))):return None
    k1d,k4h,k1h,k30,k15=(ks[x] for x in ("1d","4h","1h","30m","15m"));price=get_current_price(symbol) or k1h[-1]["close"]
    t1d,t4h,t1h,t30,t15=[calculate_timeframe_trend(x) for x in (k1d,k4h,k1h,k30,k15)];structure,bos=detect_market_structure(k1h);liq,bp=detect_liquidity_flow(k1h);vr=calculate_volume_ratio(k1h);vt=calculate_volume_trend(k1h);rsi=calculate_rsi([x["close"] for x in k1h]) or 50;ema=ema_state(k1h);bottom=detect_bottom_accumulation(k1h);support,resistance=calculate_support_resistance(k1h);atr=calculate_atr(k1h)
    ds=((price-support)/price*100) if support else 0;dr=((resistance-price)/price*100) if resistance else 0
    ls=ss=0;rl=[];rs=[]
    for t,w,txt in ((t1d,15,"1D"),(t4h,15,"4H"),(t1h,15,"1H")):
        if t=="LONG":ls+=w;rl.append(f"{txt} يدعم الاتجاه الصاعد")
        elif t=="SHORT":ss+=w;rs.append(f"{txt} يدعم الاتجاه الهابط")
    if t30=="LONG":ls+=8
    elif t30=="SHORT":ss+=8
    if t15=="LONG":ls+=6
    elif t15=="SHORT":ss+=6
    if bos=="BULLISH":ls+=12;rl.append("BOS صاعد مؤكد")
    elif bos=="BEARISH":ss+=12;rs.append("BOS هابط مؤكد")
    if structure=="BULLISH":ls+=8
    elif structure=="BEARISH":ss+=8
    if liq=="INFLOW":ls+=10;rl.append("السيولة تدخل للسوق")
    elif liq=="OUTFLOW":ss+=10;rs.append("السيولة تخرج من السوق")
    if bp>=57:ls+=6
    elif bp<=43:ss+=6
    if vr>=1.10:(ls if bp>=50 else ss).__class__
    if vr>=1.10:
        if bp>=50:ls+=5
        else:ss+=5
    elif vr>=.80:
        if bp>=50:ls+=2
        else:ss+=2
    if 35<=rsi<=48:ls+=5
    elif 52<=rsi<=65:ss+=5
    elif rsi<30:ls+=7
    elif rsi>70:ss+=7
    if ema=="BULLISH":ls+=5;rl.append("EMA9 فوق EMA20")
    elif ema=="BEARISH":ss+=5;rs.append("EMA9 تحت EMA20")
    if bottom["found"]:ls+=8;rl.append("تم اكتشاف احتمال قاع/تجميع")
    direction="LONG" if ls>ss else "SHORT" if ss>ls else "NEUTRAL";score=max(0,min(100,int(max(ls,ss))));reasons=rl if direction=="LONG" else rs
    lconf=t1h=="LONG" and (t30=="LONG" or t15=="LONG" or bos=="BULLISH" or liq=="INFLOW");sconf=t1h=="SHORT" and (t30=="SHORT" or t15=="SHORT" or bos=="BEARISH" or liq=="OUTFLOW")
    trade="NO TRADE";decision="انتظار تأكيد إضافي";entry=sl=tp1=tp2=tp3=None
    if direction=="LONG" and score>=48 and lconf:
        trade="ENTRY READY";decision="صفقة LONG جاهزة";entry=price;sl=entry-atr*1.25 if atr else (support*.995 if support else entry*.97);risk=entry-sl
        if risk>0:tp1=entry+risk*1.2;tp2=entry+risk*2;tp3=entry+risk*3
    elif direction=="SHORT" and score>=48 and sconf:
        trade="ENTRY READY";decision="صفقة SHORT جاهزة";entry=price;sl=entry+atr*1.25 if atr else (resistance*1.005 if resistance else entry*1.03);risk=sl-entry
        if risk>0:tp1=entry-risk*1.2;tp2=entry-risk*2;tp3=entry-risk*3
    elif direction=="LONG" and bottom["found"] and score>=30:trade="REVERSAL WATCH";decision="ننتظر تأكيد التحول الصاعد على 1H/BOS"
    elif direction=="SHORT" and score>=30 and (bos=="BEARISH" or liq=="OUTFLOW"):trade="REVERSAL WATCH";decision="ننتظر تأكيد التحول الهابط على 1H/BOS"
    elif bottom["found"] and score>=20:trade="ACCUMULATION WATCH";decision="تجميع مبكر؛ ننتظر تحول 1H/BOS"
    return {"symbol":symbol,"price":price,"direction":direction,"final_direction":direction,"score":score,"entry_score":score,"trade_type":trade,"status":trade,"decision":decision,"trend_1d":t1d,"trend_4h":t4h,"trend_1h":t1h,"trend_30m":t30,"trend_15m":t15,"structure":structure,"bos":bos,"liquidity":liq,"buy_pressure":bp,"volume_ratio":vr,"volume_trend":vt,"rsi":rsi,"ema_state":ema,"bottom_found":bottom["found"],"bottom_score":bottom["score"],"drawdown":bottom["drawdown"],"support":support,"resistance":resistance,"distance_support":ds,"distance_resistance":dr,"atr":atr,"entry":entry,"stop_loss":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,"move_2":calculate_recent_move(k1h,2),"move_6":calculate_recent_move(k1h,6),"reasons":reasons,"long_score":ls,"short_score":ss,"bottom_reasons":bottom["reason"]}

def scan_market(limit=5):
    start=time.time();symbols=get_futures_symbols()
    if not symbols:return []
    # IMPORTANT: do not scan only the first 30 contracts. BingX may return the
    # list in an order that hides trending altcoins. Scan the whole universe.
    # The 1H prefilter is intentionally cheap; only the best candidates get 5-TF deep analysis.
    priority=[s for s in PRIORITY_SYMBOLS if s in set(symbols)]
    rest=[s for s in symbols if s not in PRIORITY_SYMBOLS]
    selected=priority+rest
    candidates=[]
    for symbol in selected:
        try:
            k=get_klines(symbol,"1h",80)
            if len(k)<50:continue
            c=[x["close"] for x in k];trend=calculate_timeframe_trend(k);vr=calculate_volume_ratio(k);rsi=calculate_rsi(c) or 50;structure,bos=detect_market_structure(k);liq,bp=detect_liquidity_flow(k);bottom=detect_bottom_accumulation(k);move=calculate_recent_move(k,6)
            # Trend-momentum score: favors active movers, not only BTC/ETH.
            fs=0
            if trend in ("LONG","SHORT"):fs+=10
            if bos!="NONE":fs+=15
            if structure!="MIXED":fs+=10
            if liq!="NEUTRAL":fs+=15
            if vr>=.80:fs+=10
            if vr>=1.20:fs+=5
            if bottom["found"]:fs+=20
            if abs(move)>=.7:fs+=5
            if abs(move)>=2.0:fs+=5
            if rsi<=42 or rsi>=58:fs+=10
            if bp>=57 or bp<=43:fs+=5
            # Extra trend strength from price/EMA alignment.
            e9=calculate_ema(c,9)[-1];e20=calculate_ema(c,20)[-1]
            if e9 and e20 and ((trend=="LONG" and e9>e20) or (trend=="SHORT" and e9<e20)):fs+=5
            candidates.append({"symbol":symbol,"fast_score":fs,"move":move,"volume":vr})
        except Exception as e:logger.warning("Fast scan error %s: %s",symbol,e)
    candidates.sort(key=lambda x:(x["fast_score"],abs(x["move"]),x["volume"]),reverse=True)
    # Deep-analyze more names so the scanner can actually catch daily trending alts.
    deep_results=[]
    for item in candidates[:20]:
        try:
            d=get_coin_analysis(item["symbol"])
            if d and (d["score"]>=20 or d["bottom_found"] or d["trade_type"]!="NO TRADE"):deep_results.append(d)
        except Exception as e:logger.warning("Deep analysis error %s: %s",item["symbol"],e)
    if not deep_results:
        for item in candidates[:5]:
            try:
                d=get_coin_analysis(item["symbol"])
                if d:deep_results.append(d)
            except Exception:pass
    rank={"ENTRY READY":4,"REVERSAL WATCH":3,"ACCUMULATION WATCH":2,"NO TRADE":1}
    deep_results.sort(key=lambda x:(rank.get(x["trade_type"],0),x["score"],abs(x.get("move_6",0)),x.get("bottom_score",0)),reverse=True)
    logger.info("Market scan finished: %.2fs | universe=%s | candidates=%s | results=%s",time.time()-start,len(symbols),len(candidates),len(deep_results))
    return deep_results[:limit]

def _fmt_price(v):
    if v is None:return "غير محدد"
    try:
        v=float(v)
        return f"{v:.2f}" if v>=1000 else f"{v:.5f}" if v>=1 else f"{v:.6f}" if v>=.01 else f"{v:.8f}"
    except Exception:return "غير محدد"

def _fmt_percent(v):
    try:return f"{float(v or 0):.2f}%"
    except Exception:return "0.00%"

def generate_evidence_report(data):
    symbol=data.get("symbol","UNKNOWN");direction=data.get("direction","NEUTRAL");score=data.get("score",0);trade=data.get("trade_type","NO TRADE")
    direction_text="🟢 LONG" if trade=="ENTRY READY" and direction=="LONG" else "🔴 SHORT" if trade=="ENTRY READY" and direction=="SHORT" else "🟡 NO TRADE"
    state={"ENTRY READY":"🟢 ENTRY READY - صفقة جاهزة","REVERSAL WATCH":"🟡 REVERSAL WATCH - ننتظر تأكيد الانعكاس","ACCUMULATION WATCH":"🔵 ACCUMULATION WATCH - تجميع مبكر"}.get(trade,"🟡 NO TRADE - الشروط غير مكتملة")
    lines=["🤖 BingX AI Scanner","",f"💎 العملة: {symbol}",f"📈 الاتجاه النهائي: {direction_text}",f"⭐ Entry Score: {score}/100","",f"🧠 الحالة: {state}",f"🧭 القرار: {data.get('decision','انتظار')}","","📊 الاتجاه العام",f"1D: {data.get('trend_1d','NEUTRAL')}",f"4H: {data.get('trend_4h','NEUTRAL')}","","🔎 تأكيد الدخول",f"1H: {data.get('trend_1h','NEUTRAL')}",f"30m: {data.get('trend_30m','NEUTRAL')}",f"15m: {data.get('trend_15m','NEUTRAL')}",f"هيكل السوق: {data.get('structure','MIXED')}"]
    bos=data.get("bos","NONE");lines.append("BOS: 🟢 BULLISH" if bos=="BULLISH" else "BOS: 🔴 BEARISH" if bos=="BEARISH" else "BOS: ⚪ NONE")
    liq=data.get("liquidity","NEUTRAL");lt="🟢 INFLOW" if liq=="INFLOW" else "🔴 OUTFLOW" if liq=="OUTFLOW" else "🟡 سيولة محايدة"
    lines += [f"💧 السيولة: {lt}",f"📊 Volume: {float(data.get('volume_ratio',0)):.2f}x",f"📈 Volume Trend: {data.get('volume_trend','NEUTRAL')}",f"💪 Buy Pressure: {data.get('buy_pressure',50)}%",f"📊 RSI: {float(data.get('rsi',50)):.2f}","",f"🎯 القاع/التجميع: {'🟢 نعم — تجميع مبكر' if data.get('bottom_found') else '⚪ لا يوجد تأكيد قوي'}",f"📉 الهبوط السابق: {_fmt_percent(data.get('drawdown'))}","","🛡️ الدعم والمقاومة",f"🟢 Support: {_fmt_price(data.get('support'))}",f"🔴 Resistance: {_fmt_price(data.get('resistance'))}",f"📏 البعد عن الدعم: {_fmt_percent(data.get('distance_support'))}",f"📏 البعد عن المقاومة: {_fmt_percent(data.get('distance_resistance'))}","","📍 منطقة الدخول",f"Entry: {_fmt_price(data.get('entry')) if data.get('entry') else '⏳ انتظار تأكيد'}","",f"🛑 Stop Loss: {_fmt_price(data.get('stop_loss'))}","","🎯 الأهداف",f"TP1: {_fmt_price(data.get('tp1'))}",f"TP2: {_fmt_price(data.get('tp2'))}",f"TP3: {_fmt_price(data.get('tp3'))}","","📊 الحركة الأخيرة",f"آخر شمعتين تقريباً: {_fmt_percent(data.get('move_2'))}",f"آخر 6 شموع تقريباً: {_fmt_percent(data.get('move_6'))}","","🔍 أسباب القرار"]
    reasons=data.get("reasons",[]);lines += [f"• {x}" for x in reasons[:8]] if reasons else ["• لا توجد عوامل قوية كافية حالياً"]
    lines += ["","🏗️ أدلة هيكل السوق",("• تم تأكيد كسر هيكل صاعد BOS" if bos=="BULLISH" else "• تم تأكيد كسر هيكل هابط BOS" if bos=="BEARISH" else "• لا يوجد BOS مؤكد حالياً"),"","💧 أدلة السيولة",("• تدفق شرائي واضح" if liq=="INFLOW" else "• ضغط بيعي واضح" if liq=="OUTFLOW" else "• السيولة ما زالت محايدة")]
    if data.get("bottom_found"):
        lines += ["","🎯 أدلة التجميع"]+[f"• {x}" for x in data.get("bottom_reasons",[]) or ["توجد مؤشرات تجميع مبكرة"]]
    if trade!="ENTRY READY": lines += ["","🚫 لماذا لم يدخل؟","• لا يوجد تأكيد دخول كامل حالياً"]
    lines += ["","⚠️ إشارة تحليلية وليست ضماناً للربح.","⚠️ 1D + 4H للاتجاه العام.","⚠️ 1H + 30m + 15m لتأكيد الدخول.","⚠️ BOS + السيولة + الحجم عوامل تأكيد.","⚠️ ENTRY READY لا تعني ضمان الربح."]
    return "\n".join(lines)
