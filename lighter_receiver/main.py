"""
Lighter DEX 深度数据接收器 - 按天记录到 CSV (Tardis 格式)
"""

import logging
import argparse
import gzip
import sys
import os
from datetime import datetime, timezone
from typing import Dict, Optional

sys.path.append("/home/ec2-user/test_lighter_dex/adapter_exchanges/lighter_receiver")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lighter_receiver import LighterDepthReceiver, TardisL2Update

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

MARKET_SYMBOL_MAP = {
    0: "ETHUSDT",
    # 1: "BTCUSDT",
    # 2: "SOLUSDT",
}

CSV_HEADER = "exchange,symbol,timestamp,local_timestamp,is_snapshot,side,price,amount\n"


class DailyCSVWriter:
    """按天按symbol保存CSV文件，格式: {output_dir}/{exchange}_book_snapshot_l2_{symbol}_{date}.csv.gz"""

    def __init__(self, output_dir: str, exchange: str = "lighter", compress: bool = True):
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
        filename = f"{self.exchange}_book_snapshot_l2_{symbol}_{date}.csv"
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
        f.write(CSV_HEADER)
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

    def write(self, update: TardisL2Update):
        """写入一条更新记录"""
        symbol = update.symbol
        date = self._get_date_from_timestamp(update.timestamp)

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
        self._files[file_key].write(update.to_csv_row() + "\n")
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
    parser = argparse.ArgumentParser(description="Lighter DEX 深度数据接收器 (按天保存)")
    parser.add_argument("-m", "--markets", type=str, default="0", help="市场ID，逗号分隔 (默认: 0)")
    parser.add_argument("-o", "--output-dir", type=str, default="./data", help="输出目录 (默认: ./data)")
    parser.add_argument("--no-compress", action="store_true", help="不压缩CSV文件")
    args = parser.parse_args()

    market_ids = [int(x.strip()) for x in args.markets.split(",")]
    market_symbol_map = {mid: MARKET_SYMBOL_MAP.get(mid, f"MARKET_{mid}") for mid in market_ids}

    writer = DailyCSVWriter(
        output_dir=args.output_dir,
        exchange="lighter",
        compress=not args.no_compress,
    )

    def on_update(update: TardisL2Update):
        writer.write(update)

    receiver = LighterDepthReceiver(market_ids=market_ids, market_symbol_map=market_symbol_map)
    receiver.on_update = on_update

    try:
        logger.info(f"开始接收数据，市场: {market_ids}，输出目录: {args.output_dir}")
        receiver.start()
    except KeyboardInterrupt:
        logger.info("用户中断")
    finally:
        receiver.stop()
        writer.close_all()
        logger.info(f"总共写入 {writer.get_total_count()} 条记录")


if __name__ == "__main__":
    main()
