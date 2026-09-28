# داخل bot_worker في main.py، عدل جزء فحص العمليات ليكون هكذا:

for symbol in symbols:
    try:
        analyzed_count += 1
        signal = bot.evaluate_strategy(symbol)

        if not signal:
            time.sleep(1.0) # تأخير إضافي لتخفيف الضغط
            continue

        score = signal.get('score', 0)
        decision = str(signal.get('decision', '')).upper()

        if score <= 0 or decision in ['NEUTRAL', 'NO_TRADE', '']:
            time.sleep(0.5)
            continue

        if not should_send_signal(signal):
            continue

        message = build_signal_message(signal)
        if not message:
            continue

        sent = send_telegram_message(message)
        if sent:
            mark_signal_sent(signal)
            signals_found += 1

        # رفع معدل الأمان والتأخير بين كل عملة وأخرى لتجنب حظر الـ API والـ Rate Limit
        time.sleep(2.5)

    except Exception as e:
        logger.warning("Error analyzing %s: %s", symbol, e)
        time.sleep(2)
