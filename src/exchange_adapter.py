import uuid
import time
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional, Dict, List, Tuple, TypeVar, Generic
from decimal import Decimal

from src.data_types import (
    AdapterResponse,
    BookTicker,
    Depth,
    SymbolPosition,
    OrderInfo,
    OrderPlacementResult,
    OrderCancelResult,
    UmAccountInfo,
)


class ExchangeAdapter(ABC):
    """交易所适配器基类，定义统一的接口"""

    def __init__(self, client, exchange_name: str):
        """
        初始化交易所适配器

        Args:
            client: 交易所API客户端
            exchange_name: 交易所名称
        """
        self.client = client
        self.exchange_name = exchange_name.lower()

    @abstractmethod
    def get_orderbook_ticker(self, symbol: str) -> AdapterResponse[BookTicker]:
        """获取盘口价格"""
        pass

    @abstractmethod
    def get_depth(self, symbol: str, limit: int = 50) -> AdapterResponse[Depth]:
        """获取深度数据"""
        pass

    @abstractmethod
    def place_limit_order(
        self, symbol: str, side: str, position_side: str, quantity: float, price: float
    ) -> AdapterResponse[OrderPlacementResult]:
        """下限价单"""
        pass

    @abstractmethod
    def place_market_open_order(
        self, symbol: str, side: str, position_side: str, quantity: float, out_price_rate: float = 0.002
    ) -> AdapterResponse[OrderPlacementResult]:
        """下市价开仓单"""
        pass

    @abstractmethod
    def place_market_close_order(
        self, symbol: str, side: str, position_side: str, quantity: float, out_price_rate: float = 0.002
    ) -> AdapterResponse[OrderPlacementResult]:
        """下市价平仓单"""
        pass

    @abstractmethod
    def query_position(self, symbol: str) -> AdapterResponse[SymbolPosition]:
        """查询持仓"""
        pass

    @abstractmethod
    def query_order(self, symbol: str, order_id: str) -> AdapterResponse[OrderInfo]:
        """查询订单"""
        pass

    @abstractmethod
    def cancel_order(
        self, symbol: str, order_id: str
    ) -> AdapterResponse[OrderCancelResult]:
        """取消订单"""
        pass

    @abstractmethod
    def get_net_value(self) -> AdapterResponse[float]:
        """获取净价值"""
        pass

    @abstractmethod
    def adjust_order_price(
        self, symbol: str, price: float, round_direction: str = "UP"
    ) -> float:
        """调整订单价格"""
        pass

    @abstractmethod
    def adjust_order_qty(self, symbol: str, quantity: float) -> float:
        """调整订单数量"""
        pass
    
    # @abstractmethod
    # def get_account_position_margin_rate(self) -> AdapterResponse[float]:
    #     """获取账户持仓保证金率"""
    #     pass

    @abstractmethod
    def get_contract_trade_unit(self, symbol: str) -> AdapterResponse[float]:
        """获取合约交易单位"""
        pass
    
    @abstractmethod
    def cancel_all_orders(self, symbol: str) -> AdapterResponse[bool]:
        """取消所有订单"""
        pass

    @abstractmethod
    def query_all_um_open_orders(self, symbol: str) -> AdapterResponse[list]:
        """查询所有未成交订单"""
        pass
    
    @abstractmethod
    def set_symbol_leverage(self, symbol: str, leverage: int) -> AdapterResponse[bool]:
        """设置合约杠杆"""
        pass
    
    @abstractmethod
    def get_um_account_info(self) -> AdapterResponse[UmAccountInfo]:
        """获取账户信息"""
        pass

    def validate_order_direction(
        self, side: str, position_side: str, is_open: bool
    ) -> Optional[str]:
        """
        验证订单方向是否有效

        Args:
            side: 方向("BUY"或"SELL")
            position_side: 持仓方向("LONG"或"SHORT")
            is_open: 是否是开仓单

        Returns:
            Optional[str]: 如果方向无效，返回错误信息；如果有效，返回None
        """
        if is_open:
            # 开仓单的验证
            if side == "BUY" and position_side == "SHORT":
                return "BUY和SHORT方向不匹配"
            if side == "SELL" and position_side == "LONG":
                return "SELL和LONG方向不匹配"
        else:
            # 平仓单的验证
            if side == "BUY" and position_side == "LONG":
                return "BUY和LONG方向不匹配"
            if side == "SELL" and position_side == "SHORT":
                return "SELL和SHORT方向不匹配"
        return None

    def transfer_side_and_position_side_combo(
        self, side: str, position_side: str, exchange_name: str, to_exchange=True, trade_side=None
    ):
        """转换交易方向和持仓方向的组合

        Args:
            side: 交易方向
            position_side: 持仓方向
            exchange_name: 交易所名称
            to_exchange: True表示从标准格式转为交易所格式，False表示从交易所格式转为标准格式
            trade_side: Bitget特有的交易方向(OPEN/CLOSE)，仅在处理Bitget时使用

        Returns:
            tuple: 对于大多数交易所，返回(转换后的交易方向, 转换后的持仓方向)
                对于Bitget，当to_exchange=True时，返回(转换后的交易方向, 转换后的持仓方向, 开平仓方向)
        """
        # 币安使用大写格式，直接返回
        if exchange_name == "binance":
            return side, position_side

        if exchange_name == "ibkr":
            return side, position_side

        # 其他交易所的映射
        mapping = {
            "okx": {
                # 标准格式 -> 交易所格式
                "to_exchange": {
                    # 开仓
                    ("BUY", "LONG"): ("buy", "long"),  # 买入开多
                    ("SELL", "SHORT"): ("sell", "short"),  # 卖出开空
                    # 平仓
                    ("SELL", "LONG"): ("sell", "long"),  # 卖出平多
                    ("BUY", "SHORT"): ("buy", "short"),  # 买入平空
                },
                # 交易所格式 -> 标准格式
                "from_exchange": {
                    # 开仓
                    ("buy", "long"): ("BUY", "LONG"),  # 买入开多
                    ("sell", "short"): ("SELL", "SHORT"),  # 卖出开空
                    # 平仓
                    ("sell", "long"): ("SELL", "LONG"),  # 卖出平多
                    ("buy", "short"): ("BUY", "SHORT"),  # 买入平空
                },
            },
            "bitget": {
                # 标准格式 -> 交易所格式
                "to_exchange": {
                    # 开仓
                    ("BUY", "LONG"): ("BUY", "LONG", "OPEN"),  # 买入开多
                    ("SELL", "SHORT"): ("SELL", "SHORT", "OPEN"),  # 卖出开空
                    # 平仓
                    ("SELL", "LONG"): ("SELL", "LONG", "CLOSE"),  # 卖出平多
                    ("BUY", "SHORT"): ("BUY", "SHORT", "CLOSE"),  # 买入平空
                },
                # 交易所格式 -> 标准格式
                "from_exchange": {
                    # 使用三元组作为键
                    ("buy", "long", "open"): ("BUY", "LONG"),  # 买入开多
                    ("sell", "short", "open"): ("SELL", "SHORT"),  # 卖出开空
                    ("buy", "long", "close"): ("SELL", "LONG"),  # 卖出平多
                    ("sell", "short", "close"): ("BUY", "SHORT"),  # 买入平空
                },
            },
            "mt5": {
                # 标准格式 -> 交易所格式
                "to_exchange": {
                    ("BUY", "LONG"): ("BUY", "LONG"),  # 买入开多
                    ("SELL", "SHORT"): ("SELL", "SHORT"),  # 卖出开空
                    ("BUY", "SHORT"): ("BUY", "SHORT"),  # 买入开空
                    ("SELL", "LONG"): ("SELL", "LONG"),  # 卖出开多
                },
                # 交易所格式 -> 标准格式
                "from_exchange": {
                    (0, 0): ("BUY", "LONG"),  # 买入开多
                    (1, 0): ("SELL", "SHORT"),  # 卖出开空
                    (1, 1): ("SELL", "LONG"),  # 卖出开多
                    (0, 1): ("BUY", "SHORT"),  # 买入开空
                },
        },
        }

        if exchange_name not in mapping:
            raise ValueError(f"不支持的交易所: {exchange_name}")

        direction = "to_exchange" if to_exchange else "from_exchange"
        
        # Bitget需要特殊处理
        if exchange_name == "bitget":
            if to_exchange:
                # 从标准转为交易所格式
                combo_key = (side, position_side)
                if combo_key not in mapping[exchange_name][direction]:
                    raise ValueError(f"不支持的交易方向和持仓方向组合: {combo_key}")
                return mapping[exchange_name][direction][combo_key]  # 返回三元组
            else:
                # 从交易所转为标准格式
                if not trade_side:
                    raise ValueError("转换Bitget格式时需要提供trade_side参数")
                combo_key = (side, position_side, trade_side)
                if combo_key not in mapping[exchange_name][direction]:
                    raise ValueError(f"不支持的交易方向、持仓方向和交易方向组合: {combo_key}")
                return mapping[exchange_name][direction][combo_key]  # 返回二元组
        else:
            # 其他交易所正常处理
            combo_key = (side, position_side)
            if combo_key not in mapping[exchange_name][direction]:
                raise ValueError(f"不支持的交易方向和持仓方向组合: {combo_key}")
            return mapping[exchange_name][direction][combo_key]