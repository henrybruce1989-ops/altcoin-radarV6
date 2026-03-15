# =====================================================
# Altcoin 1m Explosion Radar - Railway Cloud Version v3
# =====================================================

import time
import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime
from binance.client import Client
import csv

print("🚀 Altcoin Explosion Radar Cloud Version v3 Started")

# =====================================================
# 环境变量读取（Railway部署必须这样写）
# =====================================================

API_KEY = "YOUR_BINANCE_API_KEY"
API_SECRET = "YOUR_BINANCE_API_SECRET"
SERVER_CHAN_KEY = "sctp14659thuntd89pzhhlsmbwynooxu"

# =====================================================
# 参数配置
# =====================================================

TIMEFRAME = "1m"
SCAN_INTERVAL = 15  # 秒
VOLUME_THRESHOLD_24H = 15000000
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
                "velocity","momentum",
                "burst_score","burst_pct"
            ])
        writer.writerow(data)

# =====================================================
# 获取K线
# =====================================================

def get_klines(symbol):
    try:
        klines = client.futures_klines(
            symbol=symbol,
            interval=TIMEFRAME,
            limit=50
        )
        df = pd.DataFrame(klines,columns=[
            'time','open','high','low','close','volume',
            'close_time','qav','num_trades','taker_base',
            'taker_quote','ignore'
        ])
        df[['open','high','low','close','volume']] = df[
            ['open','high','low','close','volume']
        ].astype(float)
        return df
    except:
        return None

# =====================================================
# 连续爆发检测模块
# =====================================================

def burst_continuation(df):
    last3 = df.iloc[-3:]
    ups = 0
    for i in range(3):
        if last3["close"].iloc[i] > last3["open"].iloc[i]:
            ups += 1
    cumulative = (last3["close"].iloc[-1] - last3["open"].iloc[0]) / last3["open"].iloc[0] * 100
    if ups == 3 and cumulative >= 2:
        return 3, cumulative
    elif ups >= 2 and cumulative >= 1.5:
        return 2, cumulative
    else:
        return 0, cumulative

# =====================================================
# 满分10分+连续爆发评分系统
# =====================================================

def score_radar(df):
    last = df.iloc[-1]
    pct = (last["close"]-last["open"])/last["open"]*100
    ma10_vol = df["volume"].rolling(10).mean().iloc[-1]
    vol_ratio = last["volume"]/(ma10_vol+1e-6)

    # 必要条件
    if pct < 1 or vol_ratio < 1.5:
        return None

    score = 0

    # 单K涨幅评分
    if pct >= 3:
        score += 4
    elif pct >= 2:
        score += 3
    elif pct >= 1.5:
        score += 2
    else:
        score += 1

    # 成交量评分
    if vol_ratio >= 3:
        score += 3
    elif vol_ratio >= 2:
        score += 2
    else:
        score += 1

    # 涨幅速度
    velocity = (df["close"].iloc[-1] - df["open"].iloc[-4])/df["open"].iloc[-4]*100
    if velocity >= 5:
        score += 2
    elif velocity >= 3:
        score += 1

    # 动量
    ema20 = df["close"].ewm(span=20).mean().iloc[-1]
    momentum = last["close"] > ema20
    if momentum:
        score += 1

    # 连续爆发评分
    burst_score, burst_pct = burst_continuation(df)
    score += burst_score

    return score, pct, vol_ratio, velocity, momentum, burst_score, burst_pct

# =====================================================
# 信号等级
# =====================================================

def signal_level(score):
    if score >= 10:
        return "🚀绝佳"
    elif score >=7:
        return "🔥优质"
    else:
        return "⚡普通"

# =====================================================
# 主循环
# =====================================================

def run():
    processed = set()
    while True:
        start = time.time()
        matches = 0
        pushed = 0
        try:
            tickers = client.futures_ticker()
            symbols = [
                t["symbol"] for t in tickers
                if float(t["quoteVolume"]) > VOLUME_THRESHOLD_24H
            ]
            total = len(symbols)
            for symbol in symbols:
                df = get_klines(symbol)
                if df is None:
                    continue
                result = score_radar(df)
                if result is None:
                    continue
                matches += 1
                score,pct,vol_ratio,velocity,momentum,burst_score,burst_pct = result
                if symbol in processed:
                    continue
                level = signal_level(score)
                msg = f"""
币对: {symbol}
信号等级: {level} ({score}/13)

1m涨幅: {pct:.2f}%
成交量: {vol_ratio:.2f}x
速度: {velocity:.2f}%
动量: {"强" if momentum else "弱"}

连续爆发评分: {burst_score}
3K累计涨幅: {burst_pct:.2f}%

时间: {datetime.now()}
"""
                send_server_chan(f"{symbol} {level}", msg)
                save_csv([
                    datetime.now(),
                    symbol,
                    score,
                    pct,
                    vol_ratio,
                    velocity,
                    momentum,
                    burst_score,
                    burst_pct
                ])
                processed.add(symbol)
                pushed += 1

            # 实时心跳日志
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] "
                f"扫描币对:{total}, 符合条件:{matches}, 推送成功:{pushed}"
            )

        except Exception as e:
            print("系统异常:", e)

        elapsed = time.time() - start
        sleep = max(0, SCAN_INTERVAL - elapsed)
        time.sleep(sleep)

# =====================================================

if __name__ == "__main__":
    run()
