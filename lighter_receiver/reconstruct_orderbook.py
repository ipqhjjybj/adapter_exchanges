"""
从 L2 增量数据重建订单簿并检测异常

用法:
    python reconstruct_orderbook.py <csv_file> [--top N] [--verbose]

检测项目:
    1. 买卖盘交叉 (best_bid >= best_ask)
    2. 价格跳跃 (mid price 变化超过阈值)
    3. 负数或异常数量
    4. 订单簿深度异常 (层数过少)
"""

import argparse
import csv
import gzip
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from collections import defaultdict


@dataclass
class OrderBook:
    """订单簿状态"""
    bids: Dict[str, Decimal] = field(default_factory=dict)  # price -> amount
    asks: Dict[str, Decimal] = field(default_factory=dict)
    last_timestamp: int = 0

    def apply_update(self, side: str, price: str, amount: str, timestamp: int):
        """应用增量更新"""
        book = self.bids if side == "bid" else self.asks
        amt = Decimal(amount)
        if amt == 0:
            book.pop(price, None)
        else:
            book[price] = amt
        self.last_timestamp = timestamp

    def reset(self):
        """重置订单簿"""
        self.bids.clear()
        self.asks.clear()

    def get_best_bid(self) -> Optional[Tuple[Decimal, Decimal]]:
        """返回 (price, amount)"""
        if not self.bids:
            return None
        price = max(self.bids.keys(), key=Decimal)
        return Decimal(price), self.bids[price]

    def get_best_ask(self) -> Optional[Tuple[Decimal, Decimal]]:
        if not self.asks:
            return None
        price = min(self.asks.keys(), key=Decimal)
        return Decimal(price), self.asks[price]

    def get_mid_price(self) -> Optional[Decimal]:
        best_bid = self.get_best_bid()
        best_ask = self.get_best_ask()
        if best_bid and best_ask:
            return (best_bid[0] + best_ask[0]) / 2
        return None

    def get_spread(self) -> Optional[Decimal]:
        best_bid = self.get_best_bid()
        best_ask = self.get_best_ask()
        if best_bid and best_ask:
            return best_ask[0] - best_bid[0]
        return None

    def get_spread_bps(self) -> Optional[Decimal]:
        """返回 spread 的 bps"""
        mid = self.get_mid_price()
        spread = self.get_spread()
        if mid and spread and mid > 0:
            return spread / mid * 10000
        return None

    def get_top_n(self, n: int = 5) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
        """返回前 N 档 (bids, asks)"""
        sorted_bids = sorted(self.bids.items(), key=lambda x: Decimal(x[0]), reverse=True)[:n]
        sorted_asks = sorted(self.asks.items(), key=lambda x: Decimal(x[0]))[:n]
        return [(p, str(a)) for p, a in sorted_bids], [(p, str(a)) for p, a in sorted_asks]


@dataclass
class Anomaly:
    """异常记录"""
    timestamp: int
    anomaly_type: str
    message: str
    details: dict = field(default_factory=dict)


class OrderBookReconstructor:
    """订单簿重建器"""

    def __init__(
        self,
        price_jump_threshold_bps: float = 100.0,  # 1% 价格跳跃阈值
        min_depth_warning: int = 3,  # 最少深度警告阈值
        max_spread_bps: float = 500.0,  # 5% 最大正常 spread
    ):
        self.price_jump_threshold_bps = price_jump_threshold_bps
        self.min_depth_warning = min_depth_warning
        self.max_spread_bps = max_spread_bps

        self.orderbook = OrderBook()
        self.anomalies: List[Anomaly] = []
        self.stats = {
            "total_updates": 0,
            "snapshots": 0,
            "incremental_updates": 0,
            "crossed_book_count": 0,
            "price_jumps": 0,
            "low_depth_count": 0,
            "wide_spread_count": 0,
        }
        self.last_mid_price: Optional[Decimal] = None
        self.mid_price_history: List[Tuple[int, Decimal]] = []

    def process_update(
        self,
        timestamp: int,
        is_snapshot: bool,
        side: str,
        price: str,
        amount: str,
        verbose: bool = False,
    ):
        """处理一条更新"""
        self.stats["total_updates"] += 1

        # 快照时重置订单簿
        if is_snapshot:
            if self.stats["snapshots"] == 0 or self.orderbook.last_timestamp != timestamp:
                # 新的快照开始
                if self.stats["snapshots"] > 0:
                    # 不是第一个快照，说明有重连
                    self.anomalies.append(Anomaly(
                        timestamp=timestamp,
                        anomaly_type="NEW_SNAPSHOT",
                        message="检测到新的快照，可能是重连",
                    ))
                self.orderbook.reset()
                self.stats["snapshots"] += 1
            self.orderbook.apply_update(side, price, amount, timestamp)
        else:
            self.stats["incremental_updates"] += 1
            self.orderbook.apply_update(side, price, amount, timestamp)

        # 检测异常（每次更新后检查）
        self._check_anomalies(timestamp, verbose)

    def _check_anomalies(self, timestamp: int, verbose: bool):
        """检测各种异常"""
        best_bid = self.orderbook.get_best_bid()
        best_ask = self.orderbook.get_best_ask()

        # 1. 检测买卖盘交叉
        if best_bid and best_ask:
            if best_bid[0] >= best_ask[0]:
                self.stats["crossed_book_count"] += 1
                self.anomalies.append(Anomaly(
                    timestamp=timestamp,
                    anomaly_type="CROSSED_BOOK",
                    message=f"买卖盘交叉: bid={best_bid[0]} >= ask={best_ask[0]}",
                    details={"best_bid": str(best_bid[0]), "best_ask": str(best_ask[0])},
                ))

        # 2. 检测价格跳跃
        mid_price = self.orderbook.get_mid_price()
        if mid_price:
            self.mid_price_history.append((timestamp, mid_price))
            if self.last_mid_price and self.last_mid_price > 0:
                change_bps = abs(mid_price - self.last_mid_price) / self.last_mid_price * 10000
                if change_bps > self.price_jump_threshold_bps:
                    self.stats["price_jumps"] += 1
                    self.anomalies.append(Anomaly(
                        timestamp=timestamp,
                        anomaly_type="PRICE_JUMP",
                        message=f"价格跳跃 {change_bps:.2f} bps: {self.last_mid_price} -> {mid_price}",
                        details={
                            "old_mid": str(self.last_mid_price),
                            "new_mid": str(mid_price),
                            "change_bps": float(change_bps),
                        },
                    ))
            self.last_mid_price = mid_price

        # 3. 检测深度不足
        bid_depth = len(self.orderbook.bids)
        ask_depth = len(self.orderbook.asks)
        if bid_depth < self.min_depth_warning or ask_depth < self.min_depth_warning:
            # 只记录一次，避免刷屏
            if self.stats["low_depth_count"] == 0 or verbose:
                self.anomalies.append(Anomaly(
                    timestamp=timestamp,
                    anomaly_type="LOW_DEPTH",
                    message=f"深度不足: bids={bid_depth}, asks={ask_depth}",
                    details={"bid_depth": bid_depth, "ask_depth": ask_depth},
                ))
            self.stats["low_depth_count"] += 1

        # 4. 检测异常 spread
        spread_bps = self.orderbook.get_spread_bps()
        if spread_bps and spread_bps > self.max_spread_bps:
            self.stats["wide_spread_count"] += 1
            if self.stats["wide_spread_count"] <= 10 or verbose:  # 只记录前 10 次
                self.anomalies.append(Anomaly(
                    timestamp=timestamp,
                    anomaly_type="WIDE_SPREAD",
                    message=f"Spread 过大: {spread_bps:.2f} bps",
                    details={"spread_bps": float(spread_bps)},
                ))

    def get_summary(self) -> dict:
        """返回统计摘要"""
        return {
            "stats": self.stats,
            "final_orderbook": {
                "bid_levels": len(self.orderbook.bids),
                "ask_levels": len(self.orderbook.asks),
                "best_bid": str(self.orderbook.get_best_bid()) if self.orderbook.get_best_bid() else None,
                "best_ask": str(self.orderbook.get_best_ask()) if self.orderbook.get_best_ask() else None,
                "mid_price": str(self.orderbook.get_mid_price()) if self.orderbook.get_mid_price() else None,
                "spread_bps": float(self.orderbook.get_spread_bps()) if self.orderbook.get_spread_bps() else None,
            },
            "anomaly_count": len(self.anomalies),
            "anomaly_types": dict(defaultdict(int, {a.anomaly_type: sum(1 for x in self.anomalies if x.anomaly_type == a.anomaly_type) for a in self.anomalies})),
        }


def parse_bool(s: str) -> bool:
    return s.lower() == "true"


def read_csv(filepath: str):
    """读取 CSV 文件（支持 gzip）"""
    if filepath.endswith(".gz"):
        f = gzip.open(filepath, "rt", encoding="utf-8")
    else:
        f = open(filepath, "r", encoding="utf-8")

    reader = csv.DictReader(f)
    for row in reader:
        yield row
    f.close()


def format_timestamp(ts_us: int) -> str:
    """格式化微秒时间戳"""
    from datetime import datetime, timezone
    dt = datetime.fromtimestamp(ts_us / 1_000_000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def main():
    parser = argparse.ArgumentParser(description="从 L2 数据重建订单簿并检测异常")
    parser.add_argument("csv_file", help="L2 CSV 文件路径")
    parser.add_argument("--top", type=int, default=5, help="显示前 N 档盘口 (默认: 5)")
    parser.add_argument("--verbose", action="store_true", help="显示详细信息")
    parser.add_argument("--jump-threshold", type=float, default=100.0, help="价格跳跃阈值 (bps, 默认: 100)")
    parser.add_argument("--max-anomalies", type=int, default=50, help="最多显示的异常数量 (默认: 50)")
    args = parser.parse_args()

    print(f"正在处理文件: {args.csv_file}")
    print(f"价格跳跃阈值: {args.jump_threshold} bps")
    print("-" * 60)

    reconstructor = OrderBookReconstructor(
        price_jump_threshold_bps=args.jump_threshold,
    )

    row_count = 0
    for row in read_csv(args.csv_file):
        row_count += 1
        reconstructor.process_update(
            timestamp=int(row["timestamp"]),
            is_snapshot=parse_bool(row["is_snapshot"]),
            side=row["side"],
            price=row["price"],
            amount=row["amount"],
            verbose=args.verbose,
        )

        # 进度显示
        if row_count % 10000 == 0:
            print(f"已处理 {row_count} 行...")

    print(f"\n处理完成，共 {row_count} 行")
    print("=" * 60)

    # 显示统计摘要
    summary = reconstructor.get_summary()
    stats = summary["stats"]

    print("\n【统计信息】")
    print(f"  总更新数: {stats['total_updates']}")
    print(f"  快照数: {stats['snapshots']}")
    print(f"  增量更新数: {stats['incremental_updates']}")

    print("\n【异常统计】")
    print(f"  买卖盘交叉: {stats['crossed_book_count']} 次")
    print(f"  价格跳跃 (>{args.jump_threshold}bps): {stats['price_jumps']} 次")
    print(f"  深度不足: {stats['low_depth_count']} 次")
    print(f"  Spread过大: {stats['wide_spread_count']} 次")

    print("\n【最终订单簿状态】")
    final_ob = summary["final_orderbook"]
    print(f"  Bid 层数: {final_ob['bid_levels']}")
    print(f"  Ask 层数: {final_ob['ask_levels']}")
    print(f"  Best Bid: {final_ob['best_bid']}")
    print(f"  Best Ask: {final_ob['best_ask']}")
    print(f"  Mid Price: {final_ob['mid_price']}")
    print(f"  Spread: {final_ob['spread_bps']:.2f} bps" if final_ob['spread_bps'] else "  Spread: N/A")

    # 显示前 N 档
    print(f"\n【前 {args.top} 档盘口】")
    top_bids, top_asks = reconstructor.orderbook.get_top_n(args.top)

    print("  Asks:")
    for price, amount in reversed(top_asks):
        print(f"    {price:>12} | {amount}")
    print("  " + "-" * 25)
    print("  Bids:")
    for price, amount in top_bids:
        print(f"    {price:>12} | {amount}")

    # 显示异常详情
    if reconstructor.anomalies:
        print(f"\n【异常详情】(显示前 {args.max_anomalies} 条)")
        shown = 0
        for anomaly in reconstructor.anomalies:
            if shown >= args.max_anomalies:
                remaining = len(reconstructor.anomalies) - shown
                print(f"\n  ... 还有 {remaining} 条异常未显示")
                break
            ts_str = format_timestamp(anomaly.timestamp)
            print(f"  [{ts_str}] [{anomaly.anomaly_type}] {anomaly.message}")
            shown += 1
    else:
        print("\n【无异常】订单簿数据正常")

    # 价格走势简要
    if reconstructor.mid_price_history:
        print("\n【价格走势】")
        history = reconstructor.mid_price_history
        first_ts, first_price = history[0]
        last_ts, last_price = history[-1]
        min_price = min(p for _, p in history)
        max_price = max(p for _, p in history)
        print(f"  开始: {format_timestamp(first_ts)} @ {first_price}")
        print(f"  结束: {format_timestamp(last_ts)} @ {last_price}")
        print(f"  最低: {min_price}")
        print(f"  最高: {max_price}")
        if first_price > 0:
            change_pct = (last_price - first_price) / first_price * 100
            print(f"  涨跌幅: {change_pct:+.4f}%")


if __name__ == "__main__":
    main()
