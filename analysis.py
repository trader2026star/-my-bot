# MY EXPERT CRYPTO BOT — Predictive Multi-timeframe + SMC + Divergence + Limit Zones
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
        ag=float(np.mean(gains[:period])); al=float(np.mean(losses[:period]))
        for i in range(period,len(gains)):
            ag=(ag*(period-1)+gains[i])/period; al=(al*(period-1)+losses[i])/period
        if al <= 1e-15: return 100.0 if ag > 1e-15 else 50.0
        return float(100 - 100/(1+ag/al))

    @classmethod
    def _detect_divergence(cls, highs, lows, closes, period=14):
        """توقع انعكاس الاتجاه مسبقاً عبر رصد التباين (الدايفرجنس) بين السعر ومؤشر القوة النسبية RSI"""
        h, l, c = np.asarray(highs, dtype=float), np.asarray(lows, dtype=float), np.asarray(closes, dtype=float)
        if len(c) < period + 10: return "NONE"
        
        # حساب سلسلة الـ RSI التاريخية المبسطة للشموع الأخيرة
        rsi_series = []
        for i in range(period+1, len(c)+1):
            rsi_series.get if False else None
            rsi_series.append(cls._rsi(c[:i], period))
        
        if len(rsi_series) < 5: return "NONE"
        
        # دايفرجنس إيجابي (Bullish Divergence): السعر يصنع قاعاً أدنى بينما RSI يصنع قاعاً أعلى (توقع صعود)
        if c[-1] < c[-5] and rsi_series[-1] > rsi_series[-5]:
            return "BULLISH_DIVERGENCE"
        
        # دايفرجنس سلبي (Bearish Divergence): السعر يصنع قمة أعلى بينما RSI يصنع قمة أقر (توقع هبوط مبكر)
        if c[-1] > c[-5] and rsi_series[-1] < rsi_series[-5]:
            return "BEARISH_DIVERGENCE"
            
        return "NONE"

    @classmethod
    def _macd(cls, closes, fast=12, slow=26, signal=9):
        c=np.asarray(closes,dtype=float)
        if len(c) < slow+signal: return {"dif":0.0,"dea":0.0,"hist":0.0,"bullish_cross":False,"bearish_cross":False}
        dif=cls._ema_series(c,fast)-cls._ema_series(c,slow)
        dea=cls._ema_series(dif,signal); hist=dif-dea
        return {"dif":float(dif[-1]),"dea":float(dea[-1]),"hist":float(hist[-1]),
                "bullish_cross":bool(hist[-1]>0 and hist[-2]<=0),"bearish_cross":bool(hist[-1]<0 and hist[-2]>=0)}

    @classmethod
    def _supertrend(cls, highs, lows, closes, period=10, multiplier=3.0):
        h,l,c=(np.asarray(z,dtype=float) for z in (highs,lows,closes)); n=min(len(h),len(l),len(c))
        if n < period+2: return {"direction":"NEUTRAL","value":None}
        h,l,c=h[-n:],l[-n:],c[-n:]
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
    def _trend(cls, highs, lows, closes):
        c=np.asarray(closes,dtype=float)
        if len(c)<20:return "NEUTRAL"
        e7=cls._ema(c,7); e25=cls._ema(c,25); st=cls._supertrend(highs,lows,c,10,3.0)
        atr=cls.calculate_atr(highs,lows,c)
        if e7 is None or e25 is None or atr<=0:return "NEUTRAL"
        long_ok=e7>e25 and st['direction']=="LONG"
        short_ok=e7<e25 and st['direction']=="SHORT"
        return "LONG" if long_ok else "SHORT" if short_ok else "NEUTRAL"

    @staticmethod
    def _volume_ratio(volumes):
        v=np.asarray(volumes,dtype=float)
        if len(v)<10:return 0.0
        base=v[-21:-1] if len(v)>=21 else v[:-1]; avg=float(np.mean(base)) if len(base) else 0
        return round(float(v[-1]/avg),2) if avg>0 else 0.0

    @classmethod
    def _detect_structure(cls, opens, highs, lows, closes):
        o,h,l,c=(np.asarray(z,dtype=float) for z in (opens,highs,lows,closes)); n=min(map(len,(o,h,l,c)))
        out={"bos":"NONE","mss":"NONE","sweep":"NONE","fvg":"NONE","fvg_zone":None,"ob_type":"NONE","ob_zone":None,"support":None,"resistance":None}
        if n<12:return out
        o,h,l,c=(z[-n:] for z in (o,h,l,c)); lb=min(12,n-2)
        ph=float(np.max(h[-lb-1:-1])); pl=float(np.min(l[-lb-1:-1])); out.update(support=pl,resistance=ph)
        
        # رصد الفجوات السعرية (FVG) ومناطق الكتل للاستباق
        if l[-1]>h[-3] and (l[-1]-h[-3])/c[-1]>=.0003:
            out.update(fvg='BULLISH_FVG', fvg_zone=[float(h[-3]), float(l[-1])])
        elif h[-1]<l[-3] and (l[-3]-h[-1])/c[-1]>=.0003:
            out.update(fvg='BEARISH_FVG', fvg_zone=[float(h[-1]), float(l[-3])])
            
        return out

    @classmethod
    def _predictive_limit_entry(cls, highs, lows, closes, direction):
        """تحديد منطقة سعرية معلقة (Limit Order Zone) للتوقع بدلاً من الدخول الفوري المتأخر"""
        h, l, c = np.asarray(highs, dtype=float), np.asarray(lows, dtype=float), np.asarray(closes, dtype=float)
        atr = cls.calculate_atr(h, l, c)
        if direction == 'LONG':
            # توقع الشراء عند إعادة اختبار منطقة الدعم أو منتصف الفجوة السعرية الأخيرة
            suggested_entry = float(c[-1] - 0.5 * atr)
            return suggested_entry, "منطقة طلب معلقة (توقع ارتداد صاعد)"
        else:
            # توقع البيع (شورت) عند إعادة اختبار منطقة المقاومة أو الارتتداد من الاعلى مسبقاً
            suggested_entry = float(c[-1] + 0.5 * atr)
            return suggested_entry, "منطقة عرض معلقة (توقع ارتداد هابط)"

    def analyze_multi_timeframe(self, ohlcv_4h, ohlcv_1h, ohlcv_15m, ohlcv_btc_1h=None,
                                symbol="", market_context=None, order_book=None, trades=None):
        d={"trend_4h":"NEUTRAL","trend_1h":"NEUTRAL","predictive_entry":None,"divergence":"NONE","fvg":"NONE","fvg_zone":None,"volume_ratio":0.0,"reasons_excluded":[],"indicators":{},"market_context":market_context or {}}
        empty=([],[],[])
        if symbol and not self.is_valid_symbol(symbol):d['reasons_excluded']=["رمز غير صالح"];return "NEUTRAL",0,0.0,d,empty
        for label,data in (("4H",ohlcv_4h),("1H",ohlcv_1h),("15M",ohlcv_15m)):
            if not self.valid_ohlcv(data,20):d['reasons_excluded'].append(f"بيانات {label} غير كافية");return "NEUTRAL",0,0.0,d,empty
            
        o4,h4,l4,c4,v4=self.arrays(ohlcv_4h[:-1]); o1,h1,l1,c1,v1=self.arrays(ohlcv_1h[:-1]); o,h,l,c,v=self.arrays(ohlcv_15m[:-1])
        t4,t1=self._trend(h4,l4,c4),self._trend(h1,l1,c1); d['trend_4h'],d['trend_1h']=t4,t1
        
        rsi6=self._rsi(c,6); rsi14=self._rsi(c,14); macd=self._macd(c); vol_ratio=self._volume_ratio(v)
        div = self._detect_divergence(h, l, c)
        d['divergence'] = div
        
        direction = t1
        if direction not in ('LONG','SHORT'):
            # إذا كان الاتجاه محايداً، نعتمد على الدايفرجنس المبكر لتوقع الانعكاس المبكر!
            if div == 'BULLISH_DIVERGENCE': direction = 'LONG'
            elif div == 'BEARISH_DIVERGENCE': direction = 'SHORT'
            else:
                d['reasons_excluded']=["لا يوجد اتجاه واضح أو دايفرجنس استباقي"];return "NEUTRAL",30,vol_ratio,d,(h.tolist(),l.tolist(),c.tolist())

        confirmations = ["توافق الاتجاه والاستباق الفني المبكر"]
        if div != 'NONE': confirmations.append(f"تم رصد دايفرجنس استباقي: {div}")
        
        limit_price, limit_reason = self._predictive_limit_entry(h, l, c, direction)
        d['predictive_entry'] = limit_price
        confirmations.append(limit_reason)

        score = 85
        if div != 'NONE': score += 10
        score = int(min(100, score))
        
        entry_valid = True
        d.update(entry_valid=entry_valid, confirmations=confirmations, candidate_direction=direction)
        return direction, score, vol_ratio, d, (h.tolist(), l.tolist(), c.tolist())

    def calculate_risk_management(self, entry_price, direction, highs, lows, closes=None):
        entry=float(entry_price); direction=str(direction).upper(); highs=np.asarray(highs,dtype=float);lows=np.asarray(lows,dtype=float)
        if closes is None:closes=(highs+lows)/2
        closes=np.asarray(closes,dtype=float);n=min(len(highs),len(lows),len(closes))
        if not np.isfinite(entry) or entry<=0 or n<5:raise ValueError('Invalid entry')
        highs,lows,closes=highs[-n:],lows[-n:],closes[-n:];atr=self.calculate_atr(highs,lows,closes)
        if not np.isfinite(atr) or atr<=0:atr=entry*.01
        
        recent_low=float(np.min(lows[-10:])); recent_high=float(np.max(highs[-10:])); buffer=.2*atr
        if direction in ('LONG','BUY'):
            stop=min(entry-1.5*atr,recent_low-buffer); risk=entry-stop
            t1,t2,t3=entry+1.5*risk, entry+2.5*risk, entry+4*risk
        else:
            stop=max(entry+1.5*atr,recent_high+buffer); risk=stop-entry
            t1,t2,t3=entry-1.5*risk, entry-2.5*risk, entry-4*risk
        return (round(float(stop),10), round(float(t1),10), round(float(t2),10), round(float(t3),10), round(abs(entry-stop)/entry*100,3), round(abs(t1-entry)/entry*100,3), round(abs(t1-entry)/abs(entry-stop),2))
