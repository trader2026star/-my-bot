# =========================================================
# analysis.py
# BingX Futures AI Scanner
# ORDER BLOCK PRIMARY ENGINE
# Price + OB + Retest + BOS + Liquidity + MTF Confirmation
# Scanner v16.0 - RESILIENT DATA / NO-FAKE-TRADE
#
# IMPORTANT:
# - 1H = PRIMARY Order Block engine
# - 4H = MTF Order Block
# - 1D / 30m / 15m = confirmations only
# - Order Block remains the PRIMARY engine
# - No synthetic/fake trade
# - Optional timeframe failure MUST NOT kill analysis
# - Improved BingX request/retry/rate-limit handling
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
    "User-Agent": "CryptoZeroReversal-BingX-OB-Scanner/16.0",
    "Accept": "application/json",
})

logger = logging.getLogger(__name__)

SYMBOL_CACHE_SECONDS = 600
KLINE_CACHE_SECONDS = 60
PRICE_CACHE_SECONDS = 3

_SYMBOL_CACHE = set()
_SYMBOL_CACHE_TIME = 0.0

_KLINE_CACHE = {}
_PRICE_CACHE = {}

_RATE_LIMIT_UNTIL = 0.0
_RATE_LOCK = threading.Lock()

_REQUEST_LOCK = threading.Lock()
_LAST_REQUEST_TIME = 0.0

# Slower than previous version to reduce BingX throttling.
MIN_REQUEST_INTERVAL = 0.60


# =========================================================
# BINGX REQUEST
# =========================================================

def bingx_get(path, params=None, timeout=12, retries=3):
    """
    Resilient BingX request layer.

    IMPORTANT:
    This function only handles API communication.
    It does NOT change Order Block logic.
    """

    global _RATE_LIMIT_UNTIL
    global _LAST_REQUEST_TIME

    last_error = None

    for attempt in range(retries):

        # -------------------------------------------------
        # Rate-limit cooldown
        # -------------------------------------------------
        with _RATE_LOCK:
            remaining = (
                _RATE_LIMIT_UNTIL
                - time.time()
            )

        if remaining > 0:
            logger.warning(
                "BingX cooldown %.1fs | %s",
                remaining,
                path,
            )
            return None

        # -------------------------------------------------
        # Global request throttle
        # -------------------------------------------------
        with _REQUEST_LOCK:

            now = time.time()

            wait = (
                MIN_REQUEST_INTERVAL
                - (now - _LAST_REQUEST_TIME)
            )

            if wait > 0:
                time.sleep(wait)

            _LAST_REQUEST_TIME = time.time()

        try:

            response = SESSION.get(
                BINGX_URL + path,
                params=params or {},
                timeout=timeout,
            )

            # -------------------------------------------------
            # HTTP RATE LIMIT
            # -------------------------------------------------
            if response.status_code in (429, 418):

                logger.warning(
                    "BingX HTTP RATE LIMIT %s | %s",
                    response.status_code,
                    path,
                )

                with _RATE_LOCK:
                    _RATE_LIMIT_UNTIL = max(
                        _RATE_LIMIT_UNTIL,
                        time.time() + 8,
                    )

                return None

            # -------------------------------------------------
            # HTTP ERROR
            # -------------------------------------------------
            if response.status_code != 200:

                last_error = (
                    f"HTTP {response.status_code}"
                )

                logger.warning(
                    "BingX HTTP %s | %s | %s",
                    response.status_code,
                    path,
                    response.text[:300],
                )

                if attempt < retries - 1:
                    time.sleep(
                        0.8 * (attempt + 1)
                    )
                    continue

                return None

            # -------------------------------------------------
            # JSON
            # -------------------------------------------------
            try:
                data = response.json()

            except ValueError:

                last_error = "INVALID_JSON"

                logger.warning(
                    "BingX INVALID JSON | %s | %s",
                    path,
                    response.text[:300],
                )

                if attempt < retries - 1:
                    time.sleep(0.6)
                    continue

                return None

            if not isinstance(data, dict):
                last_error = "INVALID_RESPONSE"

                if attempt < retries - 1:
                    time.sleep(0.6)
                    continue

                return None

            code = data.get("code")

            # -------------------------------------------------
            # SUCCESS
            # -------------------------------------------------
            if code in (0, None):
                return data

            # -------------------------------------------------
            # RATE LIMIT API CODES
            # -------------------------------------------------
            if code in (109429, 109400):

                logger.warning(
                    "BingX RATE LIMIT | code=%s | %s",
                    code,
                    path,
                )

                # Short cooldown.
                # Do NOT lock scanner for 90 seconds.
                with _RATE_LOCK:
                    _RATE_LIMIT_UNTIL = max(
                        _RATE_LIMIT_UNTIL,
                        time.time() + 8,
                    )

                return None

            # -------------------------------------------------
            # TEMPORARY API ERROR
            # -------------------------------------------------
            if code in (
                100001,
                100002,
                100003,
                100004,
                100500,
            ):

                last_error = (
                    f"API_CODE_{code}"
                )

                logger.warning(
                    "BingX TEMP API ERROR | code=%s | %s",
                    code,
                    path,
                )

                if attempt < retries - 1:
                    time.sleep(
                        0.8 * (attempt + 1)
                    )
                    continue

                return None

            # -------------------------------------------------
            # NORMAL API ERROR
            # -------------------------------------------------
            logger.warning(
                "BingX API ERROR | code=%s | %s | %s",
                code,
                path,
                str(data)[:400],
            )

            return None

        except requests.Timeout as exc:

            last_error = str(exc)

            logger.warning(
                "BingX TIMEOUT | %s | attempt=%s/%s",
                path,
                attempt + 1,
                retries,
            )

            if attempt < retries - 1:
                time.sleep(
                    0.8 * (attempt + 1)
                )
                continue

        except requests.ConnectionError as exc:

            last_error = str(exc)

            logger.warning(
                "BingX CONNECTION ERROR | %s | attempt=%s/%s",
                path,
                attempt + 1,
                retries,
            )

            if attempt < retries - 1:
                time.sleep(
                    0.8 * (attempt + 1)
                )
                continue

        except requests.RequestException as exc:

            last_error = str(exc)

            logger.warning(
                "BingX REQUEST ERROR | %s | %s",
                path,
                exc,
            )

            if attempt < retries - 1:
                time.sleep(
                    0.8 * (attempt + 1)
                )
                continue

        except Exception as exc:

            last_error = str(exc)

            logger.exception(
                "BingX UNKNOWN ERROR | %s | %s",
                path,
                exc,
            )

            if attempt < retries - 1:
                time.sleep(0.6)
                continue

    logger.warning(
        "BingX REQUEST FAILED AFTER RETRIES | %s | %s",
        path,
        last_error,
    )

    return None


# =========================================================
# SYMBOL HELPERS
# =========================================================

def normalize_symbol(text):

    text = (
        str(text)
        .strip()
        .upper()
        .replace(" ", "")
        .replace("-", "")
        .replace("_", "")
        .replace("/", "")
    )

    if text.endswith("USDT"):
        return text

    if text.endswith("USDC"):
        return text

    return text + "USDT"


def bingx_symbol(symbol):

    symbol = normalize_symbol(symbol)

    if symbol.endswith("USDT"):
        return symbol[:-4] + "-USDT"

    if symbol.endswith("USDC"):
        return symbol[:-4] + "-USDC"

    return symbol


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
        and now - _SYMBOL_CACHE_TIME
        < SYMBOL_CACHE_SECONDS
    ):
        return set(_SYMBOL_CACHE)

    endpoints = (
        "/openApi/swap/v2/quote/contracts",
        "/openApi/swap/v2/quote/contracts/",
    )

    data = None

    for endpoint in endpoints:

        data = bingx_get(
            endpoint,
            timeout=12,
            retries=2,
        )

        if data:
            break

    if not data:

        logger.warning(
            "Unable to load BingX futures contracts"
        )

        # IMPORTANT:
        # If cache exists, use it.
        if _SYMBOL_CACHE:
            return set(_SYMBOL_CACHE)

        return set()

    rows = data.get("data")

    if not isinstance(rows, list):

        logger.warning(
            "BingX contracts invalid data | %s",
            str(data)[:400],
        )

        if _SYMBOL_CACHE:
            return set(_SYMBOL_CACHE)

        return set()

    symbols = set()

    for item in rows:

        if not isinstance(item, dict):
            continue

        raw = str(
            item.get("symbol", "")
        ).upper()

        raw = (
            raw
            .replace("-", "")
            .replace("_", "")
            .replace("/", "")
        )

        if not raw.endswith("USDT"):
            continue

        status = item.get("status")

        if status not in (
            1,
            "1",
            None,
        ):
            continue

        symbols.add(raw)

    if symbols:

        _SYMBOL_CACHE = symbols
        _SYMBOL_CACHE_TIME = now

        logger.info(
            "Loaded %s BingX USDT futures symbols",
            len(symbols),
        )

    return set(_SYMBOL_CACHE)


def symbol_exists(symbol):

    symbol = normalize_symbol(symbol)

    symbols = get_futures_symbols()

    # If contracts endpoint fails temporarily,
    # do not block direct analysis.
    if not symbols:
        return True

    return symbol in symbols


# =========================================================
# PRICE HELPERS
# =========================================================

def _extract_price_from_row(row):

    if not isinstance(row, dict):
        return None

    for key in (
        "price",
        "lastPrice",
        "last",
        "close",
        "markPrice",
    ):

        try:

            value = float(
                row.get(key)
            )

            if value > 0:
                return value

        except (
            TypeError,
            ValueError,
        ):
            continue

    return None


def get_current_price(symbol, force=False):

    symbol = normalize_symbol(symbol)

    now = time.time()

    cached = _PRICE_CACHE.get(symbol)

    if (
        not force
        and cached
        and now - cached[0]
        < PRICE_CACHE_SECONDS
    ):
        return cached[1]

    # -------------------------------------------------
    # V2 PRICE
    # -------------------------------------------------

    data = bingx_get(
        "/openApi/swap/v2/quote/price",
        {
            "symbol": bingx_symbol(symbol),
        },
        timeout=10,
        retries=2,
    )

    if data:

        row = data.get("data")

        price = _extract_price_from_row(
            row
        )

        if price:

            _PRICE_CACHE[symbol] = (
                now,
                price,
            )

            return price

    # -------------------------------------------------
    # V2 TICKER
    # -------------------------------------------------

    data = bingx_get(
        "/openApi/swap/v2/quote/ticker",
        timeout=10,
        retries=2,
    )

    if data:

        rows = data.get("data")

        if isinstance(rows, list):

            for row in rows:

                if not isinstance(row, dict):
                    continue

                raw = str(
                    row.get("symbol", "")
                ).upper()

                raw = (
                    raw
                    .replace("-", "")
                    .replace("_", "")
                    .replace("/", "")
                )

                if raw != symbol:
                    continue

                price = _extract_price_from_row(
                    row
                )

                if price:

                    _PRICE_CACHE[symbol] = (
                        now,
                        price,
                    )

                    return price

        elif isinstance(rows, dict):

            raw = str(
                rows.get("symbol", "")
            ).upper()

            raw = (
                raw
                .replace("-", "")
                .replace("_", "")
                .replace("/", "")
            )

            if (
                not raw
                or raw == symbol
            ):

                price = _extract_price_from_row(
                    rows
                )

                if price:

                    _PRICE_CACHE[symbol] = (
                        now,
                        price,
                    )

                    return price

    # -------------------------------------------------
    # V3 PRICE FALLBACK
    # -------------------------------------------------

    data = bingx_get(
        "/openApi/swap/v3/quote/price",
        {
            "symbol": bingx_symbol(symbol),
        },
        timeout=10,
        retries=2,
    )

    if data:

        row = data.get("data")

        price = _extract_price_from_row(
            row
        )

        if price:

            _PRICE_CACHE[symbol] = (
                now,
                price,
            )

            return price

    logger.warning(
        "CURRENT PRICE FAILED | %s",
        symbol,
    )

    return None


# =========================================================
# KLINE PARSER
# =========================================================

def _parse_kline_rows(rows):

    result = []

    if not isinstance(rows, list):
        return result

    for row in rows:

        try:

            if isinstance(row, dict):

                timestamp = (
                    row.get("time")
                    or row.get("timestamp")
                    or row.get("openTime")
                    or row.get("open_time")
                    or 0
                )

                op = row.get("open")
                hi = row.get("high")
                lo = row.get("low")
                cl = row.get("close")

                vol = row.get(
                    "volume",
                    row.get(
                        "vol",
                        row.get(
                            "quoteVolume",
                            0,
                        ),
                    ),
                )

                if None in (
                    op,
                    hi,
                    lo,
                    cl,
                ):
                    continue

                result.append([
                    timestamp,
                    float(op),
                    float(hi),
                    float(lo),
                    float(cl),
                    float(vol or 0),
                ])

            elif (
                isinstance(row, list)
                and len(row) >= 6
            ):

                result.append([
                    row[0],
                    float(row[1]),
                    float(row[2]),
                    float(row[3]),
                    float(row[4]),
                    float(row[5]),
                ])

        except (
            TypeError,
            ValueError,
            IndexError,
        ):
            continue

    # -------------------------------------------------
    # Sort only when timestamps are usable.
    # -------------------------------------------------

    try:

        if result:

            valid_timestamps = True

            for x in result:

                if x[0] in (
                    None,
                    "",
                    0,
                    "0",
                ):
                    valid_timestamps = False
                    break

            if valid_timestamps:
                result.sort(
                    key=lambda x: float(x[0])
                )

    except Exception:
        pass

    return result


# =========================================================
# KLINES
# =========================================================

def get_bingx_klines(
    symbol,
    interval="1h",
    limit=200,
):

    symbol = normalize_symbol(symbol)

    interval = str(
        interval
    ).lower()

    limit = int(limit)

    key = (
        symbol,
        interval,
        limit,
    )

    now = time.time()

    cached = _KLINE_CACHE.get(key)

    if (
        cached
        and now - cached[0]
        < KLINE_CACHE_SECONDS
    ):
        return cached[1]

    params = {
        "symbol": bingx_symbol(symbol),
        "interval": interval,
        "limit": limit,
    }

    endpoints = (
        "/openApi/swap/v2/quote/klines",
        "/openApi/swap/v3/quote/klines",
    )

    best_result = None

    for endpoint in endpoints:

        data = bingx_get(
            endpoint,
            params,
            timeout=12,
            retries=2,
        )

        if not data:
            continue

        rows = data.get("data")

        result = _parse_kline_rows(
            rows
        )

        if result:

            if (
                best_result is None
                or len(result)
                > len(best_result)
            ):
                best_result = result

            if len(result) >= 30:

                _KLINE_CACHE[key] = (
                    now,
                    result,
                )

                return result

        logger.warning(
            "KLINE EMPTY/INSUFFICIENT | %s %s | %s | rows=%s",
            symbol,
            interval,
            endpoint,
            len(result),
        )

    if best_result:

        _KLINE_CACHE[key] = (
            now,
            best_result,
        )

        return best_result

    logger.warning(
        "KLINE FAILED ALL ENDPOINTS | %s %s",
        symbol,
        interval,
    )

    return None


# =========================================================
# CALCULATIONS
# =========================================================

def calculate_ema(values, period):

    if len(values) < period:
        return None

    multiplier = 2 / (
        period + 1
    )

    ema = sum(
        values[:period]
    ) / period

    for price in values[period:]:

        ema = (
            (price - ema)
            * multiplier
        ) + ema

    return ema


def calculate_rsi(
    closes,
    period=14,
):

    if len(closes) < period + 1:
        return 50.0

    gains = []
    losses = []

    for i in range(
        1,
        len(closes),
    ):

        change = (
            closes[i]
            - closes[i - 1]
        )

        gains.append(
            max(change, 0)
        )

        losses.append(
            max(-change, 0)
        )

    avg_gain = (
        sum(gains[:period])
        / period
    )

    avg_loss = (
        sum(losses[:period])
        / period
    )

    for i in range(
        period,
        len(gains),
    ):

        avg_gain = (
            avg_gain
            * (period - 1)
            + gains[i]
        ) / period

        avg_loss = (
            avg_loss
            * (period - 1)
            + losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0

    rs = (
        avg_gain
        / avg_loss
    )

    return round(
        100 - (
            100 / (1 + rs)
        ),
        2,
    )


def calculate_atr(
    klines,
    period=14,
):

    if len(klines) < period + 1:
        return None

    trs = []

    for i in range(
        1,
        len(klines),
    ):

        h = klines[i][2]
        l = klines[i][3]
        pc = klines[i - 1][4]

        trs.append(
            max(
                h - l,
                abs(h - pc),
                abs(l - pc),
            )
        )

    atr = (
        sum(trs[:period])
        / period
    )

    for value in trs[period:]:

        atr = (
            atr
            * (period - 1)
            + value
        ) / period

    return atr


def calculate_volume_ratio(
    volumes,
    period=20,
):

    if len(volumes) < (
        period + 4
    ):
        return 1.0

    recent = volumes[-4:-1]

    baseline = volumes[
        -period - 4:-4
    ]

    if not recent or not baseline:
        return 1.0

    recent_avg = (
        sum(recent)
        / len(recent)
    )

    baseline_avg = (
        sum(baseline)
        / len(baseline)
    )

    if baseline_avg <= 0:
        return 1.0

    return round(
        max(
            0.05,
            min(
                5.0,
                recent_avg
                / baseline_avg,
            ),
        ),
        2,
    )


def calculate_volume_trend(
    volumes,
    short_period=5,
    long_period=20,
):

    if len(volumes) < (
        long_period
        + short_period
        + 1
    ):
        return "NEUTRAL"

    short = volumes[
        -short_period - 1:-1
    ]

    previous = volumes[
        -long_period
        - short_period
        - 1:
        -short_period - 1
    ]

    if not short or not previous:
        return "NEUTRAL"

    s = sum(short) / len(short)
    p = sum(previous) / len(previous)

    if p <= 0:
        return "NEUTRAL"

    ratio = s / p

    if ratio >= 1.12:
        return "RISING"

    if ratio <= 0.88:
        return "FALLING"

    return "NEUTRAL"


def percentage_change(
    old_price,
    new_price,
):

    if not old_price:
        return 0.0

    return (
        (
            new_price
            - old_price
        )
        / old_price
    ) * 100


# =========================================================
# SUPPORT / RESISTANCE
# =========================================================

def calculate_support_resistance(
    klines,
):

    if not klines:
        return 0.0, 0.0

    current = klines[-1][4]

    lookback = min(
        80,
        len(klines),
    )

    highs = [
        k[2]
        for k in klines[-lookback:]
    ]

    lows = [
        k[3]
        for k in klines[-lookback:]
    ]

    supports = [
        x
        for x in lows
        if x < current
    ]

    resistances = [
        x
        for x in highs
        if x > current
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


# =========================================================
# ORDER BLOCK ENGINE
# =========================================================

def _candle_direction(k):

    if k[4] > k[1]:
        return "BULLISH"

    if k[4] < k[1]:
        return "BEARISH"

    return "NEUTRAL"


def _candle_body(k):
    return abs(
        k[4] - k[1]
    )


def _candle_range(k):
    return max(
        k[2] - k[3],
        0,
    )


def detect_order_blocks(
    klines,
    lookback=100,
):

    if len(klines) < 30:

        return {
            "bullish": [],
            "bearish": [],
        }

    start = max(
        5,
        len(klines) - lookback,
    )

    bullish = []
    bearish = []

    for i in range(
        start,
        len(klines) - 3,
    ):

        base = klines[i]
        displacement = klines[i + 1]

        base_range = _candle_range(
            base
        )

        disp_range = _candle_range(
            displacement
        )

        if (
            base_range <= 0
            or disp_range <= 0
        ):
            continue

        body = _candle_body(
            displacement
        )

        body_ratio = (
            body / disp_range
        )

        if body_ratio < 0.50:
            continue

        previous_high = max(
            k[2]
            for k in klines[
                max(0, i - 5):i
            ]
        )

        previous_low = min(
            k[3]
            for k in klines[
                max(0, i - 5):i
            ]
        )

        displacement_change = (
            percentage_change(
                displacement[1],
                displacement[4],
            )
        )

        # -------------------------------------------------
        # BULLISH OB
        # -------------------------------------------------

        if (
            _candle_direction(base)
            == "BEARISH"
            and
            _candle_direction(
                displacement
            ) == "BULLISH"
            and
            displacement[4]
            > previous_high
        ):

            zone_low = min(
                base[3],
                base[1],
            )

            zone_high = max(
                base[3],
                base[1],
            )

            strength = (
                body_ratio * 50
                +
                min(
                    max(
                        displacement_change,
                        0,
                    ),
                    5,
                ) * 5
            )

            bullish.append({
                "type": "BULLISH",
                "index": i,
                "low": zone_low,
                "high": zone_high,
                "mid": (
                    zone_low
                    + zone_high
                ) / 2,
                "strength": round(
                    min(
                        100,
                        strength,
                    ),
                    2,
                ),
            })

        # -------------------------------------------------
        # BEARISH OB
        # -------------------------------------------------

        if (
            _candle_direction(base)
            == "BULLISH"
            and
            _candle_direction(
                displacement
            ) == "BEARISH"
            and
            displacement[4]
            < previous_low
        ):

            zone_low = min(
                base[1],
                base[2],
            )

            zone_high = max(
                base[1],
                base[2],
            )

            strength = (
                body_ratio * 50
                +
                min(
                    abs(
                        min(
                            displacement_change,
                            0,
                        )
                    ),
                    5,
                ) * 5
            )

            bearish.append({
                "type": "BEARISH",
                "index": i,
                "low": zone_low,
                "high": zone_high,
                "mid": (
                    zone_low
                    + zone_high
                ) / 2,
                "strength": round(
                    min(
                        100,
                        strength,
                    ),
                    2,
                ),
            })

    bullish.sort(
        key=lambda x: (
            x["index"],
            x["strength"],
        ),
        reverse=True,
    )

    bearish.sort(
        key=lambda x: (
            x["index"],
            x["strength"],
        ),
        reverse=True,
    )

    return {
        "bullish": bullish[:10],
        "bearish": bearish[:10],
    }


def price_inside_ob(
    price,
    ob,
    tolerance=0.003,
):

    if not ob:
        return False

    low = ob["low"]
    high = ob["high"]

    margin = max(
        (high - low)
        * tolerance,
        0,
    )

    return (
        low - margin
        <= price
        <= high + margin
    )


def ob_distance_percent(
    price,
    ob,
):

    if not ob or price <= 0:
        return 999.0

    if price_inside_ob(
        price,
        ob,
    ):
        return 0.0

    if price < ob["low"]:

        return (
            (
                ob["low"]
                - price
            )
            / price
        ) * 100

    return (
        (
            price
            - ob["high"]
        )
        / price
    ) * 100


def find_active_order_block(
    klines,
    direction,
    current_price,
):

    if not klines:
        return None

    obs = detect_order_blocks(
        klines
    )

    candidates = (
        obs["bullish"]
        if direction == "LONG"
        else obs["bearish"]
    )

    if not candidates:
        return None

    best = None

    for ob in candidates:

        distance = (
            ob_distance_percent(
                current_price,
                ob,
            )
        )

        if distance > 8.0:
            continue

        recency_bonus = 0.0

        if (
            ob["index"]
            >= len(klines) - 12
        ):
            recency_bonus = 8.0

        elif (
            ob["index"]
            >= len(klines) - 25
        ):
            recency_bonus = 4.0

        score = (
            ob["strength"]
            + recency_bonus
            - distance * 5
        )

        candidate = (
            score,
            distance,
            ob,
        )

        if (
            best is None
            or score > best[0]
        ):
            best = candidate

    return (
        best[2]
        if best
        else None
    )


def detect_ob_retest(
    klines,
    ob,
    direction,
):

    if (
        not ob
        or len(klines) < 3
    ):
        return False, []

    reasons = []

    touched = False
    rejected = False

    recent = klines[-10:]

    for k in recent:

        low = k[3]
        high = k[2]
        close = k[4]

        if (
            low <= ob["high"]
            and high >= ob["low"]
        ):

            touched = True

            if direction == "LONG":

                if close >= ob["mid"]:
                    rejected = True

            else:

                if close <= ob["mid"]:
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
# MARKET STRUCTURE / BOS
# =========================================================

def detect_market_structure(
    klines,
):

    if len(klines) < 25:

        return {
            "structure": "UNKNOWN",
            "bos": "NONE",
            "liquidity_zone": "NONE",
            "reasons": [],
        }

    highs = [
        k[2]
        for k in klines
    ]

    lows = [
        k[3]
        for k in klines
    ]

    closes = [
        k[4]
        for k in klines
    ]

    current = closes[-1]
    previous = closes[-2]

    ref_high = max(
        highs[-30:-5]
    )

    ref_low = min(
        lows[-30:-5]
    )

    bos = "NONE"
    structure = "MIXED"

    reasons = []

    if (
        current > ref_high
        and previous <= ref_high
    ):

        bos = "BULLISH_BOS"
        structure = "BULLISH"

        reasons.append(
            "BOS صاعد مؤكد"
        )

    elif (
        current < ref_low
        and previous >= ref_low
    ):

        bos = "BEARISH_BOS"
        structure = "BEARISH"

        reasons.append(
            "BOS هابط مؤكد"
        )

    else:

        rh = max(
            highs[-10:]
        )

        rl = min(
            lows[-10:]
        )

        if current >= rh * 0.997:
            structure = "BULLISH"

        elif current <= rl * 1.003:
            structure = "BEARISH"

        reasons.append(
            "لا يوجد BOS جديد مؤكد"
        )

    rh = max(
        highs[-10:]
    )

    rl = min(
        lows[-10:]
    )

    low_distance = (
        abs(current - rl)
        / current
        * 100
    )

    high_distance = (
        abs(current - rh)
        / current
        * 100
    )

    zone = "NONE"

    if low_distance <= 0.60:

        zone = "LOW_LIQUIDITY"

        reasons.append(
            "السعر قريب من السيولة السفلية"
        )

    elif high_distance <= 0.60:

        zone = "HIGH_LIQUIDITY"

        reasons.append(
            "السعر قريب من السيولة العلوية"
        )

    return {
        "structure": structure,
        "bos": bos,
        "liquidity_zone": zone,
        "reasons": reasons,
    }


# =========================================================
# LIQUIDITY
# =========================================================

def detect_liquidity_flow(
    klines,
):

    if len(klines) < 25:

        return (
            "NEUTRAL",
            0,
            [],
        )

    rows = klines[:-1]

    opens = [
        k[1]
        for k in rows
    ]

    closes = [
        k[4]
        for k in rows
    ]

    volumes = [
        k[5]
        for k in rows
    ]

    reasons = []

    vr = calculate_volume_ratio(
        volumes,
        20,
    )

    recent = volumes[-5:]

    previous = volumes[-15:-5]

    rv = (
        sum(recent)
        / max(len(recent), 1)
    )

    pv = (
        sum(previous)
        / len(previous)
        if previous
        else rv
    )

    rc = percentage_change(
        closes[-6],
        closes[-1],
    )

    bull = 0.0
    bear = 0.0

    start = max(
        0,
        len(rows) - 15,
    )

    for i in range(
        start,
        len(rows),
    ):

        if closes[i] > opens[i]:
            bull += volumes[i]

        elif closes[i] < opens[i]:
            bear += volumes[i]

    total = bull + bear

    buy_share = (
        bull / total
        if total > 0
        else 0.5
    )

    score = 0

    if (
        buy_share >= 0.56
        and vr >= 0.85
    ):

        score += 2

        reasons.append(
            "ضغط الشراء أعلى من البيع"
        )

    if (
        rv > pv * 1.05
        and rc >= -2.0
    ):

        score += 1

        reasons.append(
            "الحجم يتحسن مع استقرار السعر"
        )

    if (
        buy_share <= 0.44
        and vr >= 0.85
    ):

        score -= 2

        reasons.append(
            "ضغط البيع أعلى من الشراء"
        )

    if (
        rv > pv * 1.05
        and rc <= -2.0
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

def calculate_timeframe_trend(
    klines,
):

    if not klines:
        return "UNKNOWN"

    closes = [
        k[4]
        for k in klines
    ]

    e9 = calculate_ema(
        closes,
        9,
    )

    e20 = calculate_ema(
        closes,
        20,
    )

    e50 = calculate_ema(
        closes,
        50,
    )

    if None in (
        e9,
        e20,
        e50,
    ):
        return "UNKNOWN"

    current = closes[-1]

    if (
        e9 > e20 > e50
        and current > e20
    ):
        return "LONG"

    if (
        e9 < e20 < e50
        and current < e20
    ):
        return "SHORT"

    return "NEUTRAL"


# =========================================================
# ACCUMULATION
# =========================================================

def detect_bottom_accumulation(
    klines,
):

    if len(klines) < 40:

        return (
            False,
            0,
            [],
        )

    closes = [
        k[4]
        for k in klines
    ]

    volumes = [
        k[5]
        for k in klines
    ]

    split = min(
        30,
        len(closes) // 2,
    )

    old = closes[
        -split * 2:-split
    ]

    recent = closes[-split:]

    if (
        not old
        or not recent
    ):

        return (
            False,
            0,
            [],
        )

    old_high = max(old)

    recent_low = min(recent)
    recent_high = max(recent)

    drawdown = (
        (
            recent_low
            - old_high
        )
        / old_high
        * 100
    )

    recent_range = (
        (
            recent_high
            - recent_low
        )
        / recent_low
        * 100
        if recent_low
        else 0
    )

    old_volume = (
        sum(
            volumes[
                -split * 2:-split
            ]
        )
        / max(len(old), 1)
    )

    recent_volume = (
        sum(volumes[-10:])
        / max(
            min(
                10,
                len(volumes),
            ),
            1,
        )
    )

    score = 0
    reasons = []

    if drawdown <= -4:

        score += 1

        reasons.append(
            "هبوط سابق واضح"
        )

    if recent_range <= 18:

        score += 1

        reasons.append(
            "النطاق السعري بدأ يضيق"
        )

    if (
        old_volume > 0
        and recent_volume
        >= old_volume * 0.65
    ):

        score += 1

        reasons.append(
            "الحجم ما زال موجوداً بعد الهبوط"
        )

    if score >= 2:

        return (
            True,
            score,
            reasons,
        )

    return (
        False,
        score,
        reasons,
    )


# =========================================================
# ROUNDING
# =========================================================

def smart_round(value):

    if value is None:
        return 0

    try:
        value = float(value)

    except (
        TypeError,
        ValueError,
    ):
        return 0

    if value >= 1000:
        return round(value, 2)

    if value >= 100:
        return round(value, 3)

    if value >= 1:
        return round(value, 4)

    if value >= 0.1:
        return round(value, 5)

    if value >= 0.01:
        return round(value, 6)

    return round(value, 8)


# =========================================================
# SAFE DEFAULT
# =========================================================

def _empty_analysis(
    symbol,
    current_price=None,
    reason="بيانات السوق غير مكتملة",
):

    price = smart_round(
        current_price
    )

    return {
        "symbol": symbol,
        "direction": "WAIT",
        "score": 0,
        "entry_score": 0,
        "state": (
            "WAIT - "
            + reason
        ),
        "price": price,

        "rsi": 50.0,
        "volume_ratio": 1.0,
        "volume_trend": "NEUTRAL",

        "liquidity_state": "NEUTRAL",
        "liquidity_score": 0,

        "bottom_detected": False,
        "bottom_score": 0,
        "drawdown": 0,

        "buy_pressure": 50.0,

        "trend": "NEUTRAL",

        "trend_1d": "UNKNOWN",
        "trend_4h": "UNKNOWN",
        "trend_1h": "UNKNOWN",
        "trend_30m": "UNKNOWN",
        "trend_15m": "UNKNOWN",

        "structure": "UNKNOWN",
        "bos": "NONE",
        "liquidity_zone": "NONE",

        "bullish_ob": None,
        "bearish_ob": None,

        "bullish_ob_4h": None,
        "bearish_ob_4h": None,

        "bullish_ob_distance": 999.0,
        "bearish_ob_distance": 999.0,

        "bullish_ob_retest": False,
        "bearish_ob_retest": False,

        "recent_change_2": 0.0,
        "recent_change_6": 0.0,

        "crash_detected": False,
        "pump_detected": False,

        "entry_min": None,
        "entry_max": None,

        "stop_loss": None,

        "tp1": None,
        "tp2": None,
        "tp3": None,

        "support": 0,
        "resistance": 0,

        "support_distance": 999.0,
        "resistance_distance": 999.0,

        "long_score": 0,
        "short_score": 0,

        "analysis_lines": [],
        "liquidity_reasons": [],
        "bottom_reasons": [],
        "structure_reasons": [],

        "bullish_retest_reasons": [],
        "bearish_retest_reasons": [],

        "rejection_reasons": [
            reason
        ],
    }


# =========================================================
# FULL COIN ANALYSIS
# =========================================================

def get_coin_analysis(symbol):

    symbol = normalize_symbol(
        symbol
    )

    logger.info(
        "START ANALYSIS | %s",
        symbol,
    )

    # -----------------------------------------------------
    # SYMBOL CHECK
    # -----------------------------------------------------

    if not symbol_exists(symbol):

        logger.info(
            "SYMBOL NOT FOUND | %s",
            symbol,
        )

        return _empty_analysis(
            symbol,
            None,
            "العملة غير موجودة في BingX Futures",
        )

    # -----------------------------------------------------
    # PRICE
    # -----------------------------------------------------

    current_price = get_current_price(
        symbol,
        force=True,
    )

    if current_price is None:

        logger.error(
            "PRICE UNAVAILABLE | %s",
            symbol,
        )

        return _empty_analysis(
            symbol,
            None,
            "تعذر الحصول على السعر الحالي من BingX",
        )

    logger.info(
        "PRICE OK | %s | %s",
        symbol,
        current_price,
    )

    # -----------------------------------------------------
    # PRIMARY 1H
    # -----------------------------------------------------

    k1h = get_bingx_klines(
        symbol,
        "1h",
        200,
    )

    if (
        not k1h
        or len(k1h) < 30
    ):

        logger.error(
            "PRIMARY 1H DATA UNAVAILABLE | %s | rows=%s",
            symbol,
            len(k1h)
            if k1h
            else 0,
        )

        return _empty_analysis(
            symbol,
            current_price,
            "بيانات 1H الأساسية غير متاحة حالياً",
        )

    logger.info(
        "PRIMARY 1H OK | %s | rows=%s",
        symbol,
        len(k1h),
    )

    # -----------------------------------------------------
    # OPTIONAL TIMEFRAMES
    # -----------------------------------------------------

    k4h = get_bingx_klines(
        symbol,
        "4h",
        160,
    )

    k1d = get_bingx_klines(
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

    logger.info(
        "MTF DATA | %s | 4H=%s 1D=%s 30M=%s 15M=%s",
        symbol,
        len(k4h) if k4h else 0,
        len(k1d) if k1d else 0,
        len(k30) if k30 else 0,
        len(k15) if k15 else 0,
    )

    # -----------------------------------------------------
    # TRENDS
    # -----------------------------------------------------

    trend_1d = calculate_timeframe_trend(
        k1d
    )

    trend_4h = calculate_timeframe_trend(
        k4h
    )

    trend_1h = calculate_timeframe_trend(
        k1h
    )

    trend_30m = calculate_timeframe_trend(
        k30
    )

    trend_15m = calculate_timeframe_trend(
        k15
    )

    # -----------------------------------------------------
    # 1H PRIMARY DATA
    # -----------------------------------------------------

    closes = [
        k[4]
        for k in k1h
    ]

    volumes = [
        k[5]
        for k in k1h
    ]

    rsi = calculate_rsi(
        closes
    )

    atr = calculate_atr(
        k1h
    )

    volume_ratio = calculate_volume_ratio(
        volumes,
        20,
    )

    volume_trend = calculate_volume_trend(
        volumes
    )

    support, resistance = (
        calculate_support_resistance(
            k1h
        )
    )

    structure = detect_market_structure(
        k1h
    )

    (
        liquidity_state,
        liquidity_score,
        liquidity_reasons,
    ) = detect_liquidity_flow(
        k1h
    )

    (
        bottom_detected,
        bottom_score,
        bottom_reasons,
    ) = detect_bottom_accumulation(
        k1h
    )

    # -----------------------------------------------------
    # PRIMARY ORDER BLOCK
    # -----------------------------------------------------

    bullish_ob = find_active_order_block(
        k1h,
        "LONG",
        current_price,
    )

    bearish_ob = find_active_order_block(
        k1h,
        "SHORT",
        current_price,
    )

    # -----------------------------------------------------
    # 4H MTF ORDER BLOCK
    # -----------------------------------------------------

    bullish_ob_4h = None
    bearish_ob_4h = None

    if k4h:

        bullish_ob_4h = (
            find_active_order_block(
                k4h,
                "LONG",
                current_price,
            )
        )

        bearish_ob_4h = (
            find_active_order_block(
                k4h,
                "SHORT",
                current_price,
            )
        )

    # -----------------------------------------------------
    # OB DISTANCE
    # -----------------------------------------------------

    bullish_ob_distance = (
        ob_distance_percent(
            current_price,
            bullish_ob,
        )
        if bullish_ob
        else 999.0
    )

    bearish_ob_distance = (
        ob_distance_percent(
            current_price,
            bearish_ob,
        )
        if bearish_ob
        else 999.0
    )

    # -----------------------------------------------------
    # OB RETEST
    # -----------------------------------------------------

    (
        bullish_retest,
        bullish_retest_reasons,
    ) = detect_ob_retest(
        k1h,
        bullish_ob,
        "LONG",
    )

    (
        bearish_retest,
        bearish_retest_reasons,
    ) = detect_ob_retest(
        k1h,
        bearish_ob,
        "SHORT",
    )

    long_score = 0
    short_score = 0

    analysis_lines = []
    rejection_reasons = []

    # =====================================================
    # LONG - ORDER BLOCK PRIMARY
    # =====================================================

    if bullish_ob:

        long_score += 35

        analysis_lines.append(
            "يوجد Bullish Order Block فعال على 1H"
        )

        if bullish_ob["strength"] >= 55:

            long_score += 10

            analysis_lines.append(
                "قوة Bullish OB جيدة"
            )

        if bullish_retest:

            long_score += 20

            analysis_lines.append(
                "تم تأكيد Retest للـ Bullish OB"
            )

        else:

            rejection_reasons.append(
                "Bullish OB موجود لكن Retest غير مكتمل"
            )

    else:

        rejection_reasons.append(
            "لا يوجد Bullish Order Block قريب"
        )

    # =====================================================
    # SHORT - ORDER BLOCK PRIMARY
    # =====================================================

    if bearish_ob:

        short_score += 35

        analysis_lines.append(
            "يوجد Bearish Order Block فعال على 1H"
        )

        if bearish_ob["strength"] >= 55:

            short_score += 10

            analysis_lines.append(
                "قوة Bearish OB جيدة"
            )

        if bearish_retest:

            short_score += 20

            analysis_lines.append(
                "تم تأكيد Retest للـ Bearish OB"
            )

        else:

            rejection_reasons.append(
                "Bearish OB موجود لكن Retest غير مكتمل"
            )

    else:

        rejection_reasons.append(
            "لا يوجد Bearish Order Block قريب"
        )

    # =====================================================
    # 4H MTF
    # =====================================================

    if trend_4h == "LONG":

        long_score += 15

        if bullish_ob_4h:

            long_score += 15

            analysis_lines.append(
                "4H يحتوي على Bullish MTF Order Block"
            )

        else:

            rejection_reasons.append(
                "4H صاعد لكن لا يوجد Bullish MTF OB واضح"
            )

    elif trend_4h == "SHORT":

        short_score += 15

        if bearish_ob_4h:

            short_score += 15

            analysis_lines.append(
                "4H يحتوي على Bearish MTF Order Block"
            )

        else:

            rejection_reasons.append(
                "4H هابط لكن لا يوجد Bearish MTF OB واضح"
            )

    else:

        rejection_reasons.append(
            "4H غير متاح أو محايد؛ تم تخفيف الاعتماد عليه"
        )

    # =====================================================
    # LOWER TIMEFRAME CONFIRMATION
    # =====================================================

    if trend_1h == "LONG":
        long_score += 7

    elif trend_1h == "SHORT":
        short_score += 7

    if trend_30m == "LONG":
        long_score += 5

    elif trend_30m == "SHORT":
        short_score += 5

    if trend_15m == "LONG":
        long_score += 5

    elif trend_15m == "SHORT":
        short_score += 5

    # =====================================================
    # BOS
    # =====================================================

    if structure["bos"] == "BULLISH_BOS":

        long_score += 12

        analysis_lines.append(
            "BOS صاعد يؤكد Bullish OB"
        )

    elif structure["bos"] == "BEARISH_BOS":

        short_score += 12

        analysis_lines.append(
            "BOS هابط يؤكد Bearish OB"
        )

    # =====================================================
    # LIQUIDITY
    # =====================================================

    if liquidity_state == "INFLOW":

        long_score += 8

        analysis_lines.append(
            "السيولة تميل للشراء"
        )

    elif liquidity_state == "OUTFLOW":

        short_score += 8

        analysis_lines.append(
            "السيولة تميل للبيع"
        )

    # =====================================================
    # VOLUME
    # =====================================================

    if volume_ratio >= 1.15:

        if long_score >= short_score:
            long_score += 5
        else:
            short_score += 5

        analysis_lines.append(
            "الحجم يدعم الحركة"
        )

    # =====================================================
    # RSI CONFIRMATION ONLY
    # =====================================================

    if (
        trend_4h == "LONG"
        and 38 <= rsi <= 68
    ):

        long_score += 4

    elif (
        trend_4h == "SHORT"
        and 32 <= rsi <= 65
    ):

        short_score += 4

    # =====================================================
    # SUPPORT / RESISTANCE
    # =====================================================

    if current_price > 0:

        support_distance = (
            abs(
                current_price
                - support
            )
            / current_price
            * 100
        )

        resistance_distance = (
            abs(
                resistance
                - current_price
            )
            / current_price
            * 100
        )

    else:

        support_distance = 999.0
        resistance_distance = 999.0

    # =====================================================
    # RECENT MOVEMENT
    # =====================================================

    recent_change_2 = percentage_change(
        closes[-3],
        current_price,
    )

    recent_change_6 = percentage_change(
        closes[-7],
        current_price,
    )

    crash_detected = (
        recent_change_2 <= -8
        or recent_change_6 <= -15
    )

    pump_detected = (
        recent_change_2 >= 8
        or recent_change_6 >= 15
    )

    if crash_detected:

        long_score -= 10
        short_score -= 10

        rejection_reasons.append(
            "حركة هبوط سريعة"
        )

    if pump_detected:

        long_score -= 8

        rejection_reasons.append(
            "حركة صعود سريعة؛ لا نطارد السعر"
        )

    # =====================================================
    # FINAL DIRECTION
    # =====================================================

    direction = "NO TRADE"

    state = (
        "NO TRADE - Order Block غير مكتمل"
    )

    entry_score = 0

    # -----------------------------------------------------
    # MTF CONDITIONS
    # -----------------------------------------------------

    long_mtf_ok = (
        trend_4h
        in (
            "LONG",
            "UNKNOWN",
            "NEUTRAL",
        )
    )

    short_mtf_ok = (
        trend_4h
        in (
            "SHORT",
            "UNKNOWN",
            "NEUTRAL",
        )
    )

    # -----------------------------------------------------
    # LOCAL CONFIRMATION
    # -----------------------------------------------------

    long_confirmation = (
        bullish_retest
        or
        (
            structure["bos"]
            == "BULLISH_BOS"
            and trend_1h
            == "LONG"
        )
    )

    short_confirmation = (
        bearish_retest
        or
        (
            structure["bos"]
            == "BEARISH_BOS"
            and trend_1h
            == "SHORT"
        )
    )

    # -----------------------------------------------------
    # ENTRY READY
    # -----------------------------------------------------

    long_ready = (
        bullish_ob is not None
        and long_mtf_ok
        and long_score >= 70
        and long_confirmation
        and trend_15m != "SHORT"
        and not crash_detected
        and resistance_distance > 0.20
    )

    short_ready = (
        bearish_ob is not None
        and short_mtf_ok
        and short_score >= 70
        and short_confirmation
        and trend_15m != "LONG"
        and not crash_detected
        and support_distance > 0.20
    )

    if (
        long_ready
        and long_score >= short_score
    ):

        direction = "LONG"
        entry_score = long_score

        if trend_4h == "LONG":

            state = (
                "ENTRY READY - Bullish Order Block + Retest + MTF Confirmation"
            )

        else:

            state = (
                "ENTRY READY - Bullish Order Block + Local Confirmation"
            )

    elif (
        short_ready
        and short_score > long_score
    ):

        direction = "SHORT"
        entry_score = short_score

        if trend_4h == "SHORT":

            state = (
                "ENTRY READY - Bearish Order Block + Retest + MTF Confirmation"
            )

        else:

            state = (
                "ENTRY READY - Bearish Order Block + Local Confirmation"
            )

    else:

        # -------------------------------------------------
        # REVERSAL WATCH
        # -------------------------------------------------

        if (
            bullish_ob
            and long_score >= 55
            and resistance_distance > 0.20
            and not crash_detected
            and trend_4h
            in (
                "LONG",
                "UNKNOWN",
                "NEUTRAL",
            )
        ):

            direction = "WAIT"

            entry_score = long_score

            state = (
                "REVERSAL WATCH - Bullish OB موجود وننتظر Retest/BOS"
            )

            rejection_reasons.append(
                "انتظار Retest أو BOS لتأكيد الدخول"
            )

        elif (
            bearish_ob
            and short_score >= 55
            and support_distance > 0.20
            and not crash_detected
            and trend_4h
            in (
                "SHORT",
                "UNKNOWN",
                "NEUTRAL",
            )
        ):

            direction = "WAIT"

            entry_score = short_score

            state = (
                "REVERSAL WATCH - Bearish OB موجود وننتظر Retest/BOS"
            )

            rejection_reasons.append(
                "انتظار Retest أو BOS لتأكيد الدخول"
            )

        elif bottom_detected:

            direction = "WAIT"

            entry_score = max(
                long_score,
                45,
            )

            state = (
                "ACCUMULATION WATCH - تجميع محتمل وننتظر Order Block/BOS"
            )

        else:

            entry_score = max(
                long_score,
                short_score,
                0,
            )

            state = (
                "NO TRADE - Order Block غير مكتمل التأكيد"
            )

    # =====================================================
    # ATR
    # =====================================================

    if not atr or atr <= 0:
        atr = current_price * 0.01

    # =====================================================
    # LEVELS
    # =====================================================

    entry_min = None
    entry_max = None

    stop_loss = None

    tp1 = None
    tp2 = None
    tp3 = None

    # -----------------------------------------------------
    # LONG
    # -----------------------------------------------------

    if (
        direction == "LONG"
        and bullish_ob
    ):

        entry_min = bullish_ob["low"]
        entry_max = bullish_ob["high"]

        stop_loss = min(
            bullish_ob["low"]
            - atr * 0.35,
            current_price
            - atr * 0.80,
        )

        risk = max(
            current_price
            - stop_loss,
            atr * 0.50,
        )

        tp1 = (
            current_price
            + risk * 1.20
        )

        tp2 = (
            current_price
            + risk * 2.00
        )

        tp3 = (
            current_price
            + risk * 3.00
        )

        if resistance > current_price:

            tp1 = min(
                tp1,
                resistance,
            )

    # -----------------------------------------------------
    # SHORT
    # -----------------------------------------------------

    elif (
        direction == "SHORT"
        and bearish_ob
    ):

        entry_min = bearish_ob["low"]
        entry_max = bearish_ob["high"]

        stop_loss = max(
            bearish_ob["high"]
            + atr * 0.35,
            current_price
            + atr * 0.80,
        )

        risk = max(
            stop_loss
            - current_price,
            atr * 0.50,
        )

        tp1 = (
            current_price
            - risk * 1.20
        )

        tp2 = (
            current_price
            - risk * 2.00
        )

        tp3 = (
            current_price
            - risk * 3.00
        )

        if support < current_price:

            tp1 = max(
                tp1,
                support,
            )

    # =====================================================
    # INVALIDATE BAD ENTRY
    # =====================================================

    if direction == "LONG":

        if (
            resistance_distance <= 0.12
            or stop_loss is None
            or stop_loss >= current_price
        ):

            direction = "WAIT"

            state = (
                "REVERSAL WATCH - السعر قريب من المقاومة"
            )

            entry_min = None
            entry_max = None

            stop_loss = None

            tp1 = None
            tp2 = None
            tp3 = None

    elif direction == "SHORT":

        if (
            support_distance <= 0.12
            or stop_loss is None
            or stop_loss <= current_price
        ):

            direction = "WAIT"

            state = (
                "REVERSAL WATCH - السعر قريب من الدعم"
            )

            entry_min = None
            entry_max = None

            stop_loss = None

            tp1 = None
            tp2 = None
            tp3 = None

    # =====================================================
    # BUY PRESSURE
    # =====================================================

    if liquidity_state == "INFLOW":

        buy_pressure = (
            60
            + min(
                volume_ratio * 6,
                25,
            )
        )

    elif liquidity_state == "OUTFLOW":

        buy_pressure = (
            40
            - min(
                volume_ratio * 5,
                25,
            )
        )

    else:

        buy_pressure = 50

    buy_pressure = round(
        max(
            5,
            min(
                95,
                buy_pressure,
            ),
        ),
        1,
    )

    # =====================================================
    # FINAL SCORE
    # =====================================================

    final_score = int(
        max(
            0,
            min(
                100,
                entry_score,
            ),
        )
    )

    logger.info(
        "ANALYSIS COMPLETE | %s | direction=%s | score=%s | L=%s | S=%s",
        symbol,
        direction,
        final_score,
        long_score,
        short_score,
    )

    # =====================================================
    # RETURN
    # =====================================================

    return {

        "symbol": symbol,

        "direction": direction,

        "score": final_score,

        "entry_score": final_score,

        "state": state,

        "price": smart_round(
            current_price
        ),

        "rsi": rsi,

        "volume_ratio": volume_ratio,

        "volume_trend": volume_trend,

        "liquidity_state": liquidity_state,

        "liquidity_score": liquidity_score,

        "bottom_detected": bottom_detected,

        "bottom_score": bottom_score,

        "drawdown": 0,

        "buy_pressure": buy_pressure,

        "trend": (
            "UP"
            if trend_4h == "LONG"
            else
            "DOWN"
            if trend_4h == "SHORT"
            else
            "NEUTRAL"
        ),

        "trend_1d": trend_1d,

        "trend_4h": trend_4h,

        "trend_1h": trend_1h,

        "trend_30m": trend_30m,

        "trend_15m": trend_15m,

        "structure": structure[
            "structure"
        ],

        "bos": structure["bos"],

        "liquidity_zone": structure[
            "liquidity_zone"
        ],

        "bullish_ob": bullish_ob,

        "bearish_ob": bearish_ob,

        "bullish_ob_4h": bullish_ob_4h,

        "bearish_ob_4h": bearish_ob_4h,

        "bullish_ob_distance": round(
            bullish_ob_distance,
            2,
        ),

        "bearish_ob_distance": round(
            bearish_ob_distance,
            2,
        ),

        "bullish_ob_retest": bullish_retest,

        "bearish_ob_retest": bearish_retest,

        "recent_change_2": round(
            recent_change_2,
            2,
        ),

        "recent_change_6": round(
            recent_change_6,
            2,
        ),

        "crash_detected": crash_detected,

        "pump_detected": pump_detected,

        "entry_min": (
            smart_round(
                entry_min
            )
            if entry_min is not None
            else None
        ),

        "entry_max": (
            smart_round(
                entry_max
            )
            if entry_max is not None
            else None
        ),

        "stop_loss": (
            smart_round(
                stop_loss
            )
            if stop_loss is not None
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

        "support": smart_round(
            support
        ),

        "resistance": smart_round(
            resistance
        ),

        "support_distance": round(
            support_distance,
            2,
        ),

        "resistance_distance": round(
            resistance_distance,
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

        "analysis_lines": analysis_lines,

        "liquidity_reasons": liquidity_reasons,

        "bottom_reasons": bottom_reasons,

        "structure_reasons": structure[
            "reasons"
        ],

        "bullish_retest_reasons": (
            bullish_retest_reasons
        ),

        "bearish_retest_reasons": (
            bearish_retest_reasons
        ),

        "rejection_reasons": list(
            dict.fromkeys(
                rejection_reasons
            )
        ),
    }


# =========================================================
# TOP FUTURES
# =========================================================

def get_top_futures_symbols(
    limit=30,
):

    symbols = get_futures_symbols()

    if not symbols:
        return []

    data = bingx_get(
        "/openApi/swap/v2/quote/ticker",
        timeout=12,
        retries=2,
    )

    if not data:

        logger.warning(
            "TICKER UNAVAILABLE - using contract list"
        )

        return list(symbols)[:limit]

    rows = data.get("data")

    if not isinstance(rows, list):

        return list(symbols)[:limit]

    candidates = []

    for item in rows:

        if not isinstance(item, dict):
            continue

        symbol = str(
            item.get(
                "symbol",
                "",
            )
        ).upper()

        symbol = (
            symbol
            .replace("-", "")
            .replace("_", "")
            .replace("/", "")
        )

        if symbol not in symbols:
            continue

        if not symbol.endswith(
            "USDT"
        ):
            continue

        try:

            volume = float(
                item.get(
                    "quoteVolume",
                    item.get(
                        "volume",
                        0,
                    ),
                )
            )

            change = abs(
                float(
                    item.get(
                        "priceChangePercent",
                        0,
                    )
                )
            )

            if volume <= 0:
                continue

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
                    symbol,
                    score,
                )
            )

        except (
            TypeError,
            ValueError,
        ):
            continue

    candidates.sort(
        key=lambda x: x[1],
        reverse=True,
    )

    result = [
        symbol
        for symbol, _
        in candidates[:limit]
    ]

    # -------------------------------------------------
    # If ticker parsing gives nothing,
    # don't stop the scanner.
    # -------------------------------------------------

    if not result:

        logger.warning(
            "TOP FUTURES TICKER PARSE EMPTY - fallback contracts"
        )

        return list(symbols)[:limit]

    return result


# =========================================================
# FAST STAGE
# =========================================================

def _stage1_score(symbol):

    try:

        current = get_current_price(
            symbol
        )

        if current is None:

            logger.warning(
                "STAGE1 PRICE FAILED | %s",
                symbol,
            )

            return None

        k4h = get_bingx_klines(
            symbol,
            "4h",
            80,
        )

        k1h = get_bingx_klines(
            symbol,
            "1h",
            100,
        )

        if not k1h:

            logger.warning(
                "STAGE1 1H FAILED | %s",
                symbol,
            )

            return None

        t4 = calculate_timeframe_trend(
            k4h
        )

        t1 = calculate_timeframe_trend(
            k1h
        )

        obs = detect_order_blocks(
            k1h
        )

        bullish = obs[
            "bullish"
        ]

        bearish = obs[
            "bearish"
        ]

        ob_score = 0

        if bullish:

            ob_score = max(
                ob_score,
                bullish[0][
                    "strength"
                ],
            )

        if bearish:

            ob_score = max(
                ob_score,
                bearish[0][
                    "strength"
                ],
            )

        score = 0

        if bullish:
            score += 45

        if bearish:
            score += 45

        if t4 in (
            "LONG",
            "SHORT",
        ):
            score += 20

        if t1 in (
            "LONG",
            "SHORT",
        ):
            score += 10

        return (
            symbol,
            score + ob_score,
            bool(bullish),
            bool(bearish),
            t4,
            t1,
        )

    except Exception as exc:

        logger.exception(
            "STAGE1 FAILED | %s | %s",
            symbol,
            exc,
        )

        return None


# =========================================================
# MARKET SCAN
# =========================================================

def scan_market(
    limit=5,
):

    logger.info(
        "========== MARKET SCAN START =========="
    )

    universe = get_top_futures_symbols(
        30
    )

    if not universe:

        logger.error(
            "MARKET SCAN FAILED - NO UNIVERSE"
        )

        return []

    logger.info(
        "SCAN UNIVERSE | %s symbols",
        len(universe),
    )

    stage1 = []

    for symbol in universe:

        with _RATE_LOCK:

            if (
                time.time()
                < _RATE_LIMIT_UNTIL
            ):
                logger.warning(
                    "SCAN STOPPED BY RATE LIMIT"
                )
                break

        item = _stage1_score(
            symbol
        )

        if item:

            stage1.append(
                item
            )

    stage1.sort(
        key=lambda x: x[1],
        reverse=True,
    )

    # -------------------------------------------------
    # If stage1 failed completely,
    # directly test first symbols.
    # -------------------------------------------------

    if not stage1:

        logger.warning(
            "STAGE1 EMPTY - DIRECT ANALYSIS FALLBACK"
        )

        shortlist = universe[
            :min(
                5,
                len(universe),
            )
        ]

    else:

        shortlist = [
            item[0]
            for item in stage1[:10]
        ]

    logger.info(
        "FINAL SHORTLIST | %s",
        shortlist,
    )

    results = []

    for symbol in shortlist:

        with _RATE_LOCK:

            if (
                time.time()
                < _RATE_LIMIT_UNTIL
            ):
                logger.warning(
                    "FULL SCAN STOPPED BY RATE LIMIT"
                )
                break

        try:

            data = get_coin_analysis(
                symbol
            )

            if not data:

                logger.warning(
                    "NO ANALYSIS RESULT | %s",
                    symbol,
                )

                continue

            state = data.get(
                "state",
                "",
            )

            direction = data.get(
                "direction"
            )

            keep = (
                direction
                in (
                    "LONG",
                    "SHORT",
                    "WAIT",
                )
                or
                "REVERSAL WATCH"
                in state
                or
                "ACCUMULATION WATCH"
                in state
            )

            if not keep:
                continue

            if data.get(
                "crash_detected"
            ):
                continue

            results.append(
                data
            )

        except Exception as exc:

            logger.exception(
                "FULL ANALYSIS FAILED | %s | %s",
                symbol,
                exc,
            )

    def rank(item):

        state = item.get(
            "state",
            "",
        )

        if (
            "ENTRY READY"
            in state
        ):
            state_rank = 3

        elif (
            "REVERSAL WATCH"
            in state
        ):
            state_rank = 2

        elif (
            "ACCUMULATION WATCH"
            in state
        ):
            state_rank = 1

        else:
            state_rank = 0

        return (
            state_rank,
            item.get(
                "entry_score",
                0,
            ),
            item.get(
                "bullish_ob_retest",
                False,
            ),
            item.get(
                "bearish_ob_retest",
                False,
            ),
            item.get(
                "liquidity_score",
                0,
            ),
        )

    results.sort(
        key=rank,
        reverse=True,
    )

    logger.info(
        "========== MARKET SCAN COMPLETE | results=%s ==========",
        len(results),
    )

    return results[:limit]


# =========================================================
# REPORT HELPERS
# =========================================================

def _ob_text(ob):

    if not ob:
        return "غير موجود"

    return (
        f"{smart_round(ob['low'])} - "
        f"{smart_round(ob['high'])}"
    )


# =========================================================
# REPORT
# =========================================================

def generate_evidence_report(
    data,
):

    if not data:

        return (
            "⚠️ تعذر إكمال التحليل.\n"
            "لم يتم استلام بيانات صالحة من محرك التحليل."
        )

    direction = data.get(
        "direction",
        "WAIT",
    )

    if direction == "LONG":
        emoji = "🟢"

    elif direction == "SHORT":
        emoji = "🔴"

    else:
        emoji = "🟡"

    liquidity_state = data.get(
        "liquidity_state",
        "NEUTRAL",
    )

    if liquidity_state == "INFLOW":

        liquidity = (
            "🟢 دخول سيولة محتمل"
        )

    elif liquidity_state == "OUTFLOW":

        liquidity = (
            "🔴 خروج سيولة محتمل"
        )

    else:

        liquidity = (
            "🟡 سيولة محايدة"
        )

    bos = data.get(
        "bos",
        "NONE",
    )

    if bos == "BULLISH_BOS":

        bos_text = "🟢 BULLISH"

    elif bos == "BEARISH_BOS":

        bos_text = "🔴 BEARISH"

    else:

        bos_text = "⚪ NONE"

    bottom = (
        "🟢 نعم"
        if data.get(
            "bottom_detected"
        )
        else
        "🟡 غير مؤكد"
    )

    if direction in (
        "LONG",
        "SHORT",
    ):

        decision = "جاهز للدخول"

    else:

        decision = (
            "انتظار Retest/BOS"
        )

    lines = [

        "🤖 BingX AI Scanner",
        "",

        f"💎 العملة: {data.get('symbol', '-')}",

        f"💰 السعر الحالي: {data.get('price', '-')}",

        f"📈 الاتجاه النهائي: {emoji} {direction}",

        f"⭐ Entry Score: {data.get('entry_score', 0)}/100",

        "",

        f"🧠 الحالة: {data.get('state', '-')}",

        f"🧭 القرار: {decision}",

        "",

        "🏦 ORDER BLOCK = المحرك الأساسي",

        f"🟢 Bullish OB 1H: {_ob_text(data.get('bullish_ob'))}",

        f"🔴 Bearish OB 1H: {_ob_text(data.get('bearish_ob'))}",

        f"📊 Bullish OB 4H: {_ob_text(data.get('bullish_ob_4h'))}",

        f"📊 Bearish OB 4H: {_ob_text(data.get('bearish_ob_4h'))}",

        f"🔄 Bullish OB Retest: {'YES' if data.get('bullish_ob_retest') else 'NO'}",

        f"🔄 Bearish OB Retest: {'YES' if data.get('bearish_ob_retest') else 'NO'}",

        "",

        "📊 Context",

        f"1D: {data.get('trend_1d', 'UNKNOWN')}",

        f"4H: {data.get('trend_4h', 'UNKNOWN')}",

        "",

        "⏱️ Confirmation",

        f"1H: {data.get('trend_1h', 'UNKNOWN')}",

        f"30m: {data.get('trend_30m', 'UNKNOWN')}",

        f"15m: {data.get('trend_15m', 'UNKNOWN')}",

        "",

        "🏗️ Market Structure",

        f"Structure: {data.get('structure', 'UNKNOWN')}",

        f"BOS: {bos_text}",

        "",

        f"💧 Liquidity: {liquidity}",

        f"📊 Volume: {data.get('volume_ratio', 1.0)}x",

        f"📈 Volume Trend: {data.get('volume_trend', 'NEUTRAL')}",

        f"💪 Buy Pressure: {data.get('buy_pressure', 50)}%",

        f"📊 RSI: {data.get('rsi', 50)}",

        "",

        f"🎯 Accumulation: {bottom}",

        "",

        "🛡️ Support / Resistance",

        f"🟢 Support: {data.get('support', 0)}",

        f"🔴 Resistance: {data.get('resistance', 0)}",

        f"📏 Support Distance: {data.get('support_distance', 999)}%",

        f"📏 Resistance Distance: {data.get('resistance_distance', 999)}%",

        "",
    ]

    # -----------------------------------------------------
    # ENTRY
    # -----------------------------------------------------

    if direction in (
        "LONG",
        "SHORT",
    ):

        lines += [

            "📍 منطقة الدخول",

            f"{data.get('entry_min')} - {data.get('entry_max')}",

            "",

            f"🛑 Stop Loss: {data.get('stop_loss')}",

            "",

            "🎯 الأهداف",

            f"TP1: {data.get('tp1')}",

            f"TP2: {data.get('tp2')}",

            f"TP3: {data.get('tp3')}",

            "",
        ]

    else:

        lines += [

            "📍 منطقة الدخول",

            "⏳ انتظار Retest / BOS",

            "",

            "🛑 Stop Loss: غير محدد",

            "",

            "🎯 الأهداف",

            "TP1: غير محدد",

            "TP2: غير محدد",

            "TP3: غير محدد",

            "",
        ]

    # -----------------------------------------------------
    # MOVEMENT
    # -----------------------------------------------------

    lines += [

        "📊 الحركة الأخيرة",

        f"آخر شمعتين تقريباً: {data.get('recent_change_2', 0)}%",

        f"آخر 6 شموع تقريباً: {data.get('recent_change_6', 0)}%",

        "",

        "🔍 أسباب القرار",
    ]

    for line in data.get(
        "analysis_lines",
        [],
    )[:10]:

        lines.append(
            f"• {line}"
        )

    # -----------------------------------------------------
    # RETEST
    # -----------------------------------------------------

    retest_reasons = (
        data.get(
            "bullish_retest_reasons",
            [],
        )
        +
        data.get(
            "bearish_retest_reasons",
            [],
        )
    )

    if retest_reasons:

        lines += [
            "",
            "🔄 أدلة Retest",
        ]

        for reason in retest_reasons[:4]:

            lines.append(
                f"• {reason}"
            )

    # -----------------------------------------------------
    # STRUCTURE
    # -----------------------------------------------------

    structure_reasons = data.get(
        "structure_reasons",
        [],
    )

    if structure_reasons:

        lines += [
            "",
            "🏗️ أدلة الهيكل",
        ]

        for reason in structure_reasons[:4]:

            lines.append(
                f"• {reason}"
            )

    # -----------------------------------------------------
    # LIQUIDITY
    # -----------------------------------------------------

    liquidity_reasons = data.get(
        "liquidity_reasons",
        [],
    )

    if liquidity_reasons:

        lines += [
            "",
            "💧 أدلة السيولة",
        ]

        for reason in liquidity_reasons[:4]:

            lines.append(
                f"• {reason}"
            )

    # -----------------------------------------------------
    # REJECTION
    # -----------------------------------------------------

    rejection_reasons = data.get(
        "rejection_reasons",
        [],
    )

    if rejection_reasons:

        lines += [
            "",
            "🚫 لماذا لم يدخل؟",
        ]

        for reason in rejection_reasons[:8]:

            lines.append(
                f"• {reason}"
            )

    # -----------------------------------------------------
    # FOOTER
    # -----------------------------------------------------

    lines += [

        "",

        "🛡️ ORDER BLOCK هو العامل الأساسي.",

        "⚠️ 1D = Context.",

        "⚠️ 4H = MTF Order Block.",

        "⚠️ 1H = Primary Order Block.",

        "⚠️ 30m + 15m = Confirmation.",

        "⚠️ BOS + Liquidity + Volume = تأكيدات.",

        "⚠️ لا يتم اعتبار الشموع وحدها سبباً للدخول.",

        "⚠️ الإشارة تحليلية وليست ضماناً للربح.",
    ]

    return "\n".join(lines)
