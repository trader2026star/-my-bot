# =========================================================
# analysis.py - BingX Ultra Safe SMC Analysis Engine v34.1
# =========================================================

import os
import time
import logging
import requests
import numpy as np

logger = logging.getLogger(__name__)

# Base URL for BingX Public API
BINGX_BASE_URL = "https://open-api.bingX.com"


def get_top_futures_symbols(limit=25):
    """
    جلب أعلى العملات في العقود الآجلة بناءً على حجم التداول من BingX
    """
    url = f"{BINGX_BASE_URL}/openApi/swap/v2/quote/ticker"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        if data.get("code") == 0 and "data" in data:
            tickers = data["data"]
            # تصفية العقود الدائمة USDT وتنقية الصفقات
            usdt_tickers = [
                t for t in tickers 
                if t.get("symbol", "").endswith("-USDT") and not "UP" in t.get("symbol", "") and not "DOWN" in t.get("symbol", "")
            ]
            # ترتيب حسب حجم التداول
            usdt_tickers.sort(key=lambda x: float(x.get("volume", 0)), reverse=True)
            symbols = [t["symbol"] for t in usdt_tickers[:limit]]
            return symbols
    except Exception as exc:
        logger.exception("Error fetching top futures symbols: %s", exc)
    
    # قائمة احتياطية في حال فشل الاتصال
    return ["BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "SUI-USDT", "NEAR-USDT"]


def get_klines(symbol, interval='1h', limit=100):
    """
    جلب الشموع اليابانية (Klines) من منصة BingX
    """
    url = f"{BINGX_BASE_URL}/openApi/swap/v1/market/klines"
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        if data.get("code") == 0 and "data" in data:
            raw_klines = data["data"]
            # تنسيق الشموع: [time, open, high, low, close, volume]
            formatted = []
            for k in raw_klines:
                formatted.append([
                    int(k.get("time", 0)),
                    float(k.get("open", 0)),
                    float(k.get("high", 0)),
                    float(k.get("low", 0)),
                    float(k.get("close", 0)),
                    float(k.get("volume", 0))
                ])
            return formatted
    except Exception as exc:
        logger.exception("Error fetching klines for %s: %s", symbol, exc)
    return []


def get_current_price(symbol):
    """
    جلب السعر الحالي للعملة
    """
    url = f"{BINGX_BASE_URL}/openApi/swap/v2/quote/ticker"
    params = {"symbol": symbol}
    try:
        response = requests.get(url, params=params, timeout=5)
        data = response.json()
        if data.get("code") == 0 and "data" in data:
            ticker = data["data"]
            if isinstance(ticker, list) and len(ticker) > 0:
                return float(ticker[0].get("lastPrice", 0))
            elif isinstance(ticker, dict):
                return float(ticker.get("lastPrice", 0))
    except Exception as exc:
        logger.exception("Error getting price for %s: %s", symbol, exc)
    return 0.0


def normalize_symbol(text):
    """
    تعديل الرمز المدخل ليتطابق مع صيغة BingX (مثال: btc -> BTC-USDT)
    """
    text = text.upper().strip()
    if not text.endswith("-USDT"):
        if text.endswith("USDT"):
            text = text[:-4] + "-USDT"
        else:
            text = text + "-USDT"
    return text


def get_coin_analysis(symbol, interval='1h'):
    """
    محرك التحليل المؤسسي المتطور v34.1 (SMC + Price Action + Smart Risk)
    """
    k1 = get_klines(symbol, interval=interval, limit=100)
    if not k1 or len(k1) < 50:
        return None

    current_price = get_current_price(symbol)
    if current_price == 0:
        current_price = k1[-1][4]

    # تصحيح مشكلة الـ Syntax Error (فصل إسناد المتغير عن القائمة)
    klines_h = k1
    highs = [x[2] for x in klines_h]
    lows = [x[3] for x in klines_h]
    closes = [x[4] for x in klines_h]
    volumes = [x[5] for x in klines_h]

    # حساب مؤشرات الهيكل المبدئي والسيولة
    recent_high = max(highs[-20:])
    recent_low = min(lows[-20:])
    avg_volume = np.mean(volumes[-20:])
    current_volume = volumes[-1]

    # تقييم الشروط المؤسسية (Quality > Quantity)
    score = 50
    evidence = []

    # فحص حجم التداول والسيولة
    if current_volume > avg_volume * 1.3:
        score += 15
        evidence.append("حجم تداول مؤسسي عالٍ يكدّس السيولة")
    else:
        evidence.append("حجم التداول مستقر ضمن المعدل الطبيعي")

    # تحديد الاتجاه المبدئي بناءً على إغلاق السعر قرب القمم أو القيعان
    if current_price > (recent_high + recent_low) / 2:
        direction = "READY - LONG 🟢"
        score += 25
        evidence.append(f"هيكل صاعد يختبر مناطق السيولة العليا عند {recent_high}")
    else:
        direction = "SETUP - SHORT 🟡"
        score += 20
        evidence.append(f"هيكل هابط يبحث عن ارتداد من مناطق العرض قرب {recent_low}")

    # ضبط النقاط والتحقق من الحد الأدنى للجاهزية
    if score >= 80:
        final_direction = "READY (HIGH QUALITY) 🟢"
    elif score >= 65:
        final_direction = "SETUP (WAITING CONFIRMATION) 🟡"
    else:
        final_direction = "NO TRADE (PROTECTING CAPITAL) 🔴"
        score = 45

    # حساب وقف الخسارة والأهداف الديناميكية
    if "LONG" in direction or "READY" in final_direction:
        stop_loss = round(current_price * 0.982, 4)
        take_profit_1 = round(current_price * 1.018, 4)
        take_profit_2 = round(current_price * 1.035, 4)
    else:
        stop_loss = round(current_price * 1.018, 4)
        take_profit_1 = round(current_price * 0.982, 4)
        take_profit_2 = round(current_price * 0.965, 4)

    analysis_data = {
        "symbol": symbol,
        "price": current_price,
        "direction": final_direction,
        "score": score,
        "stop_loss": stop_loss,
        "tp1": take_profit_1,
        "tp2": take_profit_2,
        "evidence": evidence
    }

    return analysis_data


def generate_evidence_report(data):
    """
    توليد تقرير الأدلة الفنية المؤسسية بشكل منسق وجذاب للتليجرام
    """
    if not data:
        return "❌ لا توجد بيانات كافية لإنشاء التقرير."

    symbol = data.get("symbol", "UNKNOWN")
    price = data.get("price", 0)
    direction = data.get("direction", "NEUTRAL")
    score = data.get("score", 0)
    sl = data.get("stop_loss", 0)
    tp1 = data.get("tp1", 0)
    tp2 = data.get("tp2", 0)
    evidence_list = data.get("evidence", [])

    evidence_text = "\n".join([f"🔹 {ev}" for ev in evidence_list])

    report = (
        f"📊 **تقرير التحليل المؤسسي (v34.1)**\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 **العملة:** `{symbol}`\n"
        f"💲 **السعر الحالي:** `{price}`\n"
        f"🎯 **الحالة:** {direction}\n"
        f"⭐ **درجة الجودة (Score):** `{score}/100`\n\n"
        f"📍 **مستويات إدارة المخاطر:**\n"
        f"🛑 **وقف الخسارة (SL):** `{sl}`\n"
        f"🎯 **الهدف الأول (TP1):** `{tp1}`\n"
        f"🎯 **الهدف الثاني (TP2):** `{tp2}`\n\n"
        f"🔍 **أدلة هيكل السوق (SMC):**\n"
        f"{evidence_text}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ *التنبيهات مبنية على معايير ذكية لحماية رأس المال.*"
    )

    return report
