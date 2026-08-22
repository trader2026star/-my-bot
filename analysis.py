def build_scan_message(results):

    if not results:

        return (
            "🔥 Crypto Zero Reversal\n\n"
            "⚠️ لم تصل بيانات كافية من Binance.\n\n"
            "أعد /scan بعد لحظات."
        )

    message = (
        "🔥 Crypto Zero Reversal\n"
        "📡 BEST MARKET SETUPS\n\n"
        "15m + 30m + 1H + 4H + 1D\n"
        "💧 Liquidity + Volume + Momentum\n"
        "🎯 Entry / SL / TP\n\n"
    )

    for index, result in enumerate(
        results[:8],
        1
    ):

        signal = result.get(
            "signal",
            "WAIT"
        )

        # =================================================
        # تحديد نوع الفرصة
        # =================================================

        if signal == "EARLY_LONG":
            setup = "🟢 LONG — فرصة قوية"

        elif signal == "WATCH_LONG":
            setup = "🟢 LONG — مراقبة دخول"

        elif signal == "SHORT":
            setup = "🔴 SHORT — فرصة قوية"

        elif signal == "WATCH_SHORT":
            setup = "🔴 SHORT — مراقبة دخول"

        else:
            setup = "⚪ أفضل فرصة متاحة حاليًا"

        message += (
            f"#{index} 🪙 {result['symbol']}\n"
        )

        message += (
            "💰 السعر: "
            + fmt_price(result["price"])
            + "\n"
        )

        message += (
            "🎯 الحالة: "
            + setup
            + "\n"
        )

        message += (
            "🟢 Long: "
            + str(result["long_score"])
            + "/100\n"
        )

        message += (
            "🔴 Short: "
            + str(result["short_score"])
            + "/100\n"
        )

        message += (
            "📊 15m: "
            + tf_direction(
                result["tf15_bull"],
                result["tf15_bear"]
            )
            + "\n"
        )

        message += (
            "📊 30m: "
            + tf_direction(
                result["tf30_bull"],
                result["tf30_bear"]
            )
            + "\n"
        )

        message += (
            "📊 1H: "
            + tf_direction(
                result["tf1h_bull"],
                result["tf1h_bear"]
            )
            + "\n"
        )

        message += (
            "📊 4H: "
            + tf_direction(
                result["tf4h_bull"],
                result["tf4h_bear"]
            )
            + "\n"
        )

        message += (
            "📊 1D: "
            + tf_direction(
                result["tf1d_bull"],
                result["tf1d_bear"]
            )
            + "\n"
        )

        message += (
            "📈 RSI 15m: "
            + fmt_rsi(result["rsi15"])
            + "\n"
        )

        message += (
            "📦 Volume: "
            + "{:.2f}".format(
                result["volume_ratio"]
            )
            + "x\n"
        )

        message += (
            "📈 Volume Trend: "
            + "{:.2f}".format(
                result["volume_trend"]
            )
            + "x\n"
        )

        # =================================================
        # STRUCTURE
        # =================================================

        if result.get("accumulation"):
            message += "🟢 Accumulation: YES\n"

        if result.get("distribution"):
            message += "🔴 Distribution: YES ⚠️\n"

        if result.get("late_pump"):
            message += "🚀 Late Pump: HIGH ⚠️\n"

        if result.get("overheated"):
            message += "🔥 Overheated: YES ⚠️\n"

        # =================================================
        # TRADE
        # =================================================

        trade = prepare_trade(result)

        if trade:

            message += (
                "\n🎯 الصفقة:\n"
            )

            message += (
                "النوع: "
                + trade["side"]
                + "\n"
            )

            message += (
                "Entry: "
                + trade["entry"]
                + "\n"
            )

            message += (
                "SL: "
                + trade["stop"]
                + "\n"
            )

            message += (
                "TP1: "
                + trade["tp1"]
                + "\n"
            )

            message += (
                "TP2: "
                + trade["tp2"]
                + "\n"
            )

            message += (
                "TP3: "
                + trade["tp3"]
                + "\n"
            )

        else:

            message += (
                "\n⏳ لا يوجد دخول آمن الآن.\n"
            )

        # =================================================
        # REASONS
        # =================================================

        if signal in (
            "EARLY_LONG",
            "WATCH_LONG"
        ):

            reasons = result.get(
                "long_reasons",
                []
            )

        elif signal in (
            "SHORT",
            "WATCH_SHORT"
        ):

            reasons = result.get(
                "short_reasons",
                []
            )

        else:

            reasons = []

        if reasons:

            message += (
                "\n🧠 الأسباب:\n"
            )

            for reason in reasons[:5]:

                message += (
                    "• "
                    + str(reason)
                    + "\n"
                )

        message += (
            "\n━━━━━━━━━━━━━━\n\n"
        )

    return message
