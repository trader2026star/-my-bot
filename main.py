# ============================================================
# MY EXPERT CRYPTO BOT - Main Controller V73.0
# LONG ONLY | SIGNAL ONLY | FULL METRICS & /SCAN COMMAND
# ============================================================

import os
import time
import threading
import logging
import ccxt
import requests
from flask import Flask, jsonify
from analysis import StrategyEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("MainBot")
app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
BOT_CAPITAL_USD = max(1.0, float(os.environ.get("BOT_CAPITAL_USD", "10000")))
RISK_PER_TRADE = min(0.02, max(0.001, float(os.environ.get("RISK_PER_TRADE", "0.01"))))
MAX_SCAN_SYMBOLS = max(5, min(150, int(os.environ.get("MAX_SCAN_SYMBOLS", "40"))))
SCAN_INTERVAL_SECONDS = max(60, int(os.environ.get("SCAN_INTERVAL_SECONDS", "180")))
SIGNAL_COOLDOWN_SECONDS = max(300, int(os.environ.get("SIGNAL_COOLDOWN_SECONDS", "3600")))

active_positions = {}
positions_lock = threading.Lock()
last_signal_time = {}
signal_lock = threading.Lock()
scan_stats = {"scanned_pairs": 0, "signals_sent": 0, "errors": 0}

bingx = ccxt.bingx({
    "enableRateLimit": True,
    "timeout": 20000,
    "options": {"defaultType": "swap"},
    "apiKey": os.environ.get("BINGX_API_KEY", ""),
    "secret": os.environ.get("BINGX_SECRET_KEY", "")
})
engine = StrategyEngine(capital=BOT_CAPITAL_USD, risk_per_trade=RISK_PER_TRADE)

bot = None
try:
    import telebot
    if TELEGRAM_BOT_TOKEN:
        bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN, parse_mode="Markdown")
        logger.info("Telegram initialized.")
    else:
        logger.warning("TELEGRAM_BOT_TOKEN is missing.")
except Exception as exc:
    logger.warning("Telegram initialization failed: %s", exc)


@app.route("/")
def home():
    return "MY EXPERT CRYPTO BOT V73.0 Active - LONG signals only."


@app.route("/health")
def health():
    with positions_lock:
        count = len(active_positions)
    return jsonify({
        "status": "healthy", "version": "73.0",
        "stats": scan_stats, "active_positions_count": count,
        "telegram_active": bot is not None
    }), 200


def send_telegram_message(message, chat_id=None):
    target = chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not target:
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": target, "text": message, "parse_mode": "Markdown",
                  "disable_web_page_preview": True},
            timeout=15
        )
        return r.status_code == 200
    except Exception as exc:
        logger.error("Telegram send error: %s", exc)
        return False


def normalize_symbol(raw):
    s = str(raw).strip().upper().replace(" ", "")
    s = s.replace("_", "").replace("-", "/")
    if ":" in s:
        s = s.split(":")[0]
    if "/" not in s:
        if s.endswith("USDT"):
            s = s[:-4] + "/USDT"
        else:
            s += "/USDT"
    return s


def get_exchange_data(symbol_raw, timeframe, limit=100):
    base = normalize_symbol(symbol_raw).split("/")[0]
    candidates = [f"{base}/USDT:USDT", f"{base}/USDT"]
    for symbol in candidates:
        try:
            bars = bingx.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            if bars and len(bars) > 10:
                return symbol, bars
        except Exception:
            time.sleep(0.2)
    return None, None


def get_current_price(symbol):
    try:
        ticker = bingx.fetch_ticker(symbol)
        last = ticker.get("last") or ticker.get("close")
        return float(last) if last else 0.0
    except Exception:
        return 0.0


def calculate_position_size(current_price, stop_loss):
    try:
        distance = abs(float(current_price) - float(stop_loss))
        if current_price <= 0 or stop_loss <= 0 or distance <= 0:
            return 0.0
        return round((BOT_CAPITAL_USD * RISK_PER_TRADE) / distance, 6)
    except Exception:
        return 0.0


def can_send_signal(symbol):
    now = time.time()
    with signal_lock:
        previous = last_signal_time.get(symbol, 0)
        if now - previous < SIGNAL_COOLDOWN_SECONDS:
            return False
        with positions_lock:
            if symbol in active_positions:
                return False
        return True


def register_signal(symbol, direction, price, details):
    rm = details.get("risk_management", {})
    size = calculate_position_size(price, details.get("stop_loss", 0))
    with positions_lock:
        active_positions[symbol] = {
            "side": direction, "entry": price, "size": size,
            "tp1": rm.get("take_profit_1"), "tp2": rm.get("take_profit_2"),
            "tp3": rm.get("take_profit_3"),
            "stop_loss": details.get("stop_loss"),
            "tp1_done": False, "tp2_done": False,
            "created_at": time.time()
        }
    with signal_lock:
        last_signal_time[symbol] = time.time()


def generate_analysis_report(symbol, direction, price, details):
    rm = details.get("risk_management", {})
    price = float(price or details.get("trigger_price") or 0)
    if price <= 0:
        price = get_current_price(symbol)
    decimals = 8 if price < 0.1 else (6 if price < 1 else (4 if price < 100 else 2))

    def fmt(value):
        try:
            value = float(value)
            return f"{value:.{decimals}f}" if value > 0 else "غير متاح"
        except Exception:
            return "غير متاح"

    size = calculate_position_size(price, details.get("stop_loss", 0))
    entry = details.get("entry_zone", {})
    valid = bool(details.get("trade_valid")) and direction == "LONG"
    status = "🟢 LONG مؤكدة (شروط مكتملة)" if valid else "⚪ لا توجد صفقة (تم الرفض)"
    
    report = (
        f"🏛️ *MY EXPERT CRYPTO BOT V73.0*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🪙 العملة: `{symbol}`\n"
        f"📌 الحالة: {status}\n"
        f"⭐ التقييم الحقيقي: `{details.get('score', 0)} / 100`\n"
        f"💵 السعر الحالي: `{fmt(price)}`\n"
        f"📊 RSI 15M: `{details.get('rsi', 50)}`\n"
        f"📈 حجم التداول: `{entry.get('volume_ratio', 0)}x`\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎯 سعر الدخول: `{fmt(price)}`\n"
        f"🥇 TP1: `{fmt(rm.get('take_profit_1'))}`\n"
        f"🥈 TP2: `{fmt(rm.get('take_profit_2'))}`\n"
        f"🥉 TP3: `{fmt(rm.get('take_profit_3'))}`\n"
        f"🛑 وقف الخسارة: `{fmt(details.get('stop_loss'))}`\n"
        f"📦 حجم الوحدات التقديري: `{size}`\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🔎 دايفيرجنس إيجابي: `{entry.get('regular_bullish', False)}`\n"
        f"💧 Liquidity Sweep: `{entry.get('liquidity_sweep', False)}`\n"
        f"📐 BOS (هيكل صاعد): `{entry.get('bullish_structure', False)}`\n"
        f"📊 حجم السيولة: `{entry.get('volume_confirmed', False)}`\n"
        f"⏱️ تأكيد 5M: `{entry.get('confirmed_5m', False)}`\n"
        f"📈 توافق الاتجاه (EMA): `{entry.get('trend_confirmed', False)}`\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📝 *سبب الرفض أو التفاصيل:* \n{details.get('reason', '')}\n\n"
        f"⚠️ إشارة تحليلية ذكية فقط؛ لا ينفذ البوت صفقات حية."
    )
    return report


def analyze_symbol(symbol, chat_id=None, send_no_signal=True):
    resolved, candles15 = get_exchange_data(symbol, "15m", 110)
    if not resolved or not candles15 or len(candles15) < 65:
        if send_no_signal:
            send_telegram_message(f"❌ لا تتوفر بيانات كافية للرمز `{symbol}`.", chat_id)
        return False, None
    _, candles5 = get_exchange_data(resolved, "5m", 40)
    scan_stats["scanned_pairs"] += 1
    direction, price, details = engine.analyze_market_structure(
        ohlcv_5m=candles5, ohlcv_15m=candles15, asset_type="crypto"
    )
    valid = bool(details.get("trade_valid")) and direction == "LONG"
    report = generate_analysis_report(resolved, direction, price, details)
    if valid:
        if can_send_signal(resolved):
            sent = send_telegram_message(report, chat_id)
            if sent:
                register_signal(resolved, direction, price, details)
                scan_stats["signals_sent"] += 1
        elif send_no_signal:
            send_telegram_message(report, chat_id)
    elif send_no_signal:
        send_telegram_message(report, chat_id)
    return valid, details


def get_scan_universe():
    try:
        markets = bingx.load_markets()
        candidates = [
            s for s, m in markets.items()
            if m.get("swap") and m.get("active", True)
            and m.get("quote") == "USDT" and m.get("settle") == "USDT"
            and m.get("base") and m["base"] not in ("USDC", "BUSD", "TUSD", "FDUSD")
        ]
        return candidates[:MAX_SCAN_SYMBOLS]
    except Exception:
        return ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "XRP/USDT:USDT", "BNB/USDT:USDT"]


def automated_signal_scanner_loop():
    time.sleep(15)
    while True:
        started = time.time()
        try:
            symbols = get_scan_universe()
            logger.info("V73 scanning %s USDT markets.", len(symbols))
            for symbol in symbols:
                try:
                    if can_send_signal(symbol):
                        analyze_symbol(symbol, send_no_signal=False)
                    time.sleep(1.0)
                except Exception as exc:
                    scan_stats["errors"] += 1
                    logger.warning("Scan failed %s: %s", symbol, exc)
                    time.sleep(2)
        except Exception as exc:
            scan_stats["errors"] += 1
            logger.exception("Scanner loop error: %s", exc)
        elapsed = time.time() - started
        time.sleep(max(10, SCAN_INTERVAL_SECONDS - elapsed))


def position_tracker_loop():
    while True:
        time.sleep(10)
        with positions_lock:
            snapshot = list(active_positions.items())
        for symbol, pos in snapshot:
            try:
                price = get_current_price(symbol)
                if price <= 0:
                    continue
                entry = float(pos["entry"])
                sl = float(pos["stop_loss"])
                tp1, tp2, tp3 = pos.get("tp1"), pos.get("tp2"), pos.get("tp3")
                if price <= sl:
                    with positions_lock:
                        active_positions.pop(symbol, None)
                    send_telegram_message(f"🛑 `{symbol}` ضرب وقف الخسارة عند `{price}`.")
                    continue
                if tp1 and price >= float(tp1) and not pos.get("tp1_done"):
                    with positions_lock:
                        if symbol in active_positions:
                            active_positions[symbol]["tp1_done"] = True
                            active_positions[symbol]["stop_loss"] = entry
                    send_telegram_message(f"🎯 `{symbol}` حقق TP1 عند `{price}`. تم نقل الستوب لنقطة الدخول.")
                if tp2 and price >= float(tp2) and not pos.get("tp2_done"):
                    with positions_lock:
                        if symbol in active_positions:
                            active_positions[symbol]["tp2_done"] = True
                    send_telegram_message(f"🥈 `{symbol}` حقق TP2 عند `{price}`.")
                if tp3 and price >= float(tp3):
                    with positions_lock:
                        active_positions.pop(symbol, None)
                    send_telegram_message(f"🚀 `{symbol}` حقق الهدف الثالث TP3 بنجاح.")
            except Exception as exc:
                logger.debug("Position tracking failed %s: %s", symbol, exc)


if bot:
    @bot.message_handler(commands=["start", "help"])
    def handle_start(message):
        bot.reply_to(
            message,
            "مرحباً بك في MY EXPERT CRYPTO BOT V73.0.\n"
            "أرسل رمز العملة مثل `BTC` أو `SOL` لتحليلها بالتقييم الكامل.\n"
            "أو استخدم الأمر `/scan` لفحص السوق وابحث عن الفرص القوية."
        )

    @bot.message_handler(commands=["scan"])
    def handle_scan_command(message):
        bot.reply_to(message, "🔍 جاري فحص السوق والبحث عن أقوى الفرص المتاحة حالياً...")
        universe = get_scan_universe()[:15] # فحص عينة سريعة للأمر
        found = 0
        for sym in universe:
            try:
                valid, details = analyze_symbol(sym, chat_id=message.chat.id, send_no_signal=False)
                if valid or (details and details.get("score", 0) >= 60):
                    report = generate_analysis_report(sym, details.get("direction", "NEUTRAL"), details.get("trigger_price", 0), details)
                    bot.send_message(message.chat.id, report, parse_mode="Markdown")
                    found += 1
                    if found >= 3: # أقصى عدد يعرضه الأمر لعدم الإزعاج
                        break
            except Exception:
                continue
        if found == 0:
            bot.send_message(message.chat.id, "⚪ لم يتم العثور على فرص مطابقة للمعايير الصارمة حالياً في عينة الفحص السريع.")

    @bot.message_handler(func=lambda message: bool(message.text))
    def handle_symbol(message):
        raw = message.text.strip()
        if raw.startswith("/"):
            return
        symbol = normalize_symbol(raw)
        if len(symbol) > 24 or not symbol.endswith("/USDT"):
            bot.reply_to(message, "أرسل رمز USDT صحيحاً مثل `BTC` أو `ETH` أو `SOL/USDT`.")
            return
        bot.reply_to(message, f"🔍 جارٍ فحص عملة `{symbol}` بتقييم شامل على BingX...")
        analyze_symbol(symbol, chat_id=message.chat.id, send_no_signal=True)


def telegram_listener():
    if not bot:
        return
    try:
        bot.remove_webhook()
        time.sleep(1)
    except Exception:
        pass
    while True:
        try:
            logger.info("Telegram polling active.")
            bot.infinity_polling(skip_pending=True, timeout=20, long_polling_timeout=20)
        except Exception as exc:
            logger.error("Telegram polling error: %s", exc)
            time.sleep(5)


if __name__ == "__main__":
    threading.Thread(target=position_tracker_loop, daemon=True).start()
    threading.Thread(target=automated_signal_scanner_loop, daemon=True).start()
    if bot:
        threading.Thread(target=telegram_listener, daemon=True).start()
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
