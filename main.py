        # تم ضبط العدد على 20 عملة لضمان عدم استهلاك الـ RAM بالكامل على السيرفر المجاني
        symbols_to_scan = sorted_symbols[:20]
          
        telegram_msg = f"🚨 *Smart Money Volume-Scan Report (BingX - Top 20)* 🚀\n\n"  
        html_output = f"<h2>Smart Money Scanner Active 🚀 (Optimized Batch)</h2>"  
          
        import time
        for symbol in symbols_to_scan:  
            html_output += f"<h3>Analysis for {symbol}:</h3><ul>"  
            telegram_msg += f"📊 *Symbol: {symbol}*\n"  
              
            try:  
                result = analyst_engine.evaluate_strategy(symbol=symbol, account_balance=1000.0, risk_percentage=0.01)  
                for key, value in result.items():  
                    html_output += f"<li><b>{key}:</b> {value}</li>"  
                    telegram_msg += f"• *{key}* {value}\n"  
            except Exception as ex:  
                html_output += f"<li><b>Error:</b> {ex}</li>"  
                telegram_msg += f"• Error analyzing this coin.\n"  
                  
            html_output += "</ul><hr>"  
            telegram_msg += "-------------------\n"  
            
            # مهلة صغيرة جداً (ثانية واحدة) بين كل عملة والتانية لتفريغ الـ RAM ومنع الـ SIGKILL
            time.sleep(1)
