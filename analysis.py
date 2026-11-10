# ============================================================
# main.py — BingX Trading Bot Runner
# ============================================================
import time
import logging
import ccxt
from analysis import StrategyEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("TradingBotMain")

def run_bot():
    logger.info("🚀 Starting Trading Bot...")
    try:
        exchange = ccxt.bingx({
            'apiKey': 'YOUR_BINGX_API_KEY',
            'secret': 'YOUR_BINGX_SECRET_KEY',
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        })
    except Exception as e:
        logger.error(f"Failed to initialize exchange: {e}")
        return

    engine = StrategyEngine(capital=10000.0, risk_per_trade=0.01, min_score=75)
    symbols_to_scan = ['BTC/USDT:USDT', 'ETH/USDT:USDT', 'ONUSDT/USDT:USDT', 'SLXUSDT/USDT:USDT']

    while True:
        try:
            for symbol in symbols_to_scan:
                try:
                    ohlcv_15m = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=100)
                    ohlcv_1h = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=55)

                    if not ohlcv_15m or not ohlcv_1h:
                        continue

                    direction, price, signal = engine.analyze_market_structure(ohlcv_15m=ohlcv_15m, ohlcv_1h=ohlcv_1h)

                    if direction == "LONG":
                        logger.info(f"🚨 [LONG SIGNAL] {symbol} at {price} | Reason: {signal['reason']}")
                    else:
                        logger.debug(f"Neutral for {symbol}: {signal.get('reason')}")
                except Exception as inner_e:
                    logger.error(f"Error on {symbol}: {inner_e}")

            time.sleep(300)
        except Exception as outer_e:
            logger.error(f"Main loop error: {outer_e}")
            time.sleep(60)

if __name__ == "__main__":
    run_bot()
