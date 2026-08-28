# =========================================================
# analysis.py - BingX Futures AI Scanner v20.0
# =========================================================
# ORDER BLOCK PRIMARY ENGINE
#
# 1D  = Context
# 4H  = MTF Order Block / Context
# 1H  = PRIMARY ORDER BLOCK
# 30m = Confirmation
# 15m = Confirmation
#
# v20 FIXES:
# - Keeps ORDER BLOCK as the primary engine
# - More practical ENTRY logic
# - Does NOT require fresh BOS when OB retest/rejection exists
# - Does NOT allow ENTRY when price is far from the OB
# - 4H trend is contextual, not an absolute blocker
# - 30m/15m confirmation is flexible
# - RSI is a quality filter, not a hard entry blocker
# - Prevents chasing extreme moves
# - Keeps WAIT for valid OB setups that need confirmation
# - Keeps NO TRADE when there is no valid OB
# - Better OB proximity and ranking
# - Robust BingX price + kline handling
# =========================================================

import time
import logging
import threading
import requests


# =========================================================
# CONFIG
# =========================================================

BINGX_URL = "https://open-api.bingx.com"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "CryptoZeroReversal-BingX-OB-Scanner/20.0",
    "Accept": "application/json",
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

# v20: faster than v18 while still protecting BingX
MIN_REQUEST_INTERVAL = 0.45


# =========================================================
# BINGX REQUEST
# =========================================================

def bingx_get(path, params=None, timeout=12):
    global _RATE_LIMIT_UNTIL
    global _LAST_REQUEST_TIME

    with _RATE_LOCK:
        if time.time() < _RATE_LIMIT_UNTIL:
            return None

    with _REQUEST_LOCK:
        wait = MIN_REQUEST_INTERVAL - (
            time.time() - _LAST_REQUEST_TIME
        )

        if wait > 0:
            time.sleep(wait)

        _LAST_REQUEST_TIME = time.time()

    try:
        r = SESSION.get(
            BINGX_URL + path,
            params=params or {},
            timeout=timeout,
        )

        if r.status_code != 200:
            logger.warning(
                "BingX HTTP %s | %s",
                r.status_code,
                path,
            )
            return None

        d = r.json()

        if not isinstance(d, dict):
            return None

        code = d.get("code")

        if code in (109429, 109400):
            with _RATE_LOCK:
                _RATE_LIMIT_UNTIL = max(
                    _RATE_LIMIT_UNTIL,
                    time.time() + 60,
                )
            logger.warning(
                "BingX RATE LIMIT | code=%s",
                code,
            )
            return None

        if code not in (0, None):
            logger.warning(
                "BingX API ERROR code=%s | %s",
                code,
                path,
            )
            return None

        return d

    except Exception as e:
        logger.warning(
            "BingX REQUEST FAILED | %s | %s",
            path,
            e,
        )
        return None


# =========================================================
# SYMBOL HELPERS
# =========================================================

def normalize_symbol(s):
    s = str(s).strip().upper()
    s = s.replace(" ", "")
    s = s.replace("-", "")
    s = s.replace("_", "")
    s = s.replace("/", "")

    if s.endswith(("USDT", "USDC")):
        return s

    return s + "USDT"


def bingx_symbol(s):
    s = normalize_symbol(s)
    return s[:-4] + "-" + s[-4:]


def _rows(d):
    if not isinstance(d, dict):
        return []

    x = d.get("data")

    if isinstance(x, list):
        return x

    if isinstance(x, dict):
        return [x]

    return []


def _is_crypto_usdt_symbol(s):
    s = str(s).upper().replace("-", "")

    if not s.endswith("USDT"):
        return False

    base = s[:-4]

    blocked = (
        "SP500",
        "NASDAQ",
        "DJI",
        "US30",
        "DXY",
        "GOLD",
        "SILVER",
        "XAU",
        "XAG",
        "OIL",
        "BRENT",
        "WTI",
        "COPPER",
        "PLATINUM",
        "PALLADIUM",
    )

    if base.endswith("USD"):
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

    now = time.time()

    if (
        not force_refresh
        and _SYMBOL_CACHE
        and now - _SYMBOL_CACHE_TIME < SYMBOL_CACHE_SECONDS
    ):
        return set(_SYMBOL_CACHE)

    d = bingx_get(
        "/openApi/swap/v2/quote/contracts"
    )

    out = set()

    for x in _rows(d):
        if not isinstance(x, dict):
            continue

        s = str(
            x.get("symbol", "")
        ).replace("-", "").upper()

        status = x.get("status")

        if (
            _is_crypto_usdt_symbol(s)
            and status in (1, "1", None)
        ):
            out.add(s)

    if out:
        _SYMBOL_CACHE = out
        _SYMBOL_CACHE_TIME = now

    return set(_SYMBOL_CACHE)


def symbol_exists(s):
    s = normalize_symbol(s)
    sy = get_futures_symbols()

    # If BingX failed to return contracts,
    # don't block analysis unnecessarily.
    return not sy or s in sy


# =========================================================
# PRICE
# =========================================================

def _price_row(x):
    if not isinstance(x, dict):
        return None

    for k in (
        "price",
        "lastPrice",
        "last",
        "close",
        "markPrice",
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

    now = time.time()

    if (
        not force
        and _TICKER_CACHE is not None
        and now - _TICKER_CACHE_TIME < TICKER_CACHE_SECONDS
    ):
        return _TICKER_CACHE

    x = _rows(
        bingx_get(
            "/openApi/swap/v2/quote/ticker"
        )
    )

    if x:
        _TICKER_CACHE = x
        _TICKER_CACHE_TIME = now

    return x


def get_current_price(s, force=False):
    s = normalize_symbol(s)

    now = time.time()

    cached = _PRICE_CACHE.get(s)

    if (
        not force
        and cached
        and now - cached[0] < PRICE_CACHE_SECONDS
    ):
        return cached[1]

    # -----------------------------------------------------
    # TICKER
    # -----------------------------------------------------

    for x in _ticker_rows(force):
        if not isinstance(x, dict):
            continue

        xs = str(
            x.get("symbol", "")
        ).replace("-", "").upper()

        if xs != s:
            continue

        p = _price_row(x)

        if p:
            _PRICE_CACHE[s] = (now, p)
            return p

    # -----------------------------------------------------
    # DIRECT PRICE ENDPOINTS
    # -----------------------------------------------------

    endpoints = (
        "/openApi/swap/v2/quote/price",
        "/openApi/swap/v1/ticker/price",
        "/openApi/swap/v3/quote/price",
    )

    for ep in endpoints:
        rows = _rows(
            bingx_get(
                ep,
                {"symbol": bingx_symbol(s)},
            )
        )

        for x in rows:
            p = _price_row(x)

            if p:
                _PRICE_CACHE[s] = (now, p)
                return p

    # -----------------------------------------------------
    # LAST KLINE FALLBACK
    # -----------------------------------------------------

    k = get_bingx_klines(
        s,
        "1h",
        60,
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
# KLINES
# =========================================================

def _parse(rows):
    out = []

    for x in rows:
        try:
            if isinstance(x, dict):
                t = (
                    x.get("time")
                    or x.get("timestamp")
                    or x.get("openTime")
                    or 0
                )

                o = x.get("open")
                h = x.get("high")
                l = x.get("low")
                c = x.get("close")

                v = x.get(
                    "volume",
                    x.get("vol", 0),
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
                float(v or 0),
            ])

        except Exception:
            pass

    try:
        out.sort(
            key=lambda z: z[0]
        )
    except Exception:
        pass

    return out


def get_bingx_klines(
    s,
    interval="1h",
    limit=200,
):
    s = normalize_symbol(s)

    key = (
        s,
        interval,
        int(limit),
    )

    now = time.time()

    cached = _KLINE_CACHE.get(key)

    if (
        cached
        and now - cached[0] < KLINE_CACHE_SECONDS
    ):
        return cached[1]

    params = {
        "symbol": bingx_symbol(s),
        "interval": str(interval).lower(),
        "limit": int(limit),
    }

    best = []

    endpoints = (
        "/openApi/swap/v3/quote/klines",
        "/openApi/swap/v2/quote/klines",
    )

    for ep in endpoints:
        r = _parse(
            _rows(
                bingx_get(ep, params)
            )
        )

        if len(r) > len(best):
            best = r

        if len(r) >= 30:
            _KLINE_CACHE[key] = (
                now,
                r,
            )
            return r

    if best:
        _KLINE_CACHE[key] = (
            now,
            best,
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

    gains = []
    losses = []

    for i in range(1, len(c)):
        change = c[i] - c[i - 1]

        gains.append(
            max(change, 0)
        )

        losses.append(
            max(-change, 0)
        )

    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        ag = (
            ag * (period - 1)
            + gains[i]
        ) / period

        al = (
            al * (period - 1)
            + losses[i]
        ) / period

    if al == 0:
        return 100.0

    return round(
        100 - 100 / (1 + ag / al),
        2,
    )


def calculate_atr(k, n=14):
    if len(k) < n + 1:
        return None

    tr = []

    for i, x in enumerate(k[1:], 1):
        value = max(
            x[2] - x[3],
            abs(x[2] - k[i - 1][4]),
            abs(x[3] - k[i - 1][4]),
        )

        tr.append(value)

    a = sum(tr[:n]) / n

    for x in tr[n:]:
        a = (
            a * (n - 1)
            + x
        ) / n

    return a


def calculate_volume_ratio(v, n=20):
    if len(v) < n + 4:
        return 1.0

    recent = sum(
        v[-4:-1]
    ) / 3

    previous = sum(
        v[-n-4:-4]
    ) / n

    if previous <= 0:
        return 1.0

    return round(
        max(
            0.05,
            min(
                5,
                recent / previous,
            ),
        ),
        2,
    )


def calculate_volume_trend(
    v,
    short_period=5,
    long_period=20,
):
    if (
        len(v)
        < long_period + short_period + 1
    ):
        return "NEUTRAL"

    recent = sum(
        v[-short_period-1:-1]
    ) / short_period

    previous = sum(
        v[
            -long_period-short_period-1:
            -short_period-1
        ]
    ) / long_period

    if previous <= 0:
        return "NEUTRAL"

    ratio = recent / previous

    if ratio >= 1.10:
        return "RISING"

    if ratio <= 0.90:
        return "FALLING"

    return "NEUTRAL"


def percentage_change(a, b):
    if not a:
        return 0

    return (
        (b - a) / a
    ) * 100


# =========================================================
# SUPPORT / RESISTANCE
# =========================================================

def calculate_support_resistance(k):
    if not k:
        return 0, 0

    p = k[-1][4]

    recent = k[-80:]

    highs = [
        x[2]
        for x in recent
    ]

    lows = [
        x[3]
        for x in recent
    ]

    supports = [
        x for x in lows
        if x < p
    ]

    resistances = [
        x for x in highs
        if x > p
    ]

    support = (
        max(supports)
        if supports
        else min(lows)
    )

    resistance = (
        min(resistances)
        if resistances
        else max(highs)
    )

    return support, resistance


def _dir(k):
    if k[4] > k[1]:
        return "BULLISH"

    if k[4] < k[1]:
        return "BEARISH"

    return "NEUTRAL"


# =========================================================
# ORDER BLOCK ENGINE
# =========================================================

def detect_order_blocks(
    k,
    lookback=120,
):
    """
    PRIMARY ORDER BLOCK ENGINE

    Pattern:
    Opposite candle
        +
    Strong displacement candle
        +
    Local BOS / liquidity break

    The OB itself remains the primary signal.
    """

    if len(k) < 30:
        return {
            "bullish": [],
            "bearish": [],
        }

    bull = []
    bear = []

    start = max(
        5,
        len(k) - lookback,
    )

    for i in range(
        start,
        len(k) - 2,
    ):
        base = k[i]
        displacement = k[i + 1]

        rng = max(
            displacement[2]
            - displacement[3],
            1e-12,
        )

        body = abs(
            displacement[4]
            - displacement[1]
        )

        body_ratio = body / rng

        # v20:
        # Slightly easier displacement requirement.
        if body_ratio < 0.40:
            continue

        left = k[
            max(0, i - 12):i
        ]

        if not left:
            continue

        previous_high = max(
            x[2] for x in left
        )

        previous_low = min(
            x[3] for x in left
        )

        bull_bos = (
            displacement[4] > previous_high
            or (
                displacement[2] > previous_high
                and displacement[4]
                >= displacement[1]
            )
        )

        bear_bos = (
            displacement[4] < previous_low
            or (
                displacement[3] < previous_low
                and displacement[4]
                <= displacement[1]
            )
        )

        move_pct = percentage_change(
            displacement[1],
            displacement[4],
        )

        # -------------------------------------------------
        # BULLISH OB
        # -------------------------------------------------

        if (
            _dir(base) == "BEARISH"
            and _dir(displacement) == "BULLISH"
            and bull_bos
        ):
            lo, hi = sorted(
                (
                    base[1],
                    base[4],
                )
            )

            strength = min(
                100,
                42
                + body_ratio * 35
                + min(
                    max(move_pct, 0),
                    6,
                ) * 4,
            )

            bull.append({
                "type": "BULLISH",
                "index": i,
                "low": lo,
                "high": hi,
                "mid": (lo + hi) / 2,
                "strength": round(
                    strength,
                    1,
                ),
            })

        # -------------------------------------------------
        # BEARISH OB
        # -------------------------------------------------

        if (
            _dir(base) == "BULLISH"
            and _dir(displacement) == "BEARISH"
            and bear_bos
        ):
            lo, hi = sorted(
                (
                    base[1],
                    base[4],
                )
            )

            strength = min(
                100,
                42
                + body_ratio * 35
                + min(
                    max(-move_pct, 0),
                    6,
                ) * 4,
            )

            bear.append({
                "type": "BEARISH",
                "index": i,
                "low": lo,
                "high": hi,
                "mid": (lo + hi) / 2,
                "strength": round(
                    strength,
                    1,
                ),
            })

    bull.sort(
        key=lambda x: (
            x["index"],
            x["strength"],
        ),
        reverse=True,
    )

    bear.sort(
        key=lambda x: (
            x["index"],
            x["strength"],
        ),
        reverse=True,
    )

    return {
        "bullish": bull[:15],
        "bearish": bear[:15],
    }


# =========================================================
# OB PROXIMITY
# =========================================================

def price_inside_ob(
    p,
    o,
    tolerance=0.008,
):
    if not o:
        return False

    width = max(
        o["high"] - o["low"],
        0,
    )

    tolerance_price = max(
        width * tolerance,
        0,
    )

    return (
        o["low"] - tolerance_price
        <= p
        <= o["high"] + tolerance_price
    )


def ob_distance_percent(p, o):
    if not o or p <= 0:
        return 999

    if price_inside_ob(p, o):
        return 0

    if p < o["low"]:
        return (
            (o["low"] - p)
            / p
            * 100
        )

    return (
        (p - o["high"])
        / p
        * 100
    )


def ob_position(p, o):
    """
    Returns:
        INSIDE
        BELOW
        ABOVE
    """

    if not o:
        return "NONE"

    if price_inside_ob(p, o):
        return "INSIDE"

    if p < o["low"]:
        return "BELOW"

    return "ABOVE"


# =========================================================
# OB VALIDATION
# =========================================================

def _ob_valid(k, o, direction):
    if not o:
        return False

    start = o["index"] + 2

    for x in k[start:]:
        close = x[4]

        # Bullish OB is invalidated only by
        # a meaningful candle close below it.
        if (
            direction == "LONG"
            and close
            < o["low"] * 0.998
        ):
            return False

        # Bearish OB invalidated only by
        # meaningful close above it.
        if (
            direction == "SHORT"
            and close
            > o["high"] * 1.002
        ):
            return False

    return True


# =========================================================
# ACTIVE OB
# =========================================================

def find_active_order_block(
    k,
    direction,
    p,
):
    obs = detect_order_blocks(k)

    candidates = obs[
        "bullish"
        if direction == "LONG"
        else "bearish"
    ]

    best = None

    for o in candidates:

        if not _ob_valid(
            k,
            o,
            direction,
        ):
            continue

        dist = ob_distance_percent(
            p,
            o,
        )

        # v20:
        # Keep maximum practical OB search
        # at 8% instead of 6%.
        if dist > 8:
            continue

        age = len(k) - o["index"]

        if age <= 12:
            recency = 16
        elif age <= 30:
            recency = 11
        elif age <= 55:
            recency = 6
        else:
            recency = 2

        proximity = max(
            0,
            28 - dist * 3.2,
        )

        inside_bonus = (
            18
            if price_inside_ob(p, o)
            else 0
        )

        score = (
            o["strength"]
            + recency
            + proximity
            + inside_bonus
        )

        if (
            best is None
            or score > best[0]
        ):
            best = (
                score,
                o,
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
    direction,
):
    if not o:
        return False, []

    touched = False
    rejected = False

    reasons = []

    start = max(
        o["index"] + 2,
        len(k) - 25,
    )

    for x in k[start:]:

        low = x[3]
        high = x[2]
        close = x[4]

        if (
            low <= o["high"]
            and high >= o["low"]
        ):
            touched = True

            if (
                direction == "LONG"
                and close >= o["mid"]
            ):
                rejected = True

            if (
                direction == "SHORT"
                and close <= o["mid"]
            ):
                rejected = True

    if touched:
        reasons.append(
            "السعر أعاد اختبار Order Block"
        )

    if rejected:
        reasons.append(
            "ظهر رفض من منطقة Order Block"
        )

    return (
        touched and rejected,
        reasons,
    )


# =========================================================
# MARKET STRUCTURE
# =========================================================

def detect_market_structure(k):
    if len(k) < 25:
        return {
            "structure": "UNKNOWN",
            "bos": "NONE",
            "liquidity_zone": "NONE",
            "reasons": [],
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

    bos = "NONE"
    structure = "MIXED"
    reasons = []

    if (
        c > rh
        and prev <= rh
    ):
        bos = "BULLISH_BOS"
        structure = "BULLISH"
        reasons.append(
            "BOS صاعد مؤكد"
        )

    elif (
        c < rl
        and prev >= rl
    ):
        bos = "BEARISH_BOS"
        structure = "BEARISH"
        reasons.append(
            "BOS هابط مؤكد"
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

        if c >= hh * 0.997:
            structure = "BULLISH"

        elif c <= ll * 1.003:
            structure = "BEARISH"

        else:
            structure = "MIXED"

        reasons.append(
            "لا يوجد BOS جديد مؤكد"
        )

    hh = max(
        x[2]
        for x in k[-10:]
    )

    ll = min(
        x[3]
        for x in k[-10:]
    )

    low_distance = (
        abs(c - ll)
        / c
        * 100
    )

    high_distance = (
        abs(hh - c)
        / c
        * 100
    )

    if low_distance <= 0.8:
        zone = "LOW_LIQUIDITY"

    elif high_distance <= 0.8:
        zone = "HIGH_LIQUIDITY"

    else:
        zone = "NONE"

    return {
        "structure": structure,
        "bos": bos,
        "liquidity_zone": zone,
        "reasons": reasons,
    }


# =========================================================
# LIQUIDITY
# =========================================================

def detect_liquidity_flow(k):
    if len(k) < 25:
        return (
            "NEUTRAL",
            0,
            [],
        )

    r = k[:-1]

    recent = r[-15:]

    bullish_volume = sum(
        x[5]
        for x in recent
        if x[4] > x[1]
    )

    bearish_volume = sum(
        x[5]
        for x in recent
        if x[4] < x[1]
    )

    total = (
        bullish_volume
        + bearish_volume
    )

    share = (
        bullish_volume / total
        if total
        else 0.5
    )

    vr = calculate_volume_ratio(
        [x[5] for x in r]
    )

    rc = percentage_change(
        r[-6][4],
        r[-1][4],
    )

    recent_volume = sum(
        x[5]
        for x in r[-5:]
    ) / 5

    previous_volume = sum(
        x[5]
        for x in r[-15:-5]
    ) / 10

    score = 0
    reasons = []

    if (
        share >= 0.55
        and vr >= 0.85
    ):
        score += 2
        reasons.append(
            "ضغط الشراء أعلى من البيع"
        )

    if (
        recent_volume
        > previous_volume * 1.05
        and rc >= -2.5
    ):
        score += 1
        reasons.append(
            "الحجم يتحسن مع استقرار السعر"
        )

    if (
        share <= 0.45
        and vr >= 0.85
    ):
        score -= 2
        reasons.append(
            "ضغط البيع أعلى من الشراء"
        )

    if (
        recent_volume
        > previous_volume * 1.05
        and rc <= -2.5
    ):
        score -= 1
        reasons.append(
            "ارتفاع الحجم مع ضغط بيعي"
        )

    if score >= 2:
        return (
            "INFLOW",
            score,
            reasons,
        )

    if score <= -2:
        return (
            "OUTFLOW",
            score,
            reasons,
        )

    return (
        "NEUTRAL",
        score,
        reasons,
    )


# =========================================================
# TIMEFRAME TREND
# =========================================================

def calculate_timeframe_trend(k):
    if not k:
        return "UNKNOWN"

    c = [
        x[4]
        for x in k
    ]

    ema9 = calculate_ema(c, 9)
    ema20 = calculate_ema(c, 20)
    ema50 = calculate_ema(c, 50)

    if None in (
        ema9,
        ema20,
        ema50,
    ):
        return "UNKNOWN"

    if (
        ema9 > ema20 > ema50
        and c[-1] > ema20
    ):
        return "LONG"

    if (
        ema9 < ema20 < ema50
        and c[-1] < ema20
    ):
        return "SHORT"

    return "NEUTRAL"


# =========================================================
# BOTTOM / ACCUMULATION
# =========================================================

def detect_bottom_accumulation(k):
    if len(k) < 40:
        return (
            False,
            0,
            [],
        )

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
        len(c) // 2,
    )

    old = c[
        -2 * n:-n
    ]

    recent = c[-n:]

    if not old or not recent:
        return (
            False,
            0,
            [],
        )

    drawdown = (
        (
            min(recent)
            - max(old)
        )
        / max(old)
        * 100
    )

    recent_range = (
        (
            max(recent)
            - min(recent)
        )
        / min(recent)
        * 100
    )

    old_volume = (
        sum(v[-2 * n:-n])
        / len(old)
        if old
        else 0
    )

    recent_volume = (
        sum(v[-10:]) / 10
    )

    score = 0

    if drawdown <= -4:
        score += 1

    if recent_range <= 20:
        score += 1

    if (
        old_volume > 0
        and recent_volume
        >= old_volume * 0.65
    ):
        score += 1

    reasons = []

    if drawdown <= -4:
        reasons.append(
            "هبوط سابق واضح"
        )

    if recent_range <= 20:
        reasons.append(
            "النطاق السعري بدأ يضيق"
        )

    if score >= 2:
        reasons.append(
            "الحجم ما زال موجوداً بعد الهبوط"
        )

    return (
        score >= 2,
        score,
        reasons,
    )


# =========================================================
# ROUND
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

    if v >= 0.1:
        return round(v, 5)

    if v >= 0.01:
        return round(v, 6)

    return round(v, 8)


# =========================================================
# EXTREME MOVE FILTER
# =========================================================

def detect_extreme_move(c):
    if len(c) < 8:
        return (
            False,
            False,
        )

    ch2 = percentage_change(
        c[-3],
        c[-1],
    )

    ch6 = percentage_change(
        c[-7],
        c[-1],
    )

    crash = (
        ch2 <= -8
        or ch6 <= -15
    )

    pump = (
        ch2 >= 8
        or ch6 >= 15
    )

    return crash, pump


# =========================================================
# MTF CONFIRMATION
# =========================================================

def mtf_confirmation(
    direction,
    t4,
    t1,
    t30,
    t15,
):
    """
    v20:
    No need for all TFs to agree.

    Strong:
        3+ aligned

    Good:
        2 aligned + no strong opposite

    Weak:
        1 aligned

    Block:
        2+ strong opposite
    """

    trends = [
        t4,
        t1,
        t30,
        t15,
    ]

    aligned = sum(
        1
        for x in trends
        if x == direction
    )

    opposite = (
        "SHORT"
        if direction == "LONG"
        else "LONG"
    )

    opposing = sum(
        1
        for x in trends
        if x == opposite
    )

    if opposing >= 3:
        return (
            "BLOCK",
            aligned,
            opposing,
        )

    if aligned >= 3:
        return (
            "STRONG",
            aligned,
            opposing,
        )

    if aligned >= 2:
        return (
            "GOOD",
            aligned,
            opposing,
        )

    if aligned == 1:
        return (
            "WEAK",
            aligned,
            opposing,
        )

    return (
        "NONE",
        aligned,
        opposing,
    )


# =========================================================
# ENTRY QUALITY
# =========================================================

def evaluate_entry_quality(
    direction,
    p,
    ob,
    ob_retest,
    ob_strength,
    t4,
    t1,
    t30,
    t15,
    bos,
    liquidity,
    volume_ratio,
    rsi,
    resistance_distance,
    support_distance,
    crash,
    pump,
):
    """
    Returns:

        score
        ready
        confirmation
        reasons
    """

    if not ob:
        return (
            0,
            False,
            "NONE",
            [],
        )

    score = 0
    reasons = []

    # -----------------------------------------------------
    # PRIMARY OB
    # -----------------------------------------------------

    score += 35
    reasons.append(
        "يوجد Order Block أساسي صالح على 1H"
    )

    if ob_strength >= 55:
        score += 8
        reasons.append(
            "قوة Order Block جيدة"
        )

    elif ob_strength >= 48:
        score += 5
        reasons.append(
            "قوة Order Block مقبولة"
        )

    # -----------------------------------------------------
    # PRICE LOCATION
    # -----------------------------------------------------

    position = ob_position(
        p,
        ob,
    )

    dist = ob_distance_percent(
        p,
        ob,
    )

    if position == "INSIDE":
        score += 22
        reasons.append(
            "السعر داخل منطقة Order Block"
        )

    elif dist <= 0.8:
        score += 18
        reasons.append(
            "السعر قريب جداً من Order Block"
        )

    elif dist <= 1.5:
        score += 12
        reasons.append(
            "السعر قريب من Order Block"
        )

    elif dist <= 3:
        score += 5

    else:
        # Important:
        # Existing OB but far price = WATCH,
        # not direct entry.
        score -= 8
        reasons.append(
            "السعر بعيد نسبياً عن Order Block"
        )

    # -----------------------------------------------------
    # RETEST
    # -----------------------------------------------------

    if ob_retest:
        score += 20
        reasons.append(
            "Order Block حصل له Retest + Rejection"
        )

    # -----------------------------------------------------
    # BOS
    # -----------------------------------------------------

    if direction == "LONG":
        if bos == "BULLISH_BOS":
            score += 10
            reasons.append(
                "BOS صاعد يؤكد Bullish OB"
            )

        elif bos == "BEARISH_BOS":
            score -= 6

    else:
        if bos == "BEARISH_BOS":
            score += 10
            reasons.append(
                "BOS هابط يؤكد Bearish OB"
            )

        elif bos == "BULLISH_BOS":
            score -= 6

    # -----------------------------------------------------
    # MTF
    # -----------------------------------------------------

    confirmation, aligned, opposing = (
        mtf_confirmation(
            direction,
            t4,
            t1,
            t30,
            t15,
        )
    )

    if confirmation == "STRONG":
        score += 14
        reasons.append(
            "تأكيد MTF قوي"
        )

    elif confirmation == "GOOD":
        score += 9
        reasons.append(
            "تأكيد MTF جيد"
        )

    elif confirmation == "WEAK":
        score += 3

    elif confirmation == "BLOCK":
        score -= 12
        reasons.append(
            "تعارض قوي في الفريمات"
        )

    # -----------------------------------------------------
    # LIQUIDITY
    # -----------------------------------------------------

    if (
        direction == "LONG"
        and liquidity == "INFLOW"
    ):
        score += 7
        reasons.append(
            "السيولة تميل للشراء"
        )

    elif (
        direction == "SHORT"
        and liquidity == "OUTFLOW"
    ):
        score += 7
        reasons.append(
            "السيولة تميل للبيع"
        )

    elif (
        direction == "LONG"
        and liquidity == "OUTFLOW"
    ):
        score -= 5

    elif (
        direction == "SHORT"
        and liquidity == "INFLOW"
    ):
        score -= 5

    # -----------------------------------------------------
    # VOLUME
    # -----------------------------------------------------

    if volume_ratio >= 1.15:
        score += 5
        reasons.append(
            "الحجم يدعم الحركة"
        )

    elif volume_ratio >= 1.0:
        score += 2

    # -----------------------------------------------------
    # RSI
    # -----------------------------------------------------

    # RSI is NOT a hard blocker anymore.

    if direction == "LONG":

        if 42 <= rsi <= 70:
            score += 4
            reasons.append(
                "RSI مناسب للشراء"
            )

        elif 30 <= rsi < 42:
            score += 2

        elif rsi > 78:
            score -= 5
            reasons.append(
                "RSI مرتفع؛ الحذر من مطاردة السعر"
            )

    else:

        if 30 <= rsi <= 62:
            score += 4
            reasons.append(
                "RSI مناسب للبيع"
            )

        elif 62 < rsi <= 72:
            score += 2

        elif rsi < 22:
            score -= 5
            reasons.append(
                "RSI منخفض جداً؛ الحذر من مطاردة الهبوط"
            )

    # -----------------------------------------------------
    # EXTREME MOVE
    # -----------------------------------------------------

    if crash:
        score -= 12
        reasons.append(
            "هبوط سريع؛ لا نطارد السعر"
        )

    if pump:
        score -= 10
        reasons.append(
            "صعود سريع؛ لا نطارد السعر"
        )

    # -----------------------------------------------------
    # SUPPORT / RESISTANCE
    # -----------------------------------------------------

    if direction == "LONG":
        if resistance_distance <= 0.15:
            score -= 12
            reasons.append(
                "السعر قريب جداً من المقاومة"
            )
        elif resistance_distance <= 0.30:
            score -= 5

    else:
        if support_distance <= 0.15:
            score -= 12
            reasons.append(
                "السعر قريب جداً من الدعم"
            )
        elif support_distance <= 0.30:
            score -= 5

    score = int(
        max(
            0,
            min(
                100,
                score,
            ),
        )
    )

    # -----------------------------------------------------
    # v20 ENTRY GATE
    # -----------------------------------------------------

    # OB must be reasonably close.
    near_ob = dist <= 1.5

    inside_ob = position == "INSIDE"

    # Retest is strong enough to compensate for
    # absence of a fresh BOS.
    retest_confirmation = ob_retest

    # MTF confirmation.
    mtf_ok = (
        confirmation
        in (
            "STRONG",
            "GOOD",
        )
    )

    # One of the following must exist:
    # 1. OB retest
    # 2. fresh BOS
    # 3. price inside OB + good MTF
    confirmation_ok = (
        retest_confirmation
        or (
            direction == "LONG"
            and bos == "BULLISH_BOS"
        )
        or (
            direction == "SHORT"
            and bos == "BEARISH_BOS"
        )
        or (
            inside_ob
            and mtf_ok
        )
    )

    # Price must be close to the OB.
    proximity_ok = (
        near_ob
        or inside_ob
    )

    # Strong opposite MTF blocks.
    no_mtf_block = (
        confirmation != "BLOCK"
    )

    # Don't enter during a confirmed crash.
    no_crash = not crash

    # v20:
    # Lower threshold than v18.
    #
    # But threshold alone is not enough.
    ready = (
        score >= 62
        and proximity_ok
        and confirmation_ok
        and no_mtf_block
        and no_crash
    )

    return (
        score,
        ready,
        confirmation,
        reasons,
    )


# =========================================================
# COIN ANALYSIS
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
        "1h",
        200,
    )

    p = get_current_price(
        symbol,
        True,
    )

    if p is None and k1:
        try:
            p = float(
                k1[-1][4]
            )
        except Exception:
            p = None

    if p is None:
        return None

    if (
        not k1
        or len(k1) < 30
    ):
        return {
            "symbol": symbol,
            "direction": "NO TRADE",
            "score": 0,
            "entry_score": 0,
            "state": (
                "NO TRADE - "
                "بيانات 1H غير مكتملة"
            ),
            "price": smart_round(p),
        }

    # -----------------------------------------------------
    # MTF
    # -----------------------------------------------------

    k4 = get_bingx_klines(
        symbol,
        "4h",
        160,
    )

    kd = get_bingx_klines(
        symbol,
        "1d",
        120,
    )

    k30 = get_bingx_klines(
        symbol,
        "30m",
        160,
    )

    k15 = get_bingx_klines(
        symbol,
        "15m",
        160,
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
    # INDICATORS
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
        or p * 0.01
    )

    vr = calculate_volume_ratio(v)

    vt = calculate_volume_trend(v)

    sup, res = (
        calculate_support_resistance(k1)
    )

    # -----------------------------------------------------
    # STRUCTURE
    # -----------------------------------------------------

    st = detect_market_structure(k1)

    liq, liq_score, liq_reasons = (
        detect_liquidity_flow(k1)
    )

    bottom, bottom_score, bottom_reasons = (
        detect_bottom_accumulation(k1)
    )

    # -----------------------------------------------------
    # PRIMARY 1H OB
    # -----------------------------------------------------

    bullish_ob = find_active_order_block(
        k1,
        "LONG",
        p,
    )

    bearish_ob = find_active_order_block(
        k1,
        "SHORT",
        p,
    )

    # -----------------------------------------------------
    # MTF 4H OB
    # -----------------------------------------------------

    bullish_ob_4h = (
        find_active_order_block(
            k4,
            "LONG",
            p,
        )
        if k4
        else None
    )

    bearish_ob_4h = (
        find_active_order_block(
            k4,
            "SHORT",
            p,
        )
        if k4
        else None
    )

    # -----------------------------------------------------
    # RETEST
    # -----------------------------------------------------

    bullish_retest, bullish_retest_reasons = (
        detect_ob_retest(
            k1,
            bullish_ob,
            "LONG",
        )
    )

    bearish_retest, bearish_retest_reasons = (
        detect_ob_retest(
            k1,
            bearish_ob,
            "SHORT",
        )
    )

    bullish_distance = (
        ob_distance_percent(
            p,
            bullish_ob,
        )
        if bullish_ob
        else 999
    )

    bearish_distance = (
        ob_distance_percent(
            p,
            bearish_ob,
        )
        if bearish_ob
        else 999
    )

    # -----------------------------------------------------
    # CHANGE / EXTREME
    # -----------------------------------------------------

    ch2 = percentage_change(
        c[-3],
        p,
    )

    ch6 = percentage_change(
        c[-7],
        p,
    )

    crash, pump = detect_extreme_move(c)

    # -----------------------------------------------------
    # EVALUATE BOTH SIDES
    # -----------------------------------------------------

    long_score = 0
    long_ready = False
    long_confirmation = "NONE"
    long_reasons = []

    short_score = 0
    short_ready = False
    short_confirmation = "NONE"
    short_reasons = []

    # -----------------------------------------------------
    # LONG
    # -----------------------------------------------------

    if bullish_ob:

        (
            long_score,
            long_ready,
            long_confirmation,
            long_reasons,
        ) = evaluate_entry_quality(
            "LONG",
            p,
            bullish_ob,
            bullish_retest,
            bullish_ob["strength"],
            t4,
            t1,
            t30,
            t15,
            st["bos"],
            liq,
            vr,
            rsi,
            abs(res - p) / p * 100,
            abs(p - sup) / p * 100,
            crash,
            pump,
        )

    # -----------------------------------------------------
    # SHORT
    # -----------------------------------------------------

    if bearish_ob:

        (
            short_score,
            short_ready,
            short_confirmation,
            short_reasons,
        ) = evaluate_entry_quality(
            "SHORT",
            p,
            bearish_ob,
            bearish_retest,
            bearish_ob["strength"],
            t4,
            t1,
            t30,
            t15,
            st["bos"],
            liq,
            vr,
            rsi,
            abs(res - p) / p * 100,
            abs(p - sup) / p * 100,
            crash,
            pump,
        )

    # -----------------------------------------------------
    # PICK PRIMARY SIDE
    # -----------------------------------------------------

    direction = "NO TRADE"
    state = "NO TRADE"
    es = max(
        long_score,
        short_score,
    )

    analysis_lines = []

    # -----------------------------------------------------
    # BOTH SIDES
    # -----------------------------------------------------

    if (
        long_ready
        and short_ready
    ):
        # Prefer stronger score.
        if long_score >= short_score + 5:
            direction = "LONG"
            es = long_score
            state = (
                "ENTRY READY - "
                "Bullish Order Block + Confirmation"
            )
            analysis_lines = long_reasons

        elif short_score >= long_score + 5:
            direction = "SHORT"
            es = short_score
            state = (
                "ENTRY READY - "
                "Bearish Order Block + Confirmation"
            )
            analysis_lines = short_reasons

        else:
            direction = "WAIT"
            es = max(
                long_score,
                short_score,
            )
            state = (
                "WAIT - "
                "Bullish/Bearish OB conflict"
            )
            analysis_lines = (
                long_reasons[:4]
                + short_reasons[:4]
            )

    # -----------------------------------------------------
    # LONG READY
    # -----------------------------------------------------

    elif long_ready:

        direction = "LONG"
        es = long_score

        state = (
            "ENTRY READY - "
            "Bullish Order Block + Confirmation"
        )

        analysis_lines = long_reasons

    # -----------------------------------------------------
    # SHORT READY
    # -----------------------------------------------------

    elif short_ready:

        direction = "SHORT"
        es = short_score

        state = (
            "ENTRY READY - "
            "Bearish Order Block + Confirmation"
        )

        analysis_lines = short_reasons

    # -----------------------------------------------------
    # LONG WATCH
    # -----------------------------------------------------

    elif (
        bullish_ob
        and long_score >= 48
        and bullish_distance <= 8
        and not crash
    ):

        direction = "WAIT"
        es = long_score

        if bullish_distance <= 1.5:
            state = (
                "REVERSAL WATCH - "
                "Bullish OB قريب وننتظر التأكيد"
            )
        else:
            state = (
                "REVERSAL WATCH - "
                "Bullish OB موجود وننتظر Retest"
            )

        analysis_lines = long_reasons

    # -----------------------------------------------------
    # SHORT WATCH
    # -----------------------------------------------------

    elif (
        bearish_ob
        and short_score >= 48
        and bearish_distance <= 8
        and not crash
    ):

        direction = "WAIT"
        es = short_score

        if bearish_distance <= 1.5:
            state = (
                "REVERSAL WATCH - "
                "Bearish OB قريب وننتظر التأكيد"
            )
        else:
            state = (
                "REVERSAL WATCH - "
                "Bearish OB موجود وننتظر Retest"
            )

        analysis_lines = short_reasons

    # -----------------------------------------------------
    # ACCUMULATION WATCH
    # -----------------------------------------------------

    elif bottom and (
        bullish_ob_4h
        or bearish_ob_4h
    ):

        mtf_ob = (
            bullish_ob_4h
            if bullish_ob_4h
            else bearish_ob_4h
        )

        mtf_distance = ob_distance_percent(
            p,
            mtf_ob,
        )

        if mtf_distance <= 8:

            direction = "WAIT"
            es = max(
                es,
                45,
            )

            state = (
                "ACCUMULATION WATCH - "
                "MTF Order Block قريب"
            )

            analysis_lines = (
                bottom_reasons
            )

        else:

            direction = "NO TRADE"
            es = max(es, 0)

            state = (
                "NO TRADE - "
                "MTF Order Block بعيد"
            )

    # -----------------------------------------------------
    # NO TRADE
    # -----------------------------------------------------

    else:

        direction = "NO TRADE"
        es = max(
            es,
            0,
        )

        if not (
            bullish_ob
            or bearish_ob
        ):
            state = (
                "NO TRADE - "
                "لا يوجد Order Block صالح"
            )

        else:
            state = (
                "NO TRADE - "
                "جودة الـ Order Block غير كافية"
            )

    # =====================================================
    # ENTRY / SL / TP
    # =====================================================

    entry_min = None
    entry_max = None

    sl = None
    tp1 = None
    tp2 = None
    tp3 = None

    # -----------------------------------------------------
    # LONG LEVELS
    # -----------------------------------------------------

    if (
        direction == "LONG"
        and bullish_ob
    ):

        entry_min = bullish_ob["low"]
        entry_max = bullish_ob["high"]

        # If price is below/inside OB, SL from OB.
        sl = min(
            bullish_ob["low"]
            - atr * 0.35,
            p - atr * 0.80,
        )

        risk = max(
            p - sl,
            atr * 0.50,
        )

        tp1 = p + risk * 1.20
        tp2 = p + risk * 2.00
        tp3 = p + risk * 3.00

        if res > p:
            tp1 = min(
                tp1,
                res,
            )

    # -----------------------------------------------------
    # SHORT LEVELS
    # -----------------------------------------------------

    elif (
        direction == "SHORT"
        and bearish_ob
    ):

        entry_min = bearish_ob["low"]
        entry_max = bearish_ob["high"]

        sl = max(
            bearish_ob["high"]
            + atr * 0.35,
            p + atr * 0.80,
        )

        risk = max(
            sl - p,
            atr * 0.50,
        )

        tp1 = p - risk * 1.20
        tp2 = p - risk * 2.00
        tp3 = p - risk * 3.00

        if sup < p:
            tp1 = max(
                tp1,
                sup,
            )

    # =====================================================
    # FINAL ENTRY SANITY CHECK
    # =====================================================

    if direction == "LONG":

        if (
            sl is None
            or sl >= p
        ):
            direction = "WAIT"
            state = (
                "WAIT - "
                "مستوى Stop Loss غير صالح"
            )

            entry_min = None
            entry_max = None
            sl = None
            tp1 = None
            tp2 = None
            tp3 = None

        elif (
            abs(res - p)
            / p
            * 100
            <= 0.12
        ):
            direction = "WAIT"
            state = (
                "WAIT - "
                "السعر قريب جداً من المقاومة"
            )

            entry_min = None
            entry_max = None
            sl = None
            tp1 = None
            tp2 = None
            tp3 = None

    elif direction == "SHORT":

        if (
            sl is None
            or sl <= p
        ):
            direction = "WAIT"
            state = (
                "WAIT - "
                "مستوى Stop Loss غير صالح"
            )

            entry_min = None
            entry_max = None
            sl = None
            tp1 = None
            tp2 = None
            tp3 = None

        elif (
            abs(p - sup)
            / p
            * 100
            <= 0.12
        ):
            direction = "WAIT"
            state = (
                "WAIT - "
                "السعر قريب جداً من الدعم"
            )

            entry_min = None
            entry_max = None
            sl = None
            tp1 = None
            tp2 = None
            tp3 = None

    # =====================================================
    # BUY PRESSURE
    # =====================================================

    if liq == "INFLOW":
        buy_pressure = (
            60
            + min(
                vr * 6,
                25,
            )
        )

    elif liq == "OUTFLOW":
        buy_pressure = (
            40
            - min(
                vr * 5,
                25,
            )
        )

    else:
        buy_pressure = 50

    # =====================================================
    # DRAW RESULT
    # =====================================================

    trend = (
        "UP"
        if t4 == "LONG"
        else "DOWN"
        if t4 == "SHORT"
        else "NEUTRAL"
    )

    return {
        "symbol": symbol,
        "direction": direction,

        "score": int(
            max(
                0,
                min(
                    100,
                    es,
                ),
            )
        ),

        "entry_score": int(
            max(
                0,
                min(
                    100,
                    es,
                ),
            )
        ),

        "state": state,

        "price": smart_round(p),

        "rsi": rsi,

        "volume_ratio": vr,
        "volume_trend": vt,

        "liquidity_state": liq,
        "liquidity_score": liq_score,

        "bottom_detected": bottom,
        "bottom_score": bottom_score,

        "drawdown": 0,

        "buy_pressure": round(
            max(
                5,
                min(
                    95,
                    buy_pressure,
                ),
            ),
            1,
        ),

        "trend": trend,

        "trend_1d": td,
        "trend_4h": t4,
        "trend_1h": t1,
        "trend_30m": t30,
        "trend_15m": t15,

        "structure": st["structure"],
        "bos": st["bos"],
        "liquidity_zone": st[
            "liquidity_zone"
        ],

        "bullish_ob": bullish_ob,
        "bearish_ob": bearish_ob,

        "bullish_ob_4h": bullish_ob_4h,
        "bearish_ob_4h": bearish_ob_4h,

        "bullish_ob_distance": round(
            bullish_distance,
            2,
        ),

        "bearish_ob_distance": round(
            bearish_distance,
            2,
        ),

        "bullish_ob_retest": bullish_retest,
        "bearish_ob_retest": bearish_retest,

        "recent_change_2": round(
            ch2,
            2,
        ),

        "recent_change_6": round(
            ch6,
            2,
        ),

        "crash_detected": crash,
        "pump_detected": pump,

        "entry_min": (
            smart_round(entry_min)
            if entry_min is not None
            else None
        ),

        "entry_max": (
            smart_round(entry_max)
            if entry_max is not None
            else None
        ),

        "stop_loss": (
            smart_round(sl)
            if sl is not None
            else None
        ),

        "tp1": (
            smart_round(tp1)
            if tp1 is not None
            else None
        ),

        "tp2": (
            smart_round(tp2)
            if tp2 is not None
            else None
        ),

        "tp3": (
            smart_round(tp3)
            if tp3 is not None
            else None
        ),

        "support": smart_round(sup),
        "resistance": smart_round(res),

        "support_distance": round(
            abs(p - sup) / p * 100,
            2,
        ),

        "resistance_distance": round(
            abs(res - p) / p * 100,
            2,
        ),

        "long_score": int(
            max(
                0,
                min(
                    100,
                    long_score,
                ),
            )
        ),

        "short_score": int(
            max(
                0,
                min(
                    100,
                    short_score,
                ),
            )
        ),

        "analysis_lines": list(
            dict.fromkeys(
                analysis_lines
            )
        ),

        "liquidity_reasons": liq_reasons,

        "bottom_reasons": bottom_reasons,

        "structure_reasons": st[
            "reasons"
        ],

        "bullish_retest_reasons": (
            bullish_retest_reasons
        ),

        "bearish_retest_reasons": (
            bearish_retest_reasons
        ),

        "rejection_reasons": [],
    }


# =========================================================
# MARKET DATA TEST
# =========================================================

def test_market_data(
    symbol="BTCUSDT",
):
    symbol = normalize_symbol(symbol)

    p = get_current_price(
        symbol,
        True,
    )

    a = get_bingx_klines(
        symbol,
        "1h",
        60,
    )

    b = get_bingx_klines(
        symbol,
        "4h",
        60,
    )

    return {
        "symbol": symbol,
        "price_ok": p is not None,
        "price": p,
        "1h_rows": len(a)
        if a
        else 0,
        "4h_rows": len(b)
        if b
        else 0,
        "ok": (
            p is not None
            and bool(a)
            and len(a) >= 30
        ),
    }


# =========================================================
# TOP FUTURES
# =========================================================

def get_top_futures_symbols(
    limit=30,
):
    sy = get_futures_symbols()

    if not sy:
        return []

    rows = _ticker_rows()

    candidates = []

    for x in rows:
        try:
            s = str(
                x.get("symbol", "")
            ).replace(
                "-",
                "",
            ).upper()

            volume = float(
                x.get(
                    "quoteVolume",
                    x.get(
                        "volume",
                        0,
                    ),
                )
            )

            change = abs(
                float(
                    x.get(
                        "priceChangePercent",
                        0,
                    )
                )
            )

            if (
                s in sy
                and s.endswith("USDT")
                and volume > 0
            ):
                score = (
                    volume
                    * (
                        1
                        + min(
                            change / 100,
                            0.30,
                        )
                    )
                )

                candidates.append(
                    (
                        s,
                        score,
                    )
                )

        except Exception:
            pass

    candidates.sort(
        key=lambda x: x[1],
        reverse=True,
    )

    if candidates:
        return [
            x[0]
            for x in candidates[:limit]
        ]

    return list(sy)[:limit]


# =========================================================
# STAGE 1
# =========================================================

def _stage1_score(symbol):
    p = get_current_price(symbol)

    k = get_bingx_klines(
        symbol,
        "1h",
        120,
    )

    if (
        p is None
        or not k
        or len(k) < 30
    ):
        return None

    obs = detect_order_blocks(k)

    candidates = []

    t = calculate_timeframe_trend(k)

    for best in (
        obs["bullish"]
        + obs["bearish"]
    ):

        direction = (
            "LONG"
            if best["type"] == "BULLISH"
            else "SHORT"
        )

        if not _ob_valid(
            k,
            best,
            direction,
        ):
            continue

        distance = ob_distance_percent(
            p,
            best,
        )

        # v20 stage-1 allows a slightly
        # wider practical OB search.
        if distance > 8:
            continue

        retest, _ = detect_ob_retest(
            k,
            best,
            direction,
        )

        position = ob_position(
            p,
            best,
        )

        score = (
            45
            + min(
                best["strength"],
                30,
            )
            + (
                18
                if retest
                else 0
            )
            + (
                12
                if t == direction
                else 0
            )
            + (
                10
                if position == "INSIDE"
                else 0
            )
            - distance * 3
        )

        candidates.append(
            (
                symbol,
                score,
                direction,
                retest,
            )
        )

    if not candidates:
        return None

    return max(
        candidates,
        key=lambda x: x[1],
    )


# =========================================================
# MARKET SCAN
# =========================================================

def scan_market(limit=5):
    universe = get_top_futures_symbols(30)

    stage = []

    for symbol in universe:
        try:
            result = _stage1_score(
                symbol
            )

            if result:
                stage.append(result)

        except Exception:
            logger.exception(
                "STAGE1 FAILED | %s",
                symbol,
            )

    stage.sort(
        key=lambda x: x[1],
        reverse=True,
    )

    results = []

    # Analyze more candidates than requested
    # so we can find genuine OB setups.
    for symbol, *_ in stage[:12]:

        try:
            d = get_coin_analysis(
                symbol
            )

            if not d:
                continue

            direction = d.get(
                "direction"
            )

            if direction not in (
                "LONG",
                "SHORT",
                "WAIT",
            ):
                continue

            if d.get(
                "crash_detected"
            ):
                continue

            has_1h_ob = bool(
                d.get("bullish_ob")
                or d.get("bearish_ob")
            )

            has_mtf_ob = bool(
                (
                    d.get(
                        "bullish_ob_4h"
                    )
                    and d.get(
                        "bullish_ob_distance",
                        999,
                    ) <= 8
                )
                or (
                    d.get(
                        "bearish_ob_4h"
                    )
                    and d.get(
                        "bearish_ob_distance",
                        999,
                    ) <= 8
                )
            )

            # Scanner remains OB-only.
            if not (
                has_1h_ob
                or has_mtf_ob
            ):
                continue

            results.append(d)

        except Exception:
            logger.exception(
                "FULL ANALYSIS FAILED | %s",
                symbol,
            )

    def rank(x):

        state = x.get(
            "state",
            "",
        )

        direction = x.get(
            "direction",
            "",
        )

        retest = (
            x.get(
                "bullish_ob_retest",
                False,
            )
            or x.get(
                "bearish_ob_retest",
                False,
            )
        )

        if "ENTRY READY" in state:
            state_rank = 4

        elif "REVERSAL WATCH" in state:
            state_rank = 3

        elif "ACCUMULATION WATCH" in state:
            state_rank = 2

        else:
            state_rank = 1

        return (
            state_rank,
            1 if retest else 0,
            x.get(
                "entry_score",
                0,
            ),
            1
            if direction in (
                "LONG",
                "SHORT",
            )
            else 0,
        )

    results.sort(
        key=rank,
        reverse=True,
    )

    return results[:limit]


# =========================================================
# OB TEXT
# =========================================================

def _ob_text(o):
    if not o:
        return "غير موجود"

    return (
        f"{smart_round(o['low'])}"
        f" - "
        f"{smart_round(o['high'])}"
    )


# =========================================================
# REPORT
# =========================================================

def generate_evidence_report(d):

    if not d:
        return (
            "⚠️ تعذر إكمال التحليل.\n"
            "لم يتم استلام بيانات صالحة "
            "من محرك التحليل."
        )

    direction = d.get(
        "direction",
        "WAIT",
    )

    emoji = (
        "🟢"
        if direction == "LONG"
        else "🔴"
        if direction == "SHORT"
        else "🟡"
    )

    liquidity = (
        "🟢 دخول سيولة محتمل"
        if d.get(
            "liquidity_state"
        ) == "INFLOW"
        else
        "🔴 خروج سيولة محتمل"
        if d.get(
            "liquidity_state"
        ) == "OUTFLOW"
        else
        "🟡 سيولة محايدة"
    )

    bos = (
        "🟢 BULLISH"
        if d.get("bos")
        == "BULLISH_BOS"
        else
        "🔴 BEARISH"
        if d.get("bos")
        == "BEARISH_BOS"
        else
        "⚪ NONE"
    )

    lines = [

        "🤖 BingX AI Scanner\n",

        f"💎 العملة: "
        f"{d.get('symbol', '-')}",

        f"💰 السعر الحالي: "
        f"{d.get('price', '-')}",

        f"📈 الاتجاه النهائي: "
        f"{emoji} {direction}",

        f"⭐ Entry Score: "
        f"{d.get('entry_score', 0)}/100",

        "",

        f"🧠 الحالة: "
        f"{d.get('state', '-')}",

        "",

        "🏦 ORDER BLOCK = المحرك الأساسي",

        f"🟢 Bullish OB 1H: "
        f"{_ob_text(d.get('bullish_ob'))}",

        f"🔴 Bearish OB 1H: "
        f"{_ob_text(d.get('bearish_ob'))}",

        f"📊 Bullish OB 4H: "
        f"{_ob_text(d.get('bullish_ob_4h'))}",

        f"📊 Bearish OB 4H: "
        f"{_ob_text(d.get('bearish_ob_4h'))}",

        f"📏 Bullish OB Distance: "
        f"{d.get('bullish_ob_distance', 999)}%",

        f"📏 Bearish OB Distance: "
        f"{d.get('bearish_ob_distance', 999)}%",

        f"🔄 Bullish Retest: "
        f"{'YES' if d.get('bullish_ob_retest') else 'NO'}",

        f"🔄 Bearish Retest: "
        f"{'YES' if d.get('bearish_ob_retest') else 'NO'}",

        "",

        "📊 Context",

        f"1D: "
        f"{d.get('trend_1d')}",

        f"4H: "
        f"{d.get('trend_4h')}",

        "",

        "⏱️ Confirmation",

        f"1H: "
        f"{d.get('trend_1h')}",

        f"30m: "
        f"{d.get('trend_30m')}",

        f"15m: "
        f"{d.get('trend_15m')}",

        "",

        "🏗️ Structure",

        f"{d.get('structure')} "
        f"| BOS: {bos}",

        "",

        f"💧 Liquidity: "
        f"{liquidity}",

        f"📊 Volume: "
        f"{d.get('volume_ratio')}x",

        f"📈 Volume Trend: "
        f"{d.get('volume_trend')}",

        f"💪 Buy Pressure: "
        f"{d.get('buy_pressure')}%",

        f"📊 RSI: "
        f"{d.get('rsi')}",

        "",

        f"🛡️ Support: "
        f"{d.get('support')}",

        f"🔴 Resistance: "
        f"{d.get('resistance')}",
    ]

    # =====================================================
    # TRADE LEVELS
    # =====================================================

    if direction in (
        "LONG",
        "SHORT",
    ):

        lines += [

            "",

            "📍 منطقة الدخول",

            f"{d.get('entry_min')}"
            f" - "
            f"{d.get('entry_max')}",

            "",

            f"🛑 Stop Loss: "
            f"{d.get('stop_loss')}",

            "",

            f"🎯 TP1: "
            f"{d.get('tp1')}",

            f"🎯 TP2: "
            f"{d.get('tp2')}",

            f"🎯 TP3: "
            f"{d.get('tp3')}",
        ]

    else:

        lines += [

            "",

            "📍 منطقة الدخول",

            "⏳ انتظار Retest / BOS / "
            "تأكيد MTF",

            "",

            "🛑 Stop Loss: غير محدد",
        ]

    # =====================================================
    # REASONS
    # =====================================================

    lines += [

        "",

        "🔍 أسباب القرار",
    ]

    reasons = d.get(
        "analysis_lines",
        [],
    )

    for x in reasons[:12]:
        lines.append(
            f"• {x}"
        )

    lines += [

        "",

        "🛡️ ORDER BLOCK هو العامل الأساسي.",

        "⚠️ 1D = Context | "
        "4H = MTF | "
        "1H = Primary OB | "
        "30m + 15m = Confirmation.",

        "⚠️ الإشارة تحليلية وليست "
        "ضماناً للربح.",
    ]

    return "\n".join(lines)
