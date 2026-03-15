# =====================================================
# Altcoin 1m Explosion Radar - WebSocket Full Version
# =====================================================
# 满分10分职业级评分：
# 单K涨幅 1-4分
# 成交量 1-3分
# 涨幅速度 0-2分
# 动量 0-1分
# 连续爆发 0-3分
# =====================================================

import time
import os
import csv
import requests
import pandas as pd
from datetime import datetime
from binance.client import Client
from binance.websockets import ThreadedWebsocketManager

print("🚀 Altcoin Explosion Radar WebSocket Version Started")

# =====================================================
# 环境变量读取（Railway部署必须这样写）
# =====================================================
API_KEY = os.getenv("BINANCE_API_KEY", "YOUR_BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET", "YOUR_BINANCE_API_SECRET")
SERVER_CHAN_KEY = os.getenv("SERVER_CHAN_KEY", "sctp14659thuntd89pzhhlsmbwynooxu")

VOLUME_THRESHOLD_24H = 15_000_000
SIGNAL_CSV = "signals.csv"

client = Client(API_KEY, API_SECRET)

# =====================================================
# Server酱推送
# =====================================================
def send_server_chan(title, content):
    url = f"https://sctapi.ftqq.com/{SERVER_CHAN_KEY}.send"
    data = {"title": title, "desp": content}
    try:
        requests.post(url, data=data, timeout=5)
    except Exception as e:
        print("推送失败:", e)

# =====================================================
# 保存CSV
# =====================================================
def save_csv(data):
    file_exists = os.path.isfile(SIGNAL_CSV)
    with open(SIGNAL_CSV,"a",newline='',encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                "time","symbol","score",
                "pct","volume_ratio",
                "velocity","momentum","consecutive"
            ])
        writer.writerow(data)

# =====================================================
# 满分10分评分函数
# =====================================================
def score_radar(df, history_scores):
    last = df.iloc[-1]
    pct = (last["close"] - last["open"]) / last["open"] * 100
    ma10_vol = df["volume"].rolling(10).mean().iloc[-1]
    vol_ratio = last["volume"] / (ma10_vol + 1e-6)
    
    # 必要条件：单K涨幅 ≥1% 且放量 ≥1.5x
    if pct < 1 or vol_ratio < 1.5:
        return None
    
    score = 0

    # 1. 单K涨幅评分
    if pct >= 3: score += 4
    elif pct >= 2: score += 3
    elif pct >= 1.5: score += 2
    else: score += 1

    # 2. 成交量评分
    if vol_ratio >= 3: score += 3
    elif vol_ratio >= 2: score += 2
    else: score += 1

    # 3. 涨幅速度评分
    if len(df) >= 4:
        velocity = (df["close"].iloc[-1] - df["open"].iloc[-4]) / df["open"].iloc[-4] * 100
        if velocity >= 5: score += 2
        elif velocity >= 3: score += 1
    else:
        velocity = 0

    # 4. 动量评分
    ema20 = df["close"].ewm(span=20).mean().iloc[-1]
    momentum = last["close"] > ema20
    if momentum: score +=1

    # 5. 连续爆发评分
    consecutive = 0
    if len(history_scores) >= 3:
        recent = history_scores[-3:]
        consecutive = sum([1 for s in recent if s >= 1])
        if consecutive >= 2: score +=1
        if consecutive >= 3: score +=2
    return score, pct, vol_ratio, velocity, momentum, consecutive

# =====================================================
# 信号等级
# =====================================================
def signal_level(score):
    if score >= 8: return "🚀绝佳"
    elif score >=5: return "🔥优质"
    else: return "⚡普通"

# =====================================================
# 获取24h交易额≥阈值的USDT合约
# =====================================================
def get_usdt_symbols():
    tickers = client.futures_ticker()
    symbols = [t["symbol"] for t in tickers if "USDT" in t["symbol"] and float(t["quoteVolume"])>=VOLUME_THRESHOLD_24H]
    return symbols

# =====================================================
# K线缓存
# =====================================================
klines_cache = {}       # symbol -> pd.DataFrame
score_history = {}      # symbol -> list

# =====================================================
# WebSocket回调
# =====================================================
def kline_message(msg):
    if msg['e'] != 'kline': return
    symbol = msg['s']
    k = msg['k']
    is_closed = k['x']
    if not is_closed: return
    
    df = klines_cache.get(symbol)
    new_row = pd.DataFrame([{
        "open": float(k["o"]),
        "high": float(k["h"]),
        "low": float(k["l"]),
        "close": float(k["c"]),
        "volume": float(k["v"])
    }])
    if df is None:
        df = new_row
    else:
        df = pd.concat([df, new_row], ignore_index=True).tail(50)
    klines_cache[symbol] = df

    hist = score_history.get(symbol, [])
    result = score_radar(df, hist)
    if result is None: 
        score_history[symbol] = hist[-10:]  # 保留历史
        return

    score, pct, vol_ratio, velocity, momentum, consecutive = result
    hist.append(1)  # 标记此次有爆发
    score_history[symbol] = hist[-10:]

    level = signal_level(score)
    msg_text = f"""
币对: {symbol}
信号等级: {level} ({score}/10)
1m涨幅: {pct:.2f}%
成交量: {vol_ratio:.2f}x
速度: {velocity:.2f}%
动量: {"强" if momentum else "弱"}
连续爆发: {consecutive}
时间: {datetime.now()}
"""
    send_server_chan(f"{symbol} {level}", msg_text)
    save_csv([
        datetime.now(), symbol, score, pct, vol_ratio, velocity, momentum, consecutive
    ])
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {symbol} | 信号等级:{level} | 分数:{score}")

# =====================================================
# 启动WebSocket
# =====================================================
def main():
    symbols = get_usdt_symbols()
    print(f"扫描USDT合约币对数: {len(symbols)}")

    twm = ThreadedWebsocketManager(api_key=API_KEY, api_secret=API_SECRET)
    twm.start()

    for s in symbols:
        twm.start_kline_socket(callback=kline_message, symbol=s, interval='1m')

    # 心跳显示
    try:
        while True:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 活动币对:{len(symbols)} 监控中...")
            time.sleep(30)
    except KeyboardInterrupt:
        twm.stop()
        print("🛑 Radar Stopped")

if __name__=="__main__":
    main()
