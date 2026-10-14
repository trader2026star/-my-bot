# MY EXPERT CRYPTO BOT — Multi-timeframe indicators + SMC + liquidity context
# Indicators are calculated and used in scoring; they are not decorative labels.
import numpy as np

class StrategyEngine:
    def __init__(self):
        self.min_candles = 20

    @staticmethod
    def is_valid_symbol(symbol):
        if not symbol or not isinstance(symbol, str) or len(symbol) > 30:
            return False
        s = symbol.upper()
        return not any(x in s for x in ("AAPL", "TSLA", "GOOG", "AMZN", "MSFT", "NFLX", "NVDA", "META", "TEST", "DEMO", "FAKE", "NCSK"))

    @staticmethod
    def valid_ohlcv(data, minimum=20):
        if not isinstance(data, (list, tuple)) or len(data) < minimum:
            return False
        try:
            prev = -1.0
            for row in data:
                if len(row) < 6: return False
                ts, o, h, l, c, v = map(float, row[:6])
                if not all(np.isfinite(z) for z in (ts,o,h,l,c,v)): return False
                if min(o,h,l,c) <= 0 or v < 0 or h < max(o,c) or l > min(o,c) or h < l or ts <= prev: return False
                prev = ts
            return True
        except (TypeError, ValueError, IndexError):
            return False

    @staticmethod
    def arrays(data):
        return tuple(np.asarray([float(row[i]) for row in data], dtype=float) for i in (1,2,3,4,5))

    @staticmethod
    def _ema_series(values, period):
        x = np.asarray(values, dtype=float)
        if len(x) == 0: return np.asarray([], dtype=float)
        alpha = 2.0 / (float(period) + 1.0)
        out = np.empty(len(x), dtype=float); out[0] = x[0]
        for i in range(1, len(x)): out[i] = alpha*x[i] + (1-alpha)*out[i-1]
        return out

    @classmethod
    def _ema(cls, values, period):
        x = np.asarray(values, dtype=float)
        if len(x) < period: return None
        return float(cls._ema_series(x, period)[-1])

    @staticmethod
    def calculate_atr(highs, lows, closes, period=14):
        h,l,c = (np.asarray(z,dtype=float) for z in (highs,lows,closes)); n=min(len(h),len(l),len(c))
        if n < 2: return 0.0
        h,l,c=h[-n:],l[-n:],c[-n:]
        tr=np.maximum(h[1:]-l[1:],np.maximum(np.abs(h[1:]-c[:-1]),np.abs(l[1:]-c[:-1])))
        if not len(tr): return 0.0
        return float(np.mean(tr[-min(int(period),len(tr)):]))

    @classmethod
    def _rsi(cls, closes, period=14):
        c=np.asarray(closes,dtype=float)
        if len(c) < period+1: return 50.0
        d=np.diff(c); gains=np.maximum(d,0); losses=np.maximum(-d,0)
        # Wilder smoothing, initialized from the first period.
        ag=float(np.mean(gains[:period])); al=float(np.mean(losses[:period]))
        for i in range(period,len(gains)):
            ag=(ag*(period-1)+gains[i])/period; al=(al*(period-1)+losses[i])/period
        if al <= 1e-15: return 100.0 if ag > 1e-15 else 50.0
        return float(100 - 100/(1+ag/al))

    @classmethod
    def _macd(cls, closes, fast=12, slow=26, signal=9):
        c=np.asarray(closes,dtype=float)
        if len(c) < slow+signal: return {"dif":0.0,"dea":0.0,"hist":0.0,"bullish_cross":False,"bearish_cross":False}
        dif=cls._ema_series(c,fast)-cls._ema_series(c,slow)
        dea=cls._ema_series(dif,signal); hist=dif-dea
        return {"dif":float(dif[-1]),"dea":float(dea[-1]),"hist":float(hist[-1]),
                "bullish_cross":bool(hist[-1]>0 and hist[-2]<=0),"bearish_cross":bool(hist[-1]<0 and hist[-2]>=0)}

    @classmethod
    def _adx(cls, highs, lows, closes, period=14):
        h,l,c=(np.asarray(z,dtype=float) for z in (highs,lows,closes)); n=min(len(h),len(l),len(c))
        if n < period+2: return 0.0
        h,l,c=h[-n:],l[-n:],c[-n:]
        up=h[1:]-h[:-1]; down=l[:-1]-l[1:]
        plus=np.where((up>down)&(up>0),up,0.0); minus=np.where((down>up)&(down>0),down,0.0)
        tr=np.maximum(h[1:]-l[1:],np.maximum(np.abs(h[1:]-c[:-1]),np.abs(l[1:]-c[:-1])))
        def wilder(a):
            out=np.empty(len(a)); out[0]=np.sum(a[:period])
            for i in range(1,len(a)): out[i]=out[i-1]-out[i-1]/period+a[i]
            return out
        if len(tr)<period: return 0.0
        atrs=wilder(tr); pdi=100*wilder(plus)/np.maximum(atrs,1e-12); mdi=100*wilder(minus)/np.maximum(atrs,1e-12)
        dx=100*np.abs(pdi-mdi)/np.maximum(pdi+mdi,1e-12)
        return float(np.mean(dx[-period:])) if len(dx) else 0.0

    @classmethod
    def _supertrend(cls, highs, lows, closes, period=10, multiplier=3.0):
        h,l,c=(np.asarray(z,dtype=float) for z in (highs,lows,closes)); n=min(len(h),len(l),len(c))
        if n < period+2: return {"direction":"NEUTRAL","value":None}
        h,l,c=h[-n:],l[-n:],c[-n:]
        # ATR rolling mean of true range; iterative final bands and trend state.
        tr=np.empty(n); tr[0]=h[0]-l[0]
        for i in range(1,n): tr[i]=max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1]))
        atr=np.zeros(n)
        for i in range(n): atr[i]=np.mean(tr[max(0,i-period+1):i+1])
        mid=(h+l)/2; upper=mid+multiplier*atr; lower=mid-multiplier*atr
        final_u=upper.copy(); final_l=lower.copy(); direction=np.ones(n,dtype=int)
        for i in range(1,n):
            final_u[i]=upper[i] if (upper[i]<final_u[i-1] or c[i-1]>final_u[i-1]) else final_u[i-1]
            final_l[i]=lower[i] if (lower[i]>final_l[i-1] or c[i-1]<final_l[i-1]) else final_l[i-1]
            if direction[i-1] == 1: direction[i] = -1 if c[i] < final_l[i] else 1
            else: direction[i] = 1 if c[i] > final_u[i] else -1
        value=final_l[-1] if direction[-1]==1 else final_u[-1]
        return {"direction":"LONG" if direction[-1]==1 else "SHORT","value":float(value)}

    @classmethod
    def _ema_stack(cls, closes):
        c=np.asarray(closes,dtype=float)
        periods=(7,25,50,99,120,200)
        vals={str(p):cls._ema(c,p) for p in periods}
        valid=[(p,vals[str(p)]) for p in periods if vals[str(p)] is not None]
        if len(valid)<3: direction="NEUTRAL"
        else:
            ordered=[v for _,v in valid]
            bullish=all(ordered[i]>=ordered[i+1] for i in range(len(ordered)-1))
            bearish=all(ordered[i]<=ordered[i+1] for i in range(len(ordered)-1))
            direction="LONG" if bullish and c[-1]>ordered[0] else "SHORT" if bearish and c[-1]<ordered[0] else "NEUTRAL"
        return vals,direction

    @classmethod
    def _trend(cls, highs, lows, closes):
        c=np.asarray(closes,dtype=float)
        if len(c)<20:return "NEUTRAL"
        e7=cls._ema(c,7); e25=cls._ema(c,25); e50=cls._ema(c,50) if len(c)>=50 else None
        st=cls._supertrend(highs,lows,c,10,3.0)
        atr=cls.calculate_atr(highs,lows,c)
        if e7 is None or e25 is None or atr<=0:return "NEUTRAL"
        long_ok=e7>e25 and c[-1]>e25 and st['direction']=="LONG"
        short_ok=e7<e25 and c[-1]<e25 and st['direction']=="SHORT"
        if e50 is not None:
            long_ok=long_ok and c[-1]>e50; short_ok=short_ok and c[-1]<e50
        return "LONG" if long_ok else "SHORT" if short_ok else "NEUTRAL"

    @staticmethod
    def _volume_ratio(volumes):
        v=np.asarray(volumes,dtype=float)
        if len(v)<10:return 0.0
        base=v[-21:-1] if len(v)>=21 else v[:-1]; avg=float(np.mean(base)) if len(base) else 0
        return round(float(v[-1]/avg),2) if avg>0 else 0.0

    @staticmethod
    def _vwap(highs,lows,closes,volumes,period=30):
        h,l,c,v=(np.asarray(z,dtype=float) for z in (highs,lows,closes,volumes)); n=min(len(h),len(l),len(c),len(v))
        if n==0:return 0.0
        h,l,c,v=(z[-min(period,n):] for z in (h,l,c,v)); typical=(h+l+c)/3; total=float(np.sum(v))
        return float(np.sum(typical*v)/total) if total>0 else float(c[-1])

    @classmethod
    def _detect_structure(cls, opens, highs, lows, closes):
        o,h,l,c=(np.asarray(z,dtype=float) for z in (opens,highs,lows,closes)); n=min(map(len,(o,h,l,c)))
        out={"bos":"NONE","mss":"NONE","sweep":"NONE","fvg":"NONE","fvg_zone":None,"ob_type":"NONE","ob_zone":None,"support":None,"resistance":None}
        if n<12:return out
        o,h,l,c=(z[-n:] for z in (o,h,l,c)); lb=min(12,n-2)
        ph=float(np.max(h[-lb-1:-1])); pl=float(np.min(l[-lb-1:-1])); out.update(support=pl,resistance=ph)
        rng=max(float(h[-1]-l[-1]),1e-12); body=abs(float(c[-1]-o[-1]))/rng
        if c[-1]>ph and c[-1]>o[-1] and body>=.35:out['bos']='BULLISH_BOS'
        elif c[-1]<pl and c[-1]<o[-1] and body>=.35:out['bos']='BEARISH_BOS'
        if l[-1]<pl and c[-1]>pl:out['sweep']='SELL_SIDE_SWEEP'
        elif h[-1]>ph and c[-1]<ph:out['sweep']='BUY_SIDE_SWEEP'
        if l[-1]>h[-3] and (l[-1]-h[-3])/c[-1]>=.0003:out.update(fvg='BULLISH_FVG',fvg_zone=[float(h[-3]),float(l[-1])])
        elif h[-1]<l[-3] and (l[-3]-h[-1])/c[-1]>=.0003:out.update(fvg='BEARISH_FVG',fvg_zone=[float(h[-1]),float(l[-3])])
        prev=float(c[-3]-c[-7])
        if prev<0 and out['bos']=='BULLISH_BOS':out['mss']='BULLISH_MSS'
        elif prev>0 and out['bos']=='BEARISH_BOS':out['mss']='BEARISH_MSS'
        atr=cls.calculate_atr(h,l,c); displacement=abs(float(c[-1]-o[-1]))>=1.15*atr if atr>0 else False
        if displacement and out['bos']!='NONE':
            for j in range(n-2,max(-1,n-7),-1):
                if out['bos']=='BULLISH_BOS' and c[j]<o[j]:out.update(ob_type='BULLISH_OB',ob_zone=[float(l[j]),float(h[j])]);break
                if out['bos']=='BEARISH_BOS' and c[j]>o[j]:out.update(ob_type='BEARISH_OB',ob_zone=[float(l[j]),float(h[j])]);break
        return out

    @classmethod
    def _break_retest(cls, opens, highs, lows, closes, volumes, direction):
        o,h,l,c,v=(np.asarray(z,dtype=float) for z in (opens,highs,lows,closes,volumes)); n=min(map(len,(o,h,l,c,v)))
        if n<15:return False,None,"بيانات غير كافية للكسر وإعادة الاختبار"
        o,h,l,c,v=(z[-n:] for z in (o,h,l,c,v)); atr=cls.calculate_atr(h,l,c)
        lb=min(10,n-2); level=float(np.max(h[-lb-1:-1])) if direction=='LONG' else float(np.min(l[-lb-1:-1]))
        rng=max(float(h[-1]-l[-1]),1e-12); body=abs(float(c[-1]-o[-1]))/rng
        if direction=='LONG':
            ext=(c[-1]-level)/max(atr,c[-1]*1e-9)
            if c[-1]>level and c[-1]>o[-1] and body>=.30 and ext<=1.6:return True,level,"اختراق صاعد حديث"
            if ext>1.6:return False,level,"السعر ممتد بعد الاختراق"
            for j in range(max(5,n-7),n-1):
                left=max(0,j-10); old=float(np.max(h[left:j]))
                if c[j]>old and c[j]>o[j] and l[-1]<=old*1.003 and c[-1]>=old and c[-1]>o[-1]:return True,old,"إعادة اختبار صاعدة"
        else:
            ext=(level-c[-1])/max(atr,c[-1]*1e-9)
            if c[-1]<level and c[-1]<o[-1] and body>=.30 and ext<=1.6:return True,level,"كسر هابط حديث"
            if ext>1.6:return False,level,"السعر ممتد بعد الكسر"
            for j in range(max(5,n-7),n-1):
                left=max(0,j-10); old=float(np.min(l[left:j]))
                if c[j]<old and c[j]<o[j] and h[-1]>=old*.997 and c[-1]<=old and c[-1]<o[-1]:return True,old,"إعادة اختبار هابطة"
        return False,level,"لا يوجد اختراق/كسر أو إعادة اختبار مؤكدة"

    @staticmethod
    def _liquidity_metrics(order_book=None, trades=None, large_trade_usd=10000):
        result={"orderbook_imbalance":None,"large_buy_usd":0.0,"large_sell_usd":0.0,"whale_flow":"UNAVAILABLE","large_trade_count":0}
        try:
            bids=(order_book or {}).get('bids') or []; asks=(order_book or {}).get('asks') or []
            b=sum(float(x[0])*float(x[1]) for x in bids[:20] if len(x)>=2); a=sum(float(x[0])*float(x[1]) for x in asks[:20] if len(x)>=2)
            if b+a>0: result['orderbook_imbalance']=round((b-a)/(b+a),3)
        except Exception:pass
        buys=sells=0.0; count=0
        for t in (trades or []):
            try:
                price=float(t.get('price') or 0); amount=float(t.get('amount') or 0); notional=price*amount
                side=str(t.get('side') or '').lower()
                if not side:
                    info=t.get('info') or {}; maker=info.get('buyerMaker',info.get('isBuyerMaker'))
                    if maker is not None: side='sell' if str(maker).lower() in ('true','1') else 'buy'
                if notional>=large_trade_usd and side in ('buy','sell'):
                    count+=1
                    if side=='buy':buys+=notional
                    else:sells+=notional
            except (TypeError,ValueError):continue
        result.update(large_buy_usd=round(buys,2),large_sell_usd=round(sells,2),large_trade_count=count)
        if count:result['whale_flow']='BUY_DOMINANT' if buys>sells*1.2 else 'SELL_DOMINANT' if sells>buys*1.2 else 'MIXED'
        return result

    def analyze_multi_timeframe(self, ohlcv_4h, ohlcv_1h, ohlcv_15m, ohlcv_btc_1h=None,
                                symbol="", market_context=None, order_book=None, trades=None):
        d={"trend_4h":"NEUTRAL","trend_1h":"NEUTRAL","break_retest":False,"break_level":None,"bos":"NONE","mss":"NONE","sweep":"NONE","fvg":"NONE","fvg_zone":None,"ob_type":"NONE","ob_zone":None,"volume_ratio":0.0,"vwap_price":0.0,"support":None,"resistance":None,"retest_advice":"انتظار تأكيد فعلي","entry_valid":False,"btc_trend":"UNKNOWN","confirmations":[],"reasons_excluded":[],"momentum":False,"indicators":{},"market_context":market_context or {}}
        empty=([],[],[])
        if symbol and not self.is_valid_symbol(symbol):d['reasons_excluded']=["رمز غير صالح"];return "NEUTRAL",0,0.0,d,empty
        for label,data in (("4H",ohlcv_4h),("1H",ohlcv_1h),("15M",ohlcv_15m)):
            if not self.valid_ohlcv(data,20):d['reasons_excluded'].append(f"بيانات {label} غير كافية/غير صالحة");return "NEUTRAL",0,0.0,d,empty
        # Drop currently forming candles, so decisions use closed candles only.
        o4,h4,l4,c4,v4=self.arrays(ohlcv_4h[:-1]); o1,h1,l1,c1,v1=self.arrays(ohlcv_1h[:-1]); o,h,l,c,v=self.arrays(ohlcv_15m[:-1])
        t4,t1=self._trend(h4,l4,c4),self._trend(h1,l1,c1); d['trend_4h'],d['trend_1h']=t4,t1
        if self.valid_ohlcv(ohlcv_btc_1h,20):
            _,bh,bl,bc,_=self.arrays(ohlcv_btc_1h[:-1]);d['btc_trend']=self._trend(bh,bl,bc)
        # Indicators on closed 15m candles. Long EMA periods are reported when enough history exists.
        ema_values,ema_stack=self._ema_stack(c); macd=self._macd(c); rsi6=self._rsi(c,6); rsi14=self._rsi(c,14)
        st=self._supertrend(h,l,c,10,3); atr=self.calculate_atr(h,l,c); adx=self._adx(h,l,c)
        vol_ratio=self._volume_ratio(v); vwap=self._vwap(h,l,c,v)
        d['indicators']={"ema":ema_values,"ema_stack":ema_stack,"supertrend_direction":st['direction'],"supertrend_value":st['value'],"rsi6":round(rsi6,2),"rsi14":round(rsi14,2),"macd":macd,"adx":round(adx,2),"atr":atr,"volume_ma20":float(np.mean(v[-20:])) if len(v)>=20 else float(np.mean(v)),"vwap":vwap}
        d['volume_ratio']=vol_ratio;d['vwap_price']=vwap;d.update(self._detect_structure(o,h,l,c))
        confirmations=[];excluded=[]; direction=t1
        if direction not in ('LONG','SHORT'):
            d['reasons_excluded']=["اتجاه 1H غير مؤكد من EMA/SuperTrend"];return "NEUTRAL",30,vol_ratio,d,(h.tolist(),l.tolist(),c.tolist())
        d['candidate_direction']=direction
        if t4!=direction:excluded.append("اتجاه 4H لا يؤكد اتجاه 1H")
        else:confirmations.append("اتجاه 4H و1H متوافق")
        if ema_stack==direction:confirmations.append("ترتيب المتوسطات EMA متوافق")
        else:excluded.append("ترتيب EMA الكامل غير متوافق/تاريخ البيانات لا يكفي")
        if st['direction']==direction:confirmations.append("SuperTrend (10,3) يؤكد الاتجاه")
        else:excluded.append("SuperTrend يعاكس الاتجاه")
        macd_ok=(macd['hist']>0 and macd['dif']>macd['dea']) if direction=='LONG' else (macd['hist']<0 and macd['dif']<macd['dea'])
        if macd_ok:confirmations.append("MACD DIF/DEA والهستوجرام يؤكد الزخم")
        else:excluded.append("MACD لا يؤكد الزخم الحالي")
        rsi_ok=(rsi6>=50 and 45<=rsi14<=75) if direction=='LONG' else (rsi6<=50 and 25<=rsi14<=55)
        if rsi_ok:confirmations.append(f"RSI6/RSI14 متوافقان ({rsi6:.0f}/{rsi14:.0f})")
        else:excluded.append(f"RSI6/RSI14 لا يؤكدان الدخول ({rsi6:.0f}/{rsi14:.0f})")
        structure=self._detect_structure(o,h,l,c); expected='BULLISH_BOS' if direction=='LONG' else 'BEARISH_BOS'
        if d['bos']==expected:confirmations.append("BOS على 15M")
        else:excluded.append("لا يوجد BOS حديث في اتجاه الصفقة")
        if d['mss']==('BULLISH_MSS' if direction=='LONG' else 'BEARISH_MSS'):confirmations.append("MSS يؤكد تحول الهيكل")
        if d['sweep']==('SELL_SIDE_SWEEP' if direction=='LONG' else 'BUY_SIDE_SWEEP'):confirmations.append("Liquidity sweep متوافق")
        if d['fvg']==('BULLISH_FVG' if direction=='LONG' else 'BEARISH_FVG'):confirmations.append("FVG في اتجاه الصفقة")
        if d['ob_type']==('BULLISH_OB' if direction=='LONG' else 'BEARISH_OB'):confirmations.append("Order Block مرصود من شمعة معاكسة قبل الاندفاع")
        br,level,reason=self._break_retest(o,h,l,c,v,direction);d.update(break_retest=br,break_level=level,retest_advice=reason,retest_bos_valid=bool(br and 'إعادة اختبار' in reason))
        if br:confirmations.append(reason)
        else:excluded.append(reason)
        if vol_ratio>=1.15:confirmations.append(f"Volume أعلى من المتوسط ({vol_ratio}x)")
        else:excluded.append(f"Volume غير كافٍ ({vol_ratio}x)")
        vwap_ok=(c[-1]>=vwap) if direction=='LONG' else (c[-1]<=vwap)
        if vwap_ok:confirmations.append("السعر في الجانب المؤيد من VWAP")
        else:excluded.append("السعر على الجانب المعاكس من VWAP")
        momentum=macd_ok and ((c[-1]>c[-2] and c[-1]>c[-4]) if direction=='LONG' else (c[-1]<c[-2] and c[-1]<c[-4]))
        d['momentum']=bool(momentum)
        btc=d['btc_trend']; btc_ok=btc==direction
        if btc_ok:confirmations.append("اتجاه BTC متوافق")
        elif btc in ('LONG','SHORT'):excluded.append("اتجاه BTC معاكس")
        # External market-wide snapshot: current/previous CoinGecko global stats proxy, not literal TOTAL1.
        ctx=market_context or {}; cap_change=ctx.get('market_cap_change_pct'); dom_change=ctx.get('btc_dominance_change_pct')
        if cap_change is not None:
            broad_ok=(cap_change>=0) if direction=='LONG' else (cap_change<=0)
            if broad_ok:confirmations.append(f"اتجاه القيمة السوقية العامة داعم ({cap_change:+.3f}%)")
            else:excluded.append(f"القيمة السوقية العامة تعاكس الاتجاه ({cap_change:+.3f}%)")
        if dom_change is not None and direction=='LONG' and cap_change is not None and cap_change>0 and dom_change<0:confirmations.append("هيمنة BTC تتراجع مع ارتفاع السوق: دعم نسبي للألتكوين")
        liq=self._liquidity_metrics(order_book,trades,float(ctx.get('large_trade_usd',10000)));d['liquidity']=liq
        imb=liq.get('orderbook_imbalance')
        if imb is not None:
            book_ok=imb>=.08 if direction=='LONG' else imb<=-.08
            if book_ok:confirmations.append(f"ضغط دفتر الأوامر مؤيد ({imb:+.3f})")
            elif abs(imb)>=.08:excluded.append(f"ضغط دفتر الأوامر يعاكس الاتجاه ({imb:+.3f})")
        flow=liq['whale_flow']
        if flow==('BUY_DOMINANT' if direction=='LONG' else 'SELL_DOMINANT'):confirmations.append(f"تدفق صفقات كبيرة ظاهر مؤيد: {flow} (${liq['large_buy_usd']:,.0f} شراء / ${liq['large_sell_usd']:,.0f} بيع)")
        elif flow in ('BUY_DOMINANT','SELL_DOMINANT'):excluded.append(f"تدفق الصفقات الكبيرة يعاكس الاتجاه: {flow}")
        # Scoring: capped evidence points, never a win probability. External data can only add modest weight.
        score=20
        score+=10 if t4==direction else 0;score+=8 if ema_stack==direction else 0;score+=7 if st['direction']==direction else 0
        score+=8 if macd_ok else 0;score+=5 if rsi_ok else 0;score+=12 if d['bos']==expected else 0
        score+=4 if d['mss']!='NONE' else 0;score+=4 if d['sweep']!='NONE' else 0;score+=3 if d['fvg']!='NONE' else 0
        score+=3 if d['ob_zone'] is not None else 0;score+=7 if br else 0;score+=5 if vol_ratio>=1.15 else 0
        score+=4 if vwap_ok else 0;score+=4 if momentum else 0;score+=3 if btc_ok else 0
        score+=2 if cap_change is not None and ((cap_change>=0)==(direction=='LONG')) else 0
        score+=2 if imb is not None and ((imb>0)==(direction=='LONG')) else 0
        score+=2 if flow==('BUY_DOMINANT' if direction=='LONG' else 'SELL_DOMINANT') else 0
        score=int(max(0,min(100,score)))
        core=bool(t4==direction and st['direction']==direction and macd_ok and br and d['bos']==expected and vol_ratio>=1.15 and momentum)
        entry_valid=bool(core and len(confirmations)>=4)
        # Do not let a strongly opposing order book alone invalidate every setup, but flag it; hard block only at extreme imbalance.
        if imb is not None and ((direction=='LONG' and imb<-.55) or (direction=='SHORT' and imb>.55)):entry_valid=False;excluded.append("ضغط دفتر الأوامر معاكس بشدة؛ تم منع الإشارة")
        if not core:score=min(score,69)
        if not entry_valid:excluded.append("شروط الدخول المتعددة غير مكتملة؛ لا توجد إشارة تنفيذ")
        d.update(entry_valid=entry_valid,confirmations=confirmations,reasons_excluded=excluded,market_context=ctx)
        return (direction if entry_valid else 'NEUTRAL'),score,vol_ratio,d,(h.tolist(),l.tolist(),c.tolist())

    def calculate_risk_management(self, entry_price, direction, highs, lows, closes=None):
        entry=float(entry_price); direction=str(direction).upper(); highs=np.asarray(highs,dtype=float);lows=np.asarray(lows,dtype=float)
        if closes is None:closes=(highs+lows)/2
        closes=np.asarray(closes,dtype=float);n=min(len(highs),len(lows),len(closes))
        if not np.isfinite(entry) or entry<=0 or n<5:raise ValueError('Invalid entry price or insufficient candles')
        highs,lows,closes=highs[-n:],lows[-n:],closes[-n:];atr=self.calculate_atr(highs,lows,closes)
        if not np.isfinite(atr) or atr<=0:atr=entry*.01
        recent_low=float(np.min(lows[-10:]));recent_high=float(np.max(highs[-10:]));buffer=.15*atr
        if direction in ('LONG','BUY'):
            stop=min(entry-1.2*atr,recent_low-buffer);risk=entry-stop
            if risk<=0:raise ValueError('Invalid long stop')
            t1,t2,t3=entry+1.5*risk,entry+2.5*risk,entry+4*risk
        elif direction in ('SHORT','SELL'):
            stop=max(entry+1.2*atr,recent_high+buffer);risk=stop-entry
            if risk<=0:raise ValueError('Invalid short stop')
            t1,t2,t3=entry-1.5*risk,entry-2.5*risk,entry-4*risk
            if t3<=0:raise ValueError('Non-positive short target')
        else:raise ValueError('Direction must be LONG or SHORT')
        return (round(float(stop),10),round(float(t1),10),round(float(t2),10),round(float(t3),10),round(abs(entry-stop)/entry*100,3),round(abs(t1-entry)/entry*100,3),round(abs(t1-entry)/abs(entry-stop),2))
