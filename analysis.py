# =========================================================
# analysis.py - BingX Futures AI Scanner v20.0
#
# ORDER BLOCK PRIMARY:
# 1H OB -> Retest / BOS -> Liquidity -> MTF Confirmation
#
# v20 CHANGES:
# - Keep ORDER BLOCK as the primary engine.
# - Relax entry threshold without creating random signals.
# - Strong OB can qualify with partial MTF confirmation.
# - Retest OR BOS is enough confirmation.
# - Lower timeframes are confirmation, NOT primary signal.
# - Reduce excessive WAIT / NO TRADE results.
# - Keep crash/pump protection.
# - Keep price / kline robustness and rate-limit protection.
# =========================================================

import time
import logging
import threading
import requests


# =========================================================
# CONFIG
# =========================================================

BINGX_URL = 'https://open-api.bingx.com'

SESSION = requests.Session()
SESSION.headers.update({
    'User-Agent': 'CryptoZeroReversal-BingX-OB-Scanner/20.0',
    'Accept': 'application/json'
})

logger = logging.getLogger(__name__)

SYMBOL_CACHE_SECONDS = 600
KLINE_CACHE_SECONDS = 60
PRICE_CACHE_SECONDS = 3
TICKER_CACHE_SECONDS = 5

_SYMBOL_CACHE = set()
_SYMBOL_CACHE_TIME = 0

_KLINE_CACHE = {}
_PRICE_CACHE = {}

_TICKER_CACHE = None
_TICKER_CACHE_TIME = 0

_RATE_LIMIT_UNTIL = 0
_RATE_LOCK = threading.Lock()
_REQUEST_LOCK = threading.Lock()
_LAST_REQUEST_TIME = 0.0

# v20: faster but still protected against BingX rate limits.
MIN_REQUEST_INTERVAL = 0.75


# =========================================================
# BINGX REQUEST
# =========================================================

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
        r = SESSION.get(
            BINGX_URL + path,
            params=params or {},
            timeout=timeout
        )

        if r.status_code != 200:
            logger.warning(
                'BingX HTTP %s | %s',
                r.status_code,
                path
            )
            return None

        d = r.json()

        if not isinstance(d, dict):
            return None

        code = d.get('code')

        if code in (109429, 109400):
            with _RATE_LOCK:
                _RATE_LIMIT_UNTIL = max(
                    _RATE_LIMIT_UNTIL,
                    time.time() + 90
                )

            logger.warning(
                'BingX RATE LIMIT | code=%s | cooldown=90s',
                code
            )

            return None

        if code not in (0, None):
            logger.warning(
                'BingX API ERROR code=%s | %s',
                code,
                path
            )
            return None

        return d

    except Exception as e:
        logger.warning(
            'BingX REQUEST FAILED | %s | %s',
            path,
            e
        )
        return None


# =========================================================
# SYMBOL HELPERS
# =========================================================

def normalize_symbol(s):
    s = str(s).strip().upper()
    s = (
        s.replace(' ', '')
        .replace('-', '')
        .replace('_', '')
        .replace('/', '')
    )

    if s.endswith(('USDT', 'USDC')):
        return s

    return s + 'USDT'


def bingx_symbol(s):
    s = normalize_symbol(s)
    return s[:-4] + '-' + s[-4:]


def _rows(d):
    if not isinstance(d, dict):
        return []

    x = d.get('data')

    if isinstance(x, list):
        return x

    if isinstance(x, dict):
        return [x]

    return []


def _is_crypto_usdt_symbol(s):
    s = str(s).upper().replace('-', '')

    if not s.endswith('USDT'):
        return False

    base = s[:-4]

    blocked = (
        'SP500',
        'NASDAQ',
        'DJI',
        'US30',
        'DXY',
        'GOLD',
        'SILVER',
        'XAU',
        'XAG',
        'OIL',
        'BRENT',
        'WTI',
        'COPPER',
        'PLATINUM',
        'PALLADIUM'
    )

    if base.endswith('USD'):
        return False

    if any(x in base for x in blocked):
        return False

    return True


# =========================================================
# FUTURES SYMBOLS
# =========================================================

def get_futures_symbols(force_refresh=False):
    global _SYMBOL_CACHE
    global _SYMBOL_CACHE_TIME

    if (
        not force_refresh
        and _SYMBOL_CACHE
        and time.time() - _SYMBOL_CACHE_TIME < SYMBOL_CACHE_SECONDS
    ):
        return set(_SYMBOL_CACHE)

    d = bingx_get('/openApi/swap/v2/quote/contracts')

    out = set()

    for x in _rows(d):
        if not isinstance(x, dict):
            continue

        s = str(
            x.get('symbol', '')
        ).replace('-', '').upper()

        if not _is_crypto_usdt_symbol(s):
            continue

        if x.get('status') in (1, '1', None):
            out.add(s)

    if out:
        _SYMBOL_CACHE = out
        _SYMBOL_CACHE_TIME = time.time()

    return set(_SYMBOL_CACHE)


def symbol_exists(s):
    s = normalize_symbol(s)
    sy = get_futures_symbols()

    # If contracts endpoint temporarily failed,
    # do not block analysis.
    return not sy or s in sy


# =========================================================
# PRICE
# =========================================================

def _price_row(x):
    if not isinstance(x, dict):
        return None

    for k in (
        'price',
        'lastPrice',
        'last',
        'close',
        'markPrice'
    ):
        try:
            v = float(x.get(k))

            if v > 0:
                return v

        except Exception:
            pass

    return None


def _ticker_rows(force=False):
    global _TICKER_CACHE
    global _TICKER_CACHE_TIME

    if (
        not force
        and _TICKER_CACHE is not None
        and time.time() - _TICKER_CACHE_TIME < TICKER_CACHE_SECONDS
    ):
        return _TICKER_CACHE

    x = _rows(
        bingx_get('/openApi/swap/v2/quote/ticker')
    )

    if x:
        _TICKER_CACHE = x
        _TICKER_CACHE_TIME = time.time()

    return x


def get_current_price(s, force=False):
    s = normalize_symbol(s)

    now = time.time()
    c = _PRICE_CACHE.get(s)

    if (
        not force
        and c
        and now - c[0] < PRICE_CACHE_SECONDS
    ):
        return c[1]

    # -----------------------------------------------------
    # 1. Global ticker
    # -----------------------------------------------------

    for x in _ticker_rows(force):
        if not isinstance(x, dict):
            continue

        xs = str(
            x.get('symbol', '')
        ).replace('-', '').upper()

        if xs != s:
            continue

        p = _price_row(x)

        if p:
            _PRICE_CACHE[s] = (now, p)
            return p

    # -----------------------------------------------------
    # 2. Direct price endpoints
    # -----------------------------------------------------

    endpoints = (
        '/openApi/swap/v2/quote/price',
        '/openApi/swap/v1/ticker/price',
        '/openApi/swap/v3/quote/price'
    )

    for ep in endpoints:
        rows = _rows(
            bingx_get(
                ep,
                {'symbol': bingx_symbol(s)}
            )
        )

        for x in rows:
            p = _price_row(x)

            if p:
                _PRICE_CACHE[s] = (now, p)
                return p

    # -----------------------------------------------------
    # 3. Kline fallback
    # -----------------------------------------------------

    k = get_bingx_klines(
        s,
        '1h',
        60
    )

    if k:
        try:
            p = float(k[-1][4])

            if p > 0:
                _PRICE_CACHE[s] = (now, p)
                return p

        except Exception:
            pass

    return None


# =========================================================
# KLINE PARSER
# =========================================================

def _parse(rows):
    out = []

    for x in rows:
        try:
            if isinstance(x, dict):
                t = (
                    x.get('time')
                    or x.get('timestamp')
                    or x.get('openTime')
                    or 0
                )

                o = x.get('open')
                h = x.get('high')
                l = x.get('low')
                c = x.get('close')
                v = x.get(
                    'volume',
                    x.get('vol', 0)
                )

            elif isinstance(x, list) and len(x) >= 6:
                t, o, h, l, c, v = x[:6]

            else:
                continue

            if None in (o, h, l, c):
                continue

            out.append([
                t,
                float(o),
                float(h),
                float(l),
                float(c),
                float(v or 0)
            ])

        except Exception:
            pass

    try:
        out.sort(key=lambda z: z[0])
    except Exception:
        pass

    return out


# =========================================================
# KLINES
# =========================================================

def get_bingx_klines(
    s,
    interval='1h',
    limit=200
):
    s = normalize_symbol(s)

    key = (
        s,
        interval,
        int(limit)
    )

    now = time.time()

    c = _KLINE_CACHE.get(key)

    if (
        c
        and now - c[0] < KLINE_CACHE_SECONDS
    ):
        return c[1]

    best = []

    params = {
        'symbol': bingx_symbol(s),
        'interval': str(interval).lower(),
        'limit': int(limit)
    }

    endpoints = (
        '/openApi/swap/v3/quote/klines',
        '/openApi/swap/v2/quote/klines'
    )

    for ep in endpoints:
        r = _parse(
            _rows(
                bingx_get(
                    ep,
                    params
                )
            )
        )

        if len(r) > len(best):
            best = r

        if len(r) >= 30:
            _KLINE_CACHE[key] = (
                now,
                r
            )
            return r

    if best:
        _KLINE_CACHE[key] = (
            now,
            best
        )
        return best

    return None


# =========================================================
# INDICATORS
# =========================================================

def calculate_ema(v, n):
    if len(v) < n:
        return None

    e = sum(v[:n]) / n
    m = 2 / (n + 1)

    for x in v[n:]:
        e = (x - e) * m + e

    return e


def calculate_rsi(c, period=14):
    if len(c) < period + 1:
        return 50.0

    g = [
        max(c[i] - c[i - 1], 0)
        for i in range(1, len(c))
    ]

    l = [
        max(c[i - 1] - c[i], 0)
        for i in range(1, len(c))
    ]

    ag = sum(g[:period]) / period
    al = sum(l[:period]) / period

    for i in range(period, len(g)):
        ag = (
            ag * (period - 1) + g[i]
        ) / period

        al = (
            al * (period - 1) + l[i]
        ) / period

    if al == 0:
        return 100.0

    return round(
        100 - 100 / (1 + ag / al),
        2
    )


def calculate_atr(k, n=14):
    if len(k) < n + 1:
        return None

    tr = [
        max(
            x[2] - x[3],
            abs(x[2] - k[i - 1][4]),
            abs(x[3] - k[i - 1][4])
        )
        for i, x in enumerate(k[1:], 1)
    ]

    a = sum(tr[:n]) / n

    for x in tr[n:]:
        a = (
            a * (n - 1) + x
        ) / n

    return a


def calculate_volume_ratio(v, n=20):
    if len(v) < n + 4:
        return 1.0

    a = sum(v[-4:-1]) / 3
    b = sum(v[-n-4:-4]) / n

    if b <= 0:
        return 1.0

    return round(
        max(
            0.05,
            min(5, a / b)
        ),
        2
    )


def calculate_volume_trend(
    v,
    short_period=5,
    long_period=20
):
    if len(v) < long_period + short_period + 1:
        return 'NEUTRAL'

    a = (
        sum(v[-short_period-1:-1])
        / short_period
    )

    b = (
        sum(
            v[
                -long_period-short_period-1:
                -short_period-1
            ]
        )
        / long_period
    )

    if not b:
        return 'NEUTRAL'

    ratio = a / b

    if ratio >= 1.10:
        return 'RISING'

    if ratio <= 0.90:
        return 'FALLING'

    return 'NEUTRAL'


def percentage_change(a, b):
    if not a:
        return 0

    return (b - a) / a * 100


# =========================================================
# SUPPORT / RESISTANCE
# =========================================================

def calculate_support_resistance(k):
    if not k:
        return 0, 0

    p = k[-1][4]

    h = [
        x[2]
        for x in k[-80:]
    ]

    l = [
        x[3]
        for x in k[-80:]
    ]

    s = [
        x
        for x in l
        if x < p
    ]

    r = [
        x
        for x in h
        if x > p
    ]

    support = (
        max(s)
        if s
        else min(l)
    )

    resistance = (
        min(r)
        if r
        else max(h)
    )

    return support, resistance


def _dir(k):
    if k[4] > k[1]:
        return 'BULLISH'

    if k[4] < k[1]:
        return 'BEARISH'

    return 'NEUTRAL'


# =========================================================
# ORDER BLOCK ENGINE
# =========================================================

def detect_order_blocks(
    k,
    lookback=120
):
    """
    PRIMARY ENGINE

    Bullish OB:
        bearish candle
        followed by bullish displacement
        + local BOS / wick BOS

    Bearish OB:
        bullish candle
        followed by bearish displacement
        + local BOS / wick BOS
    """

    if len(k) < 30:
        return {
            'bullish': [],
            'bearish': []
        }

    bull = []
    bear = []

    start = max(
        5,
        len(k) - lookback
    )

    for i in range(
        start,
        len(k) - 2
    ):
        b = k[i]
        d = k[i + 1]

        rng = max(
            d[2] - d[3],
            1e-12
        )

        body = abs(
            d[4] - d[1]
        )

        displacement = body / rng

        # v20:
        # Slightly relaxed from 0.45 to 0.40.
        if displacement < 0.40:
            continue

        left = k[
            max(0, i - 12):i
        ]

        if not left:
            continue

        ph = max(
            x[2]
            for x in left
        )

        pl = min(
            x[3]
            for x in left
        )

        bull_bos = (
            d[4] > ph
            or (
                d[2] > ph
                and d[4] >= d[1]
            )
        )

        bear_bos = (
            d[4] < pl
            or (
                d[3] < pl
                and d[4] <= d[1]
            )
        )

        # -------------------------------------------------
        # BULLISH OB
        # -------------------------------------------------

        if (
            _dir(b) == 'BEARISH'
            and _dir(d) == 'BULLISH'
            and bull_bos
        ):
            lo, hi = sorted(
                (b[1], b[4])
            )

            move = max(
                percentage_change(
                    d[1],
                    d[4]
                ),
                0
            )

            strength = min(
                100,
                40
                + displacement * 35
                + min(move, 6) * 4
            )

            bull.append({
                'type': 'BULLISH',
                'index': i,
                'low': lo,
                'high': hi,
                'mid': (lo + hi) / 2,
                'strength': round(
                    strength,
                    1
                )
            })

        # -------------------------------------------------
        # BEARISH OB
        # -------------------------------------------------

        if (
            _dir(b) == 'BULLISH'
            and _dir(d) == 'BEARISH'
            and bear_bos
        ):
            lo, hi = sorted(
                (b[1], b[4])
            )

            move = max(
                -percentage_change(
                    d[1],
                    d[4]
                ),
                0
            )

            strength = min(
                100,
                40
                + displacement * 35
                + min(move, 6) * 4
            )

            bear.append({
                'type': 'BEARISH',
                'index': i,
                'low': lo,
                'high': hi,
                'mid': (lo + hi) / 2,
                'strength': round(
                    strength,
                    1
                )
            })

    bull = sorted(
        bull,
        key=lambda x: (
            x['index'],
            x['strength']
        ),
        reverse=True
    )[:12]

    bear = sorted(
        bear,
        key=lambda x: (
            x['index'],
            x['strength']
        ),
        reverse=True
    )[:12]

    return {
        'bullish': bull,
        'bearish': bear
    }


# =========================================================
# OB DISTANCE
# =========================================================

def price_inside_ob(
    p,
    o,
    tolerance=0.005
):
    if not o:
        return False

    m = max(
        (o['high'] - o['low'])
        * tolerance,
        0
    )

    return (
        o['low'] - m
        <= p
        <= o['high'] + m
    )


def ob_distance_percent(p, o):
    if not o or p <= 0:
        return 999

    if price_inside_ob(p, o):
        return 0

    if p < o['low']:
        return (
            (o['low'] - p)
            / p
            * 100
        )

    return (
        (p - o['high'])
        / p
        * 100
    )


# =========================================================
# OB VALIDATION
# =========================================================

def _ob_valid(k, o, d):
    if not o:
        return False

    for x in k[o['index'] + 2:]:
        if (
            d == 'LONG'
            and x[4] <
            o['low'] * (1 - 0.0015)
        ):
            return False

        if (
            d == 'SHORT'
            and x[4] >
            o['high'] * (1 + 0.0015)
        ):
            return False

    return True


# =========================================================
# FIND ACTIVE OB
# =========================================================

def find_active_order_block(
    k,
    d,
    p
):
    obs = detect_order_blocks(k)

    candidates = obs[
        'bullish'
        if d == 'LONG'
        else 'bearish'
    ]

    best = None

    for o in candidates:

        if not _ob_valid(k, o, d):
            continue

        dist = ob_distance_percent(
            p,
            o
        )

        # v20:
        # 6% -> 8% maximum search range.
        if dist > 8:
            continue

        age = (
            len(k) - 1
            - o['index']
        )

        if age <= 12:
            rec = 14

        elif age <= 30:
            rec = 10

        elif age <= 50:
            rec = 6

        else:
            rec = 2

        proximity = max(
            0,
            25 - dist * 3
        )

        # Extra quality for a block that
        # is actually close to current price.
        near_bonus = (
            8
            if dist <= 1.0
            else 5
            if dist <= 2.5
            else 2
        )

        score = (
            o['strength']
            + rec
            + proximity
            + near_bonus
        )

        if (
            best is None
            or score > best[0]
        ):
            best = (
                score,
                o
            )

    return (
        best[1]
        if best
        else None
    )


# =========================================================
# OB RETEST
# =========================================================

def detect_ob_retest(
    k,
    o,
    d
):
    if not o:
        return False, []

    touched = False
    rejected = False

    reasons = []

    start = max(
        o['index'] + 2,
        len(k) - 20
    )

    for x in k[start:]:

        if (
            x[3] <= o['high']
            and x[2] >= o['low']
        ):
            touched = True

            if (
                d == 'LONG'
                and x[4] >= o['mid']
            ):
                rejected = True

            if (
                d == 'SHORT'
                and x[4] <= o['mid']
            ):
                rejected = True

    if touched:
        reasons.append(
            'السعر أعاد اختبار Order Block'
        )

    if rejected:
        reasons.append(
            'ظهر رفض من منطقة Order Block'
        )

    return (
        touched and rejected,
        reasons
    )


# =========================================================
# MARKET STRUCTURE
# =========================================================

def detect_market_structure(k):
    if len(k) < 25:
        return {
            'structure': 'UNKNOWN',
            'bos': 'NONE',
            'liquidity_zone': 'NONE',
            'reasons': []
        }

    c = k[-1][4]
    prev = k[-2][4]

    rh = max(
        x[2]
        for x in k[-30:-5]
    )

    rl = min(
        x[3]
        for x in k[-30:-5]
    )

    bos = 'NONE'
    st = 'MIXED'
    rs = []

    if (
        c > rh
        and prev <= rh
    ):
        bos = 'BULLISH_BOS'
        st = 'BULLISH'
        rs.append(
            'BOS صاعد مؤكد'
        )

    elif (
        c < rl
        and prev >= rl
    ):
        bos = 'BEARISH_BOS'
        st = 'BEARISH'
        rs.append(
            'BOS هابط مؤكد'
        )

    else:
        hh = max(
            x[2]
            for x in k[-10:]
        )

        ll = min(
            x[3]
            for x in k[-10:]
        )

        st = (
            'BULLISH'
            if c >= hh * .997
            else 'BEARISH'
            if c <= ll * 1.003
            else 'MIXED'
        )

        rs.append(
            'لا يوجد BOS جديد مؤكد'
        )

    hh = max(
        x[2]
        for x in k[-10:]
    )

    ll = min(
        x[3]
        for x in k[-10:]
    )

    zone = (
        'LOW_LIQUIDITY'
        if abs(c - ll) / c * 100 <= .6
        else
        'HIGH_LIQUIDITY'
        if abs(hh - c) / c * 100 <= .6
        else
        'NONE'
    )

    return {
        'structure': st,
        'bos': bos,
        'liquidity_zone': zone,
        'reasons': rs
    }


# =========================================================
# LIQUIDITY FLOW
# =========================================================

def detect_liquidity_flow(k):
    if len(k) < 25:
        return (
            'NEUTRAL',
            0,
            []
        )

    r = k[:-1]

    bull = sum(
        x[5]
        for x in r[-15:]
        if x[4] > x[1]
    )

    bear = sum(
        x[5]
        for x in r[-15:]
        if x[4] < x[1]
    )

    tot = bull + bear

    share = (
        bull / tot
        if tot
        else .5
    )

    vr = calculate_volume_ratio(
        [x[5] for x in r]
    )

    rc = percentage_change(
        r[-6][4],
        r[-1][4]
    )

    rv = (
        sum(x[5] for x in r[-5:])
        / 5
    )

    pv = (
        sum(x[5] for x in r[-15:-5])
        / 10
    )

    sc = 0
    rs = []

    # v20: slightly easier liquidity confirmation.
    if (
        share >= .55
        and vr >= .80
    ):
        sc += 2
        rs.append(
            'ضغط الشراء أعلى من البيع'
        )

    if (
        rv > pv * 1.03
        and rc >= -2.5
    ):
        sc += 1
        rs.append(
            'الحجم يتحسن مع استقرار السعر'
        )

    if (
        share <= .45
        and vr >= .80
    ):
        sc -= 2
        rs.append(
            'ضغط البيع أعلى من الشراء'
        )

    if (
        rv > pv * 1.03
        and rc <= -2.5
    ):
        sc -= 1
        rs.append(
            'ارتفاع الحجم مع ضغط بيعي'
        )

    if sc >= 2:
        return (
            'INFLOW',
            sc,
            rs
        )

    if sc <= -2:
        return (
            'OUTFLOW',
            sc,
            rs
        )

    return (
        'NEUTRAL',
        sc,
        rs
    )


# =========================================================
# MTF TREND
# =========================================================

def calculate_timeframe_trend(k):
    if not k:
        return 'UNKNOWN'

    c = [
        x[4]
        for x in k
    ]

    a = calculate_ema(
        c,
        9
    )

    b = calculate_ema(
        c,
        20
    )

    d = calculate_ema(
        c,
        50
    )

    if None in (a, b, d):
        return 'UNKNOWN'

    if (
        a > b
        and b > d
        and c[-1] > b
    ):
        return 'LONG'

    if (
        a < b
        and b < d
        and c[-1] < b
    ):
        return 'SHORT'

    return 'NEUTRAL'


# =========================================================
# BOTTOM / ACCUMULATION
# =========================================================

def detect_bottom_accumulation(k):
    if len(k) < 40:
        return False, 0, []

    c = [
        x[4]
        for x in k
    ]

    v = [
        x[5]
        for x in k
    ]

    n = min(
        30,
        len(c) // 2
    )

    old = c[-2 * n:-n]
    rec = c[-n:]

    if not old or not rec:
        return False, 0, []

    dd = (
        min(rec) - max(old)
    ) / max(old) * 100

    rr = (
        max(rec) - min(rec)
    ) / min(rec) * 100

    score = (
        1 if dd <= -4 else 0
    ) + (
        1 if rr <= 18 else 0
    ) + (
        1
        if sum(v[-10:]) / 10
        >= (
            sum(v[-2*n:-n])
            / len(old)
            * .65
        )
        else 0
    )

    rs = []

    if dd <= -4:
        rs.append(
            'هبوط سابق واضح'
        )

    if rr <= 18:
        rs.append(
            'النطاق السعري بدأ يضيق'
        )

    if score >= 2:
        rs.append(
            'الحجم ما زال موجوداً بعد الهبوط'
        )

    return (
        score >= 2,
        score,
        rs
    )


# =========================================================
# ROUNDING
# =========================================================

def smart_round(v):
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

    if v >= .1:
        return round(v, 5)

    if v >= .01:
        return round(v, 6)

    return round(v, 8)


# =========================================================
# MAIN COIN ANALYSIS
# =========================================================

def get_coin_analysis(symbol):
    symbol = normalize_symbol(symbol)

    if not symbol_exists(symbol):
        return None

    # -----------------------------------------------------
    # 1H PRIMARY
    # -----------------------------------------------------

    k1 = get_bingx_klines(
        symbol,
        '1h',
        200
    )

    p = get_current_price(
        symbol,
        True
    )

    if p is None and k1:
        try:
            p = float(k1[-1][4])
        except Exception:
            p = None

    if p is None:
        return None

    if (
        not k1
        or len(k1) < 30
    ):
        return {
            'symbol': symbol,
            'direction': 'NO TRADE',
            'score': 0,
            'entry_score': 0,
            'state':
                'NO TRADE - بيانات 1H غير مكتملة',
            'price': smart_round(p)
        }

    # -----------------------------------------------------
    # MTF DATA
    # -----------------------------------------------------

    k4 = get_bingx_klines(
        symbol,
        '4h',
        160
    )

    kd = get_bingx_klines(
        symbol,
        '1d',
        120
    )

    k30 = get_bingx_klines(
        symbol,
        '30m',
        160
    )

    k15 = get_bingx_klines(
        symbol,
        '15m',
        160
    )

    # -----------------------------------------------------
    # TRENDS
    # -----------------------------------------------------

    t1 = calculate_timeframe_trend(k1)
    t4 = calculate_timeframe_trend(k4)
    td = calculate_timeframe_trend(kd)
    t30 = calculate_timeframe_trend(k30)
    t15 = calculate_timeframe_trend(k15)

    # -----------------------------------------------------
    # 1H DATA
    # -----------------------------------------------------

    c = [
        x[4]
        for x in k1
    ]

    v = [
        x[5]
        for x in k1
    ]

    rsi = calculate_rsi(c)

    atr = (
        calculate_atr(k1)
        or p * .01
    )

    vr = calculate_volume_ratio(v)

    vt = calculate_volume_trend(v)

    sup, res = calculate_support_resistance(k1)

    # -----------------------------------------------------
    # STRUCTURE / LIQUIDITY
    # -----------------------------------------------------

    st = detect_market_structure(k1)

    liq, liqs, liqr = detect_liquidity_flow(k1)

    bottom, bs, br = detect_bottom_accumulation(k1)

    # -----------------------------------------------------
    # ORDER BLOCKS
    # -----------------------------------------------------

    bo = find_active_order_block(
        k1,
        'LONG',
        p
    )

    so = find_active_order_block(
        k1,
        'SHORT',
        p
    )

    bo4 = (
        find_active_order_block(
            k4,
            'LONG',
            p
        )
        if k4
        else None
    )

    so4 = (
        find_active_order_block(
            k4,
            'SHORT',
            p
        )
        if k4
        else None
    )

    # -----------------------------------------------------
    # RETEST
    # -----------------------------------------------------

    bor, bor_r = detect_ob_retest(
        k1,
        bo,
        'LONG'
    )

    sor, sor_r = detect_ob_retest(
        k1,
        so,
        'SHORT'
    )

    bd = (
        ob_distance_percent(p, bo)
        if bo
        else 999
    )

    sd = (
        ob_distance_percent(p, so)
        if so
        else 999
    )

    # =====================================================
    # SCORING
    #
    # IMPORTANT:
    # OB remains the biggest component.
    # =====================================================

    l = 0
    s = 0

    lines = []
    reject = []

    # -----------------------------------------------------
    # BULLISH OB
    # -----------------------------------------------------

    if bo:
        l += 35

        lines.append(
            'يوجد Bullish Order Block فعال على 1H'
        )

        if bo['strength'] >= 55:
            l += 10

            lines.append(
                'قوة Bullish OB جيدة'
            )

        elif bo['strength'] >= 48:
            l += 5

            lines.append(
                'قوة Bullish OB مقبولة'
            )

        if bor:
            l += 20

            lines.append(
                'Bullish OB حصل له Retest + Rejection'
            )

        elif bd <= 1.5:
            l += 7

            lines.append(
                'Bullish OB قريب جداً من السعر'
            )

    # -----------------------------------------------------
    # BEARISH OB
    # -----------------------------------------------------

    if so:
        s += 35

        lines.append(
            'يوجد Bearish Order Block فعال على 1H'
        )

        if so['strength'] >= 55:
            s += 10

            lines.append(
                'قوة Bearish OB جيدة'
            )

        elif so['strength'] >= 48:
            s += 5

            lines.append(
                'قوة Bearish OB مقبولة'
            )

        if sor:
            s += 20

            lines.append(
                'Bearish OB حصل له Retest + Rejection'
            )

        elif sd <= 1.5:
            s += 7

            lines.append(
                'Bearish OB قريب جداً من السعر'
            )

    # =====================================================
    # 4H MTF
    # =====================================================

    if t4 == 'LONG':
        l += 12

        if bo4:
            l += 8

        lines.append(
            '4H يدعم الاتجاه الصاعد'
        )

    elif t4 == 'SHORT':
        s += 12

        if so4:
            s += 8

        lines.append(
            '4H يدعم الاتجاه الهابط'
        )

    # -----------------------------------------------------
    # 1H
    # -----------------------------------------------------

    if t1 == 'LONG':
        l += 6

    elif t1 == 'SHORT':
        s += 6

    # -----------------------------------------------------
    # 30M
    # -----------------------------------------------------

    if t30 == 'LONG':
        l += 5

    elif t30 == 'SHORT':
        s += 5

    # -----------------------------------------------------
    # 15M
    # -----------------------------------------------------

    if t15 == 'LONG':
        l += 4

    elif t15 == 'SHORT':
        s += 4

    # =====================================================
    # BOS
    # =====================================================

    if st['bos'] == 'BULLISH_BOS':
        l += 12

        lines.append(
            'BOS صاعد يؤكد Bullish OB'
        )

    elif st['bos'] == 'BEARISH_BOS':
        s += 12

        lines.append(
            'BOS هابط يؤكد Bearish OB'
        )

    # =====================================================
    # LIQUIDITY
    # =====================================================

    if liq == 'INFLOW':
        l += 7

        lines.append(
            'السيولة تميل للشراء'
        )

    elif liq == 'OUTFLOW':
        s += 7

        lines.append(
            'السيولة تميل للبيع'
        )

    # =====================================================
    # VOLUME
    # =====================================================

    if vr >= 1.10:

        if l >= s:
            l += 4

        else:
            s += 4

        lines.append(
            'الحجم يدعم الحركة'
        )

    # =====================================================
    # RSI
    #
    # Confirmation only.
    # =====================================================

    if t4 == 'LONG':
        if 35 <= rsi <= 70:
            l += 3

    elif t4 == 'SHORT':
        if 30 <= rsi <= 68:
            s += 3

    # =====================================================
    # SUPPORT / RESISTANCE DISTANCE
    # =====================================================

    supd = (
        abs(p - sup)
        / p
        * 100
    )

    resd = (
        abs(res - p)
        / p
        * 100
    )

    # =====================================================
    # RECENT MOVEMENT PROTECTION
    # =====================================================

    ch2 = percentage_change(
        c[-3],
        p
    )

    ch6 = percentage_change(
        c[-7],
        p
    )

    crash = (
        ch2 <= -8
        or ch6 <= -15
    )

    pump = (
        ch2 >= 8
        or ch6 >= 15
    )

    # v20:
    # Crash remains strong protection.
    #
    # Pump is not automatically rejecting the trade.
    # It only reduces confidence.
    # =====================================================

    if crash:
        l -= 12
        s -= 12

        reject.append(
            'حركة هبوط سريعة'
        )

    if pump:
        l -= 5
        s -= 5

        reject.append(
            'حركة صعود سريعة؛ الحذر من مطاردة السعر'
        )

    # =====================================================
    # CONFIRMATION ENGINE
    #
    # Retest OR BOS.
    #
    # We do NOT require all MTF timeframes.
    # =====================================================

    long_retest_confirmation = bor

    short_retest_confirmation = sor

    long_bos_confirmation = (
        st['bos'] == 'BULLISH_BOS'
    )

    short_bos_confirmation = (
        st['bos'] == 'BEARISH_BOS'
    )

    # Lower timeframe agreement.
    long_ltf = (
        t1 == 'LONG'
        or t30 == 'LONG'
        or t15 == 'LONG'
    )

    short_ltf = (
        t1 == 'SHORT'
        or t30 == 'SHORT'
        or t15 == 'SHORT'
    )

    # MTF agreement.
    long_mtf = (
        t4 == 'LONG'
        or bo4 is not None
        or td == 'LONG'
    )

    short_mtf = (
        t4 == 'SHORT'
        or so4 is not None
        or td == 'SHORT'
    )

    # =====================================================
    # v20 ENTRY LOGIC
    #
    # Main principle:
    #
    # OB + score + (Retest/BOS/strong proximity)
    #
    # not:
    # OB + ALL timeframes + ALL indicators.
    # =====================================================

    # Strong OB can enter if:
    # - score >= 62
    # - OB close
    # - MTF/LTF agrees
    # - no crash
    # - enough room to resistance
    #
    long_ready = (
        bool(bo)
        and l >= 62
        and (
            long_retest_confirmation
            or long_bos_confirmation
            or (
                bd <= 1.5
                and long_ltf
                and long_mtf
                and bo['strength'] >= 52
            )
        )
        and not crash
        and resd > 0.12
    )

    short_ready = (
        bool(so)
        and s >= 62
        and (
            short_retest_confirmation
            or short_bos_confirmation
            or (
                sd <= 1.5
                and short_ltf
                and short_mtf
                and so['strength'] >= 52
            )
        )
        and not crash
        and supd > 0.12
    )

    # =====================================================
    # FINAL DIRECTION
    # =====================================================

    if (
        long_ready
        and l >= s
    ):
        direction = 'LONG'
        es = l

        state = (
            'ENTRY READY - '
            'Bullish Order Block + Confirmation'
        )

    elif (
        short_ready
        and s > l
    ):
        direction = 'SHORT'
        es = s

        state = (
            'ENTRY READY - '
            'Bearish Order Block + Confirmation'
        )

    # -----------------------------------------------------
    # WAIT BULLISH
    # -----------------------------------------------------

    elif (
        bo
        and l >= 52
        and bd <= 8
        and not crash
        and resd > 0.10
    ):
        direction = 'WAIT'
        es = l

        if bor:
            state = (
                'REVERSAL WATCH - '
                'Bullish OB + Retest'
            )

        elif long_bos_confirmation:
            state = (
                'REVERSAL WATCH - '
                'Bullish OB + BOS'
            )

        else:
            state = (
                'REVERSAL WATCH - '
                'Bullish OB موجود وننتظر Retest/BOS'
            )

    # -----------------------------------------------------
    # WAIT BEARISH
    # -----------------------------------------------------

    elif (
        so
        and s >= 52
        and sd <= 8
        and not crash
        and supd > 0.10
    ):
        direction = 'WAIT'
        es = s

        if sor:
            state = (
                'REVERSAL WATCH - '
                'Bearish OB + Retest'
            )

        elif short_bos_confirmation:
            state = (
                'REVERSAL WATCH - '
                'Bearish OB + BOS'
            )

        else:
            state = (
                'REVERSAL WATCH - '
                'Bearish OB موجود وننتظر Retest/BOS'
            )

    # -----------------------------------------------------
    # ACCUMULATION WATCH
    # -----------------------------------------------------

    elif (
        bottom
        and (
            bo4
            or so4
        )
    ):
        m4 = (
            bo4
            if bo4
            else so4
        )

        m4d = ob_distance_percent(
            p,
            m4
        )

        if m4d <= 8:
            direction = 'WAIT'

            es = max(
                l,
                s,
                45
            )

            state = (
                'ACCUMULATION WATCH - '
                'MTF Order Block قريب وننتظر تأكيد 1H'
            )

        else:
            direction = 'NO TRADE'
            es = max(
                l,
                s,
                0
            )

            state = (
                'NO TRADE - '
                'لا يوجد Order Block قريب'
            )

    else:
        direction = 'NO TRADE'

        es = max(
            l,
            s,
            0
        )

        state = (
            'NO TRADE - '
            'لا يوجد Order Block صالح قريب'
        )

    # =====================================================
    # ENTRY / SL / TP
    # =====================================================

    emin = None
    emax = None
    sl = None
    tp1 = None
    tp2 = None
    tp3 = None

    # -----------------------------------------------------
    # LONG
    # -----------------------------------------------------

    if (
        direction == 'LONG'
        and bo
    ):
        emin = bo['low']
        emax = bo['high']

        sl = min(
            bo['low'] - atr * .35,
            p - atr * .80
        )

        risk = max(
            p - sl,
            atr * .5
        )

        tp1 = p + risk * 1.2
        tp2 = p + risk * 2
        tp3 = p + risk * 3

        if res > p:
            tp1 = min(
                tp1,
                res
            )

    # -----------------------------------------------------
    # SHORT
    # -----------------------------------------------------

    elif (
        direction == 'SHORT'
        and so
    ):
        emin = so['low']
        emax = so['high']

        sl = max(
            so['high'] + atr * .35,
            p + atr * .80
        )

        risk = max(
            sl - p,
            atr * .5
        )

        tp1 = p - risk * 1.2
        tp2 = p - risk * 2
        tp3 = p - risk * 3

        if sup < p:
            tp1 = max(
                tp1,
                sup
            )

    # =====================================================
    # FINAL SAFETY CHECK
    # =====================================================

    if (
        direction == 'LONG'
        and (
            resd <= .10
            or sl is None
            or sl >= p
        )
    ):
        direction = 'WAIT'

        state = (
            'REVERSAL WATCH - '
            'السعر قريب جداً من المقاومة'
        )

        emin = None
        emax = None
        sl = None
        tp1 = None
        tp2 = None
        tp3 = None

    if (
        direction == 'SHORT'
        and (
            supd <= .10
            or sl is None
            or sl <= p
        )
    ):
        direction = 'WAIT'

        state = (
            'REVERSAL WATCH - '
            'السعر قريب جداً من الدعم'
        )

        emin = None
        emax = None
        sl = None
        tp1 = None
        tp2 = None
        tp3 = None

    # =====================================================
    # BUY PRESSURE
    # =====================================================

    if liq == 'INFLOW':
        buy = (
            60
            + min(
                vr * 6,
                25
            )
        )

    elif liq == 'OUTFLOW':
        buy = (
            40
            - min(
                vr * 5,
                25
            )
        )

    else:
        buy = 50

    # =====================================================
    # RESULT
    # =====================================================

    final_score = int(
        max(
            0,
            min(
                100,
                es
            )
        )
    )

    return {
        'symbol': symbol,

        'direction': direction,

        'score': final_score,

        'entry_score': final_score,

        'state': state,

        'price': smart_round(p),

        'rsi': rsi,

        'volume_ratio': vr,

        'volume_trend': vt,

        'liquidity_state': liq,

        'liquidity_score': liqs,

        'bottom_detected': bottom,

        'bottom_score': bs,

        'drawdown': 0,

        'buy_pressure': round(
            max(
                5,
                min(
                    95,
                    buy
                )
            ),
            1
        ),

        'trend':
            'UP'
            if t4 == 'LONG'
            else
            'DOWN'
            if t4 == 'SHORT'
            else
            'NEUTRAL',

        'trend_1d': td,
        'trend_4h': t4,
        'trend_1h': t1,
        'trend_30m': t30,
        'trend_15m': t15,

        'structure':
            st['structure'],

        'bos':
            st['bos'],

        'liquidity_zone':
            st['liquidity_zone'],

        'bullish_ob': bo,
        'bearish_ob': so,

        'bullish_ob_4h': bo4,
        'bearish_ob_4h': so4,

        'bullish_ob_distance':
            round(bd, 2),

        'bearish_ob_distance':
            round(sd, 2),

        'bullish_ob_retest': bor,
        'bearish_ob_retest': sor,

        'recent_change_2':
            round(ch2, 2),

        'recent_change_6':
            round(ch6, 2),

        'crash_detected': crash,
        'pump_detected': pump,

        'entry_min':
            smart_round(emin)
            if emin is not None
            else None,

        'entry_max':
            smart_round(emax)
            if emax is not None
            else None,

        'stop_loss':
            smart_round(sl)
            if sl is not None
            else None,

        'tp1':
            smart_round(tp1)
            if tp1 is not None
            else None,

        'tp2':
            smart_round(tp2)
            if tp2 is not None
            else None,

        'tp3':
            smart_round(tp3)
            if tp3 is not None
            else None,

        'support':
            smart_round(sup),

        'resistance':
            smart_round(res),

        'support_distance':
            round(supd, 2),

        'resistance_distance':
            round(resd, 2),

        'long_score':
            int(
                max(
                    0,
                    min(
                        100,
                        l
                    )
                )
            ),

        'short_score':
            int(
                max(
                    0,
                    min(
                        100,
                        s
                    )
                )
            ),

        'analysis_lines':
            lines,

        'liquidity_reasons':
            liqr,

        'bottom_reasons':
            br,

        'structure_reasons':
            st['reasons'],

        'bullish_retest_reasons':
            bor_r,

        'bearish_retest_reasons':
            sor_r,

        'rejection_reasons':
            list(
                dict.fromkeys(
                    reject
                )
            )
    }


# =========================================================
# MARKET DATA TEST
# =========================================================

def test_market_data(
    symbol='BTCUSDT'
):
    symbol = normalize_symbol(symbol)

    p = get_current_price(
        symbol,
        True
    )

    a = get_bingx_klines(
        symbol,
        '1h',
        60
    )

    b = get_bingx_klines(
        symbol,
        '4h',
        60
    )

    return {
        'symbol': symbol,
        'price_ok': p is not None,
        'price': p,
        '1h_rows':
            len(a)
            if a
            else 0,
        '4h_rows':
            len(b)
            if b
            else 0,
        'ok':
            p is not None
            and bool(a)
            and len(a) >= 30
    }


# =========================================================
# TOP FUTURES SYMBOLS
# =========================================================

def get_top_futures_symbols(
    limit=30
):
    sy = get_futures_symbols()

    if not sy:
        return []

    rows = _ticker_rows()

    cand = []

    for x in rows:
        try:
            s = str(
                x.get('symbol', '')
            ).replace(
                '-',
                ''
            ).upper()

            v = float(
                x.get(
                    'quoteVolume',
                    x.get(
                        'volume',
                        0
                    )
                )
            )

            ch = abs(
                float(
                    x.get(
                        'priceChangePercent',
                        0
                    )
                )
            )

            if (
                s in sy
                and s.endswith('USDT')
                and v > 0
            ):
                cand.append(
                    (
                        s,
                        v * (
                            1
                            + min(
                                ch / 100,
                                .3
                            )
                        )
                    )
                )

        except Exception:
            pass

    cand.sort(
        key=lambda x: x[1],
        reverse=True
    )

    return (
        [x[0] for x in cand[:limit]]
        or list(sy)[:limit]
    )


# =========================================================
# STAGE 1
#
# OB proximity filter only.
# It does NOT create the final signal.
# =========================================================

def _stage1_score(symbol):
    p = get_current_price(symbol)

    k = get_bingx_klines(
        symbol,
        '1h',
        100
    )

    if p is None or not k:
        return None

    o = detect_order_blocks(k)

    candidates = []

    for best in (
        o['bullish']
        + o['bearish']
    ):
        d = (
            'LONG'
            if best['type'] == 'BULLISH'
            else
            'SHORT'
        )

        if not _ob_valid(
            k,
            best,
            d
        ):
            continue

        dist = ob_distance_percent(
            p,
            best
        )

        # v20: 6% -> 8%
        if dist > 8:
            continue

        ret, _ = detect_ob_retest(
            k,
            best,
            d
        )

        t = calculate_timeframe_trend(
            k
        )

        score = (
            50
            + min(
                best['strength'],
                30
            )
            + (
                15
                if ret
                else 0
            )
            + (
                10
                if t == d
                else 0
            )
            - dist * 3
        )

        # Extra proximity priority.
        if dist <= 1.5:
            score += 5

        candidates.append(
            (
                symbol,
                score,
                d,
                ret
            )
        )

    if not candidates:
        return None

    return max(
        candidates,
        key=lambda x: x[1]
    )


# =========================================================
# MARKET SCAN
# =========================================================

def scan_market(limit=5):
    uni = get_top_futures_symbols(30)

    stage = []

    for s in uni:
        try:
            x = _stage1_score(s)

            if x:
                stage.append(x)

        except Exception:
            logger.exception(
                'STAGE1 FAILED | %s',
                s
            )

    stage.sort(
        key=lambda x: x[1],
        reverse=True
    )

    res = []

    # Analyze top 10 OB candidates.
    for s, *_ in stage[:10]:

        try:
            d = get_coin_analysis(s)

            if not d:
                continue

            if d.get('crash_detected'):
                continue

            if d.get('direction') not in (
                'LONG',
                'SHORT',
                'WAIT'
            ):
                continue

            # ---------------------------------------------
            # Genuine OB requirement.
            # ---------------------------------------------

            has_1h_ob = bool(
                d.get('bullish_ob')
                or
                d.get('bearish_ob')
            )

            has_near_mtf_ob = bool(
                (
                    d.get('bullish_ob_4h')
                    and
                    d.get(
                        'bullish_ob_distance',
                        999
                    ) <= 8
                )
                or
                (
                    d.get('bearish_ob_4h')
                    and
                    d.get(
                        'bearish_ob_distance',
                        999
                    ) <= 8
                )
            )

            if (
                has_1h_ob
                or has_near_mtf_ob
            ):
                res.append(d)

        except Exception:
            logger.exception(
                'FULL ANALYSIS FAILED | %s',
                s
            )

    # =====================================================
    # RANKING
    # =====================================================

    def rank(x):

        direction = x.get(
            'direction',
            'WAIT'
        )

        state = x.get(
            'state',
            ''
        )

        ob_retest = (
            x.get(
                'bullish_ob_retest',
                False
            )
            or
            x.get(
                'bearish_ob_retest',
                False
            )
        )

        bos = x.get(
            'bos',
            'NONE'
        )

        return (
            5
            if direction in (
                'LONG',
                'SHORT'
            )
            and ob_retest
            else
            4
            if direction in (
                'LONG',
                'SHORT'
            )
            and bos != 'NONE'
            else
            3
            if 'ENTRY READY' in state
            else
            2
            if 'REVERSAL WATCH' in state
            else
            1
            if 'ACCUMULATION WATCH' in state
            else
            0,

            x.get(
                'entry_score',
                0
            ),

            1
            if ob_retest
            else 0
        )

    res.sort(
        key=rank,
        reverse=True
    )

    return res[:limit]


# =========================================================
# REPORT HELPERS
# =========================================================

def _ob_text(o):
    if not o:
        return 'غير موجود'

    return (
        f"{smart_round(o['low'])}"
        f" - "
        f"{smart_round(o['high'])}"
    )


# =========================================================
# EVIDENCE REPORT
# =========================================================

def generate_evidence_report(d):
    if not d:
        return (
            '⚠️ تعذر إكمال التحليل.\n'
            'لم يتم استلام بيانات صالحة من محرك التحليل.'
        )

    dr = d.get(
        'direction',
        'WAIT'
    )

    emo = (
        '🟢'
        if dr == 'LONG'
        else
        '🔴'
        if dr == 'SHORT'
        else
        '🟡'
    )

    liq = (
        '🟢 دخول سيولة محتمل'
        if d.get(
            'liquidity_state'
        ) == 'INFLOW'
        else
        '🔴 خروج سيولة محتمل'
        if d.get(
            'liquidity_state'
        ) == 'OUTFLOW'
        else
        '🟡 سيولة محايدة'
    )

    bos = (
        '🟢 BULLISH'
        if d.get(
            'bos'
        ) == 'BULLISH_BOS'
        else
        '🔴 BEARISH'
        if d.get(
            'bos'
        ) == 'BEARISH_BOS'
        else
        '⚪ NONE'
    )

    lines = [
        '🤖 BingX AI Scanner\n',

        f"💎 العملة: {d.get('symbol', '-')}",
        f"💰 السعر الحالي: {d.get('price', '-')}",
        f"📈 الاتجاه النهائي: {emo} {dr}",
        f"⭐ Entry Score: {d.get('entry_score', 0)}/100",

        f"\n🧠 الحالة: {d.get('state', '-')}",

        '\n🏦 ORDER BLOCK = المحرك الأساسي',

        f"🟢 Bullish OB 1H: "
        f"{_ob_text(d.get('bullish_ob'))}",

        f"🔴 Bearish OB 1H: "
        f"{_ob_text(d.get('bearish_ob'))}",

        f"📊 Bullish OB 4H: "
        f"{_ob_text(d.get('bullish_ob_4h'))}",

        f"📊 Bearish OB 4H: "
        f"{_ob_text(d.get('bearish_ob_4h'))}",

        f"🔄 Bullish Retest: "
        f"{'YES' if d.get('bullish_ob_retest') else 'NO'}",

        f"🔄 Bearish Retest: "
        f"{'YES' if d.get('bearish_ob_retest') else 'NO'}",

        '\n📊 Context',

        f"1D: {d.get('trend_1d')}",
        f"4H: {d.get('trend_4h')}",

        '\n⏱️ Confirmation',

        f"1H: {d.get('trend_1h')}",
        f"30m: {d.get('trend_30m')}",
        f"15m: {d.get('trend_15m')}",

        '\n🏗️ Structure',

        f"{d.get('structure')} | BOS: {bos}",

        f"\n💧 Liquidity: {liq}",

        f"📊 Volume: "
        f"{d.get('volume_ratio')}x",

        f"📈 Volume Trend: "
        f"{d.get('volume_trend')}",

        f"💪 Buy Pressure: "
        f"{d.get('buy_pressure')}%",

        f"📊 RSI: "
        f"{d.get('rsi')}",

        f"\n🛡️ Support: "
        f"{d.get('support')}",

        f"🔴 Resistance: "
        f"{d.get('resistance')}"
    ]

    # =====================================================
    # TRADE LEVELS
    # =====================================================

    if dr in (
        'LONG',
        'SHORT'
    ):
        lines += [
            '\n📍 منطقة الدخول',

            f"{d.get('entry_min')}"
            f" - "
            f"{d.get('entry_max')}",

            f"\n🛑 Stop Loss: "
            f"{d.get('stop_loss')}",

            f"\n🎯 TP1: "
            f"{d.get('tp1')}",

            f"🎯 TP2: "
            f"{d.get('tp2')}",

            f"🎯 TP3: "
            f"{d.get('tp3')}"
        ]

    else:
        lines += [
            '\n📍 منطقة الدخول',
            '⏳ انتظار Retest / BOS',
            '\n🛑 Stop Loss: غير محدد'
        ]

    # =====================================================
    # REASONS
    # =====================================================

    lines += [
        '\n\n🔍 أسباب القرار'
    ]

    for x in d.get(
        'analysis_lines',
        []
    )[:10]:
        lines.append(
            f'• {x}'
        )

    lines += [
        '\n🛡️ ORDER BLOCK هو العامل الأساسي.',

        '⚠️ 1D = Context | '
        '4H = MTF | '
        '1H = Primary OB | '
        '30m + 15m = Confirmation.',

        '⚠️ الإشارة تحليلية وليست ضماناً للربح.'
    ]

    return '\n'.join(lines)
