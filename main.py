# ==========================================
# MY EXPERT CRYPTO BOT - Main Controller (v3.8 - Elite Institutional Edition)
# ==========================================
import os
import time
import threading
import logging
import requests
import ccxt
from flask import Flask, jsonify
from analysis import StrategyEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("MainBot")

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
SIGNAL_COOLDOWN_SECONDS = max(60, int(os.environ.get("SIGNAL_COOLDOWN_SECONDS", "3600")))
API_MIN_INTERVAL_SECONDS = max(0.25, float(os.environ.get("API_MIN_INTERVAL_SECONDS", "0.35")))
SYMBOL_PAUSE_SECONDS = max(0.05, float(os.environ.get("SYMBOL_PAUSE_SECONDS", "0.10")))
MAX_API_RETRIES = max(0, min(3, int(os.environ.get("MAX_API_RETRIES", "2"))))

BOT_CAPITAL_USD = max(1.0, float(os.environ.get("BOT_CAPITAL_USD", "10000")))
RISK_PER_TRADE = min(0.05, max(0.001, float(os.environ.get("RISK_PER_TRADE", "0.01"))))

signal_history = {}
active_positions = {}  # الصفقات النشطة لمنع التعارض تماماً
scan_stats = {"scanned_pairs": 0, "signals_sent": 0}

history_lock = threading.Lock()
api_lock = threading.Lock()
positions_lock = threading.Lock()
_last_api_request = 0.0

bingx = ccxt.bingx({
    "enableRateLimit": True,
    "timeout": 20000,
    "options": {"defaultType": "swap"},
    "apiKey": os.environ.get("BINGX_API_KEY", ""),
    "secret": os.environ.get("BINGX_SECRET_KEY", "")
})

@app.route("/")
def home():
    return "MY EXPERT CRYPTO BOT (v3.8 Elite Institutional SMC & Anti-Conflict) Active!"

@app.route("/health")
def health():
    return jsonify({"status": "healthy", "stats": scan_stats, "active_positions_count": len(active_positions)}), 200

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown", "disable_web_page_preview": True},
            timeout=15
        )
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Telegram error: {e}")
        return False

def bingx_call(method_name, *args, **kwargs):
    global _last_api_request
    method = getattr(bingx, method_name)
    for attempt in range(MAX_API_RETRIES + 1):
        with api_lock:
            now = time.monotonic()
            wait_for = max(0.0, API_MIN_INTERVAL_SECONDS - (now - _last_api_request))
            if wait_for > 0:
                time.sleep(wait_for)
            _last_api_request = time.monotonic()
        try:
            return method(*args, **kwargs)
        except Exception:
            if attempt >= MAX_API_RETRIES:
                return None
            time.sleep(1.0)
    return None

def get_all_usdt_symbols():
    try:
        markets = bingx_call("load_markets")
        if not markets:
            return []
        symbols = []
        for symbol, market in markets.items():
            if (
                market.get("linear", False)
                and market.get("quote") == "USDT"
                and market.get("active", True)
                and "/USDT:USDT" in symbol
                and market.get("swap", True)
            ):
                base_asset = symbol.split('/')[0].upper()
                if any(x in symbol.upper() for x in ["TEST", "UP/", "DOWN/", "BULL", "BEAR"]):
                    continue
                if len(base_asset) > 12:
                    continue
                symbols.append(symbol)
        return sorted(set(symbols))
    except Exception as e:
        logger.error(f"Error loading markets: {e}")
        return []

def position_tracker_loop():
    """مراقب الصفقات الذكي: إدارة التعادل، جني الأرباح، وتحرير العملة فور انتهائها"""
    while True:
        try:
            with positions_lock:
                positions_to_check = list(active_positions.items())

            for symbol, pos_data in positions_to_check:
                ticker = bingx_call("fetch_ticker", symbol)
                if not ticker:
                    continue
                current_price = float(ticker.get("last") or ticker.get("close") or 0)
                if current_price <= 0:
                    continue

                direction = pos_data["direction"]
                entry_price = pos_data["entry"]
                tp1 = pos_data["tp1"]
                tp3 = pos_data["tp3"]
                stop_loss = pos_data["stop_loss"]
                be_done = pos_data["breakeven_done"]

                # التحقق من ضرب وقف الخسارة (SL) أو الهدف النهائي (TP3) لتطهير القائمة
                is_stopped_out = (direction == "LONG" and current_price <= stop_loss) or (direction == "SHORT" and current_price >= stop_loss)
                is_fully_target_hit = (direction == "LONG" and current_price >= tp3) or (direction == "SHORT" and current_price <= tp3)

                if is_stopped_out or is_fully_target_hit:
                    with positions_lock:
                        if symbol in active_positions:
                            del active_positions[symbol]
                    send_telegram_message(f"🏁 *انتهت الصفقة للعملة `{symbol}` ({direction}) وتم تحريرها من القائمة النشطة لبدء مسح جديد.*")
                    continue

                # تفعيل نقطة التعادل عند ضرب الهدف الأول (TP1)
                if not be_done:
                    if direction == "LONG" and current_price >= tp1:
                        send_telegram_message(
                            f"🎯 *تم تحقيق الهدف الأول (TP1) وجني الأرباح الجزئي للعملة `{symbol}`!*\n"
                            f"💰 *إغلاق 50% من الصفقة لتأمين الأرباح.*\n"
                            f"🛡️ *نقل وقف الخسارة للتعادل عند (`{entry_price}`)...*"
                        )
                        try:
                            bingx_call("private_post_trade_order", {"symbol": symbol, "side": "SELL", "type": "STOP_MARKET", "stopPrice": entry_price})
                        except Exception:
                            pass
                        
                        with positions_lock:
                            active_positions[symbol]["breakeven_done"] = True

                    elif direction == "SHORT" and current_price <= tp1:
                        send_telegram_message(
                            f"🎯 *تم تحقيق الهدف الأول (TP1) وجني الأرباح الجزئي للعملة `{symbol}`!*\n"
                            f"💰 *إغلاق 50% من الصفقة لتأمين الأرباح.*\n"
                            f"🛡️ *نقل وقف الخسارة للتعادل عند (`{entry_price}`)...*"
                        )
                        try:
                            bingx_call("private_post_trade_order", {"symbol": symbol, "side": "BUY", "type": "STOP_MARKET", "stopPrice": entry_price})
                        except Exception:
                            pass
                        
                        with positions_lock:
                            active_positions[symbol]["breakeven_done"] = True

            time.sleep(15)
        except Exception as e:
            logger.error(f"Position Tracker Error: {e}")
            time.sleep(30)

def background_scanner():
    time.sleep(5)
    send_telegram_message(
        "🏛️ *تم تشغيل بوت الصفقات المؤسسية النخبوية (v3.8 - مضاد التناقض والإشارات المزدوجة)*\n"
        "النظام يعمل بأقصى درجات الانضباط المالي!"
    )
    engine = StrategyEngine(capital=BOT_CAPITAL_USD, risk_per_trade=RISK_PER_TRADE)

    while True:
        try:
            symbols = get_all_usdt_symbols()
            if not symbols:
                time.sleep(30)
                continue

            btc_ohlcv_1d = bingx_call("fetch_ohlcv", "BTC/USDT:USDT", timeframe="1d", limit=25)

            for symbol in symbols:
                if symbol == "BTC/USDT:USDT":
                    continue
                
                # 🛑 حراسة صارمة: تخطي العملة تماماً إذا كانت تمتلك صفقة نشطة حالياً
                with positions_lock:
                    if symbol in active_positions:
                        continue

                now = time.time()
                with history_lock:
                    if now - signal_history.get(symbol, 0) < SIGNAL_COOLDOWN_SECONDS:
                        continue

                ticker = bingx_call("fetch_ticker", symbol)
                if not ticker:
                    continue

                quote_volume = float(ticker.get("quoteVolume") or ticker.get("baseVolume") or 0)
                if quote_volume < 4000000:
                    continue

                ohlcv_15m = bingx_call("fetch_ohlcv", symbol, timeframe="15m", limit=30)
                ohlcv_1h = bingx_call("fetch_ohlcv", symbol, timeframe="1h", limit=30)
                ohlcv_4h = bingx_call("fetch_ohlcv", symbol, timeframe="4h", limit=30)
                ohlcv_1d = bingx_call("fetch_ohlcv", symbol, timeframe="1d", limit=25)

                if not (ohlcv_15m and ohlcv_1h and ohlcv_4h and ohlcv_1d):
                    continue

                direction, entry_price, details = engine.analyze_market_structure(
                    ohlcv_15m=ohlcv_15m, ohlcv_1h=ohlcv_1h, ohlcv_4h=ohlcv_4h, ohlcv_1d=ohlcv_1d, btc_ohlcv_1d=btc_ohlcv_1d
                )
                scan_stats["scanned_pairs"] += 1

                if direction in ["LONG", "SHORT"] and details.get("trade_valid", False):
                    rm = details.get("risk_management", {})
                    ps = details.get("position_sizing", {})
                    icon = "🟢" if direction == "LONG" else "🔴"
                    
                    message = (
                        f"🏛️ *فرصة ELITE SMC مؤكدة ({direction})* {icon}\n\n"
                        f"🔹 العملة: `{symbol}`\n"
                        f"⚖️ الاتجاه: `{direction}`\n"
                        f"💵 سعر الدخول (منطقة OB): `{entry_price}`\n"
                        f"🟥 وقف الخسارة المحمي: `{details.get('stop_loss')}`\n\n"
                        f"📊 *إدارة رأس المال والعقد:* \n"
                        f"• حجم العقد الكلي: `{ps.get('units')}` وحدة\n"
                        f"• القيمة بالدولار: `${ps.get('margin_usd')}`\n"
                        f"• المخاطرة المستهدفة: `${ps.get('risk_amount_usd')}`\n\n"
                        f"🟩 **الأهداف وخطة الخروج:**\n"
                        f"• TP1: `{rm.get('take_profit_1')}` (أغلق 50% وانقل الوقف للتعادل)\n"
                        f"• TP2: `{rm.get('take_profit_2')}`\n"
                        f"• TP3: `{rm.get('take_profit_3')}`\n\n"
                        f"💡 *ملاحظة SMC:* `{details.get('smc_note')}`"
                    )
                    sent = send_telegram_message(message)
                    if sent:
                        scan_stats["signals_sent"] += 1
                        with history_lock:
                            signal_history[symbol] = time.time()
                        with positions_lock:
                            active_positions[symbol] = {
                                "direction": direction,
                                "entry": entry_price,
                                "stop_loss": details.get("stop_loss"),
                                "tp1": rm.get("take_profit_1"),
                                "tp3": rm.get("take_profit_3"),
                                "breakeven_done": False
                            }
                time.sleep(SYMBOL_PAUSE_SECONDS)

            time.sleep(60)
        except Exception as exc:
            logger.error(f"Scanner Loop Error: {exc}")
            time.sleep(30)

scanner_thread = threading.Thread(target=background_scanner, daemon=True, name="scanner")
scanner_thread.start()

tracker_thread = threading.Thread(target=position_tracker_loop, daemon=True, name="position-tracker")
tracker_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
