# =====================================================
# Altcoin 1m Explosion Radar - BinanceSocketManager WebSocket Cloud Version
# =====================================================

import time
import os
import requests
import pandas as pd
from datetime import datetime
from binance.client import Client
from binance.streams import BinanceSocketManager
import threading
import numpy as np
import csv

print("🚀 Altcoin Explosion Radar WebSocket Cloud Version Started")

# =====================================================
# 环境变量读取（Railway部署必须这样写）
# =====================================================
API_KEY = os.environ.get("API_KEY", "YOUR_BINANCE_API_KEY")
API_SECRET = os.environ.get("API_SECRET", "YOUR_BINANCE_API_SECRET")
SERVER_CHAN_KEY = os.environ.get("SERVER_CHAN_KEY", "sctp14659thuntd89pzhhlsmbwynooxu")

# =====================================================
# 参数配置
# =====================================================
TIMEFRAME = "1m"
VOLUME_THRESHOLD_24H = 15_000_000  # 24h交易额阈值
SIGNAL_CSV = "signals.csv"

# =====================================================
# 初始化客户端
# =====================================================
client = Client(API_KEY, API_SECRET)
bsm = BinanceSocketManager(client)

# =====================================================
# Server酱推送函数
# =====================================================
def send_server_chan(title, content):
    url = f"https://sctapi.ftqq.com/{SERVER_CHAN_KEY}.send"
    data = {"title": title, "desp": content}
    try:
        requests.post(url, data=data, timeout=5)
    except Exception as e:
        print(f"[推送失败] {e}")

# =====================================================
# CSV保存
# =====================================================
def save_csv(data):
    file_exists = os.path.isfile(SIGNAL_CSV)
    with open(SIGNAL_CSV, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                "time","symbol","score","single_pct","single_vol_ratio",
                "velocity","momentum","consecutive_score"
            ])
        writer.writerow(data)

# =====================================================
# 满分10分评分系统
# =====================================================
def calculate_score(df):
    last = df.iloc[-1]
    # 单K涨幅
    pct = (last["close"] - last["open"]) / last["open"] * 100
    ma10_vol = df["volume"].rolling(10).mean().iloc[-1]
    vol_ratio = last["volume"] / (ma10_vol + 1e-6)

    # 连续爆发检测
    consecutive_score = 0
    count = 0
    for i in range(-3, 0):
        k = df.iloc[i]
        k_pct = (k['close'] - k['open']) / k['open'] * 100
        if k_pct > 1:
            count += 1
    if count >= 2:
        consecutive_score = 1
    if count >= 3:
        consecutive_score = 2
    if count >= 4:
        consecutive_score = 3

    # 必要条件：单K涨幅>=1% 且成交量放大>=1.5
    if pct < 1 or vol_ratio < 1.5:
        return None

    score = 0
    # 单K涨幅评分 1-4分
    if pct >= 3:
        score += 4
    elif pct >= 2:
        score += 3
    elif pct >= 1.5:
        score += 2
    else:
        score += 1

    # 成交量评分 1-3分
    if vol_ratio >= 3:
        score += 3
    elif vol_ratio >= 2:
        score += 2
    else:
        score += 1

    # 涨幅速度评分 0-2分
    velocity = (last['close'] - df['open'].iloc[-4]) / df['open'].iloc[-4] * 100
    if velocity >= 5:
        score += 2
    elif velocity >= 3:
        score += 1

    # 动量 0-1分
    ema20 = df['close'].ewm(span=20).mean().iloc[-1]
    momentum = last['close'] > ema20
    if momentum:
        score += 1

    # 累加连续爆发 0-3分
    score += consecutive_score

    return score, pct, vol_ratio, velocity, momentum, consecutive_score

# =====================================================
# 信号等级
# =====================================================
def signal_level(score):
    if score >= 8:
        return "🚀绝佳"
    elif score >=5:
        return "🔥优质"
    else:
        return "⚡普通"

# =====================================================
# 获取所有USDT交易对
# =====================================================
def get_usdt_symbols():
    tickers = client.futures_ticker()
    symbols = [
        t['symbol'] for t in tickers
        if t['symbol'].endswith("USDT") and float(t['quoteVolume']) > VOLUME_THRESHOLD_24H
    ]
    return symbols

# =====================================================
# WebSocket Kline回调
# =====================================================
processed_symbols = set()
total_scanned = 0
matches_found = 0
pushed_count = 0

def kline_message(msg):
    global processed_symbols, total_scanned, matches_found, pushed_count
    if msg['e'] != 'kline':
        return
    symbol = msg['s']
    k = msg['k']
    if not k['x']:  # 只处理收盘的K线
        return

    # 构建DataFrame
    df = pd.DataFrame([[
        k['t'], k['o'], k['h'], k['l'], k['c'], k['v'],
        k['T'], 0, k['n'], 0,0,0
    ]], columns=['time','open','high','low','close','volume','close_time',
                 'qav','num_trades','taker_base','taker_quote','ignore'])
    df[['open','high','low','close','volume']] = df[['open','high','low','close','volume']].astype(float)

    # 评分
    result = calculate_score(df)
    total_scanned += 1
    if result is None:
        return
    matches_found += 1
    score, pct, vol_ratio, velocity, momentum, consecutive_score = result

    if symbol in processed_symbols:
        return

    level = signal_level(score)
    msg_text = f"""
币对: {symbol}
信号等级: {level} ({score}/10)
1m涨幅: {pct:.2f}%
成交量: {vol_ratio:.2f}x
速度: {velocity:.2f}%
动量: {"强" if momentum else "弱"}
连续爆发评分: {consecutive_score}/3
时间: {datetime.now()}
"""

    send_server_chan(f"{symbol} {level}", msg_text)
    save_csv([datetime.now(), symbol, score, pct, vol_ratio, velocity, momentum, consecutive_score])
    processed_symbols.add(symbol)
    pushed_count += 1

# =====================================================
# 启动 WebSocket
# =====================================================
def run_websocket():
    symbols = get_usdt_symbols()
    print(f"[{datetime.now()}] 获取USDT交易对数量: {len(symbols)}")
    # 批量订阅
    for symbol in symbols:
        bsm.start_kline_socket(symbol=symbol, interval='1m', callback=kline_message)
    bsm.start()

# =====================================================
# 心跳打印线程
# =====================================================
def heartbeat():
    global total_scanned, matches_found, pushed_count
    while True:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 扫描币对总数: {total_scanned}, 符合条件: {matches_found}, 成功推送: {pushed_count}")
        time.sleep(15)

# =====================================================
# 启动
# =====================================================
if __name__ == "__main__":
    threading.Thread(target=heartbeat, daemon=True).start()
    run_websocket()
