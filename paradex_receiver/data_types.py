"""
Paradex WebSocket data types and Tardis format definitions
"""

from dataclasses import dataclass, field
from typing import List, Optional, Literal, Dict, Any


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

    def to_book_snapshot_15_row(self) -> str:
        """转换为 book_snapshot_15 格式的 CSV 行"""
        row = [self.exchange, self.symbol, str(self.timestamp), str(self.local_timestamp)]
        
        # 填充15档asks价格和数量
        for i in range(15):
            if i < len(self.asks):
                row.extend([self.asks[i].price, self.asks[i].amount])
            else:
                row.extend(["", ""])
        
        # 填充15档bids价格和数量
        for i in range(15):
            if i < len(self.bids):
                row.extend([self.bids[i].price, self.bids[i].amount])
            else:
                row.extend(["", ""])
        
        return ",".join(row)


@dataclass
class ParadexOrderBookMessage:
    """Paradex WebSocket 订单簿消息"""
    market: str
    timestamp: int
    inserts: List[Dict[str, Any]]
    updates: List[Dict[str, Any]]
    deletes: List[Dict[str, Any]]
    seq_no: int
    last_updated_at: int

    @classmethod
    def from_ws_message(cls, data: dict) -> "ParadexOrderBookMessage":
        """从 WebSocket 消息创建 ParadexOrderBookMessage"""
        params = data.get("params", {})
        order_book_data = params.get("data", {})
        
        return cls(
            market=order_book_data.get("market", ""),
            timestamp=order_book_data.get("last_updated_at", 0),
            inserts=order_book_data.get("inserts", []),
            updates=order_book_data.get("updates", []),
            deletes=order_book_data.get("deletes", []),
            seq_no=order_book_data.get("seq_no", 0),
            last_updated_at=order_book_data.get("last_updated_at", 0)
        )

    def get_sorted_bids(self) -> List[TardisL2PriceLevel]:
        """获取排序后的买单（价格从高到低）"""
        bids = []
        for insert in self.inserts:
            if insert.get("side") == "BUY":
                bids.append(TardisL2PriceLevel(
                    price=insert.get("price", "0"),
                    amount=insert.get("size", "0")
                ))
        
        # 按价格从高到低排序
        bids.sort(key=lambda x: float(x.price), reverse=True)
        return bids[:15]  # 取前15档

    def get_sorted_asks(self) -> List[TardisL2PriceLevel]:
        """获取排序后的卖单（价格从低到高）"""
        asks = []
        for insert in self.inserts:
            if insert.get("side") == "SELL":
                asks.append(TardisL2PriceLevel(
                    price=insert.get("price", "0"),
                    amount=insert.get("size", "0")
                ))
        
        # 按价格从低到高排序
        asks.sort(key=lambda x: float(x.price))
        return asks[:15]  # 取前15档


@dataclass
class TardisTrade:
    """
    Tardis 交易记录
    
    CSV 格式: exchange,symbol,timestamp,local_timestamp,id,side,price,amount
    """
    exchange: str
    symbol: str
    timestamp: int  # 微秒
    local_timestamp: int  # 微秒
    id: str
    side: Literal["buy", "sell"]
    price: str
    amount: str

    def to_csv_row(self) -> str:
        return f"{self.exchange},{self.symbol},{self.timestamp},{self.local_timestamp},{self.id},{self.side},{self.price},{self.amount}"

    def to_dict(self) -> dict:
        return {
            "exchange": self.exchange,
            "symbol": self.symbol,
            "timestamp": self.timestamp,
            "local_timestamp": self.local_timestamp,
            "id": self.id,
            "side": self.side,
            "price": self.price,
            "amount": self.amount,
        }


@dataclass
class ParadexTradeMessage:
    """Paradex WebSocket 交易消息"""
    id: str
    market: str
    side: str
    size: str
    price: str
    created_at: int
    trade_type: str

    @classmethod
    def from_ws_message(cls, data: dict) -> "ParadexTradeMessage":
        """从 WebSocket 消息创建 ParadexTradeMessage"""
        params = data.get("params", {})
        trade_data = params.get("data", {})
        
        return cls(
            id=trade_data.get("id", ""),
            market=trade_data.get("market", ""),
            side=trade_data.get("side", ""),
            size=trade_data.get("size", "0"),
            price=trade_data.get("price", "0"),
            created_at=trade_data.get("created_at", 0),
            trade_type=trade_data.get("trade_type", "")
        )

    def to_tardis_trade(self, local_timestamp: int) -> TardisTrade:
        """转换为 Tardis 交易格式"""
        # 转换时间戳从毫秒到微秒
        timestamp_us = self.created_at * 1000
        
        # 转换 side: BUY -> buy, SELL -> sell
        side = "buy" if self.side == "BUY" else "sell"
        
        return TardisTrade(
            exchange="paradex",
            symbol=self.market,
            timestamp=timestamp_us,
            local_timestamp=local_timestamp,
            id=self.id,
            side=side,
            price=self.price,
            amount=self.size
        )