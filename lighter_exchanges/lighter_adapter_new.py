
import requests
import asyncio
import sys

# 修复 Windows 上 aiodns 需要 SelectorEventLoop 的问题
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import logging
from decimal import Decimal
from logging.handlers import RotatingFileHandler
import os
import time
from collections import defaultdict

import sys
sys.path.append(r".")

try:
    import lighter
except ImportError as e:
    logging.warning("未检测到lighter包，请确保已正确安装lighter模块。")
    # raise ImportError(
    #     "无法导入lighter包，请确保已正确安装lighter模块。"
    # ) from e

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


class LightAdapter(ExchangeAdapter):
    """
    lighter交易所适配器实现
    """
    
    def __init__(self, l1_address: str, apikey_private_key: str, api_key_index: int, proxy: str = None):
        self.base_url = "https://mainnet.zklighter.elliot.ai"

        self.l1_address = l1_address
        self.apikey_private_key = apikey_private_key
        self.api_key_index = api_key_index
        self.headers = {"accept": "application/json"}
        self.account_index = 1
        self.exchange_name = "lighter"
        if proxy == "local":
            self.proxy = None
        else:
            self.proxy = proxy
        # 创建token
        self.next_expiry_timestamp = 0
        self.auth_token = None

        # 更新交易所信息
        max_try_times = 5
        for i in range(max_try_times):
            try:
                market_index_dic, price_decimal_dic, size_decimal_dic, min_base_amount_dic = self.get_exchange_info()
                break
            except Exception as e:
                logger.error(f"get_exchange_info error: {e}")
                time.sleep(1)
                continue
        if i == max_try_times - 1:
            exit(1)
            raise Exception("get_exchange_info error")
        self.market_index_dic = market_index_dic
        self.price_decimal_dic = price_decimal_dic
        self.size_decimal_dic = size_decimal_dic
        self.min_base_amount_dic = min_base_amount_dic

        assert len(market_index_dic) > 0, "get_exchange_info error"
        assert len(price_decimal_dic) > 0, "get_exchange_info error"
        assert len(size_decimal_dic) > 0, "get_exchange_info error"
        
        # 获得账户信息
        # self.get_account_info()
        # assert self.account_index >= 0, "get_account_info error"
        self.account_index = self.get_account_index()
        assert self.account_index >= 0, "get_account_index error"
        logger.info(f"get_account_index success, account_index: {self.account_index}")

        # 跟踪已设置 margin mode 的 symbol，避免重复设置
        self._margin_mode_set = set()
        # 默认使用全仓模式
        self.default_margin_mode = lighter.SignerClient.CROSS_MARGIN_MODE  # 0: 全仓, 1: 逐仓
        self.default_leverage = 10  # 默认杠杆倍数
    
    @retry_wrapper(retries=5, sleep_seconds=1, is_adapter_method=False)
    def get_all_accounts(self):
        """获得所有的地址"""
        url = f"{self.base_url}/api/v1/account?by=l1_address&value={self.l1_address}"
        data = requests.get(url, headers=self.headers, timeout=60)
        if data.status_code == 200:
            js_data = data.json()
            if js_data["code"] == 200:
                return js_data["accounts"]
        else:
            raise Exception("get_all_accounts error")
    
    def get_account_index(self):
        """获得账户索引
        1. get 所有的 address;
        2. 针对当前的api 组建 client;
        3. 尝试下单;
        4. 下单成功;
        5. 查询订单;
        6. 双重保险, 如果都成功说明, 对应账户索引成功;
        """
        test_symbol = "SOLUSDT"
        test_side = "BUY"
        test_position_side = "LONG"
        test_quantity = 0.1
        test_price = 100
        
        all_accounts = self.get_all_accounts()
        if len(all_accounts) == 0:
            raise Exception("get_all_accounts error")
        for account in all_accounts:
            account_index = int(account["index"])
            res_data = self.place_test_order(test_symbol, test_side, test_position_side, test_quantity, test_price, account_index)
            if res_data.success:
                return account_index
            else:
                continue
        raise Exception("get_account_index failed")

    def set_margin_mode(
        self, symbol: str, margin_mode: int = None, leverage: int = None
    ) -> AdapterResponse[bool]:
        """
        设置保证金模式和杠杆

        Args:
            symbol: 交易对
            margin_mode: 保证金模式 (0: 全仓 CROSS_MARGIN_MODE, 1: 逐仓 ISOLATED_MARGIN_MODE)
            leverage: 杠杆倍数

        Returns:
            AdapterResponse: 包含设置结果的响应
        """
        if margin_mode is None:
            margin_mode = self.default_margin_mode
        if leverage is None:
            leverage = self.default_leverage

        # 如果该 symbol 已经设置过，跳过
        cache_key = f"{symbol}_{margin_mode}_{leverage}"
        if cache_key in self._margin_mode_set:
            logger.debug(f"margin mode already set for {symbol}, skipping")
            return AdapterResponse(success=True, data=True, error_msg="")

        try:
            market_id = self.market_index_dic[symbol]

            async def _set_margin_mode_with_new_client():
                new_client = lighter.SignerClient(
                    url=self.base_url,
                    api_private_keys={self.api_key_index: self.apikey_private_key},
                    account_index=self.account_index,
                )
                try:
                    result = await new_client.update_leverage(
                        market_index=market_id,
                        margin_mode=margin_mode,
                        leverage=leverage,
                    )
                    return result
                finally:
                    await new_client.close()

            x, tx_hash, err = asyncio.run(_set_margin_mode_with_new_client())

            if err is not None:
                logger.error(f"设置 margin mode 失败: {err}")
                return AdapterResponse(success=False, data=None, error_msg=str(err))

            # 设置成功，记录到缓存
            self._margin_mode_set.add(cache_key)
            logger.info(f"设置 margin mode 成功: symbol={symbol}, margin_mode={margin_mode}, leverage={leverage}")
            return AdapterResponse(success=True, data=True, error_msg="")

        except Exception as e:
            logger.error(f"设置 margin mode 失败: {e}")
            return AdapterResponse(success=False, data=None, error_msg=str(e))

    def place_test_order(
        self, symbol: str, side: str, position_side: str, quantity: float, price: float, account_index: int
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
        def is_retryable_error(err):
            try:
                # 针对"Too Many Requests"以及"couldn't get nonce"重试一次
                if err is None:
                    return False
                err_str = str(err)
                if (
                    "Too Many Requests" in err_str
                    or "couldn't get nonce" in err_str
                ):
                    return True
            except Exception:
                pass
            return False

        try:
            market_id = self.market_index_dic[symbol]
            price_decimal = self.price_decimal_dic[symbol]
            size_decimal = self.size_decimal_dic[symbol]

            if round(quantity, size_decimal) != quantity:
                return AdapterResponse(
                    success=False,
                    data=None,
                    error_msg=f"quantity must be {size_decimal} decimal places",
                )
            
            if round(price, price_decimal) != price:
                return AdapterResponse(
                    success=False,
                    data=None,
                    error_msg=f"price must be {price_decimal} decimal places",
                )
            
            send_price = int(price * (10 ** price_decimal))
            send_quantity = int(quantity * (10 ** size_decimal))

            if side == "BUY":
                is_ask = False
            else:
                is_ask = True
            
            position_side = "open"
            client_order_index = self.get_client_order_id()

            # 在新的事件循环中重新创建客户端并执行操作
            async def _create_limit_order_with_new_client():
                new_client = lighter.SignerClient(
                    url=self.base_url,
                    api_private_keys={self.api_key_index: self.apikey_private_key},
                    account_index=account_index,
                    # proxy=self.proxy,
                )
                try:
                    # 执行订单创建
                    result = await new_client.create_order(
                        market_index=market_id,
                        client_order_index=client_order_index,
                        base_amount=send_quantity,
                        price=send_price,
                        is_ask=is_ask,
                        order_type=lighter.SignerClient.ORDER_TYPE_LIMIT,
                        time_in_force=lighter.SignerClient.ORDER_TIME_IN_FORCE_IMMEDIATE_OR_CANCEL,
                        order_expiry=lighter.SignerClient.DEFAULT_IOC_EXPIRY,
                    )
                    return result
                finally:
                    # 确保关闭客户端
                    await new_client.close()
            
            # 执行下单，遇到特定错误（too many requests/nonce）仅重试一次
            for attempt in range(2):
                x = tx_hash = err = None
                try:
                    x, tx_hash, err = asyncio.run(_create_limit_order_with_new_client())
                except Exception as exc:
                    logger.error(f"异步创建限价单失败: {exc}")
                    err = exc

                if err is not None:
                    logger.error(f"下市价开仓单失败: {err}")
                    # 如果是重试后还出错，则直接返回，不再反复重试
                    if attempt == 0 and is_retryable_error(err):
                        logger.info("检测到限频/nonce失败, 重试一次下单...")
                        continue
                    else:
                        return AdapterResponse(
                            success=False,
                            data=None,
                            error_msg=str(err),
                        )
                else:
                    # 下单成功
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
            # 进入不到这里，保险起见给兜底
            return AdapterResponse(
                success=False,
                data=None,
                error_msg="Unknown error in place_limit_order",
            )
        except Exception as e:
            logger.error(f"下限价单失败: {e}")
            return AdapterResponse(
                success=False,
                data=None,
                error_msg=str(e),
            )
            
    def judge_auth_token_expired(self):
        """判断当前token是否过期，过期则重新创建"""
        t1 = time.time()
        if t1 > self.next_expiry_timestamp - 60 * 60:
            logger.info("auth token near expired, re-create auth token")
            
            # 在新的事件循环中重新创建客户端并创建token
            async def _create_token_with_new_client():
                t1 = time.time()
                # 重新创建客户端
                # new_client = lighter.SignerClient(
                #     url=self.base_url,
                #     private_key=self.apikey_private_key,
                #     account_index=self.account_index,
                #     api_key_index=self.api_key_index,
                # )
                new_client = lighter.SignerClient(
                    url=self.base_url,
                    api_private_keys={self.api_key_index: self.apikey_private_key},
                    account_index=self.account_index,
                    # proxy=self.proxy,
                    # api_key_index=self.api_key_index,
                )
                t2 = time.time()
                print(t2 - t1)
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
        pass
    #     """
    #     获得账户信息
    #     """
    #     url = f"{self.base_url}/api/v1/account?by=index&value={self.account_index}"
    #     data = requests.get(url, headers=self.headers, timeout=60)
    #     if data.status_code == 200:
    #         js_data = data.json()
    #         if js_data["code"] == 200:
    #             self.account_index = js_data["accounts"][0]["index"]
    #             logger.info(f"get_account_info success, account_index: {self.account_index}")
    #         else:
    #             raise Exception("get_account_info error")
    #     else:
    #         return None
    
    def get_client_order_id(self):
        """获得client_order_id"""
        return int(time.time() * 1000)
    
    # @retry_wrapper(retries=3, sleep_seconds=1, is_adapter_method=False)
    def get_exchange_info(self):
        """获得交易所信息"""
        url = f"{self.base_url}/api/v1/orderBookDetails"

        if self.proxy:
            proxies = {
                "http": self.proxy,
                "https": self.proxy,
            }
        else:
            proxies = None
        data = requests.get(url, headers=self.headers, timeout=60, proxies=proxies)
        if data.status_code == 200:
            js_data = data.json()
            if js_data["code"] == 200:
                order_book_details = js_data["order_book_details"]
                market_index_dic = {}
                price_decimal_dic = {}
                size_decimal_dic = {}
                min_base_amount_dic = {}

                for symbol_dic in order_book_details:
                    symbol = symbol_dic["symbol"] + "USDT"
                    market_id = int(symbol_dic["market_id"])
                    size_decimals = int(symbol_dic["size_decimals"])
                    price_decimals = int(symbol_dic["price_decimals"])
                    market_index_dic[symbol] = market_id
                    price_decimal_dic[symbol] = price_decimals
                    size_decimal_dic[symbol] = size_decimals
                    min_base_amount_dic[symbol] = float(symbol_dic["min_base_amount"])

                return market_index_dic, price_decimal_dic, size_decimal_dic, min_base_amount_dic
            else:
                raise Exception("get_exchange_info error")
        else:
            raise Exception("get_exchange_info error")
    

    @retry_wrapper(retries=5, sleep_seconds=1, is_adapter_method=True)
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
        if self.proxy:
            proxies = {
                "http": self.proxy,
                "https": self.proxy,
            }
        else:
            proxies = None
        data = requests.get(url, headers=self.headers, timeout=60, proxies=proxies)
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
    
    @retry_wrapper(retries=5, sleep_seconds=1, is_adapter_method=True)
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
        if self.proxy:
            proxies = {
                "http": self.proxy,
                "https": self.proxy,
            }
        else:
            proxies = None
        data = requests.get(url, headers=self.headers, timeout=60, proxies=proxies)
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

        quantity = self.adjust_order_qty(symbol, quantity)
        price = self.adjust_order_price(symbol, price)
        
        return self.place_limit_order(symbol, side, position_side, quantity, price)
    
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

        quantity = self.adjust_order_qty(symbol, quantity)
        price = self.adjust_order_price(symbol, price)
        
        return self.place_limit_order(symbol, side, position_side, quantity, price)
    
    
    @retry_wrapper(retries=5, sleep_seconds=1, is_adapter_method=True)
    def query_position(self, symbol: str) -> AdapterResponse[SymbolPosition]:
        """
        查询持仓

        Args:
            symbol: 交易对

        Returns:
            AdapterResponse: 包含持仓信息的响应
        """

        try:
            market_id = self.market_index_dic[symbol]

            url = f"{self.base_url}/api/v1/account?by=index&value={self.account_index}"
            if self.proxy:
                proxies = {
                    "http": self.proxy,
                    "https": self.proxy,
                }
            else:
                proxies = None
            data = requests.get(url, headers=self.headers, timeout=60, proxies=proxies)
            if data.status_code == 200:
                data = data.json()
                code = data.get("code")
                if code == 200:
                    long_qty = 0
                    short_qty = 0
                    positions = data["accounts"][0]["positions"]
                    for position_item in positions:
                        if position_item["market_id"] == market_id:
                            if position_item["sign"] == 1:
                                long_qty = float(position_item["position"])
                            else:
                                short_qty = float(position_item["position"])
                    symbol_position = SymbolPosition(
                        symbol=symbol,
                        long_qty=long_qty,
                        short_qty=short_qty,
                        api_resp=positions,
                    )
                    return AdapterResponse(success=True, data=symbol_position, error_msg="")
                else:
                    logger.error(f"查询持仓失败: {data.text}")
                    return AdapterResponse(success=False, data=None, error_msg=data.text)
            else:
                logger.error(f"查询持仓失败: {data.text}")
                return AdapterResponse(success=False, data=None, error_msg=data.text)
        except Exception as e:
            logger.error(f"查询持仓失败: {e}", exc_info=True)
            return AdapterResponse(success=False, data=None, error_msg=str(e))
    
    @retry_wrapper(retries=5, sleep_seconds=1, is_adapter_method=True)
    def query_order(self, symbol: str, order_id: str) -> AdapterResponse[OrderInfo]:
        """
        查询订单

        Args:
            symbol: 交易对
            order_id: 订单ID

        Returns:
            AdapterResponse: 包含订单信息的响应
        """
        self.judge_auth_token_expired()
        market_id = self.market_index_dic[symbol]
        try:
            # 1.先检查 open_orders 里面是否有这个订单
            url_activate_orders = f"{self.base_url}/api/v1/accountActiveOrders?account_index={self.account_index}&market_id={market_id}&auth={self.auth_token}"
            if self.proxy:
                proxies = {
                    "http": self.proxy,
                    "https": self.proxy,
                }
            else:
                proxies = None
            data = requests.get(url_activate_orders, headers=self.headers, timeout=60, proxies=proxies)
            if data.status_code == 200:
                data = data.json()
                code = data.get("code")
                if code == 200:
                    for order_item in data["orders"]:
                        if str(order_item["client_order_id"]) == str(order_id):
                            order_status = OrderStatus.NEW
                            avg_price = 0 
                            if float(order_item["filled_base_amount"]) > 0:
                                order_status = OrderStatus.PARTIALLY_FILLED
                                avg_price = float(order_item["filled_quote_amount"]) / float(order_item["filled_base_amount"])
                            if order_item["is_ask"]:
                                side = "SELL"

                            else:
                                side = "BUY"
                            position_side = "open"
                            
                            order_info = OrderInfo(
                                order_id=order_item["client_order_id"],
                                timestamp=order_item["timestamp"],
                                symbol=symbol,
                                status=order_status,
                                side=side,
                                position_side=position_side,
                                filled_qty=float(order_item["filled_base_amount"]),
                                avg_price=avg_price,
                                order_qty=float(order_item["initial_base_amount"]),
                                order_price=float(order_item["price"]),
                                api_resp=data,
                            )
                            return AdapterResponse(success=True, data=order_info, error_msg="")
                else:
                    logger.error(f"查询订单失败: {e}", exc_info=True)
                    return AdapterResponse(success=False, data=None, error_msg=str(e))
            else:
                logger.error(f"查询订单失败: {e}", exc_info=True)
                return AdapterResponse(success=False, data=None, error_msg=str(e))
            
            # 2.再检查 完成的订单里面是否有这个订单
            url_inactivate_orders = f"{self.base_url}/api/v1/accountInactiveOrders?auth={self.auth_token}&account_index={self.account_index}&market_id={market_id}&limit=100"
            if self.proxy:
                proxies = {
                    "http": self.proxy,
                    "https": self.proxy,
                }
            else:
                proxies = None
            data = requests.get(url_inactivate_orders, headers=self.headers, timeout=60, proxies=proxies)
            if data.status_code == 200:
                data = data.json()
                if data["code"] == 200:
                    for order_item in data["orders"]:
                        if str(order_item["client_order_id"]) == str(order_id):
                            avg_price = 0 
                            if float(order_item["filled_base_amount"]) > 0:
                                avg_price = float(order_item["filled_quote_amount"]) / float(order_item["filled_base_amount"])
                            order_status = OrderStatus.CANCELED
                            if order_item["status"] == "filled":
                                order_status = OrderStatus.FILLED
                            if order_item["is_ask"]:
                                side = "SELL"
                            else:
                                side = "BUY"
                            
                            position_side = "open"
                            order_info = OrderInfo(
                                order_id=order_item["client_order_id"],
                                timestamp=order_item["timestamp"],
                                symbol=symbol,
                                status=order_status,
                                side=side,
                                position_side=position_side,
                                filled_qty=float(order_item["filled_base_amount"]),
                                avg_price=avg_price,
                                order_qty=float(order_item["initial_base_amount"]),
                                order_price=float(order_item["price"]),
                                api_resp=data,
                            )
                            return AdapterResponse(success=True, data=order_info, error_msg="")
            else:
                logger.error(f"查询订单失败: {e}", exc_info=True)
                return AdapterResponse(success=False, data=None, error_msg=str(e))
            
            msg = f"Not found this order:{order_id}"
            logger.error(f"查询订单失败: {msg}", exc_info=True)
            return AdapterResponse(success=False, data=None, error_msg=msg)
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
        return self.cancel_all_orders(symbol)
    
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
        def is_retryable_error(err):
            try:
                # 针对"Too Many Requests"以及"couldn't get nonce"重试一次
                if err is None:
                    return False
                err_str = str(err)
                if (
                    "Too Many Requests" in err_str
                    or "couldn't get nonce" in err_str
                ):
                    return True
            except Exception:
                pass
            return False

        try:
            # 下单前先设置 margin mode
            # margin_result = self.set_margin_mode(symbol)
            # if not margin_result.success:
            #     logger.warning(f"设置 margin mode 失败，继续尝试下单: {margin_result.error_msg}")

            market_id = self.market_index_dic[symbol]
            price_decimal = self.price_decimal_dic[symbol]
            size_decimal = self.size_decimal_dic[symbol]

            if round(quantity, size_decimal) != quantity:
                return AdapterResponse(
                    success=False,
                    data=None,
                    error_msg=f"quantity must be {size_decimal} decimal places",
                )

            if round(price, price_decimal) != price:
                return AdapterResponse(
                    success=False,
                    data=None,
                    error_msg=f"price must be {price_decimal} decimal places",
                )

            send_price = int(price * (10 ** price_decimal))
            send_quantity = int(quantity * (10 ** size_decimal))

            if side == "BUY":
                is_ask = False
            else:
                is_ask = True

            position_side = "open"
            client_order_index = self.get_client_order_id()

            # 在新的事件循环中重新创建客户端并执行操作
            async def _create_limit_order_with_new_client():
                new_client = lighter.SignerClient(
                    url=self.base_url,
                    api_private_keys={self.api_key_index: self.apikey_private_key},
                    account_index=self.account_index,
                    #proxy=self.proxy,
                )
                try:
                    # 执行订单创建
                    result = await new_client.create_order(
                        market_index=market_id,
                        client_order_index=client_order_index,
                        base_amount=send_quantity,
                        price=send_price,
                        is_ask=is_ask,
                        order_type=lighter.SignerClient.ORDER_TYPE_LIMIT,
                        time_in_force=lighter.SignerClient.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME,
                    )
                    return result
                finally:
                    # 确保关闭客户端
                    await new_client.close()
            
            # 执行下单，遇到特定错误（too many requests/nonce）仅重试一次
            for attempt in range(2):
                x = tx_hash = err = None
                try:
                    x, tx_hash, err = asyncio.run(_create_limit_order_with_new_client())
                except Exception as exc:
                    logger.error(f"异步创建限价单失败: {exc}")
                    err = exc

                if err is not None:
                    logger.error(f"下市价开仓单失败: {err}")
                    # 如果是重试后还出错，则直接返回，不再反复重试
                    if attempt == 0 and is_retryable_error(err):
                        logger.info("检测到限频/nonce失败, 重试一次下单...")
                        continue
                    else:
                        return AdapterResponse(
                            success=False,
                            data=None,
                            error_msg=str(err),
                        )
                else:
                    # 下单成功
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
            # 进入不到这里，保险起见给兜底
            return AdapterResponse(
                success=False,
                data=None,
                error_msg="Unknown error in place_limit_order",
            )
        except Exception as e:
            logger.error(f"下限价单失败: {e}")
            return AdapterResponse(
                success=False,
                data=None,
                error_msg=str(e),
            )
    
    @retry_wrapper(retries=5, sleep_seconds=1, is_adapter_method=True)
    def get_net_value(self) -> AdapterResponse[float]:
        """
        获取净价值

        Returns:
            AdapterResponse: 包含净价值的响应
        """
        try:
            url = f"{self.base_url}/api/v1/account?by=index&value={self.account_index}"

            data = requests.get(url, headers=self.headers, timeout=60)
            if data.status_code == 200:
                data = data.json()
                code = data.get("code")
                if code == 200:
                    net_value = float(data["accounts"][0]["total_asset_value"])
                    return AdapterResponse(success=True, data=net_value, error_msg="")
                else:
                    logger.error(f"获取净价值失败: {data.text}")
                    return AdapterResponse(success=False, data=None, error_msg=data.text)
            else:
                logger.error(f"获取净价值失败: {data.text}")
                return AdapterResponse(success=False, data=None, error_msg=data.text)
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
        priceDecimal = self.price_decimal_dic[symbol]
        minPrice = round(0.1 ** priceDecimal, priceDecimal)
        maxPrice = 10 ** 9
        adjusted_price = adjust_to_price_filter(
            Decimal(str(price)),
            Decimal(str(minPrice)),
            Decimal(str(maxPrice)),
            Decimal(str(round(0.1 ** priceDecimal, priceDecimal))),
            round_direction,
        )
        adjusted_price = round(float(adjusted_price), priceDecimal)
        logger.info(
            f"按照交易所规则调整订单价格, 调整前价格为: {price}, 调整后价格为: {adjusted_price}"
        )
        return adjusted_price
        

    def adjust_order_qty(self, symbol: str, quantity: float) -> float:
        """
        调整订单数量

        Args:
            symbol: 交易对
            quantity: 原始数量

        Returns:
            float: 调整后的数量
        """
        minQty = self.min_base_amount_dic[symbol]
        sizeDecial = self.size_decimal_dic[symbol]
        maxQty = 10 ** 9
        adjusted_qty = adjust_to_lot_size(
            Decimal(str(quantity)),
            Decimal(str(minQty)),
            Decimal(str(maxQty)),
            Decimal(str(round(0.1 ** sizeDecial, sizeDecial))),
        )
        adjusted_qty = round(float(adjusted_qty), sizeDecial)
        logger.info(
            f"按照交易所规则调整订单数量, 调整前数量为: {quantity}, 调整后数量为: {adjusted_qty}"
        )
        return adjusted_qty
    
    def get_account_position_equity_ratio(self) -> AdapterResponse[float]:
        """
        获取账户持仓价值占比

        Returns:
            AdapterResponse: 包含净价值的响应
        """
        try:
            url = f"{self.base_url}/api/v1/account?by=index&value={self.account_index}"

            data = requests.get(url, headers=self.headers, timeout=60)
            if data.status_code == 200:
                data = data.json()
                code = data.get("code")
                if code == 200:
                    total_value = float(data["accounts"][0]["collateral"])
                    position_value = 0
                    for position in data["accounts"][0]["positions"]:
                        position_value += float(position["position_value"])
                    if total_value == 0:
                        ratio = 9999
                    else:
                        ratio = position_value / total_value
                    return AdapterResponse(success=True, data=ratio, error_msg="")
                else:
                    logger.error(f"获取账户持仓保证金率失败: {data.text}")
                    return AdapterResponse(success=False, data=None, error_msg=data.text)
            else:
                logger.error(f"获取账户持仓保证金率失败: {data.text}")
                return AdapterResponse(success=False, data=None, error_msg=data.text)
        except Exception as e:
            logger.error(f"获取账户持仓保证金率失败: {e}", exc_info=True)
            return AdapterResponse(
                success=False,
                data=None,
                error_msg=str(e),
            )
    
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
        try:
            # 在新的事件循环中重新创建客户端并执行操作
            async def _cancel_all_order_with_new_client():
                # 重新创建客户端
                new_client = lighter.SignerClient(
                    url=self.base_url,
                    api_private_keys={self.api_key_index: self.apikey_private_key},
                    account_index=self.account_index,
                    # api_key_index=self.api_key_index,
                    # proxy=self.proxy,
                )
                # new_client = lighter.SignerClient(
                #     url=self.base_url,
                #     private_key=self.apikey_private_key,
                #     account_index=self.account_index,
                #     api_key_index=self.api_key_index,
                # )
                
                try:
                    # 执行订单创建
                    result = await new_client.cancel_all_orders(time_in_force=new_client.CANCEL_ALL_TIF_IMMEDIATE, timestamp_ms=0)
                    return result
                finally:
                    # 确保关闭客户端
                    await new_client.close()
            
            # 使用新的事件循环
            x, tx_hash, err = asyncio.run(_cancel_all_order_with_new_client())

            if err is not None:
                logger.error(f"平仓所有订单失败: {err}")
                return AdapterResponse(
                    success=False,
                    data=None,
                    error_msg=str(err),
                )
            return AdapterResponse(success=True, data=None, error_msg="")
        except Exception as e:
            logger.error(f"取消所有订单失败: {e}", exc_info=True)
            return AdapterResponse(success=False, data=None, error_msg=str(e))
    
    def query_all_um_open_orders(self, symbol: str) -> AdapterResponse[list]:
        """
        查询所有未成交订单
        """
        self.judge_auth_token_expired()
        market_id = self.market_index_dic[symbol]
        try:
            # 1.先检查 open_orders 里面是否有这个订单
            url_activate_orders = f"{self.base_url}/api/v1/accountActiveOrders?account_index={self.account_index}&market_id={market_id}&auth={self.auth_token}"
            data = requests.get(url_activate_orders, headers=self.headers, timeout=60)
            if data.status_code == 200:
                data = data.json()
                code = data.get("code")
                if code == 200:
                    return AdapterResponse(success=True, data=data["orders"], error_msg="")
                else:
                    logger.error(f"查询所有未成交订单失败: {data.text}")
                    return AdapterResponse(success=False, data=None, error_msg=data.text)
            else:
                logger.error(f"查询所有未成交订单失败: {data.text}")
                return AdapterResponse(success=False, data=None, error_msg=data.text)
        except Exception as e:
            logger.error(f"查询所有未成交订单失败: {e}", exc_info=True)
            return AdapterResponse(success=False, data=None, error_msg=str(e))
    
    def set_symbol_leverage(self, symbol: str, leverage: int) -> AdapterResponse[bool]:
        """
        设置合约杠杆
        """
        msg = f"设置合约杠杆: {symbol}, {leverage}， 未找到api"
        logger.error(msg)
        return AdapterResponse(success=False, data=None, error_msg=msg)
    
    def get_um_account_info(self) -> AdapterResponse[UmAccountInfo]:
        """
        获取账户信息
        """
        try:
            url = f"{self.base_url}/api/v1/account?by=index&value={self.account_index}"
            if self.proxy:
                proxies = {
                    "http": self.proxy,
                    "https": self.proxy,
                }
            else:
                proxies = None
            data = requests.get(url, headers=self.headers, timeout=60, proxies=proxies)
            if data.status_code == 200:
                data = data.json()
                code = data.get("code")
                if code == 200:
                    account = data.get("accounts", [{}])[0]

                    # 1. 计算 margin_balance（保证金余额）
                    margin_balance = float(data["accounts"][0]["cross_asset_value"])

                    # 2. 计算 initial_margin（初始保证金）和 maint_margin（维持保证金）
                    initial_margin = 0.0
                    maint_margin = 0.0
                    positions = account.get("positions", [])

                    for pos in positions:
                        position = float(pos.get("position", 0.0))
                        if position == 0:  # 无持仓，跳过该仓位
                            continue
                        
                        # 若有持仓，需根据交易所规则计算该仓位的初始/维持保证金（示例逻辑，需根据实际规则调整）
                        # 示例：初始保证金 = 仓位价值 / 杠杆（初始保证金率倒数），维持保证金 = 初始保证金 * 维持保证金率
                        position_value = abs(float(pos.get("position_value", 0.0)))
                        initial_margin_fraction = float(pos.get("initial_margin_fraction", 0.0))  # 初始保证金率（百分比）
                        if initial_margin_fraction > 0:
                            pos_initial_margin = position_value / (100 / initial_margin_fraction)  # 仓位初始保证金
                            initial_margin += pos_initial_margin
                            
                            # 维持保证金率通常为初始保证金率的一定比例（示例取 50%，需按实际规则调整）
                            maint_margin_fraction = initial_margin_fraction * 0.6
                            pos_maint_margin = position_value / (100 / maint_margin_fraction)  # 仓位维持保证金
                            maint_margin += pos_maint_margin
                    
                    # 3. 计算保证金率
                    initial_margin_rate = margin_balance / initial_margin if initial_margin > 0 else 999
                    maint_margin_rate = margin_balance / maint_margin if maint_margin > 0 else 999

                    um_account_info = UmAccountInfo(
                        timestamp=int(time.time() * 1000),
                        initial_margin=initial_margin,
                        maint_margin=maint_margin,
                        margin_balance=margin_balance,
                        initial_margin_rate=margin_balance /initial_margin  if initial_margin > 0 else 999,
                        maint_margin_rate=margin_balance /maint_margin if maint_margin > 0 else 999,
                        api_resp=data,
                    )
                    return AdapterResponse(success=True, data=um_account_info, error_msg="")
                else:
                    logger.error(f"获取账户信息失败: {data.text}")
                    return AdapterResponse(success=False, data=None, error_msg=data.text)
            else:
                logger.error(f"获取账户信息失败: {data.text}")
                return AdapterResponse(success=False, data=None, error_msg=data.text)
            
        except Exception as e:
            logger.error(f"获取账户信息失败: {e}", exc_info=True)
            return AdapterResponse(success=False, data=None, error_msg=str(e))


if __name__ == "__main__":
    import sys
    import os 

    # sys.path.append(".")
    # from src.adapter_factory import AdapterFactory
    # exchange_factory = AdapterFactory()
    #lighter_adapter:LightAdapter  = exchange_factory.create_adapter(exchange_name="lighter", instance_name="lighter_3")
    lighter_adapter = LightAdapter(
        l1_address="0xc7213d067325EB01341d7AE7C966FBb1Cdb4C168",
        apikey_private_key="d3f263a3fde4def5006270ef5562e81564b4be91e474052d991544428f56ef5e49db3e5d6c7cf57b",
        api_key_index=2
    )

    lighter_adapter.judge_auth_token_expired()
    #print(lighter_adapter.get_exchange_info())

    print(lighter_adapter.auth_token)

    pass

    # print(lighter_adapter.get_orderbook_ticker("ETHUSDT"))
    # print(lighter_adapter.get_depth("ETHUSDT"))
    # data = lighter_adapter.place_market_open_order("EURUSDUSDT", "BUY", "LONG", 1)
    # order_id = data.data.order_id
    # print(order_id)
    # print(lighter_adapter.query_order("PAXGUSDT", order_id))
    # print(lighter_adapter.query_position("PAXGUSDT"))

    # print(lighter_adapter.get_net_value())
    # print(lighter_adapter.get_um_account_info())

    pass

