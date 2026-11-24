# ============================================================
# main.py — Bot V134.0 Tri-Mode Engine
# SCALP (15M/1H) + SWING (4H/1D) + POSITION (1W/1M)
# Crypto + Stocks/ETFs + Forex + Metals | LONG + SHORT
# ============================================================

import os
import time
import warnings
import threading
import logging
import sqlite3
from collections import deque
import ccxt
import requests
import numpy as np
import pandas as pd
import yfinance as yf
from flask import Flask, jsonify, request
from analysis import StrategyEngine

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logging.getLogger("yfinance").setLevel(logging.ERROR)
logger = logging.getLogger("MainBot")
app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
ALLOWED_CHAT_IDS = {c.strip() for c in os.environ.get("ALLOWED_CHAT_IDS", "").split(",") if c.strip()}
if TELEGRAM_CHAT_ID:
    ALLOWED_CHAT_IDS.add(TELEGRAM_CHAT_ID)
DB_PATH = os.environ.get("DB_PATH", "/tmp/bot_state.db")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "").strip().rstrip("/")
if not WEBHOOK_URL:
    WEBHOOK_URL = os.environ.get("RENDER_EXTERNAL_URL", "").strip().rstrip("/")

bingx = ccxt.bingx({
    "enableRateLimit": True,
    "timeout": 15000,
    "options": {"defaultType": "swap"},
})

BASE_MIN_SCORE = 78
COUNTER_REGIME_MIN_SCORE = 84
engine = StrategyEngine(capital=10000.0, risk_per_trade=0.01, min_score=BASE_MIN_SCORE)

db_lock = threading.RLock()
exchange_lock = threading.RLock()
scan_lock = threading.Lock()
cache_lock = threading.Lock()
scan_stats = {"scanned_pairs": 0, "signals_sent": 0, "guard_alerts_sent": 0, "errors": 0}
_seen_updates = deque(maxlen=500)
_seen_lock = threading.Lock()
_all_markets_cache = []
_markets_cache_time = 0
_sent_signals_cache = {}
SIGNAL_COOLDOWN_SECONDS = 14400
MAX_SAME_DIRECTION_PER_SCAN = 3
MAX_TRACKED_POSITIONS = 12
POSITION_TTL_SECONDS = 86400
SCAN_INTERVAL_SECONDS = 3600

MARKET_REGIME_CACHE = {"regime": "SIDEWAYS", "summary": "لم يُحدد بعد", "updated_ts": 0.0}
REGIME_TTL_SECONDS = 1800

US_STOCKS_AND_ETFS = [
    "SOXS", "SOXL", "SPY", "QQQ", "TQQQ", "SQQQ",
    "NVDA", "TSLA", "AAPL", "MSFT", "AMZN", "META", "AMD"
]
FOREX_AND_METALS = ["XAUUSD=X", "EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X"]
PRIORITY_SYMBOLS = [
    "BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "BNB/USDT:USDT", "XRP/USDT:USDT",
    "XAUUSD=X", "SOXS", "SOXL", "NVDA", "TSLA"
]


def _db():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def db_query(sql, params=(), one=False):
    with db_lock:
        conn = _db()
        try:
            cur = conn.execute(sql, params)
            rows = cur.fetchall()
            conn.commit()
            return rows[0] if rows and one else (None if one else rows)
        finally:
            conn.close()


def db_init():
    try:
        db_query("CREATE TABLE IF NOT EXISTS bot_state (key TEXT PRIMARY KEY, value TEXT)")
        db_query("""
            CREATE TABLE IF NOT EXISTS tracked_positions (
                signal_id TEXT PRIMARY KEY,
                symbol_raw TEXT NOT NULL,
                resolved TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_price REAL NOT NULL,
                stop_loss REAL NOT NULL,
                tp1 REAL NOT NULL,
                tp2 REAL NOT NULL,
                tp3 REAL NOT NULL,
                last_action TEXT DEFAULT 'NEW',
                created_ts REAL NOT NULL,
                updated_ts REAL NOT NULL
            )
        """)
    except Exception as exc:
        logger.error("DB init error: %s", exc)


def save_tracked_position(signal, symbol_raw, resolved):
    try:
        tps = list(signal.get("take_profits") or [])
        while len(tps) < 3:
            tps.append(0.0)
        e_low = float(signal.get("entry_low") or 0.0)
        e_high = float(signal.get("entry_high") or 0.0)
        entry_mid = (e_low + e_high) / 2.0 if (e_low > 0 and e_high > 0) else max(e_low, e_high)
        now_ts = time.time()
        db_query(
            """
            INSERT OR REPLACE INTO tracked_positions
            (signal_id, symbol_raw, resolved, direction, entry_price, stop_loss, tp1, tp2, tp3, last_action, created_ts, updated_ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'NEW', ?, ?)
            """,
            (
                signal.get("signal_id"),
                symbol_raw,
                resolved,
                signal.get("direction"),
                entry_mid,
                float(signal.get("stop_loss") or 0.0),
                float(tps[0]),
                float(tps[1]),
                float(tps[2]),
                now_ts,
                now_ts,
            ),
        )
        rows = db_query("SELECT signal_id FROM tracked_positions ORDER BY created_ts DESC")
        if len(rows) > MAX_TRACKED_POSITIONS:
            stale = [r["signal_id"] for r in rows[MAX_TRACKED_POSITIONS:]]
            for sid in stale:
                db_query("DELETE FROM tracked_positions WHERE signal_id = ?", (sid,))
    except Exception as exc:
        logger.error("save_tracked_position error: %s", exc)


def clear_tracked_positions():
    try:
        db_query("DELETE FROM tracked_positions")
        return True
    except Exception as exc:
        logger.error("clear_tracked_positions error: %s", exc)
        return False


def get_active_positions():
    try:
        now_ts = time.time()
        db_query("DELETE FROM tracked_positions WHERE (? - created_ts) > ?", (now_ts, POSITION_TTL_SECONDS))
        rows = db_query("SELECT * FROM tracked_positions ORDER BY created_ts DESC")
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.error("get_active_positions error: %s", exc)
        return []


def _find_active_position(resolved):
    try:
        base_sym = str(resolved or "").split("/")[0].upper()
        for pos in get_active_positions():
            pos_base = str(pos.get("resolved") or "").split("/")[0].upper()
            if pos_base == base_sym:
                return pos
        return None
    except Exception:
        return None


def _is_duplicate_active_position(resolved, direction):
    try:
        base_sym = str(resolved or "").split("/")[0].upper()
        for pos in get_active_positions():
            pos_base = str(pos.get("resolved") or "").split("/")[0].upper()
            if pos_base == base_sym and pos.get("direction") == direction:
                return True
        return False
    except Exception:
        return False


def ex_call(fn, *args, **kwargs):
    with exchange_lock:
        return fn(*args, **kwargs)


def _prioritize_universe(symbols):
    seen = set()
    ordered = []
    for p in PRIORITY_SYMBOLS:
        if p in symbols and p not in seen:
            ordered.append(p)
            seen.add(p)
    for s in symbols:
        if s not in seen:
            ordered.append(s)
            seen.add(s)
    return ordered


def get_full_market_universe():
    global _all_markets_cache, _markets_cache_time
    try:
        if not _all_markets_cache or time.time() - _markets_cache_time > 1800:
            markets = ex_call(bingx.load_markets, True)
            crypto = []
            for symbol, market in markets.items():
                if not market.get("swap") or not market.get("active", True):
                    continue
                if market.get("quote") == "USDT" and market.get("settle") == "USDT":
                    crypto.append(symbol)
            merged = sorted(set(crypto + US_STOCKS_AND_ETFS + FOREX_AND_METALS))
            _all_markets_cache = _prioritize_universe(merged)
            _markets_cache_time = time.time()
        return _all_markets_cache or ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOXS", "XAUUSD=X"]
    except Exception as exc:
        logger.error("Market universe error: %s", exc)
        return ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOXS", "XAUUSD=X"]


def get_top_gainers(limit=15):
    try:
        tickers = ex_call(bingx.fetch_tickers)
        gainers = []
        for sym, t in (tickers or {}).items():
            if not sym.endswith(":USDT") and "/USDT" not in sym:
                continue
            pct = t.get("percentage")
            if pct is None:
                continue
            try:
                pct_val = float(pct)
            except Exception:
                continue
            if pct_val > 3.5:
                gainers.append((pct_val, sym))
        gainers.sort(key=lambda x: x[0], reverse=True)
        return gainers[:limit]
    except Exception as exc:
        logger.error("get_top_gainers error: %s", exc)
        return []


def clean_symbol_input(raw):
    s = str(raw).strip().upper().replace(" ", "")
    return s if len(s) >= 2 else None


def _yf_interval(timeframe):
    return {
        "1m": ("5y", "1mo"),
        "1w": ("5y", "1wk"),
        "1d": ("6mo", "1d"),
        "4h": ("60d", "1h"),
        "1h": ("30d", "1h"),
        "15m": ("30d", "15m"),
    }.get(timeframe)


def _fetch_yfinance_ohlcv(ticker, timeframe):
    try:
        cfg = _yf_interval(timeframe)
        if not cfg:
            return None
        period, interval = cfg
        df = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=False, threads=False)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        if timeframe == "4h":
            df = df.resample("4h").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}).dropna()
        df = df.dropna().tail(180)
        bars = []
        for idx, row in df.iterrows():
            try:
                ts = int(pd.Timestamp(idx).timestamp() * 1000)
                vol = float(row.get("Volume", 1000) or 1000)
                if vol <= 0:
                    vol = 1000.0
                bars.append([ts, float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"]), vol])
            except Exception:
                continue
        return bars if len(bars) >= 6 else None
    except Exception as exc:
        logger.debug("yfinance fetch failed for %s %s: %s", ticker, timeframe, exc)
        return None


def fetch_ohlcv(symbol_raw, timeframe, limit=100):
    try:
        sym = clean_symbol_input(symbol_raw)
        if not sym:
            return None, None, "unknown"
        aliases = {
            "XAU": "XAUUSD=X", "XAUUSD": "XAUUSD=X", "GOLD": "XAUUSD=X",
            "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X", "USDJPY": "USDJPY=X", "AUDUSD": "AUDUSD=X",
        }
        if sym in aliases or sym.endswith("=X"):
            ticker = aliases.get(sym, sym)
            bars = _fetch_yfinance_ohlcv(ticker, timeframe)
            if bars:
                return ticker.replace("=X", ""), bars, "forex"
        if sym in US_STOCKS_AND_ETFS:
            bars = _fetch_yfinance_ohlcv(sym, timeframe)
            if bars:
                return sym, bars, "stock"

        is_crypto_pair = ("/" in sym) or (":USDT" in sym)
        base = sym.split(":")[0].split("/")[0]
        if base.endswith("USDT") and len(base) > 4:
            base = base[:-4]
        min_bars = 6 if timeframe in ("1w", "1m") else 11
        for c_sym in (f"{base}/USDT:USDT", f"{base}/USDT"):
            try:
                bars = ex_call(bingx.fetch_ohlcv, c_sym, timeframe=timeframe, limit=limit)
                if bars and len(bars) >= min_bars:
                    return c_sym, bars, "crypto"
            except Exception as exc:
                logger.debug("BingX OHLCV %s %s: %s", c_sym, timeframe, exc)
            time.sleep(0.04)
        if is_crypto_pair:
            return None, None, "unknown"
        bars = _fetch_yfinance_ohlcv(sym, timeframe)
        if bars:
            return sym, bars, "stock"
    except Exception as exc:
        logger.debug("Safe fetch_ohlcv warning for %s: %s", symbol_raw, exc)
    return None, None, "unknown"


def tg_send(message, chat_id=None):
    target = chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not target:
        return False
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": target, "text": message, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=15,
        )
        if not response.ok:
            logger.error("Telegram send failed: %s %s", response.status_code, response.text[:300])
        return response.ok
    except Exception as exc:
        logger.error("Telegram send error: %s", exc)
        return False


def configure_webhook():
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("Telegram token missing; webhook not configured.")
        return
    if not WEBHOOK_URL:
        logger.warning("WEBHOOK_URL/RENDER_EXTERNAL_URL missing; keeping existing Telegram webhook state.")
        return
    try:
        url = f"{WEBHOOK_URL}/tg-webhook"
        r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook", json={"url": url, "drop_pending_updates": False}, timeout=15)
        logger.info("Telegram webhook setup: %s", r.text[:500])
    except Exception as exc:
        logger.error("Webhook setup error: %s", exc)


def get_daily_market_regime(force=False):
    now_ts = time.time()
    if not force and (now_ts - MARKET_REGIME_CACHE["updated_ts"]) < REGIME_TTL_SECONDS:
        return MARKET_REGIME_CACHE

    leaders = ["BTC/USDT:USDT", "ETH/USDT:USDT"]
    bull_votes = 0
    bear_votes = 0
    details_lines = []

    for sym in leaders:
        resolved, daily, _ = fetch_ohlcv(sym, "1d", 220)
        if not resolved or not daily or len(daily) < 60:
            continue
        df = engine.prepare_dataframe(daily)
        if len(df) < 60:
            continue

        close = float(df["close"].iloc[-1])
        ema20 = float(engine.calculate_ema(df["close"], 20).iloc[-1])
        ema50 = float(engine.calculate_ema(df["close"], 50).iloc[-1])
        adx = float(engine.calculate_adx(df).iloc[-1])
        _, _, macd_hist = engine.calculate_macd(df["close"])
        hist = float(macd_hist.iloc[-1]) if not macd_hist.empty else 0.0

        is_bull = (close > ema20) and (ema20 >= ema50 * 0.992) and (hist >= 0) and (adx >= 16)
        is_bear = (close < ema20) and (ema20 <= ema50 * 1.008) and (hist <= 0) and (adx >= 16)

        if is_bull:
            bull_votes += 1
            tag = f"🟢 {resolved.split('/')[0]}: صاعد (ADX {adx:.1f})"
        elif is_bear:
            bear_votes += 1
            tag = f"🔴 {resolved.split('/')[0]}: هابط (ADX {adx:.1f})"
        else:
            tag = f"⚖️ {resolved.split('/')[0]}: عرضي/متذبذب (ADX {adx:.1f})"
        details_lines.append(tag)

    if bull_votes >= 2 or (bull_votes == 1 and bear_votes == 0):
        regime = "BULLISH"
        title = "🟢 اتجاه السوق اليومي: صاعد (BULLISH)"
    elif bear_votes >= 2 or (bear_votes == 1 and bull_votes == 0):
        regime = "BEARISH"
        title = "🔴 اتجاه السوق اليومي: هابط (BEARISH)"
    else:
        regime = "SIDEWAYS"
        title = "⚖️ اتجاه السوق اليومي: تذبذب عرضي (SIDEWAYS)"

    summary = f"{title}\n" + "\n".join(details_lines) if details_lines else f"{title}\nبيانات القيادات غير كافية حالياً"
    MARKET_REGIME_CACHE.update({"regime": regime, "summary": summary, "updated_ts": now_ts})
    return MARKET_REGIME_CACHE


def is_counter_regime(regime, direction):
    return (regime == "BULLISH" and direction == "SHORT") or (regime == "BEARISH" and direction == "LONG")


def decimals_for(price):
    try:
        price = float(price)
        if price < 0.0001:
            return 10
        if price < 0.01:
            return 8
        if price < 0.1:
            return 7
        if price < 1:
            return 6
        if price < 100:
            return 4
        return 2
    except Exception:
        return 4


def format_num(value, decimals):
    try:
        value = float(value)
        return "N/A" if value <= 0 else f"{value:.{decimals}f}"
    except Exception:
        return "N/A"


def _calc_rr(entry_low, entry_high, stop_loss, target):
    try:
        entry_mid = (float(entry_low) + float(entry_high)) / 2.0
        sl = float(stop_loss)
        tgt = float(target)
        risk = abs(entry_mid - sl)
        reward = abs(tgt - entry_mid)
        if risk <= 0:
            return "N/A"
        return f"1 : {reward / risk:.2f}"
    except Exception:
        return "N/A"


def _format_neutral_diagnostics(signal):
    details = (signal or {}).get("details", {}) or {}
    macro_d = details.get("1w_1m")
    dl = (details.get("daily_long") or {}).get("reason", "N/A")
    ds = (details.get("daily_short") or {}).get("reason", "N/A")
    h4l = (details.get("4h_long") or {}).get("reason", "N/A")
    h4s = (details.get("4h_short") or {}).get("reason", "N/A")
    h1l = (details.get("1h_long") or {}).get("reason", "N/A")
    h1s = (details.get("1h_short") or {}).get("reason", "N/A")
    best_cand = details.get("best_candidate")
    lines = []
    if best_cand:
        lines.append(f"• الأقرب للاكتمال: {best_cand}")
    if macro_d:
        lines.append(f"• 1W/1M: {macro_d}")
    lines.append(f"• 1D (LONG/SHORT): {dl} | {ds}")
    lines.append(f"• 4H (LONG/SHORT): {h4l} | {h4s}")
    lines.append(f"• 1H (LONG/SHORT): {h1l} | {h1s}")
    return "\n".join(lines)


def monitor_tracked_positions(chat_id=None):
    positions = get_active_positions()
    if not positions:
        return
    for pos in positions:
        try:
            _, m15, _ = fetch_ohlcv(pos["symbol_raw"], "15m", 60)
            if not m15:
                continue
            current_price = float(m15[-1][4])
            tps = [pos["tp1"], pos["tp2"], pos["tp3"]]
            res = engine.evaluate_open_position(
                direction=pos["direction"],
                entry_price=pos["entry_price"],
                stop_loss=pos["stop_loss"],
                take_profits=tps,
                current_price=current_price,
                candles_15m=m15,
            )
            action = res.get("action", "HOLD")
            if action == "HOLD" or action == pos.get("last_action"):
                continue

            d = decimals_for(current_price)
            msg = (
                "🛡️ <b>متابعة صفقة نشطة (TP1/TP2) — V134.0</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"💎 <b>الأصل:</b> <code>{pos['resolved']}</code> ({pos['direction']})\n"
                f"💵 <b>السعر الحالي:</b> <code>{format_num(current_price, d)}</code>\n"
                f"📍 <b>الدخول المرجعي:</b> <code>{format_num(pos['entry_price'], d)}</code>\n"
                f"🥇 <b>TP1:</b> <code>{format_num(pos['tp1'], d)}</code>\n"
                f"🥈 <b>TP2 (الهدف الأساسي):</b> <code>{format_num(pos['tp2'], d)}</code>\n\n"
                f"{res.get('message', '')}"
            )
            if tg_send(msg, chat_id):
                scan_stats["guard_alerts_sent"] += 1
                if action in ("STOP_HIT", "TP2_REACHED"):
                    db_query("DELETE FROM tracked_positions WHERE signal_id = ?", (pos["signal_id"],))
                else:
                    db_query(
                        "UPDATE tracked_positions SET last_action = ?, updated_ts = ? WHERE signal_id = ?",
                        (action, time.time(), pos["signal_id"]),
                    )
            time.sleep(0.1)
        except Exception as exc:
            logger.debug("Monitor position error for %s: %s", pos.get("resolved"), exc)


def analyze_symbol(symbol_raw, chat_id=None, manual=False, direction_counts=None, prefer_long=False):
    try:
        resolved, daily, asset_type = fetch_ohlcv(symbol_raw, "1d", 220)
        if not resolved or not daily or len(daily) < 55:
            if manual:
                tg_send(f"❌ الأصل <code>{symbol_raw}</code> غير متوفر أو بياناته اليومية غير كافية.", chat_id)
            return False, None
        _, h4, _ = fetch_ohlcv(symbol_raw, "4h", 100)
        _, h1, _ = fetch_ohlcv(symbol_raw, "1h", 100)
        _, m15, _ = fetch_ohlcv(symbol_raw, "15m", 120)
        _, w1, _ = fetch_ohlcv(symbol_raw, "1w", 60)
        _, mn1, _ = fetch_ohlcv(symbol_raw, "1m", 36)
        if len(h4 or []) < 35 or len(h1 or []) < 30:
            if manual:
                tg_send(f"❌ <code>{resolved}</code> بيانات 4H/1H غير كافية.", chat_id)
            return False, None

        if manual:
            active_pos = _find_active_position(resolved)
            if active_pos:
                d_pos = decimals_for(active_pos["entry_price"])
                curr_p = float(m15[-1][4]) if m15 else float(h1[-1][4])
                tg_send(
                    f"📌 <b>صفقة نشطة قيد المتابعة:</b> <code>{active_pos['resolved']}</code> ({active_pos['direction']})\n"
                    "━━━━━━━━━━━━━━━━━━\n"
                    f"💵 <b>السعر الحالي:</b> <code>{format_num(curr_p, d_pos)}</code>\n"
                    f"📍 <b>الدخول:</b> <code>{format_num(active_pos['entry_price'], d_pos)}</code>\n"
                    f"🥇 <b>TP1:</b> <code>{format_num(active_pos['tp1'], d_pos)}</code>\n"
                    f"🥈 <b>TP2:</b> <code>{format_num(active_pos['tp2'], d_pos)}</code>\n"
                    f"🛑 <b>الوقف:</b> <code>{format_num(active_pos['stop_loss'], d_pos)}</code>\n"
                    f"📊 <b>الحالة:</b> <code>{active_pos['last_action']}</code>",
                    chat_id,
                )
                return True, None

        scan_stats["scanned_pairs"] += 1
        direction, price, signal = engine.analyze_market_structure(
            daily, h4, h1, asset_type=asset_type, ohlcv_15m=m15, ohlcv_1w=w1, ohlcv_1m=mn1
        )
        if prefer_long and direction == "SHORT":
            direction = "NEUTRAL"
        market_tag = {"crypto": "🪙 Crypto", "stock": "📈 Stocks / ETFs", "forex": "💱 Forex / Metals"}.get(asset_type, "📊 Market")
        regime_info = get_daily_market_regime()
        regime = regime_info.get("regime", "SIDEWAYS")
        details = (signal or {}).get("details", {}) or {}
        trade_style = str(details.get("trade_style", "SCALP")).upper()
        is_long_term = trade_style == "POSITION"
        is_swing = trade_style == "SWING"
        counter = is_counter_regime(regime, direction)
        sig_score = int((signal or {}).get("score", 0))

        if direction in ("LONG", "SHORT"):
            if not manual:
                if _is_duplicate_active_position(resolved, direction):
                    return False, signal
                if counter and trade_style == "SCALP" and sig_score < COUNTER_REGIME_MIN_SCORE:
                    return False, signal
                if direction_counts is not None and direction_counts.get(direction, 0) >= MAX_SAME_DIRECTION_PER_SCAN:
                    return False, signal

            key = resolved.split("/")[0]
            now_ts = time.time()
            with cache_lock:
                last_sent = _sent_signals_cache.get(key, 0)
                if not manual and (now_ts - last_sent) < SIGNAL_COOLDOWN_SECONDS:
                    return False, signal
                _sent_signals_cache[key] = now_ts

            d = decimals_for(price)
            tps = list(signal.get("take_profits", []))
            while len(tps) < 3:
                tps.append(0)
            fib_poc = details.get("fib_poc", {}) or {}
            _, momentum_msg = engine.check_momentum_at_tp1(h1)
            emoji = "🟢" if direction == "LONG" else "🔴"
            side = "شراء LONG" if direction == "LONG" else "بيع SHORT"
            if is_long_term:
                style_badge = "🏛️ طويلة المدى (POSITION — 1W/1M)"
            elif is_swing:
                style_badge = "🌊 سوينج (SWING — 1D/4H)"
            else:
                style_badge = "⚡ سكالبنج لحظي (SCALP — 15M/1H)"

            close_tag = "✅ مؤكد" if details.get("close_confirmed") else "⚖️ جزئي"
            sig_regime = details.get("regime", regime)
            key_sup = details.get("key_support", 0)
            res_low = details.get("resistance_low", 0)
            res_high = details.get("resistance_high", 0)
            rr_tp1 = _calc_rr(signal.get("entry_low"), signal.get("entry_high"), signal.get("stop_loss"), tps[0])
            rr_tp2 = _calc_rr(signal.get("entry_low"), signal.get("entry_high"), signal.get("stop_loss"), tps[1])

            msg = (
                "🚀 <b>MY EXPERT MULTI-MARKET BOT V134.0</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"🏷️ <b>السوق:</b> {market_tag}\n"
                f"🎛️ <b>تصنيف الصفقة:</b> <b>{style_badge}</b>\n"
                f"🌐 <b>حالة السوق:</b> <code>{sig_regime}</code>\n"
                f"{emoji} <b>{side} — تأكيد إغلاق + فلتر زخم وسيولة وR:R</b>\n\n"
                f"💎 <b>الأصل:</b> <code>{resolved}</code>\n"
                f"⭐ <b>التقييم:</b> <code>{sig_score}/100</code> ({details.get('quality','A')})\n\n"
                f"📍 <b>منطقة الدخول:</b> <code>{format_num(signal.get('entry_low'),d)} — {format_num(signal.get('entry_high'),d)}</code>\n\n"
                "🎯 <b>الأهداف العملية (التركيز على TP1 و TP2):</b>\n"
                f"🥇 TP1 (تأمين/نقل الوقف): <code>{format_num(tps[0],d)}</code> | R:R <code>{rr_tp1}</code>\n"
                f"🥈 TP2 (الهدف الأساسي): <code>{format_num(tps[1],d)}</code> | R:R <code>{rr_tp2}</code>\n"
                f"🥉 TP3 (اختياري/إضافي): <code>{format_num(tps[2],d)}</code>\n\n"
                f"🛑 <b>وقف الخسارة (بإغلاق شمعة):</b> <code>{format_num(signal.get('stop_loss'),d)}</code>\n"
                f"📉 <b>الدعم الرئيسي:</b> <code>{format_num(key_sup, d)}</code>\n"
                f"🚧 <b>المقاومة الرئيسية:</b> <code>{format_num(res_low, d)} — {format_num(res_high, d)}</code>\n"
                f"📈 <b>RSI:</b> <code>{float(signal.get('rsi',50)):.1f}</code> | 📊 <b>ADX:</b> <code>{float(details.get('adx',25)):.1f}</code>\n"
                f"🧲 <b>PoC (أعلى حجم):</b> <code>{format_num(fib_poc.get('poc', 0), d)}</code>\n"
                f"🕯️ <b>تأكيد الإغلاق:</b> <code>{close_tag}</code> | ⚖️ <b>المخاطرة:</b> <code>{float(details.get('risk_pct',0)):.2f}%</code>\n\n"
                f"🧠 <b>السبب:</b> {signal.get('reason','')}\n\n"
                f"🎯 <b>متابعة الزخم:</b>\n{momentum_msg}\n\n"
                "⚠️ <b>إشارة تحليلية فقط — التزم بإدارة المخاطر ولا تفرط في التعرض.</b>"
            )
            sent = tg_send(msg, chat_id)
            if sent:
                scan_stats["signals_sent"] += 1
                save_tracked_position(signal, symbol_raw, resolved)
                if not manual and direction_counts is not None:
                    direction_counts[direction] = direction_counts.get(direction, 0) + 1
            else:
                with cache_lock:
                    if not manual:
                        _sent_signals_cache[key] = last_sent
            return sent, signal

        if manual:
            reason = signal.get("reason", "الشروط غير مكتملة") if signal else "الشروط غير مكتملة"
            diag_text = _format_neutral_diagnostics(signal)
            tg_send(
                f"📊 <b>تحليل:</b> <code>{symbol_raw}</code>\n🏷️ <b>السوق:</b> {market_tag}\n━━━━━━━━━━━━━━━━━━\n"
                "⚪ <b>لا توجد صفقة (SCALP/SWING/POSITION) عالية الجودة حاليًا.</b>\n"
                f"🔎 <b>السبب:</b> {reason}\n\n"
                f"📋 <b>تفاصيل الفلاتر:</b>\n<code>{diag_text}</code>", chat_id)
        return False, signal
    except Exception as exc:
        scan_stats["errors"] += 1
        logger.exception("Analyze %s error: %s", symbol_raw, exc)
        if manual:
            tg_send(f"❌ حدث خطأ مؤقت أثناء تحليل <code>{symbol_raw}</code>.", chat_id)
        return False, None


def run_gainers_scan(chat_id=None):
    if not scan_lock.acquire(blocking=False):
        if chat_id:
            tg_send("⏳ يوجد فحص قيد التشغيل حاليًا.", chat_id)
        return
    try:
        top = get_top_gainers(limit=15)
        if not top:
            if chat_id:
                tg_send("⚠️ لم أتمكن من جلب قائمة الأعلى ربحاً حالياً.", chat_id)
            return
        preview = "\n".join([f"• <code>{s.split(':')[0]}</code>: <b>+{p:.1f}%</b>" for p, s in top[:8]])
        if chat_id:
            tg_send(f"🔥 <b>فحص الأعلى ربحاً (Top Gainers — 24h):</b>\n{preview}\n\n⏳ جارٍ فحص فرص السكالبنج والسوينج والطويلة (TP1/TP2)...", chat_id)
        found = 0
        for _, sym in top:
            try:
                ok, _ = analyze_symbol(sym, chat_id=chat_id, manual=False, prefer_long=True)
                if ok:
                    found += 1
            except Exception as exc:
                logger.debug("Gainers scan skip %s: %s", sym, exc)
            time.sleep(0.15)
        if chat_id:
            tg_send(f"✅ انتهى فحص الرابحين. الفرص المكتملة: <b>{found}</b>", chat_id)
    finally:
        scan_lock.release()


def run_full_scan(chat_id=None):
    if not scan_lock.acquire(blocking=False):
        if chat_id:
            tg_send("⏳ يوجد فحص شامل قيد التشغيل حاليًا.", chat_id)
        return
    try:
        monitor_tracked_positions(chat_id=chat_id)
        regime_info = get_daily_market_regime(force=True)
        if chat_id:
            tg_send(
                "🔍 <b>جارٍ فحص Crypto + Stocks/ETFs + Forex/Metals (نسخة V134.0)...</b>\n"
                f"{regime_info.get('summary', '')}",
                chat_id,
            )
        top_gainers = [s for _, s in get_top_gainers(limit=15)]
        base_symbols = get_full_market_universe()
        symbols = []
        seen = set()
        for s in top_gainers + base_symbols:
            if s not in seen:
                symbols.append(s)
                seen.add(s)

        found = 0
        direction_counts = {"LONG": 0, "SHORT": 0}
        for sym in symbols:
            try:
                ok, _ = analyze_symbol(sym, chat_id=None, manual=False, direction_counts=direction_counts)
                if ok:
                    found += 1
            except Exception as exc:
                scan_stats["errors"] += 1
                logger.debug("Scan skip %s: %s", sym, exc)
            time.sleep(0.12)
        logger.info("Full scan complete: total=%s, found=%s, stats=%s", len(symbols), found, scan_stats)
        if chat_id:
            tg_send(f"✅ <b>انتهى الفحص.</b>\n\n🔎 الأصول المفحوصة: <code>{len(symbols)}</code>\n🟢 الفرص: <code>{found}</code>", chat_id)
    except Exception as exc:
        scan_stats["errors"] += 1
        logger.exception("Full scan error: %s", exc)
        if chat_id:
            tg_send("❌ حدث خطأ أثناء الفحص الشامل.", chat_id)
    finally:
        scan_lock.release()


def background_auto_scheduler():
    time.sleep(20)
    while True:
        try:
            if TELEGRAM_CHAT_ID:
                logger.info("Auto scheduler starting cycle (stats=%s)", scan_stats)
                run_full_scan()
                logger.info("Auto scheduler finished cycle (stats=%s)", scan_stats)
            else:
                logger.warning("Auto scheduler skipped: TELEGRAM_CHAT_ID is empty")
        except Exception as exc:
            logger.exception("Scheduler error: %s", exc)
        time.sleep(SCAN_INTERVAL_SECONDS)


HELP_TEXT = (
    "🤖 <b>MY EXPERT MULTI-MARKET BOT V134.0</b>\n━━━━━━━━━━━━━━━━━━\n\n"
    "🧭 <b>الأسواق:</b> Crypto + Stocks/ETFs + Forex/Metals\n"
    "🎛️ <b>النظام الثلاثي:</b> يحدد تلقائياً هل الفرصة <b>⚡ سكالبنج (SCALP)</b> أو <b>🌊 سوينج (SWING)</b> أو <b>🏛️ طويلة المدى (POSITION — 1W/1M)</b>\n"
    "🎯 <b>الأهداف:</b> تركيز عملي على TP1 و TP2 مع عرض R:R والدعم والمقاومة الرئيسية\n"
    "🔥 أرسل <code>/gainers</code> لاكتشاف فرص الزخم في الرابحين.\n"
    "🌐 أرسل <code>/regime</code> لمعرفة اتجاه السوق اليومي.\n"
    "📌 أرسل BTC أو ETH أو SOXS أو XAUUSD أو أي رمز مدعوم\n"
    "🔍 أرسل <code>/scan</code> للفحص الشامل ومتابعة الصفقات.\n"
    "🛡️ أرسل <code>/positions</code> لعرض الصفقات المتابعة، أو <code>/clearpos</code> لمسحها.\n"
    "⚠️ إشارات تحليلية فقط — لا تنفيذ تلقائي."
)


def handle_update(data):
    try:
        message = data.get("message") or data.get("edited_message")
        if not message:
            return
        chat_id = message.get("chat", {}).get("id")
        text = (message.get("text") or "").strip()
        if not chat_id or not text:
            return
        if ALLOWED_CHAT_IDS and str(chat_id) not in ALLOWED_CHAT_IDS:
            return
        parts = text.split()
        cmd = parts[0].split("@")[0].lower()
        if cmd in ("/start", "/help"):
            tg_send(HELP_TEXT, chat_id)
        elif cmd == "/regime":
            info = get_daily_market_regime(force=True)
            tg_send(f"🧭 <b>تقرير اتجاه السوق اليومي</b>\n━━━━━━━━━━━━━━━━━━\n{info['summary']}", chat_id)
        elif cmd == "/gainers":
            threading.Thread(target=run_gainers_scan, args=(chat_id,), daemon=True).start()
        elif cmd == "/scan":
            threading.Thread(target=run_full_scan, args=(chat_id,), daemon=True).start()
        elif cmd == "/positions":
            pos_list = get_active_positions()
            if not pos_list:
                tg_send("📭 لا توجد صفقات متابعة نشطة حالياً.", chat_id)
            else:
                lines = ["🛡️ <b>الصفقات المتابعة حالياً (TP1/TP2):</b>\n"]
                for p in pos_list:
                    d = decimals_for(p["entry_price"])
                    lines.append(
                        f"• <code>{p['resolved']}</code> ({p['direction']}) | دخول: <code>{format_num(p['entry_price'], d)}</code> | "
                        f"TP1: <code>{format_num(p['tp1'], d)}</code> | TP2: <code>{format_num(p['tp2'], d)}</code> | "
                        f"حالة: <code>{p['last_action']}</code>"
                    )
                tg_send("\n".join(lines), chat_id)
        elif cmd == "/clearpos":
            clear_tracked_positions()
            tg_send("🧹 تم مسح قائمة الصفقات المتابعة.", chat_id)
        else:
            analyze_symbol(parts[0], chat_id=chat_id, manual=True)
    except Exception:
        logger.exception("handle_update error")


@app.route("/")
def index():
    return jsonify({"status": "running", "version": "V134.0-Scalp-Swing-Position", "stats": scan_stats})


@app.route("/health")
def health():
    return "OK", 200


@app.route("/tg-webhook", methods=["POST"])
def telegram_webhook():
    data = request.get_json(silent=True) or {}
    uid = data.get("update_id")
    with _seen_lock:
        if uid is not None and uid in _seen_updates:
            return "OK", 200
        if uid is not None:
            _seen_updates.append(uid)
    threading.Thread(target=handle_update, args=(data,), daemon=True).start()
    return "OK", 200


def bootstrap():
    db_init()
    logger.info("Bot V134.0 bootstrapped: Scalp + Swing + Weekly/Monthly Position Engine.")
    threading.Thread(target=configure_webhook, daemon=True).start()
    threading.Thread(target=background_auto_scheduler, daemon=True).start()


bootstrap()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), threaded=True)
