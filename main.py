import telebot
import requests
import os

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_text = (
        "🚀 **أهلاً بك يا محمد في بوت سيولة السوق الاحترافي**\n\n"
        "• اكتب `scan` لفحص السوق وتصنيف الأصول بدقة:\n"
        "  🟢 **أصول تحت التجميع / دخلها سيولة (مرشحة للانفجار والبمب)**\n"
        "  🔴 **أصول خرجت منها السيولة (معرضة للهبوط والتصحيح)**\n"
        "• أو اكتب رمز أي عملة مباشرة (مثل `btc`, `zec`, `tao`, `morpho`) لعرض حالتها اللحظية."
    )
    bot.reply_to(message, welcome_text, parse_mode="Markdown")

@bot.message_handler(func=lambda message: True)
def handle_messages(message):
    text = message.text.lower().strip()
    
    if text == "scan":
        bot.reply_to(message, "🔍 **جاري فحص دفتر الطلبات والسيولة اللحظية...**", parse_mode="Markdown")
        try:
            url = "https://api.binance.com/api/v3/ticker/24hr"
            res = requests.get(url, timeout=10)
            data = res.json()
            
            pumping_pool = []
            dumping_pool = []
            
            for ticker in data:
                symbol = ticker['symbol']
                if symbol.endswith('USDT'):
                    change = float(ticker['priceChangePercent'])
                    volume = float(ticker['quoteVolume']) # حجم السيولة بالدولار
                    
                    if volume > 2000000: # التركيز على العملات ذات السيولة الحقيقية
                        coin_name = symbol.replace('USDT', '')
                        # تصنيف العملات التي تبني سيولة للصعود أو بدأت تخترق
                        if -1.5 <= change <= 7.0:
                            pumping_pool.append((coin_name, change, volume))
                        # تصنيف العملات التي فقدت السيولة وتهبط بقوة
                        elif change < -3.5:
                            dumping_pool.append((coin_name, change, volume))
            
            pumping_pool = sorted(pumping_pool, key=lambda x: x[2], reverse=True)[:5]
            dumping_pool = sorted(dumping_pool, key=lambda x: x[1], reverse=True)[:5]
            
            msg = "📊 **تقرير رصد السيولة المتقدم:**\n\n"
            
            msg += "🟢 **عملات دخلها سيولة (جاهزة للبمب):**\n"
            for coin, ch, vol in pumping_pool:
                msg += f"• **{coin}**: تغير {ch:+.2f}% | سيولة نشطة 💧\n"
            
            msg += "\n🔴 **عملات خرجت منها السيولة (مهددة للهبوط):**\n"
            for coin, ch, vol in dumping_pool:
                msg += f"• **{coin}**: تغير {ch:+.2f}% | هروب سيولة ⚠️\n"
                
            bot.reply_to(message, msg, parse_mode="Markdown")
        except Exception as e:
            bot.reply_to(message, "❌ حدث خطأ أثناء تحليل السيولة، حاول مجدداً.")
            
    else:
        query = text.upper().replace("$", "").strip() + "USDT"
        try:
            url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={query}"
            res = requests.get(url, timeout=5)
            data = res.json()
            
            if 'lastPrice' in data:
                price = float(data['lastPrice'])
                change = float(data['priceChangePercent'])
                volume = float(data['quoteVolume'])
                high = float(data['highPrice'])
                low = float(data['lowPrice'])
                
                status = "🟢 تدفق سيولة إيجابي" if change >= 0 else "🔴 خروج سيولة وضغط بيع"
                
                response_text = (
                    f"🎯 **تحليل الأصل: {query.replace('USDT', '')}**\n\n"
                    f"💰 **السعر الحالي:** ${price:,.4f}\n"
                    f"📈 **التغير (24س):** {change:+.2f}%\n"
                    f"🌊 **حالة السيولة:** {status}\n"
                    f"📊 **حجم التداول اليومي:** ${volume:,.0f}\n"
                    f"⬆️ **القمة:** ${high:,.4f} | ⬇️ **القاع:** ${low:,.4f}"
                )
                bot.reply_to(message, response_text, parse_mode="Markdown")
            else:
                bot.reply_to(message, "⚠️ لم يتم العثور على هذا الأصل، تأكد من الرمز.")
        except Exception as e:
            bot.reply_to(message, "⚠️ حدث خطأ في جلب بيانات الأصل.")

bot.infinity_polling()
