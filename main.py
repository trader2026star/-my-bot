# ============================================================
# main.py — BingX Trading Bot Runner (Strategy V80 - True Bottom, CHoCH & HTF Filter)
# ============================================================
import time
import logging
import ccxt
from analysis import StrategyEngine

# إعداد السجلات (Logging)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("TradingBotMain")

def run_bot():
    logger.info("🚀 Starting Trading Bot with Strategy V80 (True Bottom, CHoCH & HTF Filter)...")

    # تهيئة الاتصال بمنصة بينج إكس (BingX) عبر CCXT
    try:
        exchange = ccxt.bingx({
            'apiKey': 'YOUR_BINGX_API_KEY',
            'secret': 'YOUR_BINGX_SECRET_KEY',
            'enableRateLimit': True,
            'options': {
                'defaultType': 'swap', # لتداول العقود الآجلة (Futures / Swap)
            }
        })
    except Exception as e:
        logger.error(f"Failed to initialize exchange connection: {e}")
        return

    # تهيئة محرك الاستراتيجية برأس المال وإدارة المخاطر
    engine = StrategyEngine(capital=10000.0, risk_per_trade=0.01, min_score=75)

    # قائمة العملات المراد مراقبتها وفحصها
    symbols_to_scan = [
        'BTC/USDT:USDT',
        'ETH/USDT:USDT',
        'ONUSDT/USDT:USDT',
        'SLXUSDT/USDT:USDT'
    ]

    scan_interval_seconds = 300  # الفحص كل 5 دقائق

    while True:
        try:
            logger.info("🔍 Scanning markets for structural setups (True Bottom, CHoCH & HTF)...")
            
            for symbol in symbols_to_scan:
                symbol_err = symbol
                try:
                    # جلب شموع فريم 15 دقيقة (للتحليل والدخول)
                    ohlcv_15m = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=100)
                    # جلب شموع فريم الساعة (لتأكيد الاتجاه العام وتفعيل الفلتر)
                    ohlcv_1h = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=55)

                    if not ohlcv_15m or not ohlcv_1h:
                        logger.warning(f"Could not fetch data for {symbol}")
                        continue

                    # تحليل الهيكل مع تمرير فريم الساعة لتفعيل فلتر الاتجاه العام
                    direction, price, signal = engine.analyze_market_structure(
                        ohlcv_5m=None, 
                        ohlcv_15m=ohlcv_15m, 
                        ohlcv_1h=ohlcv_1h
                    )

                    if direction == "LONG":
                        logger.info(f"🚨 [LONG SIGNAL FOUND] Symbol: {symbol} | Price: {price}")
                        logger.info(f"   Reason: {signal['reason']}")
                        logger.info(f"   Entry: {signal['entry']} | SL: {signal['stop_loss']}")
                        logger.info(f"   Take Profits: {signal['take_profits']}")
                        logger.info(f"   Risk %: {signal['details'].get('risk_pct')}%")

                        # --- منطقة تنفيذ الأوامر أو إرسال تنبيهات تيليجرام ---
                        # order = exchange.create_market_buy_order(symbol, signal['details']['notional'] / price)
                        
                    else:
                        logger.debug(f"Market structure neutral or filtered out for {symbol} at {price} -> Reason: {signal.get('reason')}")

                except Exception as inner_e:
                    logger.error(f"Error analyzing {symbol_err}: {inner_e}")

            logger.info(f"💤 Sleeping for {scan_interval_seconds} seconds before next scan...")
            time.sleep(scan_interval_seconds)

        except KeyboardInterrupt:
            logger.info("🛑 Bot stopped manually by user.")
            break
        except Exception as outer_e:
            logger.error(f"⚠️ Error in main loop: {outer_e}")
            time.sleep(60)

if __name__ == "__main__":
    run_bot()
