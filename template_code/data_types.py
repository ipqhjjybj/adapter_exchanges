from typing import Any, Optional, Dict, List, Tuple, TypeVar, Generic
from dataclasses import dataclass
from src.enums import OrderStatus

T = TypeVar("T")

@dataclass
class UmAccountInfo:
    """账户信息"""

    timestamp: int 
    initial_margin: float   # 保证金
    maint_margin: float # 维持保证金
    margin_balance: float # 保证金余额
    initial_margin_rate: float # 初始保证金率
    maint_margin_rate: float # 维持保证金率
    api_resp: dict # 原始响应
    
    # @property
    # def initial_margin_rate(self):
    #     return self.initial_margin / self.margin_balance if self.margin_balance > 0 else 999
    
    # @property
    # def maint_margin_rate(self):
    #     return self.maint_margin / self.margin_balance if self.margin_balance > 0 else 999
    

# ===adpter 中的数据结构===
@dataclass
class OrderInfo:
    """查询订单返回的订单信息"""

    timestamp: int  # 订单创建时间戳 13位
    order_id: str
    symbol: str
    order_qty: float  # 委托数量
    order_price: float  # 委托价格
    status: OrderStatus  # 订单状态
    filled_qty: float  # 已成交数量
    avg_price: float  # 成交均价
    side: str  # 方向
    position_side: str  # 持仓方向
    api_resp: dict  # 原始响应


@dataclass
class AdapterResponse(Generic[T]):
    """最简版的交易所API响应格式"""

    success: bool
    data: Optional[T] = None
    error_msg: str = ""

    @classmethod
    def success_response(cls, data: T) -> "AdapterResponse[T]":
        """快速创建成功响应"""
        return cls(success=True, data=data)

    @classmethod
    def error_response(cls, error_msg: str) -> "AdapterResponse":
        """快速创建错误响应"""
        return cls(success=False, error_msg=error_msg)


@dataclass
class BookTicker:
    """统一的盘口信息数据结构"""

    symbol: str
    time: int
    ask_price: float
    bid_price: float
    ask_size: float
    bid_size: float


@dataclass
class Depth:
    """统一的深度数据结构"""

    symbol: str
    time: str
    bids: Any  # 价格和数量的列表
    asks: Any  # 价格和数量的列表


@dataclass
class SymbolPosition:
    """统一的持仓信息数据结构"""

    symbol: str
    long_qty: float
    short_qty: float
    api_resp: dict  # 原始响应


@dataclass
class OrderPlacementResult:
    """下单响应数据结构"""

    symbol: str
    order_id: str
    order_qty: float
    order_price: float
    side: str
    position_side: str
    api_resp: dict  # 原始响应


@dataclass
class OrderCancelResult:
    """取消订单响应数据结构"""

    order_id: str
    api_resp: dict  # 原始响应


# ===策略中的数据结构===
@dataclass
class CryptoOrderbook:
    """加密货币订单簿"""

    timestamp: str
    symbol: str
    bid_price: float
    ask_price: float
    bid_volume: float
    ask_volume: float
    check_level: int


@dataclass
class BrokerOrderbook:
    """经纪商订单簿"""

    timestamp: str
    symbol: str
    bid_price: float
    ask_price: float


@dataclass
class SpreadRecord:
    """价差记录"""

    timestamp: int
    crypto_buy_broker_sell_price_diff: float
    crypto_sell_broker_buy_price_diff: float
    crypto_buy_broker_sell_price_diff_ratio: float
    crypto_sell_broker_buy_price_diff_ratio: float
    crypto_buy_broker_sell_volume: float
    crypto_sell_broker_buy_volume: float
    crypto_orderbook: CryptoOrderbook
    broker_orderbook: BrokerOrderbook


@dataclass
class OrderPositionRecord:
    """持仓记录"""

    timestamp: int
    crypto_symbol: str
    broker_symbol: str
    crypto_long_position: float
    crypto_short_position: float
    broker_long_position: float
    broker_short_position: float

    @property
    def crypto_net_position(self):
        return self.crypto_long_position - self.crypto_short_position

    @property
    def broker_net_position(self):
        return self.broker_long_position - self.broker_short_position


@dataclass
class StrategyPositionRecord:
    """策略持仓记录"""

    timestamp: int
    crypto_symbol: str
    broker_symbol: str
    crypto_long_position: float
    crypto_short_position: float
    broker_long_position: float
    broker_short_position: float

    @property
    def crypto_net_position(self):
        return self.crypto_long_position - self.crypto_short_position

    @property
    def broker_net_position(self):
        return self.broker_long_position - self.broker_short_position


@dataclass
class ExchangePositionRecord:
    """交易所持仓记录"""

    timestamp: int
    crypto_symbol: str
    broker_symbol: str
    crypto_long_position: float
    crypto_short_position: float
    broker_long_position: float
    broker_short_position: float

    @property
    def crypto_net_position(self):
        return self.crypto_long_position - self.crypto_short_position

    @property
    def broker_net_position(self):
        return self.broker_long_position - self.broker_short_position


@dataclass
class AccountInfo:
    """账户信息"""

    timestamp: int
    crypto_balance: float
    broker_balance: float
    crypto_exchange_rate: float = 1.0
    broker_exchange_rate: float = 0.762

    @property
    def get_crypto_usd_balance(self):
        return self.crypto_balance * self.crypto_exchange_rate

    @property
    def get_broker_usd_balance(self):
        return self.broker_balance * self.broker_exchange_rate

    @property
    def get_total_usd_balance(self):
        return self.get_crypto_usd_balance + self.get_broker_usd_balance


@dataclass
class MarketDepthData:
    """市场深度数据"""

    symbol: str
    timestamp: int
    bids: List[List[str]]  # [价格, 数量]
    asks: List[List[str]]  # [价格, 数量]

    @property
    def best_bid(self) -> Tuple[Optional[float], Optional[float]]:
        """获取最优买价和数量"""
        if self.bids:
            return float(self.bids[0][0]), float(self.bids[0][1])
        return None, None

    @property
    def best_ask(self) -> Tuple[Optional[float], Optional[float]]:
        """获取最优卖价和数量"""
        if self.asks:
            return float(self.asks[0][0]), float(self.asks[0][1])
        return None, None

    def get_bid_vwap(self, vwap_use_volume: float) -> Tuple[Optional[float], float]:
        """获取买方成交量加权平均价格(VWAP)"""
        bid_volume = 0
        bid_vwap = None
        bid_cum_amount = 0

        for bid in self.bids:
            price, volume = float(bid[0]), float(bid[1])
            bid_volume += volume
            bid_cum_amount += price * volume
            if bid_volume >= vwap_use_volume:
                bid_vwap = bid_cum_amount / bid_volume
                break

        if bid_vwap is None and bid_volume > 0:
            bid_vwap = bid_cum_amount / bid_volume

        return bid_vwap, bid_volume

    def get_ask_vwap(self, vwap_use_volume: float) -> Tuple[Optional[float], float]:
        """获取卖方成交量加权平均价格(VWAP)"""
        ask_volume = 0
        ask_vwap = None
        ask_cum_amount = 0

        for ask in self.asks:
            price, volume = float(ask[0]), float(ask[1])
            ask_volume += volume
            ask_cum_amount += price * volume
            if ask_volume >= vwap_use_volume:
                ask_vwap = ask_cum_amount / ask_volume
                break

        if ask_vwap is None and ask_volume > 0:
            ask_vwap = ask_cum_amount / ask_volume

        return ask_vwap, ask_volume

    def get_mid_price(self) -> Optional[float]:
        """获取中间价格"""
        bid, _ = self.best_bid
        ask, _ = self.best_ask

        if bid is not None and ask is not None:
            return (bid + ask) / 2
        return None


    def get_executable_price(self, target_volume=None, n_levels=100) -> Tuple[Optional[float], Optional[float]]:
        """计算基于目标交易量的可执行价格
        
        Args:
            target_volume: 目标交易量，如果为None则返回最优价格
            n_levels: 考虑的深度级别数
            
        Returns:
            (vwap_asks, vwap_bids): 卖出价格和买入价格的元组
        """
        bids = self.bids[:n_levels]
        asks = self.asks[:n_levels]
        
        if not bids or not asks:
            return None, None
            
        if target_volume is None:
            return float(bids[0][0]), float(asks[0][0])
            
        # 计算买入执行价
        total_volume = 0
        weighted_price = 0
        for ask in asks:
            price, qty = float(ask[0]), float(ask[1])
            if total_volume + qty >= target_volume:
                # 最后一档部分成交
                remaining = target_volume - total_volume
                weighted_price += price * remaining
                total_volume = target_volume
                break
            else:
                weighted_price += price * qty
                total_volume += qty
                
        vwap_asks = weighted_price / total_volume if total_volume > 0 else None
        
        # 计算卖出执行价
        total_volume = 0
        weighted_price = 0
        for bid in bids:
            price, qty = float(bid[0]), float(bid[1])
            if total_volume + qty >= target_volume:
                remaining = target_volume - total_volume
                weighted_price += price * remaining
                total_volume = target_volume
                break
            else:
                weighted_price += price * qty
                total_volume += qty
                
        vwap_bids = weighted_price / total_volume if total_volume > 0 else None
        
        return vwap_asks, vwap_bids