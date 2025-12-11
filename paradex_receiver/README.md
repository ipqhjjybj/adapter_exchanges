# Paradex WebSocket 深度数据接收器

基于 lighter_receiver 实现的 Paradex 平台 WebSocket 深度数据接收器，支持接收15档盘口数据并存储为 Tardis book_snapshot_15 格式。

## 功能特性

- 接收 Paradex WebSocket 15档深度数据
- 转换为 Tardis book_snapshot_15 格式
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
python main.py -t YOUR_BEARER_TOKEN

# 指定多个交易对
python main.py -t YOUR_BEARER_TOKEN -s "PAXG-USD-PERP,ETH-USD-PERP"

# 自定义输出目录
python main.py -t YOUR_BEARER_TOKEN -o ./paradex_data

# 完整参数示例
python main.py \
  --token YOUR_BEARER_TOKEN \
  --symbols "PAXG-USD-PERP,ETH-USD-PERP" \
  --output-dir ./data \
  --levels 15 \
  --frequency 50ms \
  --min-delta 0_01 \
  --no-compress
```

### 2. 程序中使用

```python
from paradex_receiver import ParadexDepthReceiver, TardisL2Snapshot

def on_snapshot(snapshot: TardisL2Snapshot):
    print(f"收到 {snapshot.symbol} 快照，买单:{len(snapshot.bids)} 卖单:{len(snapshot.asks)}")

receiver = ParadexDepthReceiver(
    symbols=["PAXG-USD-PERP"],
    bearer_token="YOUR_TOKEN",
    levels=15
)
receiver.on_snapshot = on_snapshot
receiver.start()
```

## 参数说明

- `--token/-t`: Paradex Bearer Token (必需)
- `--symbols/-s`: 交易对列表，逗号分隔 (默认: PAXG-USD-PERP)
- `--output-dir/-o`: 输出目录 (默认: ./data)
- `--levels`: 深度档数 (默认: 15)
- `--frequency`: 更新频率 (默认: 50ms)
- `--min-delta`: 最小变化 (默认: 0_01)
- `--no-compress`: 不压缩 CSV 文件

## 输出格式

### book_snapshot_15 格式

生成的 CSV 文件格式为 `{exchange}_book_snapshot_15_{symbol}_{date}.csv.gz`:

```
exchange,symbol,timestamp,local_timestamp,asks[0].price,asks[0].amount,bids[0].price,bids[0].amount,asks[1].price,asks[1].amount,bids[1].price,bids[1].amount,...
```

包含以下列：
- exchange: 交易所名称 (paradex)
- symbol: 交易对
- timestamp: 服务器时间戳 (微秒)
- local_timestamp: 本地时间戳 (微秒)
- asks[0-14].price/amount: 15档卖单价格和数量
- bids[0-14].price/amount: 15档买单价格和数量

## Paradex WebSocket 数据格式

接收到的原始数据格式：

```json
{
  "jsonrpc": "2.0", 
  "method": "subscription", 
  "params": {
    "channel": "order_book.PAXG-USD-PERP.snapshot@15@50ms@0_01", 
    "data": {
      "seq_no": 221630136, 
      "market": "PAXG-USD-PERP", 
      "last_updated_at": 1765414160440, 
      "update_type": "s", 
      "inserts": [
        {"side": "BUY", "price": "4241.79", "size": "0.012"},
        {"side": "SELL", "price": "4242", "size": "0.1"}
      ], 
      "updates": [], 
      "deletes": []
    }
  }
}
```

## 测试

运行测试脚本：

```bash
python test_receiver.py
```

## 文件结构

```
paradex_receiver/
├── __init__.py          # 包初始化
├── data_types.py        # 数据类型定义
├── receiver.py          # WebSocket 接收器
├── main.py              # 命令行入口
├── test_receiver.py     # 测试脚本
└── README.md            # 说明文档
```