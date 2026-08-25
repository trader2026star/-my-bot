    # =====================================================
    # FINAL DECISION ENGINE
    # 4H = MASTER DIRECTION
    # 1H + STRUCTURE + LIQUIDITY + VOLUME = ENTRY GATE
    # =====================================================

    direction = "NO TRADE"
    score = 0
    state = "لا توجد صفقة"
    trend = "NEUTRAL"

    # -----------------------------------------------------
    # ENTRY CONFIRMATION
    # -----------------------------------------------------

    volume_weak = (
        volume_ratio < 0.90
        and volume_trend == "FALLING"
    )

    bullish_1h_confirmation = (
        trend_1h == "LONG"
        or structure["bos"] == "BULLISH_BOS"
        or (
            trend_1h == "NEUTRAL"
            and ema9 > ema20
            and recent_change_2 > 0
        )
    )

    bearish_1h_confirmation = (
        trend_1h == "SHORT"
        or structure["bos"] == "BEARISH_BOS"
        or (
            trend_1h == "NEUTRAL"
            and ema9 < ema20
            and recent_change_2 < 0
        )
    )

    # =====================================================
    # 4H LONG
    # =====================================================

    if trend_4h == "LONG":

        trend = "UP"

        # -------------------------------------------------
        # HARD NO TRADE CONDITIONS
        # -------------------------------------------------

        if crash_detected:

            direction = "NO TRADE"

            state = (
                "NO TRADE - 4H صاعد لكن توجد حركة انهيار سريعة"
            )

        elif trend_1h == "BEARISH" and liquidity_state == "OUTFLOW":

            direction = "NO TRADE"

            state = (
                "NO TRADE - 4H صاعد لكن 1H هابط والسيولة خارجة"
            )

        elif liquidity_state == "OUTFLOW":

            direction = "NO TRADE"

            state = (
                "NO TRADE - 4H صاعد لكن السيولة خارجة"
            )

        elif trend_1h == "BEARISH":

            direction = "NO TRADE"

            state = (
                "NO TRADE - 4H صاعد لكن هيكل 1H هابط"
            )

        elif structure["bos"] == "BEARISH_BOS":

            direction = "NO TRADE"

            state = (
                "NO TRADE - 4H صاعد لكن BOS هابط"
            )

        elif volume_weak:

            direction = "NO TRADE"

            state = (
                "NO TRADE - الحجم ضعيف ويتراجع"
            )

        elif rsi < 20:

            direction = "NO TRADE"

            state = (
                "NO TRADE - RSI منخفض جدًا؛ انتظار ارتداد"
            )

        # -------------------------------------------------
        # LONG ENTRY
        # -------------------------------------------------

        elif (
            bullish_1h_confirmation
            and
            liquidity_state == "INFLOW"
            and
            not volume_weak
            and
            not pump_detected
        ):

            # تأكيد أقوى إذا كان هناك BOS
            if structure["bos"] == "BULLISH_BOS":

                long_score += 20

                analysis_lines.append(
                    "تأكيد BOS صاعد"
                )

            # دخول السيولة شرط أساسي
            long_score += 20

            analysis_lines.append(
                "دخول سيولة يدعم LONG"
            )

            # تحسن 1H
            if trend_1h == "LONG":

                long_score += 15

                analysis_lines.append(
                    "1H يؤكد الاتجاه الصاعد"
                )

            elif ema9 > ema20:

                long_score += 8

                analysis_lines.append(
                    "1H يبدأ في التحسن"
                )

            # Volume
            if volume_trend == "RISING":

                long_score += 10

                analysis_lines.append(
                    "Volume يتحسن"
                )

            elif volume_ratio >= 1.0:

                long_score += 5

            # Buy pressure
            if buy_pressure >= 55:

                long_score += 10

                analysis_lines.append(
                    "ضغط شراء مقبول"
                )

            # RSI عامل مساعد فقط
            if 40 <= rsi <= 65:

                long_score += 5

            # Support
            if support_distance <= 3:

                long_score += 5

                analysis_lines.append(
                    "السعر قريب من الدعم"
                )

            # Bottom ليس سبب دخول
            if bottom_detected:

                analysis_lines.append(
                    "يوجد تجميع محتمل لكنه ليس سبب الدخول"
                )

            if long_score >= 60:

                direction = "LONG"

                score = long_score

                if (
                    structure["bos"]
                    == "BULLISH_BOS"
                    and
                    liquidity_state
                    == "INFLOW"
                ):

                    state = (
                        "LONG - 4H صاعد + 1H مؤكد + BOS صاعد + دخول سيولة"
                    )

                else:

                    state = (
                        "LONG - 4H صاعد + تحسن 1H + دخول سيولة"
                    )

            else:

                direction = "NO TRADE"

                state = (
                    "NO TRADE - الاتجاه صاعد لكن تأكيد الدخول غير كافٍ"
                )

        else:

            direction = "NO TRADE"

            state = (
                "NO TRADE - 4H صاعد لكن شروط دخول LONG غير مكتملة"
            )

    # =====================================================
    # 4H SHORT
    # =====================================================

    elif trend_4h == "SHORT":

        trend = "DOWN"

        # -------------------------------------------------
        # HARD NO TRADE CONDITIONS
        # -------------------------------------------------

        if crash_detected:

            direction = "NO TRADE"

            state = (
                "NO TRADE - 4H هابط لكن يوجد انهيار سريع؛ ممنوع مطاردة الشورت"
            )

        elif trend_1h == "BULLISH" and liquidity_state == "INFLOW":

            direction = "NO TRADE"

            state = (
                "NO TRADE - 4H هابط لكن 1H صاعد والسيولة داخلة"
            )

        elif liquidity_state == "INFLOW":

            direction = "NO TRADE"

            state = (
                "NO TRADE - 4H هابط لكن السيولة تدخل"
            )

        elif trend_1h == "BULLISH":

            direction = "NO TRADE"

            state = (
                "NO TRADE - 4H هابط لكن هيكل 1H صاعد"
            )

        elif structure["bos"] == "BULLISH_BOS":

            direction = "NO TRADE"

            state = (
                "NO TRADE - 4H هابط لكن BOS صاعد"
            )

        elif volume_weak:

            direction = "NO TRADE"

            state = (
                "NO TRADE - الحجم ضعيف ويتراجع"
            )

        elif rsi < 20:

            direction = "NO TRADE"

            state = (
                "NO TRADE - RSI منهار؛ ممنوع مطاردة الشورت"
            )

        elif rsi < 30:

            direction = "NO TRADE"

            state = (
                "NO TRADE - RSI منخفض؛ انتظار تصحيح"
            )

        # -------------------------------------------------
        # SHORT ENTRY
        # -------------------------------------------------

        elif (
            bearish_1h_confirmation
            and
            liquidity_state == "OUTFLOW"
            and
            not volume_weak
        ):

            if structure["bos"] == "BEARISH_BOS":

                short_score += 20

                analysis_lines.append(
                    "تأكيد BOS هابط"
                )

            # خروج السيولة شرط أساسي
            short_score += 20

            analysis_lines.append(
                "خروج سيولة يدعم SHORT"
            )

            # تأكيد 1H
            if trend_1h == "SHORT":

                short_score += 15

                analysis_lines.append(
                    "1H يؤكد الاتجاه الهابط"
                )

            elif ema9 < ema20:

                short_score += 8

                analysis_lines.append(
                    "1H يبدأ في التأكيد الهابط"
                )

            # Volume
            if volume_trend == "RISING":

                short_score += 10

                analysis_lines.append(
                    "Volume يتحسن مع الضغط البيعي"
                )

            elif volume_ratio >= 1.0:

                short_score += 5

            # RSI عامل مساعد فقط
            if 35 <= rsi <= 65:

                short_score += 5

            # Resistance
            if resistance_distance <= 3:

                short_score += 5

                analysis_lines.append(
                    "السعر قريب من المقاومة"
                )

            if short_score >= 60:

                direction = "SHORT"

                score = short_score

                if (
                    structure["bos"]
                    == "BEARISH_BOS"
                    and
                    liquidity_state
                    == "OUTFLOW"
                ):

                    state = (
                        "SHORT - 4H هابط + 1H مؤكد + BOS هابط + خروج سيولة"
                    )

                else:

                    state = (
                        "SHORT - 4H هابط + تأكيد 1H + خروج سيولة"
                    )

            else:

                direction = "NO TRADE"

                state = (
                    "NO TRADE - الاتجاه هابط لكن تأكيد الشورت غير كافٍ"
                )

        else:

            direction = "NO TRADE"

            state = (
                "NO TRADE - 4H هابط لكن شروط دخول SHORT غير مكتملة"
            )

    # =====================================================
    # 4H NEUTRAL
    # =====================================================

    else:

        direction = "NO TRADE"

        trend = "NEUTRAL"

        state = (
            "NO TRADE - 4H محايد؛ لا يوجد اتجاه رئيسي واضح"
        )

    # =====================================================
    # FINAL SCORE
    # =====================================================

    if direction == "LONG":

        score = long_score

    elif direction == "SHORT":

        score = short_score

    else:

        # WAIT لا يعني صفقة ضعيفة
        # لذلك لا نستخدم score كأنه Entry Score
        score = 0

    score = int(
        max(
            0,
            min(
                100,
                score
            )
        )
    )
