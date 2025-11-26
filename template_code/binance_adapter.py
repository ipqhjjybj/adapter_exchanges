"""
币安(Binance)交易所适配器实现
"""

import pandas as pd
from typing import Dict, Any, Optional
from decimal import Decimal
import random
import sys
import time

sys.path.append(".")
from src.exchange_adapter import ExchangeAdapter
from src.crypto.bn_api import BinanceApi
from src.utils import adjust_to_price_filter, adjust_to_lot_size
from src.enums import OrderStatus
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
from src.utils import retry_wrapper
from src.log_kit import logger


class BinanceAdapter(ExchangeAdapter):
    """币安交易所适配器实现"""

    def __init__(self, client: BinanceApi):
        """
        初始化币安交易所适配器

        Args:
            client: 币安API客户端实例
            logger: 日志记录器实例
        """
        super().__init__(client, "binance")
        self.client: BinanceApi = client

    @retry_wrapper(retries=3, sleep_seconds=1, is_adapter_method=True)
    def get_orderbook_ticker(self, symbol: str) -> AdapterResponse[BookTicker]:
        """
        获取盘口价格

        Args:
            symbol: 交易对

        Returns:
            AdapterResponse: 包含错误信息的响应
        """
        try:
            data = self.client.get_book_ticker(symbol, symbol_type="um")
            book_ticker = BookTicker(
                symbol=data["symbol"],
                time=int(data["time"]),
                ask_price=float(data["askPrice"]),
                bid_price=float(data["bidPrice"]),
                ask_size=float(data["askQty"]),
                bid_size=float(data["bidQty"]),
            )
            return AdapterResponse(success=True, data=book_ticker, error_msg="")
        except Exception as e:
            logger.error(f"获取盘口价格失败: {e}")
            return AdapterResponse(success=False, data=None, error_msg=str(e))

    @retry_wrapper(retries=3, sleep_seconds=1, is_adapter_method=True)
    def get_depth(self, symbol: str, limit: int = 50) -> AdapterResponse[Depth]:
        """
        获取深度数据

        Args:
            symbol: 交易对
            limit: 深度档数

        Returns:
            AdapterResponse: 包含深度数据的响应
        """
        try:
            data = self.client.get_depth(symbol=symbol, symbol_type="um", limit=limit)
            depth = Depth(
                symbol=symbol,
                time=int(data["T"]),
                bids=data["bids"],
                asks=data["asks"],
            )
            return AdapterResponse(success=True, data=depth, error_msg="")
        except Exception as e:
            logger.error(f"获取深度数据失败: {e}", exc_info=True)
            return AdapterResponse(
                success=False,
                data=None,
                error_msg=str(e),
            )

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
        # 验证订单方向
        error_msg = self.validate_order_direction(side, position_side, is_open=True)
        if error_msg:
            return AdapterResponse(
                success=False,
                data=None,
                error_msg=error_msg,
            )

        try:
            data = self.client.place_um_market_order(
                symbol=symbol,
                side=side,
                position_side=position_side,
                quantity=quantity,
                out_price_rate=out_price_rate,
            )
            order_placement_result = OrderPlacementResult(
                symbol=data["symbol"],
                order_id=data["orderId"],
                order_qty=data["origQty"],
                order_price=data["price"],
                side=data["side"],
                position_side=data["positionSide"],
                api_resp=data,
            )
            return AdapterResponse(
                success=True, data=order_placement_result, error_msg=""
            )
        except Exception as e:
            logger.error(f"下市价开仓单失败: {e}")
            return AdapterResponse(
                success=False,
                data=None,
                error_msg=str(e),
            )

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
        # 验证订单方向
        error_msg = self.validate_order_direction(side, position_side, is_open=False)
        if error_msg:
            return AdapterResponse(
                success=False,
                data=None,
                error_msg=error_msg,
            )

        try:
            data = self.client.place_um_market_order(
                symbol=symbol,
                side=side,
                position_side=position_side,
                quantity=quantity,
                out_price_rate=out_price_rate,
            )
            order_placement_result = OrderPlacementResult(
                symbol=data["symbol"],
                order_id=data["orderId"],
                order_qty=data["origQty"],
                order_price=data["price"],
                side=data["side"],
                position_side=data["positionSide"],
                api_resp=data,
            )
            return AdapterResponse(
                success=True, data=order_placement_result, error_msg=""
            )
        except Exception as e:
            logger.error(f"下市价平仓单失败: {e}")
            return AdapterResponse(
                success=False,
                data=None,
                error_msg=str(e),
            )

    @retry_wrapper(retries=3, sleep_seconds=1, is_adapter_method=True)
    def query_position(self, symbol: str) -> AdapterResponse[SymbolPosition]:
        """
        查询持仓

        Args:
            symbol: 交易对

        Returns:
            AdapterResponse: 包含持仓信息的响应
        """
        try:
            position_df = self.client.get_um_position_risk(symbol=symbol)
            if not position_df.empty:
                position_df = position_df.loc[position_df["symbol"] == symbol]
                buy_cond = position_df["positionSide"] == "LONG"
                sell_cond = position_df["positionSide"] == "SHORT"
                buy_volume = abs(float(position_df.loc[buy_cond, "positionAmt"].sum()))
                sell_volume = abs(
                    float(position_df.loc[sell_cond, "positionAmt"].sum())
                )
                symbol_position = SymbolPosition(
                    symbol=symbol,
                    long_qty=buy_volume,
                    short_qty=sell_volume,
                    api_resp=position_df,
                )
                return AdapterResponse(success=True, data=symbol_position, error_msg="")
            else:
                symbol_position = SymbolPosition(
                    symbol=symbol,
                    long_qty=0,
                    short_qty=0,
                    api_resp=position_df,
                )
                return AdapterResponse(success=True, data=symbol_position, error_msg="")
        except Exception as e:
            logger.error(f"查询持仓失败: {e}", exc_info=True)
            return AdapterResponse(success=False, data=None, error_msg=str(e))

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
        try:
            data = self.client.query_um_order(symbol, order_id)
            order_info = OrderInfo(
                order_id=data["orderId"],
                timestamp=data["time"],
                symbol=symbol,
                status=OrderStatus.from_exchange_status(
                    data["status"], self.exchange_name
                ),
                side=data["side"],
                position_side=data["positionSide"],
                filled_qty=float(data["executedQty"]),
                avg_price=float(data["avgPrice"]),
                order_qty=float(data["origQty"]),
                order_price=float(data["price"]),
                api_resp=data,
            )
            return AdapterResponse(success=True, data=order_info, error_msg="")
        except Exception as e:
            logger.error(f"查询订单失败: {e}", exc_info=True)
            return AdapterResponse(success=False, data=None, error_msg=str(e))

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
        try:
            data = self.client.cancel_um_order(symbol, order_id)
            cancel_dict = {
                "order_id": order_id,
                "api_resp": data,
            }
            return AdapterResponse(success=True, data=cancel_dict, error_msg="")
        except Exception as e:
            logger.error(f"取消订单失败: {e}")
            return AdapterResponse(
                success=False,
                data=None,
                error_msg=str(e),
            )

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
        try:
            data = self.client.place_um_limit_order(
                symbol,
                side,
                position_side,
                quantity,
                price,
                params={"timeInForce": "GTX"},
            )
            order_placement_result = OrderPlacementResult(
                symbol=data["symbol"],
                order_id=data["orderId"],
                order_qty=quantity,
                order_price=price,
                side=side,
                position_side=position_side,
                api_resp=data,
            )
            return AdapterResponse(success=True, data=order_placement_result, error_msg="")
        except Exception as e:
            logger.error(f"下限价单失败: {e}")
            return AdapterResponse(
                success=False,
                data=None,
                error_msg=str(e),
            )

    @retry_wrapper(retries=3, sleep_seconds=1, is_adapter_method=True)
    def get_net_value(self) -> AdapterResponse[float]:
        """
        获取净价值

        Returns:
            AdapterResponse: 包含净价值的响应
        """
        try:
            data = self.client.get_um_balance()
            net_value = float(data['totalMarginBalance'])
            return AdapterResponse(success=True, data=net_value, error_msg="")
        except Exception as e:
            logger.error(f"获取净价值失败: {e}", exc_info=True)
            return AdapterResponse(
                success=False,
                data=None,
                error_msg=str(e),
            )

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
        price_filter = self.client.get_price_filter(symbol, "um")
        adjusted_price = adjust_to_price_filter(
            Decimal(str(price)),
            Decimal(price_filter["minPrice"]),
            Decimal(price_filter["maxPrice"]),
            Decimal(price_filter["tickSize"]),
            round_direction,
        )
        logger.info(
            f"按照交易所规则调整订单价格, 调整前价格为: {price}, 调整后价格为: {adjusted_price}"
        )
        return float(adjusted_price)

    def adjust_order_qty(self, symbol: str, quantity: float) -> float:
        """
        调整订单数量

        Args:
            symbol: 交易对
            quantity: 原始数量

        Returns:
            float: 调整后的数量
        """
        lot_size_filter = self.client.get_lot_size_filter(symbol, "um")
        adjusted_qty = adjust_to_lot_size(
            Decimal(str(quantity)),
            Decimal(lot_size_filter["minQty"]),
            Decimal(lot_size_filter["maxQty"]),
            Decimal(lot_size_filter["stepSize"]),
        )
        logger.info(
            f"按照交易所规则调整订单数量, 调整前数量为: {quantity}, 调整后数量为: {adjusted_qty}"
        )
        return float(adjusted_qty)

    def get_account_position_equity_ratio(self) -> AdapterResponse[float]:
        """
        获取账户持仓价值占比
        """
        try:
            data = self.client.get_um_account_info()
            # 计算持仓价值
            position_value = 0
            for position in data['positions']:
                position_value += abs(float(position['notional']))
            
            total_value = float(data['totalMarginBalance'])

            if total_value == 0:
                ratio = 9999
            else:
                ratio = position_value / total_value
            
            return AdapterResponse(success=True, data=ratio, error_msg="")
        except Exception as e:
            logger.error(f"获取账户持仓保证金率失败: {e}", exc_info=True)
            return AdapterResponse(success=False, data=None, error_msg=str(e))
    
    def get_contract_trade_unit(self, symbol: str) -> AdapterResponse[float]:
        """
        获取合约交易单位
        """
        if symbol=="PAXGUSDT":
            return AdapterResponse(success=True, data=1, error_msg="")
        else:
            return AdapterResponse(success=False, data=None, error_msg="不支持的交易对")
        
        
    def cancel_all_orders(self, symbol: str) -> AdapterResponse[bool]:
        """
        取消所有订单
        """
        try:
            data = self.client.cancel_all_um_orders(symbol)
            return AdapterResponse(success=True, data=data, error_msg="")
        except Exception as e:
            logger.error(f"取消所有订单失败: {e}", exc_info=True)
            return AdapterResponse(success=False, data=None, error_msg=str(e))

    def query_all_um_open_orders(self, symbol: str) -> AdapterResponse[list]:
        """
        查询所有未成交订单
        """
        try:
            data = self.client.query_all_um_open_orders(symbol)
            return AdapterResponse(success=True, data=data, error_msg="")
        except Exception as e:
            logger.error(f"查询所有未成交订单失败: {e}", exc_info=True)
            return AdapterResponse(success=False, data=None, error_msg=str(e))
        
    def set_symbol_leverage(self, symbol: str, leverage: int) -> AdapterResponse[bool]:
        """
        设置合约杠杆
        """
        try:
            data = self.client.set_leverage(symbol, 'um', leverage)
            return AdapterResponse(success=True, data=data, error_msg="")
        except Exception as e:
            logger.error(f"设置合约杠杆失败: {e}", exc_info=True)
            return AdapterResponse(success=False, data=None, error_msg=str(e))
        
    def get_um_account_info(self) -> AdapterResponse[UmAccountInfo]:
        """
        获取账户信息
        """
        try:
            data = self.client.get_um_account_info()
            initial_margin = float(data['totalInitialMargin'])
            maint_margin = float(data['totalMaintMargin'])
            margin_balance = float(data['totalMarginBalance'])
            timenow = int(time.time() * 1000)
            um_account_info = UmAccountInfo(
                timestamp=timenow,
                initial_margin=initial_margin,
                maint_margin=maint_margin,
                margin_balance=margin_balance,
                initial_margin_rate=margin_balance /initial_margin  if initial_margin > 0 else 999,
                maint_margin_rate=margin_balance /maint_margin if maint_margin > 0 else 999,
                api_resp=data,
            )
            return AdapterResponse(success=True, data=um_account_info, error_msg="")
        except Exception as e:
            logger.error(f"获取账户信息失败: {e}", exc_info=True)
            return AdapterResponse(success=False, data=None, error_msg=str(e))

if __name__ == "__main__":
    import sys
    import os
    from dotenv import load_dotenv

    sys.path.append(".")
    from src.exchange_factory import ExchangeFactory
    exchange_factory = ExchangeFactory()
    binance_client = exchange_factory.create_client("binance", "binance_6")
    binance_adapter = BinanceAdapter(binance_client)
    # print(binance_adapter.set_symbol_leverage("PAXGUSDT", 3))
    print(binance_adapter.get_net_value())
    # print(binance_adapter.get_account_position_equity_ratio())
    # print(binance_adapter.get_um_account_info())
    # binance_adapter.cancel_all_orders("PAXGUSDT")
    # open_orders = binance_adapter.query_all_um_open_orders("PAXGUSDT")
    # print(open_orders.data)
    # print(binance_adapter.get_orderbook_ticker("BTCUSDT"))
    # print(binance_adapter.get_depth("BTCUSDT"))
    # print(binance_adapter.client.get_price_filter("PAXGUSDT", "um"))
    # print(binance_adapter.client.get_lot_size_filter("PAXGUSDT", "um"))
    # print(binance_adapter.adjust_order_price("PAXGUSDT", 3033.1111, "UP"))
    # print(binance_adapter.adjust_order_qty("PAXGUSDT", 0.1111))
    # print(binance_adapter.query_position("PAXGUSDT"))
    # print(binance_adapter.get_net_value())
    # price = 3033.1111
    # qty = 0.1111
    # price = binance_adapter.adjust_order_price("PAXGUSDT", price, "UP")
    # qty = binance_adapter.adjust_order_qty("PAXGUSDT", qty)
    # order_resp = binance_adapter.place_limit_order("PAXGUSDT", "BUY", "LONG", qty, price)
    # print(order_resp.data)
    # order_info = binance_adapter.query_order("PAXGUSDT", order_resp.data.order_id)
    # print(order_info.data)
    # cancel_resp = binance_adapter.cancel_order("PAXGUSDT", order_resp.data.order_id)
    # print(cancel_resp.data)
    # order_info = binance_adapter.query_order("PAXGUSDT", order_resp.data.order_id)
    # print(order_info.data)
    