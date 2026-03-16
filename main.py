# =====================================================
# Altcoin 1m Explosion Radar - WebSocket Cloud Version
# =====================================================

import os
import csv
import time
from datetime import datetime
import pandas as pd
from binance.client import Client
from binance import ThreadedWebsocketManager
import threading
import requests

# =====================================================
# 配置
# =====================================================
API_KEY = os.getenv("API_KEY", "YOUR_BINANCE_API_KEY")
API_SECRET = os.getenv("API_SECRET", "YOUR_BINANCE_API_SECRET")
SERVER_CHAN_KEY = os.getenv("SERVER_CHAN_KEY", "sctp14659thuntd89pzhhlsmbwynooxu")

VOLUME_THRESHOLD_24H = 15_000_000
SIGNAL_CSV = "signals.csv"
SCAN_INTERVAL = 5  # 秒级扫描间隔（心跳打印）

# =====================================================
# Server酱推送
# =====================================================
def send_server_chan(title, content):
    url = f"https://sctapi.ftqq.com/{SERVER_CHAN_KEY}.send"
    data = {"title": title, "desp": content}
    try:
        requests.post(url, data=data, timeout=5)
    except Exception as e:
        print(f"[推送失败] {e}")

# =====================================================
# 保存CSV
# =====================================================
def save_csv(data):
    file_exists = os.path.isfile(SIGNAL_CSV)
    with open(SIGNAL_CSV,"a",newline='',encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                "time","symbol","score","single_pct","volume_ratio",
                "velocity","momentum","consec_score"
            ])
        writer.writerow(data)

# =====================================================
# 获取符合条件的交易对
# =====================================================
client = Client(API_KEY, API_SECRET)

def get_filtered_symbols():
    tickers = client.futures_ticker()
    symbols = [t["symbol"] for t in tickers if float(t["quoteVolume"]) >= VOLUME_THRESHOLD_24H and t["symbol"].endswith("USDT")]
    return symbols

# =====================================================
# 全局缓存连续爆发数据
# =====================================================
consec_cache = {}  # symbol -> list of last 3 pct涨幅

# =====================================================
# 评分系统
# =====================================================
def score_radar(df, symbol):
    last = df.iloc[-1]
    pct = (last["close"] - last["open"])/last["open"]*100
    ma20_vol = df["volume"].rolling(20).mean().iloc[-1]
    vol_ratio = last["volume"]/(ma20_vol+1e-6)
    
    # 必要条件：单K涨幅>=1%、成交量放量>=1.5倍
    if pct <1.2 or vol_ratio<1.5:
        return None
    
    score = 0
    # 单K涨幅评分
    if pct >=3:
        score +=4
    elif pct>=2:
        score +=3
    elif pct>=1.5:
        score +=2
    else:
        score +=1
    # 成交量评分
    if vol_ratio>=3:
        score +=3
    elif vol_ratio>=2:
        score +=2
    else:
        score +=1
    # 涨幅速度
    velocity = (df["close"].iloc[-1]-df["open"].iloc[-4])/df["open"].iloc[-4]*100
    if velocity>=5:
        score+=2
    elif velocity>=3:
        score+=1
    # 动量
    ema20 = df["close"].ewm(span=20).mean().iloc[-1]
    momentum = last["close"]>ema20
    if momentum:
        score+=1
    # 连续爆发
    pct_list = consec_cache.get(symbol, [])
    pct_list.append(pct)
    if len(pct_list)>3:
        pct_list.pop(0)
    consec_cache[symbol]=pct_list
    consec_score=0
    if len(pct_list)>=2:
        count = sum(1 for p in pct_list if p>=1.5)
        if count>=2:
            consec_score=1
        if count>=3:
            consec_score=2
        if count==3 and pct>=3:
            consec_score=3
    total_score = score+consec_score
    return total_score,pct,vol_ratio,velocity,momentum,consec_score

def signal_level(score):
    if score>=10:
        return "🚀绝佳"
    elif score>=7:
        return "🔥优质"
    else:
        return "⚡普通"

# =====================================================
# WebSocket 回调
# =====================================================
processed = set()
lock = threading.Lock()

def handle_kline(msg):
    try:
        symbol = msg['s']
        k = msg['k']
        is_closed = k['x']  # True if K线已收盘
        if not is_closed:
            return
        df = pd.DataFrame([{
            'open': float(k['o']),
            'high': float(k['h']),
            'low': float(k['l']),
            'close': float(k['c']),
            'volume': float(k['v'])
        }])
        # 需要历史K线补全10根
        hist = client.futures_klines(symbol=symbol, interval='1m', limit=10)
        df_hist = pd.DataFrame(hist, columns=['t','o','h','l','c','v','ct','qav','nt','tb','tq','ig'])
        df_hist[['open','high','low','close','volume']] = df_hist[['o','h','l','c','v']].astype(float)
        df_hist = df_hist[['open','high','low','close','volume']]
        total_score = score_radar(df_hist, symbol)
        if total_score is None:
            return
        score,pct,vol_ratio,velocity,momentum,consec_score = total_score
        level = signal_level(score)
        # 防重复推送
        with lock:
            if symbol in processed:
                return
            processed.add(symbol)
        msg_send = f"""
币对: {symbol}
信号等级: {level} ({score}/13)
单K涨幅: {pct:.2f}%
成交量: {vol_ratio:.2f}x
速度: {velocity:.2f}%
动量: {"强" if momentum else "弱"}
连续爆发评分: {consec_score}
时间: {datetime.now()}
"""
        send_server_chan(f"{symbol} {level}", msg_send)
        save_csv([datetime.now(),symbol,score,pct,vol_ratio,velocity,momentum,consec_score])
    except Exception as e:
        print("处理K线异常:", e)

# =====================================================
# 心跳线程
# =====================================================
def heartbeat():
    while True:
        try:
            symbols = get_filtered_symbols()
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 扫描币对:{len(symbols)}, 符合条件:{len(processed)}, 成功推送:{len(processed)}")
        except Exception as e:
            print("心跳异常:", e)
        time.sleep(SCAN_INTERVAL)

# =====================================================
# 主函数
# =====================================================
def main():
    symbols = get_filtered_symbols()
    twm = ThreadedWebsocketManager(api_key=API_KEY, api_secret=API_SECRET)
    twm.start()
    # 订阅所有符合条件的交易对
    for s in symbols:
        twm.start_kline_socket(callback=handle_kline, symbol=s, interval='1m')
    # 启动心跳
    threading.Thread(target=heartbeat, daemon=True).start()
    # 保持主线程
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        twm.stop()
        print("Radar stopped")

# =====================================================
if __name__ == "__main__":
    main()
