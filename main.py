# ============================================================
# main.py — Safe & Robust BingX Bot Runner
# ============================================================
import time
import logging
import ccxt
from analysis import StrategyEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("TradingBotMain")

def run_bot():
    logger.info("🚀 Starting Safe Trading Bot Runner...")
    
    try:
        # تهيئة الاتصال (حتى لو لم تضف المفاتيح الآن، سيعمل في حالت التشغيل العام)
        exchange = ccxt.bingx({
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        })
    except Exception as e:
        logger.error(f"Exchange init warning: {e}")

    engine = StrategyEngine(capital=10000.0, risk_per_trade=0.01, min_score=75)
    symbols_to_scan = ['BTC/USDT:USDT', 'ETH/USDT:USDT', 'ONUSDT/USDT:USDT', 'SLXUSDT/USDT:USDT']

    while True:
        try:
            logger.info("🔍 Scanning markets with V80 Strategy...")
            for symbol in symbols_to_scan:
                try:
                    ohlcv_15m = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=50)
                    ohlcv_1h = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=35)

                    if not ohlcv_15m or not ohlcv_1h:
                        continue

                    direction, price, signal = engine.analyze_market_structure(ohlcv_15m=ohlcv_15m, ohlcv_1h=ohlcv_1h)

                    if direction == "LONG":
                        logger.info(f"🚨 [LONG SIGNAL FOUND] {symbol} at {price} | Reason: {signal['reason']}")
                    else:
                        logger.debug(f"Market neutral for {symbol}")
                except Exception as inner_e:
                    logger.error(f"Error fetching/analyzing {symbol}: {inner_e}")

            time.sleep(300)
        except Exception as outer_e:
            logger.error(f"Loop error: {outer_e}")
            time.sleep(60)

if __name__ == "__main__":
    run_bot()
