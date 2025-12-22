# Paradex WebSocket 交易数据接收器

基于 lighter_receiver 实现的 Paradex 平台 WebSocket 交易数据接收器，支持接收实时交易数据并存储为 Tardis 格式。

## 功能特性

- 接收 Paradex WebSocket 实时交易数据
- 转换为 Tardis 标准格式
- 按天、按交易对保存 CSV 文件
- 支持 gzip 压缩
- 自动重连机制
- 心跳检测

## 安装依赖

```bash
pip install websocket-client
```

## 使用方法

### 1. 命令行运行

```bash
# 基本用法
python trades_main.py -t YOUR_BEARER_TOKEN

# 指定多个交易对
python trades_main.py -t YOUR_BEARER_TOKEN -s "PAXG-USD-PERP,ETH-USD-PERP"

# 自定义输出目录
python trades_main.py -t YOUR_BEARER_TOKEN -o ./trades_data

# 完整参数示例
python trades_main.py \
  --token YOUR_BEARER_TOKEN \
  --symbols "PAXG-USD-PERP,ETH-USD-PERP" \
  --output-dir ./data \
  --no-compress
```

### 2. 程序中使用

```python
from paradex_receiver import ParadexTradesReceiver, TardisTrade

def on_trade(trade: TardisTrade):
    print(f"交易: {trade.symbol} {trade.side} {trade.price}@{trade.amount}")

receiver = ParadexTradesReceiver(
    symbols=["PAXG-USD-PERP"],
    bearer_token="YOUR_TOKEN"
)
receiver.on_trade = on_trade
receiver.start()
```

## 参数说明

- `--token/-t`: Paradex Bearer Token (必需)
- `--symbols/-s`: 交易对列表，逗号分隔 (默认: PAXG-USD-PERP)
- `--output-dir/-o`: 输出目录 (默认: ./data)
- `--no-compress`: 不压缩 CSV 文件

## 输出格式

### Tardis 交易格式

生成的 CSV 文件格式为 `{exchange}_trades_{symbol}_{date}.csv.gz`:

```
exchange,symbol,timestamp,local_timestamp,id,side,price,amount
paradex,PAXG-USD-PERP,1765418142168000,1765419003238042,1765418142160201709229040013,buy,4241,0.012
```

包含以下列：
- exchange: 交易所名称 (paradex)
- symbol: 交易对
- timestamp: 服务器时间戳 (微秒)
- local_timestamp: 本地时间戳 (微秒)
- id: 交易ID
- side: 交易方向 (buy/sell)
- price: 成交价格
- amount: 成交数量

## Paradex WebSocket 交易数据格式

接收到的原始数据格式：

```json
{
  "jsonrpc": "2.0", 
  "method": "subscription", 
  "params": {
    "channel": "trades.PAXG-USD-PERP", 
    "data": {
      "id": "1765418142160201709229040013", 
      "market": "PAXG-USD-PERP", 
      "side": "BUY", 
      "size": "0.012", 
      "price": "4241", 
      "created_at": 1765418142168, 
      "trade_type": "FILL"
    }
  }
}
```

## 数据转换

### 原始 Paradex → Tardis 格式转换

- `id` → `id` (保持不变)
- `market` → `symbol` (交易对)
- `side`: `BUY` → `buy`, `SELL` → `sell`
- `size` → `amount` (成交数量)
- `price` → `price` (成交价格)
- `created_at` (毫秒) → `timestamp` (微秒)
- 添加 `exchange` = "paradex"
- 添加 `local_timestamp` (本地接收时间，微秒)

## 测试

运行测试脚本：

```bash
# 测试数据转换
python test_data_transformation.py

# 测试实际接收器
python test_trades_receiver.py
```

## 文件结构

```
paradex_receiver/
├── __init__.py                    # 包初始化
├── data_types.py                  # 数据类型定义
├── receiver.py                    # 深度数据接收器
├── trades_receiver.py             # 交易数据接收器
├── main.py                        # 深度数据命令行入口
├── trades_main.py                 # 交易数据命令行入口
├── test_receiver.py               # 深度数据测试
├── test_trades_receiver.py        # 交易数据测试
├── test_data_transformation.py    # 数据转换测试
├── README.md                      # 深度数据说明
└── TRADES_README.md               # 交易数据说明
```

## 示例输出

运行数据转换测试的输出示例：

```
=== 原始 Paradex 消息 ===
{
  "jsonrpc": "2.0",
  "method": "subscription",
  "params": {
    "channel": "trades.PAXG-USD-PERP",
    "data": {
      "id": "1765418142160201709229040013",
      "market": "PAXG-USD-PERP",
      "side": "BUY",
      "size": "0.012",
      "price": "4241",
      "created_at": 1765418142168,
      "trade_type": "FILL"
    }
  }
}

=== Tardis 交易格式 ===
Exchange: paradex
Symbol: PAXG-USD-PERP
Timestamp: 1765418142168000
Local Timestamp: 1765419003238042
ID: 1765418142160201709229040013
Side: buy
Price: 4241
Amount: 0.012

=== CSV 格式输出 ===
exchange,symbol,timestamp,local_timestamp,id,side,price,amount
paradex,PAXG-USD-PERP,1765418142168000,1765419003238042,1765418142160201709229040013,buy,4241,0.012
```