import lighter
import requests
import asyncio
import sys

import logging
from logging.handlers import RotatingFileHandler
import os
import time
from collections import defaultdict

sys.path.append("/Users/shenzhuoheng/quant_yz/git/adapter_exchanges")
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
from src.exchange_adapter import ExchangeAdapter


class LightAdapter(ExchangeAdapter):
    """
    lighter交易所适配器实现
    """
    
    def __init__(self, l1_address: str, apikey_private_key: str, api_key_index: int):
        self.base_url = "https://mainnet.zklighter.elliot.ai"

        self.l1_address = l1_address
        self.apikey_private_key = apikey_private_key
        self.api_key_index = api_key_index
        self.headers = {"accept": "application/json"}
        self.account_index = -1

        # 获得账户信息
        self.get_account_info()
        assert self.account_index >= 0, "get_account_info error"

        # 创建token
        self.next_expiry_timestamp = 0
        self.auth_token = None

        # 更新交易所信息
        market_index_dic, price_decimal_dic, size_decimal_dic = self.get_exchange_info()
        self.market_index_dic = market_index_dic
        self.price_decimal_dic = price_decimal_dic
        self.size_decimal_dic = size_decimal_dic

        assert len(market_index_dic) > 0, "get_exchange_info error"
        assert len(price_decimal_dic) > 0, "get_exchange_info error"
        assert len(size_decimal_dic) > 0, "get_exchange_info error"
    
    def judge_auth_token_expired(self):
        """判断当前token是否过期，过期则重新创建"""
        t1 = time.time()
        if t1 > self.next_expiry_timestamp - 60 * 60:
            logger.info("auth token near expired, re-create auth token")
            
            # 在新的事件循环中重新创建客户端并创建token
            async def _create_token_with_new_client():
                # 重新创建客户端
                new_client = lighter.SignerClient(
                    url=self.base_url,
                    private_key=self.apikey_private_key,
                    account_index=self.account_index,
                    api_key_index=self.api_key_index,
                )
                
                try:
                    # 创建授权令牌
                    current_time = int(time.time())
                    interval_seconds = 6 * 3600
                    start_timestamp = (current_time // interval_seconds) * interval_seconds
                    expiry_hours = 8
                    auth_token, error = new_client.create_auth_token_with_expiry(
                        expiry_hours * 3600, timestamp=start_timestamp
                    )
                    if error is not None:
                        raise Exception(f"Failed to create auth token: {error}")
                    
                    next_expiry_timestamp = start_timestamp + expiry_hours * 3600
                    return auth_token, next_expiry_timestamp
                finally:
                    # 确保关闭客户端
                    await new_client.close()
            
            # 使用新的事件循环
            self.auth_token, self.next_expiry_timestamp = asyncio.run(_create_token_with_new_client())
            logger.info(f"new token created:{self.auth_token}")

    def get_account_info(self):
        """
        获得账户信息
        """
        url = f"{self.base_url}/api/v1/account?by=l1_address&value={self.l1_address}"
        data = requests.get(url, headers=self.headers, timeout=60)
        if data.status_code == 200:
            js_data = data.json()
            if js_data["code"] == 200:
                self.account_index = js_data["accounts"][0]["index"]
                logger.info(f"get_account_info success, account_index: {self.account_index}")
            else:
                raise Exception("get_account_info error")
        else:
            return None
    
    def get_client_order_id(self):
        """获得client_order_id"""
        return int(time.time() * 1000)
    

    def get_exchange_info(self):
        """获得交易所信息"""
        url = f"{self.base_url}/api/v1/orderBookDetails"
        data = requests.get(url, headers=self.headers, timeout=60)
        if data.status_code == 200:
            js_data = data.json()
            if js_data["code"] == 200:
                order_book_details = js_data["order_book_details"]
                market_index_dic = {}
                price_decimal_dic = {}
                size_decimal_dic = {}
                for symbol_dic in order_book_details:
                    symbol = symbol_dic["symbol"] + "USDT"
                    market_id = int(symbol_dic["market_id"])
                    size_decimals = int(symbol_dic["size_decimals"])
                    price_decimals = int(symbol_dic["price_decimals"])
                    market_index_dic[symbol] = market_id
                    price_decimal_dic[symbol] = price_decimals
                    size_decimal_dic[symbol] = size_decimals
                return market_index_dic, price_decimal_dic, size_decimal_dic
            else:
                raise Exception("get_exchange_info error")
        else:
            return {}, {}, {}
    

    @retry_wrapper(retries=3, sleep_seconds=1, is_adapter_method=True)
    def get_orderbook_ticker(self, symbol: str) -> AdapterResponse[BookTicker]:
        """
        获取盘口价格

        Args:
            symbol: 交易对 如ETHUSDT

        Returns:
            AdapterResponse: 包含错误信息的响应
        """
        market_id = self.market_index_dic[symbol]
        url = f"{self.base_url}/api/v1/orderBookOrders?market_id={market_id}&&limit=100"
        data = requests.get(url, headers=self.headers, timeout=60)
        if data.status_code == 200:
            js_data = data.json()
            if js_data["code"] == 200:
                bids_dic = defaultdict(float)
                asks_dic = defaultdict(float)
                for bid_item in js_data["bids"]:
                    bids_dic[float(bid_item['price'])] += float(bid_item['remaining_base_amount'])
                for ask_item in js_data["asks"]:
                    asks_dic[float(ask_item['price'])] += float(ask_item['remaining_base_amount'])
                
                bids_arr = sorted(bids_dic.items(), key=lambda x: x[0], reverse=True)
                asks_arr = sorted(asks_dic.items(), key=lambda x: x[0])
                if len(bids_arr) == 0 or len(asks_arr) == 0:
                    return AdapterResponse(success=False, data=None, error_msg="bids or asks is empty")
                else:
                    return AdapterResponse(
                        success=True,
                        data=BookTicker(
                            symbol=symbol,
                            time=int(time.time() * 1000),
                            bid_price=bids_arr[0][0],
                            ask_price=asks_arr[0][0],
                            ask_size=asks_arr[0][1],
                            bid_size=bids_arr[0][1],
                        ),
                        error_msg=None,
                    )
        else:
            e = data.text
            logger.error(f"获取盘口价格失败: {e}")
            return AdapterResponse(success=False, data=None, error_msg=str(e))
    
    @retry_wrapper(retries=3, sleep_seconds=1, is_adapter_method=True)
    def get_depth(self, symbol: str, limit: int=100) -> AdapterResponse[BookTicker]:
        """
        获取盘口价格

        Args:
            symbol: 交易对 如ETHUSDT

        Returns:
            AdapterResponse: 包含错误信息的响应
        """
        market_id = self.market_index_dic[symbol]
        url = f"{self.base_url}/api/v1/orderBookOrders?market_id={market_id}&&limit={limit}"
        data = requests.get(url, headers=self.headers, timeout=60)
        if data.status_code == 200:
            js_data = data.json()
            if js_data["code"] == 200:
                bids_dic = defaultdict(float)
                asks_dic = defaultdict(float)
                for bid_item in js_data["bids"]:
                    bids_dic[float(bid_item['price'])] += float(bid_item['remaining_base_amount'])
                for ask_item in js_data["asks"]:
                    asks_dic[float(ask_item['price'])] += float(ask_item['remaining_base_amount'])
                
                bids_arr = sorted(bids_dic.items(), key=lambda x: x[0], reverse=True)
                asks_arr = sorted(asks_dic.items(), key=lambda x: x[0])
                if len(bids_arr) == 0 or len(asks_arr) == 0:
                    return AdapterResponse(success=False, data=None, error_msg="bids or asks is empty")
                else:
                    depth = Depth(
                        symbol=symbol,
                        time=int(time.time() * 1000),
                        bids=bids_arr,
                        asks=asks_arr,
                    )
                    return AdapterResponse(success=True, data=depth, error_msg="")
        else:
            e = data.text
            logger.error(f"获取盘口价格失败: {e}")
            return AdapterResponse(success=False, data=None, error_msg=str(e))
    
    def place_market_open_order(
        self, symbol: str, side: str, position_side: str, quantity: float, out_price_rate: float = 0.005,
        worst_price_rate: float = 0.1
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
        
        bookticker_response = self.get_orderbook_ticker(symbol)
        if not bookticker_response.success:
            return AdapterResponse(
                success=False,
                data=None,
                error_msg=bookticker_response.error_msg,
            )
        ask_price = bookticker_response.data.ask_price
        bid_price = bookticker_response.data.bid_price

        if side == "BUY":
            price = ask_price * (1 + out_price_rate)
        else:
            price = bid_price * (1 - out_price_rate)

        market_id = self.market_index_dic[symbol]
        price_decimal = self.price_decimal_dic[symbol]
        size_decimal = self.size_decimal_dic[symbol]
        
        if round(quantity, size_decimal) != quantity:
            return AdapterResponse(
                success=False,
                data=None,
                error_msg=f"quantity must be {size_decimal} decimal places",
            )
        
        send_quantity = int(quantity * (10 ** size_decimal))
        ask_worst_price_send = int(ask_price * (1 + worst_price_rate) * (10 ** price_decimal))
        bid_worst_price_send = int(bid_price * (1 - worst_price_rate) * (10 ** price_decimal))

        if side == "BUY":
            worst_price = bid_worst_price_send
            is_ask = False
            price = ask_price
        else:
            worst_price = ask_worst_price_send
            is_ask = True
            price = bid_price

        try:
            client_order_index = self.get_client_order_id()

            # 在新的事件循环中重新创建客户端并执行操作
            async def _create_market_order_with_new_client():
                # 重新创建客户端
                new_client = lighter.SignerClient(
                    url=self.base_url,
                    private_key=self.apikey_private_key,
                    account_index=self.account_index,
                    api_key_index=self.api_key_index,
                )
                
                try:
                    # 执行订单创建
                    result = await new_client.create_market_order(
                        market_index=market_id,
                        client_order_index=client_order_index,
                        base_amount=send_quantity,
                        avg_execution_price=worst_price,
                        is_ask=is_ask,
                    )
                    return result
                finally:
                    # 确保关闭客户端
                    await new_client.close()
            
            # 使用新的事件循环
            x, tx_hash, err = asyncio.run(_create_market_order_with_new_client())

            if err is not None:
                logger.error(f"下市价开仓单失败: {err}")
                return AdapterResponse(
                    success=False,
                    data=None,
                    error_msg=str(err),
                )
            
            order_placement_result = OrderPlacementResult(
                symbol=symbol,
                order_id=client_order_index,
                order_qty=quantity,
                order_price=price,
                side=side,
                position_side=position_side,
                api_resp={"tx_hash": tx_hash, "result": x},
            )
            return AdapterResponse(
                success=True, data=order_placement_result, error_msg=""
            )

        except asyncio.TimeoutError:
            logger.error("下市价开仓单超时")
            return AdapterResponse(
                success=False,
                data=None,
                error_msg="Order creation timed out after 30 seconds",
            )
        except Exception as e:
            logger.error(f"下市价开仓单失败: {e}")
            return AdapterResponse(
                success=False,
                data=None,
                error_msg=str(e),
            )


if __name__ == "__main__":
    import sys
    import os 
    
    lighter_adapter = LightAdapter(
        l1_address="0xA2C9f815302d32757688eB0D6466466105682F54",
        apikey_private_key="9d0a9b5f993c919fd8c2b63598be0753f05dc00ae6fbc2081a180a991bfd360822bcf95322e6e50a",
        api_key_index=2
    )

    lighter_adapter.judge_auth_token_expired()
    print(lighter_adapter.auth_token)

    #print(lighter_adapter.get_orderbook_ticker("ETHUSDT"))
    #print(lighter_adapter.get_depth("ETHUSDT"))
    #print(lighter_adapter.place_market_open_order("ETHUSDT", "BUY", "LONG", 0.1))
    #print(lighter_adapter.get_account_info()


    #lighter_adapter.close()

    #lighter_adapter.get_account_info()

