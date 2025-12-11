"""
Paradex 深度数据接收器 - 按天记录到 CSV (Tardis book_snapshot_15 格式)
"""

import logging
import argparse
import gzip
import sys
import os
from datetime import datetime, timezone
from typing import Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paradex_receiver import ParadexDepthReceiver, TardisL2Snapshot

sys.path.append("/home/ec2-user/test_lighter_dex/adapter_exchanges/lighter_receiver")
sys.path.append("/Users/shenzhuoheng/quant_yz/git/adapter_exchanges/paradex_receiver")


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Paradex book_snapshot_15 CSV header (exchange, symbol, timestamp, local_timestamp, then 15 levels of asks and bids)
def get_book_snapshot_15_header() -> str:
    """生成 book_snapshot_15 格式的 CSV 头"""
    header = ["exchange", "symbol", "timestamp", "local_timestamp"]
    
    # 添加15档asks价格和数量列
    for i in range(15):
        header.extend([f"asks[{i}].price", f"asks[{i}].amount"])
    
    # 添加15档bids价格和数量列
    for i in range(15):
        header.extend([f"bids[{i}].price", f"bids[{i}].amount"])
    
    return ",".join(header) + "\n"


class DailyCSVWriter:
    """按天按symbol保存CSV文件，格式: {output_dir}/{exchange}_book_snapshot_15_{symbol}_{date}.csv.gz"""

    def __init__(self, output_dir: str, exchange: str = "paradex", compress: bool = True):
        self.output_dir = output_dir
        self.exchange = exchange
        self.compress = compress
        self._files: Dict[str, object] = {}  # key: symbol_date
        self._current_dates: Dict[str, str] = {}  # key: symbol, value: date
        self._update_counts: Dict[str, int] = {}  # key: symbol_date
        os.makedirs(output_dir, exist_ok=True)

    def _get_date_from_timestamp(self, timestamp_us: int) -> str:
        """从微秒时间戳获取日期字符串 YYYY-MM-DD"""
        dt = datetime.fromtimestamp(timestamp_us / 1_000_000, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d")

    def _get_file_key(self, symbol: str, date: str) -> str:
        return f"{symbol}_{date}"

    def _get_file_path(self, symbol: str, date: str) -> str:
        filename = f"{self.exchange}_book_snapshot_15_{symbol}_{date}.csv"
        if self.compress:
            filename += ".gz"
        return os.path.join(self.output_dir, filename)

    def _open_file(self, symbol: str, date: str):
        """打开或创建新的日期文件"""
        file_key = self._get_file_key(symbol, date)
        if file_key in self._files:
            return

        file_path = self._get_file_path(symbol, date)
        if self.compress:
            f = gzip.open(file_path, "wt", encoding="utf-8")
        else:
            f = open(file_path, "w", encoding="utf-8")
        f.write(get_book_snapshot_15_header())
        self._files[file_key] = f
        self._update_counts[file_key] = 0
        logger.info(f"创建新文件: {file_path}")

    def _close_file(self, symbol: str, date: str):
        """关闭指定文件"""
        file_key = self._get_file_key(symbol, date)
        if file_key in self._files:
            self._files[file_key].close()
            count = self._update_counts.get(file_key, 0)
            file_path = self._get_file_path(symbol, date)
            logger.info(f"关闭文件: {file_path}，共 {count} 条记录")
            del self._files[file_key]
            if file_key in self._update_counts:
                del self._update_counts[file_key]

    def write_snapshot(self, snapshot: TardisL2Snapshot):
        """写入一条快照记录"""
        symbol = snapshot.symbol
        date = self._get_date_from_timestamp(snapshot.timestamp)

        # 检查是否需要切换到新的日期文件
        old_date = self._current_dates.get(symbol)
        if old_date and old_date != date:
            self._close_file(symbol, old_date)

        self._current_dates[symbol] = date
        file_key = self._get_file_key(symbol, date)

        # 确保文件已打开
        if file_key not in self._files:
            self._open_file(symbol, date)

        # 写入数据
        self._files[file_key].write(snapshot.to_book_snapshot_15_row() + "\n")
        self._update_counts[file_key] = self._update_counts.get(file_key, 0) + 1

        # 定期flush
        if self._update_counts[file_key] % 100 == 0:
            self._files[file_key].flush()
            logger.info(f"[{symbol}][{date}] 已写入 {self._update_counts[file_key]} 条记录")

    def close_all(self):
        """关闭所有文件"""
        for symbol, date in list(self._current_dates.items()):
            self._close_file(symbol, date)
        self._current_dates.clear()

    def get_total_count(self) -> int:
        """获取总记录数"""
        return sum(self._update_counts.values())


def main():
    parser = argparse.ArgumentParser(description="Paradex 深度数据接收器 (book_snapshot_15格式)")
    # parser.add_argument("-s", "--symbols", type=str, default="PAXG-USD-PERP", 
    #                   help="交易对，逗号分隔 (默认: PAXG-USD-PERP)")
    # parser.add_argument("-t", "--token", type=str, required=True,
    #                   help="Paradex Bearer Token (必需)")
    parser.add_argument("-o", "--output-dir", type=str, default="./data", 
                      help="输出目录 (默认: ./data)")
    parser.add_argument("--levels", type=int, default=15,
                      help="深度档数 (默认: 15)")
    parser.add_argument("--frequency", type=str, default="50ms",
                      help="更新频率 (默认: 50ms)")
    parser.add_argument("--min-delta", type=str, default="0_01",
                      help="最小变化 (默认: 0_01)")
    parser.add_argument("--no-compress", action="store_true", 
                      help="不压缩CSV文件")

    args = parser.parse_args()
    
    args.symbols = "PAXG-USD-PERP"
    args.token = "JWcgwMbK0bx1uFFef0Lri35ZDwypmCG0isuBv"
    args.no_compress = True

    symbols = [x.strip() for x in args.symbols.split(",")]
    
    writer = DailyCSVWriter(
        output_dir=args.output_dir,
        exchange="paradex",
        compress=not args.no_compress,
    )

    def on_snapshot(snapshot: TardisL2Snapshot):
        writer.write_snapshot(snapshot)

    receiver = ParadexDepthReceiver(
        symbols=symbols,
        bearer_token=args.token,
        levels=args.levels,
        frequency=args.frequency,
        min_delta=args.min_delta
    )
    receiver.on_snapshot = on_snapshot

    try:
        logger.info(f"开始接收数据，交易对: {symbols}，输出目录: {args.output_dir}")
        logger.info(f"深度档数: {args.levels}, 频率: {args.frequency}, 最小变化: {args.min_delta}")
        receiver.start()
    except KeyboardInterrupt:
        logger.info("用户中断")
    finally:
        receiver.stop()
        writer.close_all()
        logger.info(f"总共写入 {writer.get_total_count()} 条记录")


if __name__ == "__main__":
    main()