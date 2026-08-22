def scan_market(limit=15):

    tickers = get_tickers()

    if not tickers:
        print("SCAN: NO TICKERS")
        return []

    candidates = []

    for ticker in tickers:

        symbol = ticker.get("symbol", "")

        if not symbol.endswith("USDT"):
            continue

        if any(x in symbol for x in [
            "UPUSDT",
            "DOWNUSDT",
            "BULLUSDT",
            "BEARUSDT"
        ]):
            continue

        try:
            quote_volume = float(
                ticker.get("quoteVolume", 0)
            )

            daily_change = float(
                ticker.get("priceChangePercent", 0)
            )

        except Exception:
            continue

        # سيولة حقيقية
        if quote_volume < 500_000:
            continue

        candidates.append({
            "symbol": symbol,
            "quote_volume": quote_volume,
            "daily_change": daily_change
        })

    if not candidates:
        print("SCAN: NO CANDIDATES")
        return []

    # =====================================================
    # اختيار العملات الأفضل من ناحية السيولة والحركة
    # =====================================================

    candidates.sort(
        key=lambda x: (
            x["quote_volume"],
            abs(x["daily_change"])
        ),
        reverse=True
    )

    # نفحص عدد محدود حتى لا نقتل Render المجاني
    candidates = candidates[:limit]

    results = []

    for item in candidates:

        symbol = item["symbol"]

        try:

            result = analyze_symbol(symbol)

            if not result:
                continue

            result["quote_volume"] = item[
                "quote_volume"
            ]

            result["daily_change"] = item[
                "daily_change"
            ]

            # =================================================
            # لا نستبعد WAIT هنا
            # لأننا نريد أفضل فرص السوق وليس فقط الإشارات القوية
            # =================================================

            results.append(result)

        except Exception as e:

            print(
                "SCAN ERROR:",
                symbol,
                repr(e)
            )

        time.sleep(0.05)

    if not results:
        print("SCAN: ANALYSIS RETURNED NOTHING")
        return []

    # =====================================================
    # RANKING
    # =====================================================

    def rank(result):

        long_score = result.get(
            "long_score",
            0
        )

        short_score = result.get(
            "short_score",
            0
        )

        direction_score = max(
            long_score,
            short_score
        )

        difference = abs(
            long_score - short_score
        )

        signal = result.get(
            "signal",
            "WAIT"
        )

        # الإشارة القوية تأخذ أفضلية
        signal_bonus = {
            "EARLY_LONG": 50,
            "SHORT": 50,
            "WATCH_LONG": 30,
            "WATCH_SHORT": 30,
            "WAIT": 5
        }.get(
            signal,
            0
        )

        # التجميع المبكر مهم جدًا
        accumulation_bonus = (
            20
            if result.get("accumulation")
            else 0
        )

        # نخفض ترتيب العملات التي دخلت Pump متأخر
        late_pump_penalty = (
            25
            if result.get("late_pump")
            else 0
        )

        # توزيع = تحذير مهم
        distribution_bonus = (
            10
            if result.get("distribution")
            else 0
        )

        # السيولة
        liquidity = result.get(
            "quote_volume",
            0
        )

        liquidity_bonus = min(
            15,
            liquidity / 5_000_000
        )

        return (
            direction_score
            + difference
            + signal_bonus
            + accumulation_bonus
            + distribution_bonus
            + liquidity_bonus
            - late_pump_penalty
        )

    results.sort(
        key=rank,
        reverse=True
    )

    # =====================================================
    # IMPORTANT
    # لو مفيش صفقة قوية:
    # نرجع أفضل فرص السوق بدل رسالة "مفيش صفقات"
    # =====================================================

    strong = [
        r for r in results
        if r["signal"] in (
            "EARLY_LONG",
            "SHORT",
            "WATCH_LONG",
            "WATCH_SHORT"
        )
    ]

    if strong:
        return strong[:8]

    # =====================================================
    # FALLBACK
    # أفضل 3 عملات حتى لو WAIT
    # =====================================================

    return results[:3]
