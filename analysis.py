    def analyze_market_structure(self, ohlcv_5m, ohlcv_15m, ohlcv_1h=None,
                                 asset_type="crypto", drop_last_candle=True):
        neutral = build_signal(
            direction="NEUTRAL", entry=0.0, stop_loss=0.0,
            take_profits=[], score=0, rsi=50.0, atr=0.0,
            reason="insufficient data or structure conditions not met",
        )
        try:
            if ohlcv_15m is None or len(ohlcv_15m) < 65:
                neutral["reason"] = "insufficient 15m data"
                return "NEUTRAL", 0.0, neutral

            # ---- [تفعيل فلتر الاتجاه العام HTF Trend Filter] ----
            if ohlcv_1h is not None and not self.htf_trend_ok(ohlcv_1h):
                neutral["reason"] = "HTF trend is bearish (blocked by 1H EMA filter)"
                return "NEUTRAL", 0.0, neutral

            df = self.prepare_dataframe(ohlcv_15m)
            if drop_last_candle and len(df) > 1:
                df = df.iloc[:-1].reset_index(drop=True)
            if len(df) < 60:
                neutral["reason"] = "insufficient clean candles"
                return "NEUTRAL", 0.0, neutral

            df["RSI"] = self.calculate_rsi(df["close"])
            df["ATR"] = self.calculate_atr(df)

            last = df.iloc[-1]
            price = float(last["close"])
            atr, rsi = float(last["ATR"]), float(last["RSI"])

            decimals = 8 if price < 0.1 else (6 if price < 1 else (4 if price < 100 else 2))
            reasons = []

            # ---- Run True Bottom & CHoCH Strategy Detection ----
            structure_ok, swing_low, setup_reason = self.detect_true_bottom_and_choch(df)
            if not structure_ok:
                reasons.append("no true bottom / CHoCH structure broken")
                neutral["reason"] = " | ".join(reasons)
                return "NEUTRAL", price, neutral

            # Stop loss below the true bottom swing low with buffer
            stop = swing_low - (0.2 * atr)
            if stop >= price:
                stop = price - (0.8 * atr)

            risk_dist = price - stop

            # 3 Take Profits based on R-multiples
            tp1 = price + (1.5 * risk_dist)
            tp2 = price + (2.5 * risk_dist)
            tp3 = price + (4.0 * risk_dist)
            targets = [tp1, tp2, tp3]

            rr1 = (tp1 - price) / risk_dist
            if rr1 < MIN_RR_TP1:
                reasons.append("R:R too low (%.2f < %.1f)" % (rr1, MIN_RR_TP1))
                neutral["reason"] = " | ".join(reasons)
                return "NEUTRAL", price, neutral

            score = 85
            if score < self.min_score:
                reasons.append("score below threshold")
                neutral["score"] = score
                neutral["reason"] = " | ".join(reasons)
                return "NEUTRAL", price, neutral

            risk = self.calculate_risk_from_levels(price, stop)
            if not risk.get("valid"):
                neutral["reason"] = "risk rejected: " + risk.get("reason", "unknown")
                return "NEUTRAL", price, neutral

            max_entry = price + MAX_CHASE_R * (price - stop)

            signal = build_signal(
                direction="LONG",
                entry=round(price, decimals),
                stop_loss=round(stop, decimals),
                take_profits=[round(tp, decimals) for tp in targets],
                score=score,
                rsi=rsi,
                atr=atr,
                reason=setup_reason + " + HTF Filter Passed",
                details={
                    "trigger_price": round(price, decimals),
                    "max_entry": round(max_entry, decimals),
                    "risk_pct": round(risk["risk_pct"], 3),
                    "notional": round(risk["notional"], 2),
                    "triggers": ["true_bottom_choch_smc", "htf_ema_filter"],
                },
            )
            return "LONG", price, signal

        except Exception as exc:
            logger.exception("analysis error: %s", exc)
            neutral["reason"] = "exception: {}".format(exc)
            return "NEUTRAL", 0.0, neutral
