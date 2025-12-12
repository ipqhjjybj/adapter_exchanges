import time
import logging
import pandas as pd
from typing import Optional, Dict
from decimal import Decimal
import sys
sys.path.append(".")
from src.exchange_adapter import ExchangeAdapter
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
from src.enums import OrderStatus
from src.broker.mt5.mt_api import MT5API
from src.log_kit import logger


class Mt5Adapter(ExchangeAdapter):
    """MT5交易所适配器"""

    def __init__(self, client):
        """
        初始化IBKR交易所适配器

        Args:
            client: IBKR API客户端
        """
        super().__init__(client, "mt5")
        self.client: MT5API = client

        
    def get_orderbook_ticker(self, symbol: str) -> AdapterResponse[BookTicker]:
        """获取盘口价格"""
        try:
            data = self.client.get_book_price(symbol)
            book_ticker = BookTicker(
                symbol=data["symbol"],
                time=int(data["time"]),
                ask_price=data["ask_price"],
                bid_price=data["bid_price"],
                ask_size=data["ask_volume"],
                bid_size=data["bid_volume"],
            )
            return AdapterResponse(success=True, data=book_ticker, error_msg="")
        except Exception as e:
            logger.error(f"获取MT5盘口价格失败: {e}", exc_info=True)
            error_msg = str(e)
            return AdapterResponse(success=False, data=None, error_msg=error_msg)

    def get_depth(self, symbol: str, limit: int = 50) -> AdapterResponse[Depth]:
        """获取深度数据"""
        try:
            data = self.client.get_book_price(symbol)
            # 自己构造的, 因为broker没有深度, 或者不需要考虑其他档位
            depth = Depth(
                symbol=symbol,
                time=int(data["time"]),
                bids = [[data["bid_price"], 100]],
                asks = [[data["ask_price"], 100]],
            )
            return AdapterResponse(success=True, data=depth, error_msg="")
        except Exception as e:
            logger.error(f"获取MT5深度数据失败: {e}", exc_info=True)
            error_msg = str(e)
            return AdapterResponse(success=False, data=None, error_msg=error_msg)

    def place_limit_order(
        self, symbol: str, side: str, position_side: str, quantity: float, price: float
    ) -> AdapterResponse[OrderPlacementResult]:
        """下限价单"""
        raise NotImplementedError("MT5 不支持下限价单")

    def place_market_open_order(
        self, symbol: str, side: str, position_side: str, quantity: float, out_price_rate: float = 0.005
    ) -> AdapterResponse[OrderPlacementResult]:
        """下市价开仓单"""
        try:
            # 验证订单方向
            error = self.validate_order_direction(side, position_side, True)
            if error:
                return AdapterResponse(success=False, data=None, error_msg=error)

            data = self.client.place_market_order(
                symbol=symbol,
                side=side,
                position_side=position_side,
                volume=quantity,
            )
            
            order_result = OrderPlacementResult(
                order_id=data["deal"],
                symbol=symbol,
                order_price=None,
                order_qty=quantity,
                side=side,
                position_side=position_side,
                api_resp=data,
            )
            return AdapterResponse(success=True, data=order_result, error_msg="")
        except Exception as e:
            logger.error(f"下MT5市价开仓单失败: {e}", exc_info=True)
            error_msg = str(e)
            return AdapterResponse(success=False, data=None, error_msg=error_msg)

    def place_market_close_order(
        self, symbol: str, side: str, position_side: str, quantity: float, out_price_rate: float = 0.005
    ) -> AdapterResponse[OrderPlacementResult]:
        """下市价平仓单"""
        try:
            # 验证订单方向
            error = self.validate_order_direction(side, position_side, False)
            if error:
                return AdapterResponse(success=False, data=None, error_msg=error)
            
            data = self.client.place_market_order(
                symbol=symbol,
                side=side,
                position_side=position_side,
                volume=quantity,
            )
            order_result = OrderPlacementResult(
                order_id=data["trades"][0]["deal"],
                symbol=symbol,
                order_price=None,
                order_qty=quantity,
                side=side,
                position_side=position_side,
                api_resp=data,
            )
            return AdapterResponse(success=True, data=order_result, error_msg="")
        except Exception as e:
            logger.error(f"下IBKR市价平仓单失败: {e}", exc_info=True)
            error_msg = str(e)
            return AdapterResponse(success=False, data=None, error_msg=error_msg)

    def query_position(self, symbol: str) -> AdapterResponse[SymbolPosition]:
        """查询持仓"""
        try:
            data = self.client.get_positions(symbol=symbol)
            if data:
                import pandas as pd
                position_df = pd.DataFrame(data)
                position_df = position_df[position_df["symbol"] == symbol]
                long_cond = position_df["type"] == "BUY"
                short_cond = position_df["type"] == "SELL"
                
                position = SymbolPosition(
                    symbol=symbol,
                    long_qty=float(position_df.loc[long_cond, "volume"].sum()),
                    short_qty=float(position_df.loc[short_cond, "volume"].sum()),
                    api_resp=data,
                )
                
                return AdapterResponse(success=True, data=position, error_msg="")
            else:
                position = SymbolPosition(
                    symbol=symbol,
                    long_qty=0,
                    short_qty=0,
                    api_resp=data,
                )
                return AdapterResponse(success=True, data=position, error_msg="")
        except Exception as e:
            logger.error(f"查询MT5持仓失败: {e}", exc_info=True)
            error_msg = str(e)
            return AdapterResponse(success=False, data=None, error_msg=error_msg)

    def query_order(self, symbol: str, order_id: str) -> AdapterResponse[OrderInfo]:
        """查询订单"""
        try:
            data = self.client.get_deals_info(ticket=order_id)
            if isinstance(data, list):
                data = data[0]
            side, position_side = self.transfer_side_and_position_side_combo(data['type'], data['entry'], self.exchange_name, to_exchange=False)
            order_info = OrderInfo(
                timestamp=int(data['time']),  # 使用当前时间戳
                order_id=order_id,
                symbol=symbol,
                order_qty=float(data["volume"]),
                order_price=None,
                status=OrderStatus.FILLED,
                side=side,
                position_side=position_side,
                filled_qty=float(data["volume"]),
                avg_price=float(data["price"]),
                api_resp=data,
            )
            return AdapterResponse(success=True, data=order_info, error_msg="")
        except Exception as e:
            logger.error(f"查询MT5订单失败: {e}", exc_info=True)
            error_msg = str(e)
            return AdapterResponse(success=False, data=None, error_msg=error_msg)

    def cancel_order(
        self, symbol: str, order_id: str
    ) -> AdapterResponse[OrderCancelResult]:
        """取消订单"""
        raise NotImplementedError("MT5 不支持取消订单")

    def get_net_value(self) -> AdapterResponse[float]:
        """获取净价值"""
        try:
            result = self.client.get_account_info()
            net_value = float(result['equity'])
            return AdapterResponse(success=True, data=net_value, error_msg="")
        except Exception as e:
            logger.error(f"获取MT5净价值失败: {e}", exc_info=True)
            error_msg = str(e)
            return AdapterResponse(success=False, data=None, error_msg=error_msg)

    def adjust_order_price(
        self, symbol: str, price: float, round_direction: str = "UP"
    ) -> float:
        """调整订单价格"""
        # 在实际应用中，需要根据MT5的价格规则进行调整
        # 这里简化处理，四舍五入到2位小数
        raise NotImplementedError("MT5 不支持调整订单价格")

    def adjust_order_qty(self, symbol: str, quantity: float) -> float:
        """调整订单数量"""
        # 在实际应用中，需要根据MT5的数量规则进行调整
        # 这里简化处理，取整数
        raise NotImplementedError("MT5 不支持调整订单数量")
    
    def get_account_position_equity_ratio(self) -> AdapterResponse[float]:
        """获取账户持仓保证金率"""
        try:
            result = self.client.get_account_info()
            account_leverage = float(result['leverage'])
            margin = float(result['margin'])
            total_position_value = account_leverage * margin
            equity = float(result['equity'])
            if equity == 0:
                margin_rate = 999
            else:
                margin_rate = total_position_value / equity
            return AdapterResponse(success=True, data=margin_rate, error_msg="")
        except Exception as e:
            logger.error(f"获取MT5持仓保证金率失败: {e}", exc_info=True)
            error_msg = str(e)
            return AdapterResponse(success=False, data=None, error_msg=error_msg)

    def get_contract_trade_unit(self, symbol: str) -> AdapterResponse[float]:
        """获取合约交易单位"""
        if "XAUUSD".lower() in symbol.lower():
            return AdapterResponse(success=True, data=100, error_msg="")
        else:
            return AdapterResponse(success=False, data=None, error_msg="不支持的交易对")

    def cancel_all_orders(self, symbol: str) -> AdapterResponse[bool]:
        """取消所有订单"""
        pass

    def query_all_um_open_orders(self, symbol: str) -> AdapterResponse[list]:
        """查询所有未成交订单"""
        pass
    
    def set_symbol_leverage(self, symbol: str, leverage: int) -> AdapterResponse[bool]:
        """设置合约杠杆"""
        logger.warning("MT5 不支持设置合约杠杆")
        return AdapterResponse(success=True, data=None, error_msg="MT5 不支持设置合约杠杆")
    
    def get_um_account_info(self) -> AdapterResponse[UmAccountInfo]:
        """
        获取U本位账户信息
        """
        try:
            result = self.client.get_account_info()
            initial_margin = float(result['margin'])
            maint_margin_rate = float(result['margin_level'])
            margin_balance = float(result['equity'])
            timenow = int(time.time() * 1000)
            um_account_info = UmAccountInfo(
                timestamp=timenow,
                initial_margin=initial_margin,
                maint_margin=initial_margin,
                margin_balance=margin_balance,
                initial_margin_rate=margin_balance /initial_margin  if initial_margin > 0 else 999,
                maint_margin_rate=maint_margin_rate/100 if maint_margin_rate > 0 else 999,
                api_resp=result,
            )
            return AdapterResponse(success=True, data=um_account_info, error_msg="")
        except Exception as e:
            logger.error(f"获取MT5账户信息失败: {e}", exc_info=True)
            error_msg = str(e)
            return AdapterResponse(success=False, data=None, error_msg=error_msg)
    
if __name__ == "__main__":
    from src.exchange_factory import ExchangeFactory
    exchange_factory = ExchangeFactory()
    mt5_client = exchange_factory.create_client("mt5", instance_name="mt5_xm_2")
    mt5_adapter = Mt5Adapter(mt5_client)
    print(mt5_adapter.get_um_account_info())
    print(mt5_adapter.get_net_value())
    # time.sleep(5)
    print(mt5_adapter.get_orderbook_ticker("GOLDm#"))
    print(mt5_adapter.get_depth("GOLDm#"))
    print(mt5_adapter.query_position("GOLDm#"))
    # order = mt5_adapter.place_market_open_order("XAUUSDz", "BUY", "LONG", 0.01)

    # order = mt5_adapter.place_market_close_order("XAUUSDz", "BUY", "SHORT", 0.01)

    # print(mt5_adapter.query_order("XAUUSDz", order.data.order_id))
    # print(mt5_adapter.client.get_account_info())
    
