"""
Lighter 数据转换为 Tardis L2 格式
"""

import time
from typing import List, Dict, Optional
from .data_types import TardisL2Update, TardisL2Snapshot, TardisL2PriceLevel, LighterOrderBookMessage


class LighterToTardisConverter:
    """将 Lighter 订单簿数据转换为 Tardis L2 格式"""

    EXCHANGE_NAME = "lighter"

    def __init__(self, market_symbol_map: Optional[Dict[int, str]] = None):
        self.market_symbol_map = market_symbol_map or {}
        self._orderbook_state: Dict[int, Dict[str, Dict[str, str]]] = {}

    def get_symbol(self, market_index: int) -> str:
        return self.market_symbol_map.get(market_index, f"MARKET_{market_index}")

    def _get_microseconds_timestamp(self) -> int:
        return int(time.time() * 1_000_000)

    def _convert_timestamp(self, timestamp: int, local_timestamp: int) -> int:
        """转换时间戳为微秒级"""
        if timestamp == 0 or timestamp is None:
            return local_timestamp
        if timestamp > 1_000_000_000_000_000:
            return timestamp
        elif timestamp > 1_000_000_000_000:
            return timestamp * 1_000
        else:
            return timestamp * 1_000_000

    def convert_to_snapshot(self, message: LighterOrderBookMessage) -> TardisL2Snapshot:
        """转换为快照"""
        local_timestamp = self._get_microseconds_timestamp()
        exchange_timestamp = self._convert_timestamp(message.timestamp, local_timestamp)
        symbol = self.get_symbol(message.market_index)

        bids = [TardisL2PriceLevel(price=b.get("price", "0"), amount=b.get("size", "0")) for b in message.bids]
        asks = [TardisL2PriceLevel(price=a.get("price", "0"), amount=a.get("size", "0")) for a in message.asks]

        snapshot = TardisL2Snapshot(
            exchange=self.EXCHANGE_NAME,
            symbol=symbol,
            timestamp=exchange_timestamp,
            local_timestamp=local_timestamp,
            bids=bids,
            asks=asks,
        )

        # 更新本地状态
        self._orderbook_state[message.market_index] = {
            "bids": {level.price: level.amount for level in bids},
            "asks": {level.price: level.amount for level in asks},
        }

        return snapshot

    def convert_to_incremental_updates(
        self, message: LighterOrderBookMessage, is_first_message: bool = False
    ) -> List[TardisL2Update]:
        """转换为增量更新"""
        local_timestamp = self._get_microseconds_timestamp()
        exchange_timestamp = self._convert_timestamp(message.timestamp, local_timestamp)
        symbol = self.get_symbol(message.market_index)
        market_index = message.market_index

        # 第一条消息或无历史状态，作为快照处理
        if is_first_message or market_index not in self._orderbook_state:
            snapshot = self.convert_to_snapshot(message)
            return snapshot.to_updates()

        updates = []
        old_state = self._orderbook_state.get(market_index, {"bids": {}, "asks": {}})

        new_bids = {b.get("price", "0"): b.get("size", "0") for b in message.bids}
        new_asks = {a.get("price", "0"): a.get("size", "0") for a in message.asks}

        # 计算差异
        for side, old_levels, new_levels in [("bid", old_state["bids"], new_bids), ("ask", old_state["asks"], new_asks)]:
            all_prices = set(old_levels.keys()) | set(new_levels.keys())
            for price in all_prices:
                old_amount = old_levels.get(price)
                new_amount = new_levels.get(price)

                if old_amount is None and new_amount is not None:  # 新增
                    updates.append(TardisL2Update(
                        exchange=self.EXCHANGE_NAME, symbol=symbol, timestamp=exchange_timestamp,
                        local_timestamp=local_timestamp, is_snapshot=False, side=side, price=price, amount=new_amount,
                    ))
                elif old_amount is not None and new_amount is None:  # 删除
                    updates.append(TardisL2Update(
                        exchange=self.EXCHANGE_NAME, symbol=symbol, timestamp=exchange_timestamp,
                        local_timestamp=local_timestamp, is_snapshot=False, side=side, price=price, amount="0",
                    ))
                elif old_amount != new_amount:  # 修改
                    updates.append(TardisL2Update(
                        exchange=self.EXCHANGE_NAME, symbol=symbol, timestamp=exchange_timestamp,
                        local_timestamp=local_timestamp, is_snapshot=False, side=side, price=price, amount=new_amount,
                    ))

        # 更新本地状态
        self._orderbook_state[market_index] = {"bids": new_bids, "asks": new_asks}

        return updates

    def reset_state(self):
        """重置本地订单簿状态"""
        self._orderbook_state.clear()
