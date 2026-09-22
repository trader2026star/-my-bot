analyst_engine = ExpertAnalystBot(exchange_id='bingx', api_key=API_KEY, secret_key=SECRET_KEY, timeframe='15m')

@app.route('/')
def home():
    """فحص العملات وحفظ التقارير وإرسالها عند توفر فرص حقيقية مطابقة لمنطق الخبير"""
    try:
        exchange = analyst_engine.exchange
        exchange.load_markets()

        # استبعاد العملات الوهمية والتركيز على العملات الحقيقية التي تنتهي بـ USDT فقط    
        all_symbols = [symbol for symbol in exchange.symbols if symbol.endswith('/USDT:USDT') and not symbol.startswith('NC')]    
            
        # اختيار عينة آمنة وسريعة (مثلاً 10 عملات حقيقية في كل زيارة)    
        sample_size = min(10, len(all_symbols))    
        symbols_to_scan = random.sample(all_symbols, sample_size)    
            
        html_output = f"<h2>Expert Fibonacci Scanner Active 📊 (Multi-Timeframe Analysis)</h2>"    
        signals_found = 0
            
        for symbol in symbols_to_scan:    
            html_output += f"<h3>Analysis for {symbol}:</h3><ul>"    
                
            try:    
                # استدعاء الاستراتيجية المحدثة التي تعتمد على فيبو ودمج الفريمات
                result = analyst_engine.evaluate_strategy(symbol=symbol)    
                
                if result and isinstance(result, dict) and "Decision" in result:
                    decision_val = result["Decision"]
                    
                    # إذا كانت النتيجة فرصة حقيقية وليست انتظار
                    if "NO TRADE" not in decision_val:
                        signals_found += 1
                        html_output += f"<li><b>Status:</b> <span style='color:green;'>EXPERT SIGNAL FOUND 🚀</span></li>"
                        html_output += f"<li><pre>{decision_val}</pre></li>"
                        
                        # إرسال رسالة التنبيه فوراً إلى تليجرام بالتنسيق المطلوب
                        send_telegram_message(decision_val)
                    else:
                        html_output += f"<li><b>Status:</b> NO TRADE ⏳ (Waiting for Fibonacci correction or breakout)</li>"
                else:
                    html_output += f"<li><b>Status:</b> Insufficient Data or Error</li>"

                for key, value in result.items():
                    if key != "Decision":
                        html_output += f"<li><b>{key}:</b> {value}</li>"
                        
            except Exception as ex:    
                html_output += f"<li><b>Error:</b> {ex}</li>"    
                    
            html_output += "</ul><hr>"    
                
        if signals_found == 0:
            logger.info("تم فحص العينة الحالية، بانتظار استيفاء شروط مستويات فيبوناتشي واتجاه الفريم الكبير.")
            
        return html_output    
    except Exception as e:    
        error_msg = f"خطأ عام أثناء فحص السوق: {e}"    
        logger.error(error_msg)    
        send_telegram_message(f"⚠️ *Market Scanner Error:* {e}")    
        return f"Bot is running, but encountered an error: {e}"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
