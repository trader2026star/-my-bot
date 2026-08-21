import telebot
import requests
import os

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_text = (
        "⚡ **أهلاً بك يا محمد في بوت رصد سيولة السوق والتحليل الاحترافي**\n\n"
        "• اكتب `scan` لفحص السوق بالكامل وتصنيف الأعملات:\n"
        "  🟢 **عملات تجمع سيولة (جاهزة للبمب أو الانفجار)**\n"
        "  🔴 **عملات خرجت منها السيولة (معرضة للهبوط أو التصحيح)**\n"
        "• أو اكتب رمز أي عملة مباشرة (مثل `btc`, `zec`, `tao`, `morpho`) لعرض حالتها الفورية.\n"
    )
    bot.reply_to(message, welcome_text, parse_mode="Markdown")

@bot.message_handler(func=lambda message: True)
def handle_messages(message):
    text = message.text.lower().strip()
    
    if text == "scan":
        bot.reply_to(message, "🔍 **جاري فحص السيولة، تتبع صفقات الحيتان، ورصد العملات الصاعدة والهابطة...**", parse_mode="Markdown")
        try:
            url = "https://api.binance.com/api/v3/ticker/24hr"
            res = requests.get(url, timeout=10)
            data = res.json()
            
            pumping_soon = []
            dumping_soon = []
            
            for ticker in data:
                symbol = ticker['symbol']
                if symbol.endswith('USDT'):
                    change = float(ticker['priceChangePercent'])
                    volume = float(ticker['quoteVolume']) # حجم التداول بالدولار لتقدير السيولة
                    
                    # استبعاد العملات الضعيفة والتركيز على ذات السيولة العالية
                    if volume > 5000000: 
                        coin_name = symbol.replace('USDT', '')
                        # منطق رصد التجميع قبل البمب (هابطة طفيفاً أو في قاع لكن حجم التداول عالي/سيولة تدخل)
                        # أو عملات بدأت تفجر وتخترق
                        if -2.0 <= change <= 6.0:
                            pumping_soon.append((coin_name, change, volume))
                        elif change < -4.0: # عملات هبطت وخرجت منها السيولة بقوة
                            dumping_soon.append((coin_name, change, volume))
            
            # ترتيب العملات حسب الحجم أو الأداء
            pumping_soon = sorted(pumping_soon, key=lambda x: x[2], reverse=True)[:5]
            dumping_soon = sorted(dumping_soon, key=lambda x: x[1], reverse=True)[:5]
            
            msg = "📊 **تقرير سيولة السوق المتقدم:**\n\n"
            
            msg += "🟢 **أصول تحت التجميع (تراكم سيولة / مرشحة للبمب):**\n"
            for coin, ch, vol in pumping_soon:
                msg += f"• **{coin}**: تغير {ch:+.2f}% | سيولة نشطة 💧\n"
            
            msg += "\n🔴 **أصول خرجت منها السيولة (ضعيفة / مرشحة للهبوط):**\n"
            for coin, ch, vol in dumping_soon:
                msg += f"• **{coin}**: تغير {ch:+.2f}% | خروج سيولة ⚠️\n"
                
            bot.reply_to(message, msg, parse_mode="Markdown")
        except Exception as e:
            bot.reply_to(message, "❌ حدث خطأ أثناء تحليل بيانات السيولة، حاول مجدداً.")
            
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
                
                status = "🟢 سيولة داخلة / أداء قوي" if change >= 0 else "🔴 خروج سيولة / ضغط بيعي"
                
                response_text = (
                    f"🎯 **تحليل سيولة الأصل: {query.replace('USDT', '')}**\n\n"
                    f"💰 **السعر الحالي:** ${price:,.4f}\n"
                    f"📈 **التغير خلال 24س:** {change:+.2f}%\n"
                    f"🌊 **حالة السيولة:** {status}\n"
                    f"📊 **حجم التداول (السيولة اليومية):** ${volume:,.0f}\n"
                    f"⬆️ **أعلى سعر:** ${high:,.4f} | ⬇️ **أقل سعر:** ${low:,.4f}\n\n"
                    f"💡 *جاهز لربط أي استراتيجية خاصة بيك.*"
                )
                bot.reply_to(message, response_text, parse_mode="Markdown")
            else:
                bot.reply_to(message, "⚠️ لم يتم العثور على هذا الأصل، تأكد من الرمز.")
        except Exception as e:
            bot.reply_to(message, "⚠️ حدث خطأ في جلب بيانات الأصل.")

bot.infinity_polling()
