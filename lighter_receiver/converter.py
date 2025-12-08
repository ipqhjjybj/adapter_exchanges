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

        return snapshot

    def convert_to_incremental_updates(
        self, message: LighterOrderBookMessage, is_first_message: bool = False
    ) -> List[TardisL2Update]:
        """转换为增量更新，直接输出原始变更数据"""
        local_timestamp = self._get_microseconds_timestamp()
        exchange_timestamp = self._convert_timestamp(message.timestamp, local_timestamp)
        symbol = self.get_symbol(message.market_index)

        updates = []

        # 直接输出 bids 变更
        for b in message.bids:
            updates.append(TardisL2Update(
                exchange=self.EXCHANGE_NAME,
                symbol=symbol,
                timestamp=exchange_timestamp,
                local_timestamp=local_timestamp,
                is_snapshot=False,
                side="bid",
                price=b.get("price", "0"),
                amount=b.get("size", "0"),
            ))

        # 直接输出 asks 变更
        for a in message.asks:
            updates.append(TardisL2Update(
                exchange=self.EXCHANGE_NAME,
                symbol=symbol,
                timestamp=exchange_timestamp,
                local_timestamp=local_timestamp,
                is_snapshot=False,
                side="ask",
                price=a.get("price", "0"),
                amount=a.get("size", "0"),
            ))

        return updates
