import telebot
import requests
import os

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_text = (
        "🚀 **أهلاً بك يا محمد في بوت إدارة السوق الاحترافي**\n\n"
        "البوت يعمل الآن بكفاءة عالية وبدون أخطاء.\n"
        "• **لفحص السوق:** اكتب كلمة `scan`\n"
        "• **للبحث عن أي عملة:** اكتب رمزها مباشرة (مثل: `btc`, `zec`, `tao`, `morpho`, `sol`)\n\n"
        "جاهز تماماً لاستقبال أوامرك وتتبعاتك اللحظية! 📈"
    )
    bot.reply_to(message, welcome_text, parse_mode="Markdown")

@bot.message_handler(func=lambda message: True)
def handle_market_requests(message):
    text = message.text.lower().strip()
    
    if text == "scan":
        bot.reply_to(message, "⚡ **جاري فحص السوق وجلب تفاصيل الأصول النشطة...**", parse_mode="Markdown")
        try:
            url = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=10&sparkline=false"
            res = requests.get(url, timeout=10)
            data = res.json()
            
            msg = "📊 **تقرير السوق اللحظي:**\n\n"
            for coin in data:
                price = coin['current_price']
                change = coin['price_change_percentage_24h']
                symbol = coin['symbol'].upper()
                
                # إضافة مؤشر اتجاه صاعد أو هابط
                trend = "🟢" if change >= 0 else "🔴"
                msg += f"{trend} **{symbol}**: ${price:,.2f} | التغير: {change:.2f}%\n"
            
            bot.reply_to(message, msg, parse_mode="Markdown")
        except Exception as e:
            bot.reply_to(message, "❌ حدث خطأ أثناء الاتصال بالخادم لجلب البيانات، حاول مجدداً.")
            
    else:
        query = text.replace("$", "").strip()
        try:
            search_url = f"https://api.coingecko.com/api/v3/search?query={query}"
            search_res = requests.get(search_url, timeout=5).json()
            coins = search_res.get('coins', [])
            
            if coins:
                coin_id = coins[0]['id']
                price_url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd&include_24hr_change=true&include_market_cap=true"
                price_data = requests.get(price_url, timeout=5).json()
                
                if coin_id in price_data:
                    price = price_data[coin_id]['usd']
                    change = price_data[coin_id].get('usd_24h_change', 0)
                    mcap = price_data[coin_id].get('usd_market_cap', 0)
                    
                    trend = "🟢 صاعد" if change >= 0 else "🔴 هابط"
                    
                    response_text = (
                        f"🎯 **تحليل الأصل: {query.upper()}**\n\n"
                        f"💰 **السعر الحالي:** ${price:,.4f}\n"
                        f"📈 **حالة 24س:** {trend} ({change:.2f}%)\n"
                        f"🏦 **القيمة السوقية:** ${mcap:,.0f}\n\n"
                        f"⚡ *جاهز لأي إعدادات أو أهداف إضافية ترغب في رصدها.*"
                    )
                    bot.reply_to(message, response_text, parse_mode="Markdown")
                else:
                    bot.reply_to(message, "⚠️ تعذر جلب السعر الدقيق لهذا الأصل، تأكد من الرمز.")
            else:
                bot.reply_to(message, "⚠️ لم يتم العثور على هذا الأصل، تأكد من كتابة الرمز بشكل صحيح (مثل BTC, ZEC, TAO).")
        except Exception as e:
            bot.reply_to(message, "⚠️ حدث خطأ في الاتصال بالبيانات.")

bot.infinity_polling()
