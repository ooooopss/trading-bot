import time
import requests
from datetime import datetime

SYMBOL = "XAUUSDT"
BASE_URL = "https://fapi.binance.com"

# 각 타임프레임별 '분(minute)' 단위 기준
# 1분봉(매분), 3분봉(3분마다), 5분봉(5분마다), 15분봉(15분마다), 1시간봉(60분마다)
INTERVAL_MINUTES = {
    "1m": 1,
    "3m": 3,
    "5m": 5,
    "15m": 15,
    "1h": 60
}

# 마지막으로 스캔을 완료한 '분(minute)'을 기록하여 중복 실행 방지
last_scanned_minute = {tf: -1 for tf in INTERVAL_MINUTES}

def fetch_klines(symbol, interval):
    endpoint = f"{BASE_URL}/fapi/v1/klines"
    params = {"symbol": symbol, "interval": interval, "limit": 5}
    try:
        res = requests.get(endpoint, params=params, timeout=5)
        res.raise_for_status()
        return res.json()
    except Exception as e:
        print(f"[{symbol} {interval}] 스캔 에러: {e}")
        return None

def run_candle_close_bot():
    print(f"🚀 {SYMBOL} 캔들 마감 기반 정석 스캐너 시작...")
    
    while True:
        now = datetime.now()
        current_minute = now.minute
        current_second = now.second
        
        # 💡 핵심: 매 분 1초~3초 사이에 캔들 마감 스캔 검사 (서버 데이터 확정 대기 1초)
        if 1 <= current_second <= 3:
            
            for tf, min_unit in INTERVAL_MINUTES.items():
                # 1. 해당 타임프레임의 주기가 되었는지 확인 (예: 5분봉은 minute % 5 == 0)
                # 2. 이번 분에 이미 스캔을 수행했는지 체크하여 중복 실행 방지
                if (current_minute % min_unit == 0) and (last_scanned_minute[tf] != current_minute):
                    
                    data = fetch_klines(SYMBOL, tf)
                    if data:
                        # data[-2]가 방금 막 '완성(마감)된 캔들' 데이터입니다.
                        closed_candle = data[-2]
                        close_price = float(closed_candle[4])
                        print(f"[{now.strftime('%H:%M:%S')}] [{SYMBOL} {tf}] 봉 완성 스캔 완료 - 마감가: {close_price}")
                    
                    # 스캔 완료 기록
                    last_scanned_minute[tf] = current_minute
                    
                    # 요청간 0.5초 안전 지연
                    time.sleep(0.5)
        
        # 0.5초마다 시간 체킹
        time.sleep(0.5)

if __name__ == "__main__":
    run_candle_close_bot()
