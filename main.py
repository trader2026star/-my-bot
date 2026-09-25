# =========================================================
# TELEGRAM (Updated with 429 Rate Limit Handling)
# =========================================================

def send_telegram_message(message):

    token = os.environ.get(
        'TELEGRAM_BOT_TOKEN',
        os.environ.get('BOT_TOKEN', '')
    )

    chat_id = os.environ.get(
        'TELEGRAM_CHAT_ID',
        os.environ.get('CHAT_ID', '')
    )

    if not token or not chat_id:
        logger.error(
            "Telegram credentials are missing."
        )
        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{token}/sendMessage"
    )

    payload = {
        'chat_id': chat_id,
        'text': message
    }

    # محاولة الإرسال مع تكرارها لو حصل ضغط (Rate Limit)
    while True:
        try:
            response = requests.post(
                url,
                json=payload,
                timeout=15
            )

            if response.ok:
                return True

            data = response.json()
            error_code = data.get("error_code")

            # لو حصل خطأ 429 (Too Many Requests)
            if error_code == 429:
                parameters = data.get("parameters", {})
                retry_after = parameters.get("retry_after", 10)
                logger.warning(
                    "Telegram rate limited (429). Retrying after %s seconds...",
                    retry_after
                )
                time.sleep(retry_after)
                continue  # إعادة المحاولة بعد انتهاء وقت الانتظار

            logger.error(
                "Telegram error: %s",
                response.text
            )

            return False

        except Exception as e:

            logger.error(
                "Telegram connection error: %s",
                e
            )

            return False
