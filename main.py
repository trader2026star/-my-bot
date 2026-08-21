from flask import Flask
app = Flask(__name__)
@app.route('/')
def home(): return "Bot is running!"
if __name__ == "__main__":
    # ده بيخلي البوت يشتغل كويب سيرفس على البورت اللي رندر بيحدده
    app.run(host='0.0.0.0', port=8080)
