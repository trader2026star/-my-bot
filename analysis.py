# =========================================================
# COIN ANALYSIS - 4H MASTER DIRECTION
# =========================================================

def get_coin_analysis(symbol):

    symbol = normalize_symbol(symbol)

    if not symbol_exists(symbol):

        logger.info(
            "Symbol not found on BingX: %s",
            symbol
        )

        return None

    # =====================================================
    # 1H DATA
    # =====================================================

    klines_1h = get_bingx_klines(
        symbol,
        "1h",
        200
    )

    if not klines_1h:
        return None

    # =====================================================
    # ONLY 4H
    # 4H IS THE MASTER TREND
    # =====================================================

    klines_4h = get_bingx_klines(
        symbol,
        "4h",
        120
    )

    if not klines_4h:
        return None

    # =====================================================
    # 1H INDICATORS
    # =====================================================

    closes = [
        k[4]
        for k in klines_1h
    ]

    volumes = [
        k[5]
        for k in klines_1h
    ]

    current = closes[-1]

    ema9 = calculate_ema(
        closes,
        9
    )

    ema20 = calculate_ema(
        closes,
        20
    )

    ema50 = calculate_ema(
        closes,
        50
    )

    if None in (
        ema9,
        ema20,
        ema50
    ):

        return None

    rsi = calculate_rsi(
        closes
    )

    volume_ratio = calculate_volume_ratio(
        volumes,
        20
    )

    volume_trend = calculate_volume_trend(
        volumes
    )

    atr = calculate_atr(
        klines_1h
    )

    support, resistance = (
        calculate_support_resistance(
            klines_1h
        )
    )

    # =====================================================
    # 4H MASTER TREND
    # =====================================================

    trend_4h = calculate_timeframe_trend(
        klines_4h
    )

    # =====================================================
    # IMPORTANT:
    # 4H NEUTRAL = NO TRADE
    # =====================================================

    if trend_4h == "UNKNOWN":

        return None

    if trend_4h == "NEUTRAL":

        return None

    # =====================================================
    # BOTTOM
    # =====================================================

    bottom_detected, bottom_score, bottom_reasons = (
        detect_bottom_accumulation(
            klines_1h
        )
    )

    # =====================================================
    # LIQUIDITY
    # =====================================================

    liquidity_state, liquidity_score, liquidity_reasons = (
        detect_liquidity_flow(
            klines_1h
        )
    )

    drawdown = calculate_recent_drawdown(
        closes
    )

    support_distance = (
        abs(current - support)
        / current * 100
    )

    resistance_distance = (
        abs(resistance - current)
        / current * 100
    )

    # =====================================================
    # SCORING
    # =====================================================

    long_score = 0
    short_score = 0

    analysis_lines = []

    # =====================================================
    # EMA
    # =====================================================

    if ema9 > ema20:

        long_score += 8

        analysis_lines.append(
            "EMA9 أعلى من EMA20"
        )

    else:

        short_score += 8

        analysis_lines.append(
            "EMA9 أسفل EMA20"
        )

    if ema20 > ema50:

        long_score += 8

        analysis_lines.append(
            "EMA20 أعلى من EMA50"
        )

    else:

        short_score += 8

        analysis_lines.append(
            "EMA20 أسفل EMA50"
        )

    # =====================================================
    # RSI
    # =====================================================

    if 40 <= rsi <= 62:

        long_score += 8

        analysis_lines.append(
            "RSI مناسب لسيناريو صاعد"
        )

    elif rsi < 35:

        long_score += 10

        analysis_lines.append(
            "RSI منخفض وقد توجد فرصة ارتداد"
        )

    elif rsi > 70:

        short_score += 10

        analysis_lines.append(
            "RSI مرتفع واحتمال تصحيح"
        )

    elif rsi >= 62:

        short_score += 3

    # =====================================================
    # VOLUME
    # =====================================================

    if volume_ratio >= 1.20:

        if ema9 >= ema20:

            long_score += 8

            analysis_lines.append(
                "حجم مرتفع مع تحسن سعري"
            )

        else:

            short_score += 8

            analysis_lines.append(
                "حجم مرتفع مع ضغط هابط"
            )

    if volume_trend == "RISING":

        if ema9 >= ema20:

            long_score += 5

        else:

            short_score += 5

    # =====================================================
    # LIQUIDITY
    # =====================================================

    if liquidity_state == "INFLOW":

        long_score += 15

        analysis_lines.append(
            "دخول سيولة محتمل"
        )

    elif liquidity_state == "OUTFLOW":

        short_score += 15

        analysis_lines.append(
            "خروج سيولة محتمل"
        )

    # =====================================================
    # BOTTOM
    # =====================================================

    if bottom_detected:

        long_score += 15

        analysis_lines.append(
            "تم رصد بنية قاع/تجميع مبكرة"
        )

        for reason in bottom_reasons[:3]:

            analysis_lines.append(
                f"قاع: {reason}"
            )

    # =====================================================
    # SUPPORT
    # =====================================================

    if support_distance <= 4:

        long_score += 8

        analysis_lines.append(
            "السعر قريب من الدعم"
        )

    if support_distance <= 1.5:

        long_score += 5

        analysis_lines.append(
            "السعر قريب جدًا من الدعم"
        )

    # =====================================================
    # RESISTANCE
    # =====================================================

    if resistance_distance <= 4:

        short_score += 6

    if resistance_distance <= 1.5:

        long_score -= 15

        analysis_lines.append(
            "السعر قريب جدًا من المقاومة"
        )

    # =====================================================
    # RECENT MOVE
    # =====================================================

    recent_change = percentage_change(
        closes[-6],
        current
    )

    if recent_change >= 8:

        long_score -= 20

        analysis_lines.append(
            "ارتفاع سريع؛ لا تطارد البمب"
        )

    if recent_change <= -8:

        short_score -= 15

        analysis_lines.append(
            "هبوط سريع؛ لا تطارد الشورت"
        )

    # =====================================================
    # 4H MASTER FILTER
    # =====================================================
    #
    # هنا أهم تعديل:
    #
    # لو 4H LONG:
    # لا يمكن إطلاق SHORT مهما كانت النقاط.
    #
    # لو 4H SHORT:
    # لا يمكن إطلاق LONG مهما كانت النقاط.
    #
    # =====================================================

    if trend_4h == "LONG":

        direction = "LONG"

        score = long_score

        trend = "UP"

        # لو أغلب الأدلة ضد الاتجاه
        # لا ندخل الصفقة

        if short_score > long_score + 12:

            direction = "WAIT"

            score = max(
                long_score,
                short_score
            )

            state = (
                "4H صاعد لكن الأدلة الداخلية متضاربة"
            )

        elif (
            bottom_detected
            and
            liquidity_state == "INFLOW"
        ):

            state = (
                "4H صاعد + قاع/تجميع + دخول سيولة"
            )

        elif bottom_detected:

            state = (
                "4H صاعد + تجميع مبكر"
            )

        elif liquidity_state == "INFLOW":

            state = (
                "4H صاعد + دخول سيولة محتمل"
            )

        else:

            state = (
                "4H صاعد + انتظار تأكيد الدخول"
            )

    elif trend_4h == "SHORT":

        direction = "SHORT"

        score = short_score

        trend = "DOWN"

        # لو أغلب الأدلة ضد الاتجاه
        # لا ندخل الشورت

        if long_score > short_score + 12:

            direction = "WAIT"

            score = max(
                long_score,
                short_score
            )

            state = (
                "4H هابط لكن الأدلة الداخلية متضاربة"
            )

        elif liquidity_state == "OUTFLOW":

            state = (
                "4H هابط + خروج سيولة"
            )

        else:

            state = (
                "4H هابط + انتظار تأكيد الشورت"
            )

    else:

        direction = "WAIT"

        score = 0

        trend = "NEUTRAL"

        state = (
            "4H غير واضح؛ لا توجد صفقة"
        )

    # =====================================================
    # SCORE LIMIT
    # =====================================================

    score = int(
        max(
            0,
            min(
                100,
                score
            )
        )
    )

    # =====================================================
    # ENTRY / SL / TP
    # =====================================================

    if not atr or atr <= 0:

        atr = current * 0.01

    # =====================================================
    # LONG
    # =====================================================

    if direction == "LONG":

        entry_min = max(
            support,
            current - atr * 0.35
        )

        entry_max = current

        stop_loss = min(
            support - atr * 0.35,
            current - atr * 1.2
        )

        risk = current - stop_loss

        if risk <= 0:

            risk = atr

        tp1 = current + risk * 1.2
        tp2 = current + risk * 2.2
        tp3 = current + risk * 3.5

        # لا نجعل TP1 يتجاوز المقاومة
        if resistance > current:

            tp1 = min(
                tp1,
                resistance
            )

    # =====================================================
    # SHORT
    # =====================================================

    elif direction == "SHORT":

        entry_min = current

        entry_max = min(
            resistance,
            current + atr * 0.35
        )

        stop_loss = max(
            resistance + atr * 0.35,
            current + atr * 1.2
        )

        risk = stop_loss - current

        if risk <= 0:

            risk = atr

        tp1 = current - risk * 1.2
        tp2 = current - risk * 2.2
        tp3 = current - risk * 3.5

        # لا نجعل TP1 يتجاوز الدعم
        if support < current:

            tp1 = max(
                tp1,
                support
            )

    # =====================================================
    # WAIT
    # =====================================================

    else:

        entry_min = current
        entry_max = current

        stop_loss = current

        tp1 = current
        tp2 = current
        tp3 = current

    # =====================================================
    # BUY PRESSURE
    # =====================================================

    if liquidity_state == "INFLOW":

        buy_pressure = (
            65
            + min(
                volume_ratio * 5,
                20
            )
        )

    elif liquidity_state == "OUTFLOW":

        buy_pressure = (
            35
            - min(
                volume_ratio * 3,
                15
            )
        )

    else:

        buy_pressure = 50

    buy_pressure = round(
        max(
            5,
            min(
                95,
                buy_pressure
            )
        ),
        1
    )

    # =====================================================
    # RETURN
    # =====================================================

    return {

        "symbol": symbol,

        "direction": direction,

        "score": score,

        "state": state,

        "price": smart_round(
            current
        ),

        "rsi": rsi,

        "volume_ratio": volume_ratio,

        "volume_trend": volume_trend,

        "liquidity_state":
            liquidity_state,

        "liquidity_score":
            liquidity_score,

        "bottom_detected":
            bottom_detected,

        "bottom_score":
            bottom_score,

        "drawdown":
            drawdown,

        "buy_pressure":
            buy_pressure,

        "trend":
            trend,

        # فقط 4H
        "trend_4h":
            trend_4h,

        "entry_min":
            smart_round(entry_min),

        "entry_max":
            smart_round(entry_max),

        "stop_loss":
            smart_round(stop_loss),

        "tp1":
            smart_round(tp1),

        "tp2":
            smart_round(tp2),

        "tp3":
            smart_round(tp3),

        "support":
            smart_round(support),

        "resistance":
            smart_round(resistance),

        "support_distance":
            round(
                support_distance,
                2
            ),

        "resistance_distance":
            round(
                resistance_distance,
                2
            ),

        "analysis_lines":
            analysis_lines,

        "liquidity_reasons":
            liquidity_reasons,

        "bottom_reasons":
            bottom_reasons
    }


# =========================================================
# SCANNER - STRICT 4H FILTER
# =========================================================

def scan_market(
    limit=5
):

    symbols = get_top_futures_symbols(
        20
    )

    if not symbols:

        return []

    results = []

    for symbol in symbols:

        if time.time() < _RATE_LIMIT_UNTIL:

            logger.warning(
                "Stopping scanner because BingX rate limit is active."
            )

            break

        try:

            data = get_coin_analysis(
                symbol
            )

            if not data:
                continue

            # =================================================
            # STRICT 4H DIRECTION
            # =================================================

            if data["trend_4h"] not in (
                "LONG",
                "SHORT"
            ):

                continue

            # =================================================
            # NEVER TRADE AGAINST 4H
            # =================================================

            if (
                data["direction"]
                != data["trend_4h"]
            ):

                continue

            # =================================================
            # LONG
            # =================================================

            if data["direction"] == "LONG":

                # لازم يكون فيه دليل واحد على الأقل
                # بجانب اتجاه 4H

                confirmation = (
                    data["bottom_detected"]
                    or
                    data["liquidity_state"]
                    == "INFLOW"
                    or
                    data["volume_ratio"]
                    >= 1.10
                    or
                    data["rsi"]
                    >= 40
                )

                if not confirmation:

                    continue

                if data["score"] < 48:

                    continue

            # =================================================
            # SHORT
            # =================================================

            elif data["direction"] == "SHORT":

                confirmation = (
                    data["liquidity_state"]
                    == "OUTFLOW"
                    or
                    data["volume_ratio"]
                    >= 1.10
                    or
                    data["rsi"]
                    >= 65
                )

                if not confirmation:

                    continue

                if data["score"] < 48:

                    continue

            # =================================================
            # PRE-PUMP PROTECTION
            # =================================================

            if (
                data["direction"]
                == "LONG"
                and
                data["drawdown"]
                > -2
                and
                data["volume_ratio"]
                > 2.5
            ):

                continue

            results.append(
                data
            )

        except Exception as exc:

            logger.exception(
                "Analysis failed for %s: %s",
                symbol,
                exc
            )

        # حماية BingX
        time.sleep(0.40)

    # =====================================================
    # RANK
    # =====================================================

    results.sort(
        key=lambda x: (
            x["score"],

            1
            if x["trend_4h"] == x["direction"]
            else 0,

            1
            if x["bottom_detected"]
            else 0,

            1
            if x["liquidity_state"]
            == "INFLOW"
            else 0,

            x["buy_pressure"]
        ),
        reverse=True
    )

    return results[:limit]
