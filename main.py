import time
import math
import requests
from datetime import datetime, timezone, timedelta

# ---------------- [ 기본 설정 ] ----------------
TELEGRAM_TOKEN = "8635915269:AAGixzm7n8jSv67lEwrNB0G6t39QNLffumw"
CHAT_ID = "5451867183"

# 모니터링할 심볼 리스트
SYMBOLS = ["XAUUSDT", "BTCUSDT"]
BASE_URL = "https://fapi.binance.com"

# 한국 표준시(KST, UTC+9) 정의
KST = timezone(timedelta(hours=9))

# 모니터링할 타임프레임 (1m, 3m 삭제 및 5m, 15m, 1h 유지)
INTERVAL_MINUTES = {
    "5m": 5,
    "15m": 15,
    "1h": 60
}

# 파인스크립트 설정값
LOOKBACK = 10      # Recent High/Low Lookback Bars
RR_RATIO = 1.5     # Risk : Reward Ratio (1 : 1.5)
LEN10 = 1          # OBV Length
LEN_OBV = 9        # MA Length
SLOW_LENGTH = 26   # MACD Slow Length
LEN5 = 2           # Slope Length

# 중복 알림 방지용 이전 상태 기록 (종목별, 타임프레임별 분리)
last_scanned_minute = {symbol: {tf: -1 for tf in INTERVAL_MINUTES} for symbol in SYMBOLS}
last_oc_state = {symbol: {tf: None for tf in INTERVAL_MINUTES} for symbol in SYMBOLS}

# ---------------- [ 보조 지표 계산 함수 ] ----------------
def ema(values, length):
    if len(values) < length:
        return []
    alpha = 2 / (length + 1)
    res = [values[0]]
    for val in values[1:]:
        res.append(alpha * val + (1 - alpha) * res[-1])
    return res

def dema(values, length):
    e1 = ema(values, length)
    e2 = ema(e1, length)
    return [2 * a - b for a, b in zip(e1, e2[len(e2)-len(e1):])]

def calc_slope(values, length):
    if len(values) < length:
        return 0.0, 0.0, 0.0
    sub = values[-length:]
    sumX = sum(i + 2.0 for i in range(length))
    sumY = sum(sub)
    sumXSqr = sum((i + 2.0) ** 2 for i in range(length))
    sumXY = sum(sub[i] * (i + 2.0) for i in range(length))

    slope = (length * sumXY - sumX * sumY) / (length * sumXSqr - sumX * sumX)
    average = sumY / length
    intercept = average - slope * sumX / length + slope
    return slope, average, intercept

def get_obv_signal(klines):
    closes = [float(k[4]) for k in klines]
    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]
    volumes = [float(k[5]) for k in klines]

    if len(closes) < 60:
        return 0

    obv = [0.0]
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        sign = 1 if diff > 0 else (-1 if diff < 0 else 0)
        obv.append(obv[-1] + sign * volumes[i])

    v_len = 14
    window_len = 28

    v_sma = []
    for i in range(len(obv)):
        if i < v_len - 1:
            v_sma.append(sum(obv[:i+1]) / (i+1))
        else:
            v_sma.append(sum(obv[i-v_len+1:i+1]) / v_len)

    v_diff = [obv[i] - v_sma[i] for i in range(len(obv))]
    hl_diff = [highs[i] - lows[i] for i in range(len(highs))]

    out_obv = []
    for i in range(len(closes)):
        if i < window_len:
            out_obv.append(closes[i])
            continue

        sub_hl = hl_diff[i-window_len+1:i+1]
        price_spread = math.sqrt(sum((x - sum(sub_hl)/window_len)**2 for x in sub_hl) / window_len)

        sub_v = v_diff[i-window_len+1:i+1]
        v_spread = math.sqrt(sum((x - sum(sub_v)/window_len)**2 for x in sub_v) / window_len)

        shadow = (v_diff[i] / v_spread * price_spread) if v_spread != 0 else 0
        out_obv.append(highs[i] + shadow if shadow > 0 else lows[i] + shadow)

    obvema = ema(out_obv, LEN10)
    ma_obv = dema(obvema, LEN_OBV)
    slow_ma = ema(closes[-len(ma_obv):], SLOW_LENGTH)

    min_len = min(len(ma_obv), len(slow_ma))
    macd = [ma_obv[i] - slow_ma[i] for i in range(-min_len, 0)]

    b5_hist = []
    for i in range(LEN5, len(macd) + 1):
        sub_macd = macd[:i]
        s, a5, i_val = calc_slope(sub_macd, LEN5)
        tt1 = i_val + s * LEN5

        if not b5_hist:
            b5_hist.append(tt1)
        else:
            prev_b5 = b5_hist[-1]
            a15 = abs(tt1 - prev_b5) / len(b5_hist)
            if tt1 > prev_b5 + a15 or tt1 < prev_b5 - a15:
                b5_hist.append(tt1)
            else:
                b5_hist.append(prev_b5)

    oc = 0
    for i in range(1, len(b5_hist)):
        diff = b5_hist[i] - b5_hist[i-1]
        if diff > 0:
            oc = 1
        elif diff < 0:
            oc = -1
    return oc

# ---------------- [ 텔레그램 전송 & 바이낸스 API ] ----------------
def send_telegram_msg(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        requests.post(url, data=payload, timeout=5)
    except Exception as e:
        print(f"텔레그램 발송 에러: {e}")

def fetch_klines(symbol, interval, limit=100):
    endpoint = f"{BASE_URL}/fapi/v1/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        res = requests.get(endpoint, params=params, timeout=5)
        res.raise_for_status()
        return res.json()
    except Exception as e:
        print(f"[{symbol} {interval}] 데이터 로드 실패: {e}")
        return None

# ---------------- [ XAUUSDT 주말 휴장 시간 체크 함수 ] ----------------
def is_xau_market_closed(now_kst):
    wd = now_kst.weekday()
    hour = now_kst.hour
    minute = now_kst.minute

    if wd == 5 and (hour > 5 or (hour == 5 and minute >= 0)):
        return True
    if wd == 6:
        return True
    if wd == 0 and hour < 7:
        return True
        
    return False

# ---------------- [ 메인 스캐너 로직 ] ----------------
def run_candle_close_bot():
    start_msg = f"🚀 <b>비트코인(BTCUSDT) & 금(XAUUSDT)</b> 파인스크립트 신호 스캐너 가동 완료!"
    print(start_msg)
    send_telegram_msg(start_msg)

    while True:
        now_kst = datetime.now(KST)
        current_minute = now_kst.minute
        current_second = now_kst.second

        if 1 <= current_second <= 3:
            xau_paused = is_xau_market_closed(now_kst)

            for symbol in SYMBOLS:
                if symbol == "XAUUSDT" and xau_paused:
                    continue

                for tf, min_unit in INTERVAL_MINUTES.items():
                    if (current_minute % min_unit == 0) and (last_scanned_minute[symbol][tf] != current_minute):

                        last_scanned_minute[symbol][tf] = current_minute

                        data = fetch_klines(symbol, tf, limit=120)
                        if data:
                            closed_klines = data[:-1]
                            current_oc = get_obv_signal(closed_klines)
                            prev_oc = last_oc_state[symbol][tf]

                            if prev_oc is None:
                                last_oc_state[symbol][tf] = current_oc
                            elif current_oc != prev_oc and current_oc != 0:

                                close_price = float(closed_klines[-1][4])
                                recent_klines = closed_klines[-LOOKBACK:]
                                time_str = now_kst.strftime("%m/%d %H:%M")

                                # 종목별 이모지 설정 (골드: 🪙 7개, 비트코인: ₿ 7개)
                                if symbol == "XAUUSDT":
                                    symbol_header = "🪙🪙🪙🪙🪙🪙🪙"
                                else:
                                    symbol_header = "₿₿₿₿₿₿₿"

                                if current_oc == 1:
                                    lowest_low = min(float(k[3]) for k in recent_klines)
                                    sl_price = lowest_low
                                    risk_points = close_price - sl_price
                                    tp_price = close_price + (risk_points * RR_RATIO)

                                    msg = (
                                        f"{symbol_header}\n"
                                        f"🟢🟢🟢 <b>[{symbol} | {tf}] 매수(BUY) 신호</b> 🟢🟢🟢\n\n"
                                        f"⏰ <b>시각:</b> {time_str}\n"
                                        f"📈 <b>진입가:</b> {close_price:,.2f}\n\n"
                                        f"🛡️ <b>손절가 (SL):</b> {sl_price:,.2f}\n"
                                        f"🎯 <b>익절가 (TP):</b> {tp_price:,.2f}"
                                    )
                                    send_telegram_msg(msg)
                                    print(f"[{time_str}] [{symbol} {tf}] BUY Signal Triggered!")

                                elif current_oc == -1:
                                    highest_high = max(float(k[2]) for k in recent_klines)
                                    sl_price = highest_high
                                    risk_points = sl_price - close_price
                                    tp_price = close_price - (risk_points * RR_RATIO)

                                    msg = (
                                        f"{symbol_header}\n"
                                        f"🔴🔴🔴 <b>[{symbol} | {tf}] 매도(SELL) 신호</b> 🔴🔴🔴\n\n"
                                        f"⏰ <b>시각:</b> {time_str}\n"
                                        f"📉 <b>진입가:</b> {close_price:,.2f}\n\n"
                                        f"🛡️ <b>손절가 (SL):</b> {sl_price:,.2f}\n"
                                        f"🎯 <b>익절가 (TP):</b> {tp_price:,.2f}"
                                    )
                                    send_telegram_msg(msg)
                                    print(f"[{time_str}] [{symbol} {tf}] SELL Signal Triggered!")

                                last_oc_state[symbol][tf] = current_oc

        time.sleep(0.5)

if __name__ == "__main__":
    run_candle_close_bot()
