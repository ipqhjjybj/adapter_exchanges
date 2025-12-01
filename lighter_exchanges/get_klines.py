import requests
import time
import pandas as pd
from datetime import datetime

base_url = "https://mainnet.zklighter.elliot.ai"
# market_id = 48
# resolution = "1m"
# #start_timestamp = 1763508840
# start_timestamp = 1763508840
# end_timestamp = 1763609427
# count_back = 3
# url = f"{base_url}/api/v1/candlesticks?market_id={market_id}&resolution={resolution}&start_timestamp={start_timestamp}&end_timestamp={end_timestamp}&count_back={count_back}"

# response = requests.get(url)
# data = response.json()

# candlesticks = data["candlesticks"]
# df = pd.DataFrame(candlesticks)
# df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
# df = df.rename(columns={
#     "volume0": "volume",
#     "volume1": "quote_volume"
# })
# df = df[["timestamp", "open", "high", "low", "close", "volume", "quote_volume"]]

def get_kline(params):
    market_id = params['market_id']
    resolution = params['resolution']
    start_timestamp = params['start_timestamp']
    end_timestamp = params['end_timestamp']
    count_back = params['count_back']
    base_url = "https://mainnet.zklighter.elliot.ai"
    url = f"{base_url}/api/v1/candlesticks?market_id={market_id}&resolution={resolution}&start_timestamp={start_timestamp}&end_timestamp={end_timestamp}&count_back={count_back}"
    response = requests.get(url)
    data = response.json()
    return data


def get_candle_df_kline(market_id, run_time, limit=1000, interval='1m'):
    _limit = limit
    if limit >= 500:  # 如果参数大于500
        _limit = 499
    
    start_time_dt = run_time - pd.to_timedelta(interval) * limit
    
    df_list = []  # 定义获取的k线数据
    data_len = 0  # 记录数据长度

    params = {
        'market_id': market_id,
        'resolution': interval,  # 获取k线周期
        'limit': _limit,  # 获取多少根
        'start_timestamp': int(time.mktime(start_time_dt.timetuple())),  # 获取币种开始时间
        'end_timestamp': int(time.mktime(run_time.timetuple())) ,  # 获取币种结束时间
        #'startTime': int(time.mktime(start_time_dt.timetuple())) * 1000  # 获取币种开始时间
        'count_back': 0
    }
    while True:
        try:
            kline = get_kline(params)

        except Exception as e:
            print(e)
            print(traceback.format_exc())
            # 如果获取k线重试出错，直接返回，当前币种不参与交易
            return pd.DataFrame()
        
        # ===整理数据
        # 将数据转换为DataFrame
        df = pd.DataFrame(kline['candlesticks'], dtype='float')
        if df.empty:
            break
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df = df.rename(columns={
            "timestamp": "candle_begin_time",
            "volume0": "volume",
            "volume1": "quote_volume"
        })
        df = df[["candle_begin_time", "open", "high", "low", "close", "volume", "quote_volume"]]
        df.sort_values(by=['candle_begin_time'], inplace=True)  # 排序
        # 数据追加
        df_list.append(df)
        data_len = data_len + df.shape[0] - 1

        # 判断请求的数据是否足够
        if data_len >= limit:
            break

        startTime = df.iloc[0]['candle_begin_time'] - pd.to_timedelta(interval) * _limit
        params['start_timestamp'] = int(startTime.timestamp()) * 1000 - 1
        # 更新一下k线数据
        params['end_timestamp'] = int(df.iloc[0]['candle_begin_time'].timestamp()) * 1000 - 1
        print("startTime:", startTime, "end_time:", df.iloc[0]['candle_begin_time'])
        # 下载太多的k线的时候，中间sleep一下
        time.sleep(0.1)
    
    all_df = pd.concat(df_list, ignore_index=True)
    
    all_df.sort_values(by=['candle_begin_time'], inplace=True)  # 排序
    all_df.drop_duplicates(subset=['candle_begin_time'], keep='last', inplace=True)
    all_df = all_df.reset_index(drop=True)
    
    print(all_df)
    return all_df

from_datetime = datetime(2025, 8, 30, 0, 0, 0)
run_time = datetime.now()
limit = (run_time.timestamp() - from_datetime.timestamp()) // 60
df = get_candle_df_kline(48, run_time, limit=limit, interval='1m')

print(df)
pass