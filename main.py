import os
import time
import threading
import requests
import pandas as pd
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
        print("텔레그램 토큰/Chat ID 미설정")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"텔레그램 전송 실패: {e}")

def calculate_signals(df):
    # 1. EMA 9 & 26 (pandas 기본 ewm 사용)
    df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['slow_ma'] = df['close'].ewm(span=26, adjust=False).mean()

    # 2. Price Spread & OBV Shadow
    df['price_spread'] = (df['high'] - df['low']).rolling(window=28).std()
    
    df['change'] = df['close'].diff()
    df['direction'] = df['change'].apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    df['obv'] = (df['direction'] * df['volume']).cumsum()
    
    df['v_smooth'] = df['obv'].rolling(window=14).mean()
    df['v_spread'] = (df['obv'] - df['v_smooth']).rolling(window=28).std()
    
    df['shadow'] = (df['obv'] - df['v_smooth']) / df['v_spread'] * df['price_spread']
    df['out_obv'] = df.apply(lambda row: row['high'] + row['shadow'] if row['shadow'] > 0 else row['low'] + row['shadow'], axis=1)
    
    # OBV EMA & DEMA
    df['obvema'] = df['out_obv'].ewm(span=1, adjust=False).mean()
    
    # DEMA = 2 * EMA(x) - EMA(EMA(x))
    ema1 = df['obvema'].ewm(span=9, adjust=False).mean()
    ema2 = ema1.ewm(span=9, adjust=False).mean()
    df['ma_obv'] = 2 * ema1 - ema2
    
    # MACD
    df['macd'] = df['ma_obv'] - df['slow_ma']

    # 최근 N봉 저점 / 고점 계산
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
    send_telegram("<b>[시스템]</b> 클라우드 봇이 정상 시작되었습니다.")

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
    t = threading.Thread(target=bot_loop)
    t.daemon = True
    t.start()
    
    run_flask()
