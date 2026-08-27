import os
import time
import threading
import requests
import pandas as pd
import pandas_ta as ta
import ccxt
from flask import Flask

# Flask 웹 서버 설정 (Render Free 플랜 유지용)
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# 텔레그램 환경 변수
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

SYMBOL = "BTC/USDT"
TIMEFRAME = "15m"
RR_RATIO = 1.5
LOOKBACK = 10

def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"텔레그램 전송 실패: {e}")

def calculate_signals(df):
    df['ema9'] = ta.ema(df['close'], length=9)
    df['price_spread'] = ta.stdev(df['high'] - df['low'], length=28)
    
    df['change'] = df['close'].diff()
    df['direction'] = df['change'].apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    df['obv'] = (df['direction'] * df['volume']).cumsum()
    
    df['v_smooth'] = ta.sma(df['obv'], length=14)
    df['v_spread'] = ta.stdev(df['obv'] - df['v_smooth'], length=28)
    
    df['shadow'] = (df['obv'] - df['v_smooth']) / df['v_spread'] * df['price_spread']
    df['out_obv'] = df.apply(lambda row: row['high'] + row['shadow'] if row['shadow'] > 0 else row['low'] + row['shadow'], axis=1)
    
    df['obvema'] = ta.ema(df['out_obv'], length=1)
    df['ma_obv'] = ta.dema(df['obvema'], length=9)
    
    df['slow_ma'] = ta.ema(df['close'], length=26)
    df['macd'] = df['ma_obv'] - df['slow_ma']

    df['lowest_low'] = df['low'].rolling(window=LOOKBACK).min()
    df['highest_high'] = df['high'].rolling(window=LOOKBACK).max()

    df['macd_diff'] = df['macd'].diff()
    df['signal'] = 0
    df.loc[df['macd_diff'] > 0, 'signal'] = 1
    df.loc[df['macd_diff'] < 0, 'signal'] = -1

    return df

def bot_loop():
    exchange = ccxt.binance()
    last_signal = 0
    send_telegram("<b>[시스템]</b> 무료 클라우드 봇이 정상 시작되었습니다.")

    while True:
        try:
            ohlcv = exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=100)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            df = calculate_signals(df)
            last_bar = df.iloc[-2]
            current_signal = last_bar['signal']
            
            if current_signal != last_signal and current_signal != 0:
                close_p = last_bar['close']
                
                if current_signal == 1:
                    sl_p = last_bar['lowest_low']
                    risk = close_p - sl_p
                    tp_p = close_p + (risk * RR_RATIO)
                    msg = f"<b>[BUY 신호 발생]</b>\n종목: {SYMBOL} ({TIMEFRAME})\n진입가: {close_p:.2f}\nSL: {sl_p:.2f}\nTP: {tp_p:.2f}"
                    send_telegram(msg)

                elif current_signal == -1:
                    sl_p = last_bar['highest_high']
                    risk = sl_p - close_p
                    tp_p = close_p - (risk * RR_RATIO)
                    msg = f"<b>[SELL 신호 발생]</b>\n종목: {SYMBOL} ({TIMEFRAME})\n진입가: {close_p:.2f}\nSL: {sl_p:.2f}\nTP: {tp_p:.2f}"
                    send_telegram(msg)
                    
                last_signal = current_signal

        except Exception as e:
            print(f"에러 발생: {e}")

        time.sleep(60)

if __name__ == '__main__':
    # 모니터링 봇은 스레드로 백그라운드 실행
    t = threading.Thread(target=bot_loop)
    t.daemon = True
    t.start()
    
    # Flask 웹 서버 실행
    run_flask()
