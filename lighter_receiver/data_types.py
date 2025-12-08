"""
Tardis L2 数据格式定义
"""

from dataclasses import dataclass, field
from typing import List, Optional, Literal


@dataclass
class TardisL2Update:
    """
    Tardis L2 增量更新

    CSV 格式: exchange,symbol,timestamp,local_timestamp,is_snapshot,side,price,amount
    """
    exchange: str
    symbol: str
    timestamp: int  # 微秒
    local_timestamp: int  # 微秒
    is_snapshot: bool
    side: Literal["bid", "ask"]
    price: str
    amount: str  # 0 表示删除

    def to_csv_row(self) -> str:
        return f"{self.exchange},{self.symbol},{self.timestamp},{self.local_timestamp},{str(self.is_snapshot).lower()},{self.side},{self.price},{self.amount}"

    def to_dict(self) -> dict:
        return {
            "exchange": self.exchange,
            "symbol": self.symbol,
            "timestamp": self.timestamp,
            "local_timestamp": self.local_timestamp,
            "is_snapshot": self.is_snapshot,
            "side": self.side,
            "price": self.price,
            "amount": self.amount,
        }


@dataclass
class TardisL2PriceLevel:
    """单个价格级别"""
    price: str
    amount: str


@dataclass
class TardisL2Snapshot:
    """Tardis L2 订单簿快照"""
    exchange: str
    symbol: str
    timestamp: int
    local_timestamp: int
    bids: List[TardisL2PriceLevel] = field(default_factory=list)
    asks: List[TardisL2PriceLevel] = field(default_factory=list)

    def to_updates(self) -> List[TardisL2Update]:
        """将快照转换为增量更新列表"""
        updates = []
        for level in self.bids:
            updates.append(TardisL2Update(
                exchange=self.exchange,
                symbol=self.symbol,
                timestamp=self.timestamp,
                local_timestamp=self.local_timestamp,
                is_snapshot=True,
                side="bid",
                price=level.price,
                amount=level.amount,
            ))
        for level in self.asks:
            updates.append(TardisL2Update(
                exchange=self.exchange,
                symbol=self.symbol,
                timestamp=self.timestamp,
                local_timestamp=self.local_timestamp,
                is_snapshot=True,
                side="ask",
                price=level.price,
                amount=level.amount,
            ))
        return updates

    @property
    def best_bid(self) -> Optional[TardisL2PriceLevel]:
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> Optional[TardisL2PriceLevel]:
        return self.asks[0] if self.asks else None


@dataclass
class LighterOrderBookMessage:
    """Lighter WebSocket 订单簿消息"""
    market_index: int
    timestamp: int
    asks: List[dict]
    bids: List[dict]

    @classmethod
    def from_ws_message(cls, data: dict) -> "LighterOrderBookMessage":
        channel = data.get("channel", "")
        market_index = 0
        if ":" in channel:
            try:
                market_index = int(channel.split(":")[1])
            except (ValueError, IndexError):
                pass
        order_book = data.get("order_book", {})
        return cls(
            market_index=market_index,
            timestamp=data.get("timestamp", 0),
            asks=order_book.get("asks", []),
            bids=order_book.get("bids", []),
        )
