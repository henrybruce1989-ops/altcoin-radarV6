# =====================================================
# Altcoin 1m Explosion Radar - WebSocket Full Version
# 包含连续爆发检测、单K涨幅、成交量、速度、动量评分
# 支持Server酱推送 + CSV保存 + 控制台心跳
# =====================================================

import os
import csv
import json
import time
import requests
import pandas as pd
from datetime import datetime
from binance.client import Client
from binance.streams import ThreadedWebsocketManager

# =====================================================
# 用户配置
# =====================================================

API_KEY = "YOUR_BINANCE_API_KEY"
API_SECRET = "YOUR_BINANCE_API_SECRET"
SERVER_CHAN_KEY = "sctp14659thuntd89pzhhlsmbwynooxu"

VOLUME_THRESHOLD_24H = 15_000_000  # 24小时成交额 USDT
SIGNAL_CSV = "signals.csv"
HEARTBEAT_INTERVAL = 60  # 控制台心跳输出间隔（秒）
EMA_PERIOD = 20  # 动量判断EMA

# =====================================================
# 初始化客户端
# =====================================================
client = Client(API_KEY, API_SECRET)
twm = ThreadedWebsocketManager(API_KEY, API_SECRET)
twm.start()

# =====================================================
# CSV保存
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
# Server酱推送
# =====================================================
def send_server_chan(title, content):
    url = f"https://sctapi.ftqq.com/{SERVER_CHAN_KEY}.send"
    try:
        requests.post(url, data={"title":title,"desp":content}, timeout=5)
    except Exception as e:
        print(f"[推送失败] {e}")

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
# 满分10分评分系统
# =====================================================
def score_radar(df):
    if len(df) < 10:
        return None
    last = df.iloc[-1]
    pct = (last["close"]-last["open"])/last["open"]*100
    ma10_vol = df["volume"].rolling(10).mean().iloc[-1]
    vol_ratio = last["volume"]/(ma10_vol+1e-6)

    # 必要条件：单K涨幅>=1% 且放量>=1.5倍
    if pct < 1 or vol_ratio < 1.5:
        return None

    score = 0

    # 1. 单K涨幅评分
    if pct >= 3: score += 4
    elif pct >=2: score += 3
    elif pct >=1.5: score +=2
    else: score +=1

    # 2. 成交量放量评分
    if vol_ratio >=3: score +=3
    elif vol_ratio >=2: score +=2
    else: score +=1

    # 3. 涨幅速度评分
    if len(df) >=4:
        velocity = (df["close"].iloc[-1] - df["open"].iloc[-4]) / df["open"].iloc[-4] *100
        if velocity >=5: score +=2
        elif velocity >=3: score +=1
    else:
        velocity = 0

    # 4. 动量评分
    ema20 = df["close"].ewm(span=EMA_PERIOD).mean().iloc[-1]
    momentum = last["close"] > ema20
    if momentum:
        score +=1

    # 5. 连续爆发评分
    consecutive = 0
    count = 0
    for k in df.iloc[-3:]:
        k_pct = (k["close"]-k["open"])/k["open"]*100
        if k_pct >= 1.5:
            count +=1
    if count >=2: consecutive = 1
    if count >=3: consecutive = 3
    score += consecutive

    return score,pct,vol_ratio,velocity,momentum,consecutive

# =====================================================
# 获取24小时交易额大于阈值的USDT合约
# =====================================================
def get_usdt_symbols():
    tickers = client.futures_ticker()
    symbols = [t['symbol'] for t in tickers if t['symbol'].endswith("USDT") and float(t['quoteVolume'])>VOLUME_THRESHOLD_24H]
    return symbols

# =====================================================
# 主循环
# =====================================================
def run():
    processed = set()
    last_heartbeat = 0

    symbols = get_usdt_symbols()
    print(f"[{datetime.now()}] 总共扫描币对: {len(symbols)}")

    # 订阅所有1m K线
    for symbol in symbols:
        twm.start_kline_socket(callback=lambda msg,s=symbol: kline_callback(msg,s), symbol=s, interval='1m')

    twm.join()  # 保持线程运行

# =====================================================
# 回调函数
# =====================================================
def kline_callback(msg,symbol):
    global processed, last_heartbeat
    try:
        k = msg['k']
        if not k['x']:  # K线未收盘，忽略
            return

        # 构建DataFrame
        df = pd.DataFrame([[
            pd.to_datetime(k['t'], unit='ms'),
            float(k['o']),float(k['h']),float(k['l']),float(k['c']),float(k['v'])
        ]],columns=['time','open','high','low','close','volume'])

        # 获取之前缓存
        if not hasattr(kline_callback, "cache"):
            kline_callback.cache = {}
        if symbol not in kline_callback.cache:
            kline_callback.cache[symbol] = df
        else:
            kline_callback.cache[symbol] = pd.concat([kline_callback.cache[symbol], df]).tail(20)

        df_full = kline_callback.cache[symbol]

        # 评分
        result = score_radar(df_full)
        if result is None:
            return
        score,pct,vol_ratio,velocity,momentum,consecutive = result

        level = signal_level(score)

        # 构建消息
        msg_text = f"""
币对: {symbol}
信号等级: {level} ({score}/10)
1m涨幅: {pct:.2f}%
成交量: {vol_ratio:.2f}x
速度: {velocity:.2f}%
动量: {"强" if momentum else "弱"}
连续爆发评分: {consecutive}
时间: {datetime.now()}
"""
        # 避免重复推送
        if (symbol,score) not in processed:
            send_server_chan(f"{symbol} {level}", msg_text)
            save_csv([datetime.now(),symbol,score,pct,vol_ratio,velocity,momentum,consecutive])
            processed.add((symbol,score))

        # 心跳打印
        if time.time() - last_heartbeat > HEARTBEAT_INTERVAL:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 扫描币对:{len(kline_callback.cache)}, 推送信号:{len(processed)}")
            last_heartbeat = time.time()

    except Exception as e:
        print(f"[{datetime.now()}] 回调异常:{e}")

# =====================================================
# 启动
# =====================================================
if __name__ == "__main__":
    run()
