import os
import time
import threading
import requests
import pandas as pd
import ccxt
from flask import Flask

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

# 트레이딩뷰 OANDA XAUUSD에 가장 가까운 바이낸스 선물 대표 심볼
SYMBOLS = ["XAUUSDT"]
TIMEFRAMES = ["1m", "5m", "15m", "1h"]
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
    df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['slow_ma'] = df['close'].ewm(span=26, adjust=False).mean()

    df['price_spread'] = (df['high'] - df['low']).rolling(window=28).std()
    
    df['change'] = df['close'].diff()
    df['direction'] = df['change'].apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    df['obv'] = (df['direction'] * df['volume']).cumsum()
    
    df['v_smooth'] = df['obv'].rolling(window=14).mean()
    df['v_spread'] = (df['obv'] - df['v_smooth']).rolling(window=28).std()
    
    df['shadow'] = (df['obv'] - df['v_smooth']) / df['v_spread'] * df['price_spread']
    df['out_obv'] = df.apply(lambda row: row['high'] + row['shadow'] if row['shadow'] > 0 else row['low'] + row['shadow'], axis=1)
    
    df['obvema'] = df['out_obv'].ewm(span=1, adjust=False).mean()
    
    ema1 = df['obvema'].ewm(span=9, adjust=False).mean()
    ema2 = ema1.ewm(span=9, adjust=False).mean()
    df['ma_obv'] = 2 * ema1 - ema2
    
    df['macd'] = df['ma_obv'] - df['slow_ma']

    df['lowest_low'] = df['low'].rolling(window=LOOKBACK).min()
    df['highest_high'] = df['high'].rolling(window=LOOKBACK).max()

    df['macd_diff'] = df['macd'].diff()
    df['signal'] = 0
    df.loc[df['macd_diff'] > 0, 'signal'] = 1
    df.loc[df['macd_diff'] < 0, 'signal'] = -1

    return df

def bot_loop():
    exchange = ccxt.binance({
        'options': {
            'defaultType': 'future',
        }
    })
    
    try:
        exchange.load_markets()
    except Exception as e:
        print(f"마켓 로딩 실패: {e}")

    last_signals = {(symbol, tf): 0 for symbol in SYMBOLS for tf in TIMEFRAMES}
    last_processed_timestamps = {(symbol, tf): 0 for symbol in SYMBOLS for tf in TIMEFRAMES}
    
    symbols_str = ", ".join(SYMBOLS)
    tf_str = ", ".join(TIMEFRAMES)
    send_telegram(f"<b>[시스템]</b> OANDA 추종 바이낸스 선물 봇 시작\n<b>종목:</b> {symbols_str}\n<b>프레임:</b> {tf_str}")

    while True:
        for symbol in SYMBOLS:
            for tf in TIMEFRAMES:
                try:
                    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=tf, limit=100)
                    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    
                    completed_bar = df.iloc[-2]
                    completed_bar_time = completed_bar['timestamp']
                    
                    if completed_bar_time > last_processed_timestamps[(symbol, tf)]:
                        df = calculate_signals(df)
                        completed_bar_with_sig = df.iloc[-2]
                        current_signal = completed_bar_with_sig['signal']
                        
                        if current_signal != last_signals[(symbol, tf)] and current_signal != 0:
                            close_p = completed_bar_with_sig['close']
                            
                            if current_signal == 1:
                                sl_p = completed_bar_with_sig['lowest_low']
                                risk = close_p - sl_p
                                tp_p = close_p + (risk * RR_RATIO)
                                msg = f"<b>[BUY 신호 발생 - 봉 마감]</b>\n<b>종목: {symbol}</b>\n<b>프레임: {tf}</b>\n진입가: {close_p:.2f}\nSL: {sl_p:.2f}\nTP: {tp_p:.2f}"
                                send_telegram(msg)

                            elif current_signal == -1:
                                sl_p = completed_bar_with_sig['highest_high']
                                risk = sl_p - close_p
                                tp_p = sl_p - (risk * RR_RATIO)
                                msg = f"<b>[SELL 신호 발생 - 봉 마감]</b>\n<b>종목: {symbol}</b>\n<b>프레임: {tf}</b>\n진입가: {close_p:.2f}\nSL: {sl_p:.2f}\nTP: {tp_p:.2f}"
                                send_telegram(msg)
                                
                            last_signals[(symbol, tf)] = current_signal
                        
                        last_processed_timestamps[(symbol, tf)] = completed_bar_time

                except Exception as e:
                    print(f"[{symbol} {tf}] 스캔 예외 발생: {e}")

        time.sleep(3)

if __name__ == '__main__':
    t = threading.Thread(target=bot_loop)
    t.daemon = True
    t.start()
    
    run_flask()
