
import requests
import asyncio
import sys
import time

import logging
from decimal import Decimal
from logging.handlers import RotatingFileHandler
import os
import time
from collections import defaultdict

sys.path.append("/Users/shenzhuoheng/quant_yz/git/adapter_exchanges")
sys.path.append("/home/ec2-user/test_lighter_dex/adapter_exchanges")
import lighter
#import lighter_my as lighter
from src.data_types import (
    BookTicker,
    Depth,
    OrderInfo,
    OrderPlacementResult,
    AdapterResponse,
    SymbolPosition,
    OrderCancelResult,
    UmAccountInfo,
)
from src.enums import OrderStatus
from src.utils import retry_wrapper, adjust_to_price_filter, adjust_to_lot_size
from src.log_kit import logger
from src.exchange_adapter import ExchangeAdapter


class ParadexAdapter(ExchangeAdapter):
    """
    lighter交易所适配器实现
    该类实现了与Lighter交易所的交互功能，包括订单管理、持仓查询、账户信息获取等
    """
    
    def __init__(self):
        # 初始化基础URL
        self.base_url = "https://api.prod.paradex.trade/v1"
    
    def get_account_info(self):
        """
        获得账户信息
        """
        pass
    
    def get_client_order_id(self):
        """获得client_order_id"""
        return int(time.time() * 1000)
    

    @retry_wrapper(retries=3, sleep_seconds=1, is_adapter_method=True)
    def get_orderbook_ticker(self, symbol: str) -> AdapterResponse[BookTicker]:
        """
        获取盘口价格

        Args:
            symbol: 交易对 如ETHUSDT

        Returns:
            AdapterResponse: 包含错误信息的响应
        """
        pass
    
    @retry_wrapper(retries=3, sleep_seconds=1, is_adapter_method=True)
    def get_depth(self, symbol: str, limit: int=100) -> AdapterResponse[BookTicker]:
        """
        获取盘口价格

        Args:
            symbol: 交易对 如ETHUSDT

        Returns:
            AdapterResponse: 包含错误信息的响应
        """
        pass
    
    def place_market_open_order(
        self, symbol: str, side: str, position_side: str, quantity: float, out_price_rate: float = 0.005
    ) -> AdapterResponse[OrderPlacementResult]:
        """
        下市价开仓单

        Args:
            symbol: 交易对
            side: 方向("BUY"或"SELL")
            position_side: 持仓方向("LONG"或"SHORT")
            quantity: 数量

        Returns:
            AdapterResponse: 包含订单信息的响应
        """
        pass
    
    def place_market_close_order(
        self, symbol: str, side: str, position_side: str, quantity: float, out_price_rate: float = 0.005
    ) -> AdapterResponse[OrderPlacementResult]:
        """
        下市价平仓单

        Args:
            symbol: 交易对
            side: 方向("BUY"或"SELL")
            position_side: 持仓方向("LONG"或"SHORT")
            quantity: 数量

        Returns:
            AdapterResponse: 包含订单信息的响应
        """
        pass
    
    
    @retry_wrapper(retries=3, sleep_seconds=1, is_adapter_method=True)
    def query_position(self, symbol: str) -> AdapterResponse[SymbolPosition]:
        """
        查询持仓

        Args:
            symbol: 交易对

        Returns:
            AdapterResponse: 包含持仓信息的响应
        """

        pass
    
    @retry_wrapper(retries=3, sleep_seconds=1, is_adapter_method=True)
    def query_order(self, symbol: str, order_id: str) -> AdapterResponse[OrderInfo]:
        """
        查询订单

        Args:
            symbol: 交易对
            order_id: 订单ID

        Returns:
            AdapterResponse: 包含订单信息的响应
        """
        pass
    
    def cancel_order(
        self, symbol: str, order_id: str
    ) -> AdapterResponse[OrderCancelResult]:
        """
        取消订单

        Args:
            symbol: 交易对
            order_id: 订单ID

        Returns:
            AdapterResponse: 包含取消结果的响应
        """
        pass
    
    def place_limit_order(
        self, symbol: str, side: str, position_side: str, quantity: float, price: float
    ) -> AdapterResponse[OrderPlacementResult]:
        """
        下限价单

        Args:
            symbol: 交易对
            side: 方向("BUY"或"SELL")
            position_side: 持仓方向("LONG"或"SHORT")
            quantity: 数量
            price: 价格

        Returns:
            AdapterResponse: 包含订单信息的响应
        """
        pass
    
    @retry_wrapper(retries=3, sleep_seconds=1, is_adapter_method=True)
    def get_net_value(self) -> AdapterResponse[float]:
        """
        获取净价值

        Returns:
            AdapterResponse: 包含净价值的响应
        """
        pass
    
    def adjust_order_price(
        self, symbol: str, price: float, round_direction: str = "UP"
    ) -> float:
        """
        调整订单价格

        Args:
            symbol: 交易对
            price: 原始价格
            round_direction: 舍入方向，'UP'向上取整，'DOWN'向下取整(默认)

        Returns:
            float: 调整后的价格
        """
        pass
        

    def adjust_order_qty(self, symbol: str, quantity: float) -> float:
        """
        调整订单数量

        Args:
            symbol: 交易对
            quantity: 原始数量

        Returns:
            float: 调整后的数量
        """
        pass
    
    def get_account_position_equity_ratio(self) -> AdapterResponse[float]:
        """
        获取账户持仓价值占比

        Returns:
            AdapterResponse: 包含净价值的响应
        """
        pass
    
    def get_contract_trade_unit(self, symbol: str) -> AdapterResponse[float]:
        """
        获取合约交易单位
        """
        size_decimal = self.size_decimal_dic[symbol]
        return AdapterResponse(success=True, data=0.1 ** size_decimal, error_msg="")


    def cancel_all_orders(self, symbol: str) -> AdapterResponse[bool]:
        """
        取消所有订单
        """
        pass
    
    def query_all_um_open_orders(self, symbol: str) -> AdapterResponse[list]:
        """
        查询所有未成交订单
        """
        pass
    
    def set_symbol_leverage(self, symbol: str, leverage: int) -> AdapterResponse[bool]:
        """
        设置合约杠杆
        """
        pass
    
    def get_um_account_info(self) -> AdapterResponse[UmAccountInfo]:
        """
        获取账户信息
        """
        pass


if __name__ == "__main__":
    import sys
    import os 
    

    pass

