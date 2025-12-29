
import requests
import asyncio
import sys
import functools
from typing import Optional, Tuple
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
    from lighter import nonce_manager
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


def retry_wrapper_async(retries=3, sleep_seconds=1.0, is_adapter_method=False):
    """
    最简单的重试装饰器

    Args:
        retries: 最大重试次数
        sleep_seconds: 重试间隔(秒)
        is_adapter_method: 是否为返回AdapterResponse的方法
    """

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            func_name = func.__name__

            for attempt in range(retries):
                try:
                    # 调用原始函数
                    result = await func(*args, **kwargs)

                    # 处理AdapterResponse
                    if is_adapter_method and hasattr(result, "success") and not result.success:
                        if attempt < retries - 1:
                            logger.warning(f"{func_name} 返回失败，准备重试 ({attempt+1}/{retries})")
                            time.sleep(sleep_seconds)
                            continue

                    # 正常结果直接返回
                    return result

                except Exception as e:
                    # 如果是最后一次尝试，记录错误并重新抛出
                    if attempt >= retries - 1:
                        logger.error(f"{func_name} 重试{retries}次后失败: {e}", exc_info=True)
                        raise

                    # 记录并等待重试
                    logger.warning(
                        f"{func_name} 失败，准备重试 ({attempt+1}/{retries}): {e}",
                        exc_info=True,
                    )
                    await asyncio.sleep(sleep_seconds)

            return None  # 这行代码实际上不会执行到

        return wrapper

    return decorator


class LightAdapter(ExchangeAdapter):
    """
    lighter交易所适配器async实现
    [TODO] 目前只能使用主账户，后续增加子账户支持
    """

    def __init__(
        self,
        l1_address: str,
        apikey_private_key: str,
        api_key_index: int,
        account_index: int = -1,
        proxy: str = None,
    ):
        self.base_url = "https://mainnet.zklighter.elliot.ai"
        self.proxy = proxy
        self.configuration = lighter.Configuration(host=self.base_url)
        if proxy:
            self.configuration.proxy = proxy
            self.configuration.verify_ssl = False
        self.client = lighter.ApiClient(self.configuration)
        self.signer_client = None

        self.l1_address = l1_address
        self.apikey_private_key = apikey_private_key
        if self.apikey_private_key in ["", None]:
            logger.warning(f"lighter adapter apikey_private_key is empty, public data only")
            self.apikey_private_key = "1" * 80
        self.api_key_index = api_key_index
        self.headers = {"accept": "application/json"}
        self.account_index = account_index

        # 创建token
        self.next_expiry_timestamp = 0
        self.auth_token = None

        self.market_index_dic = None
        self.price_decimal_dic = None
        self.size_decimal_dic = None
        self.min_base_amount_dic = None

    def get_client_order_id(self):
        """获得client_order_id"""
        return int(time.time() * 1000)

    def adjust_order_price(self, symbol: str, price: float, round_direction: str = "UP") -> float:
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
        minPrice = round(0.1**priceDecimal, priceDecimal)
        maxPrice = 10**9
        adjusted_price = adjust_to_price_filter(
            Decimal(str(price)),
            Decimal(str(minPrice)),
            Decimal(str(maxPrice)),
            Decimal(str(round(0.1**priceDecimal, priceDecimal))),
            round_direction,
        )
        adjusted_price = round(float(adjusted_price), priceDecimal)
        logger.info(f"按照交易所规则调整订单价格, 调整前价格为: {price}, 调整后价格为: {adjusted_price}")
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
        maxQty = 10**9
        adjusted_qty = adjust_to_lot_size(
            Decimal(str(quantity)),
            Decimal(str(minQty)),
            Decimal(str(maxQty)),
            Decimal(str(round(0.1**sizeDecial, sizeDecial))),
        )
        adjusted_qty = round(float(adjusted_qty), sizeDecial)
        logger.info(f"按照交易所规则调整订单数量, 调整前数量为: {quantity}, 调整后数量为: {adjusted_qty}")
        return adjusted_qty

    def get_contract_trade_unit(self, symbol: str) -> AdapterResponse[float]:
        """
        获取合约交易单位
        """
        size_decimal = self.size_decimal_dic[symbol]
        return AdapterResponse(success=True, data=0.1**size_decimal, error_msg="")

    async def connect(self):
        if self.l1_address:
            await self.get_account_info_async()
            assert self.account_index >= 0, "get_account_info error"
        else:
            logger.warning("l1_address is empty, skip get_account_info")
        market_index_dic, price_decimal_dic, size_decimal_dic, min_base_amount_dic = await self.get_exchange_info_async()
        self.market_index_dic = market_index_dic
        self.price_decimal_dic = price_decimal_dic
        self.size_decimal_dic = size_decimal_dic
        self.min_base_amount_dic = min_base_amount_dic
        assert len(market_index_dic) > 0, "get_exchange_info error"
        assert len(price_decimal_dic) > 0, "get_exchange_info error"
        assert len(size_decimal_dic) > 0, "get_exchange_info error"
        #self.signer_client = lighter.SignerClient(url=self.base_url, private_key=self.apikey_private_key, account_index=self.account_index, api_key_index=self.api_key_index, nonce_management_type=nonce_manager.NonceManagerType.API)
        self.signer_client = lighter.SignerClient(url=self.base_url, api_private_keys={self.api_key_index:self.apikey_private_key}, account_index=self.account_index, nonce_management_type=nonce_manager.NonceManagerType.API)
        self.signer_client.api_client = self.client
        self.signer_client.order_api = lighter.OrderApi(self.client)
        self.signer_client.tx_api = lighter.TransactionApi(self.client)

    async def disconnect(self):
        pass

    async def detect_account_index_async(self, test_symbol: str = "SOLUSDT", interval: float = 2.0) -> Tuple[Optional[int], str]:
        if not self.apikey_private_key:
            return None, "apikey_private_key is empty"
        all_accounts = await self.get_account_info_async()
        if all_accounts.get("code") != 200:
            return None, f"get_account_info_async error: {all_accounts}"
        accounts = all_accounts.get("accounts", [])
        for account in accounts:
            _adapter = LightAdapter(
                l1_address=self.l1_address,
                apikey_private_key=self.apikey_private_key,
                proxy=self.proxy,
                api_key_index=self.api_key_index,
                account_index=account["account_index"],
            )
            await _adapter.connect()
            try:
                orders = await _adapter.raw_query_active_orders_async(_adapter.market_index_dic[test_symbol])
                if orders.code == 200:
                    logger.info(f"Successfully queried active orders for account index {_adapter.account_index}")
                    await _adapter.disconnect()
                    return _adapter.account_index, ""
            except Exception as e:
                logger.error(f"Error querying active orders for account index {_adapter.account_index}: {e}", exc_info=True)
            logger.info(f"Wait {interval} seconds before next account...")
            await asyncio.sleep(interval) # 避免请求过快
            await _adapter.disconnect()
        else:
            return None, "No account found"

    async def judge_auth_token_expired_async(self, force: bool = False, threshold_seconds: int = 3600):
        """判断当前token是否过期，过期则重新创建"""
        _t1 = time.time()
        if _t1 > self.next_expiry_timestamp - threshold_seconds or force:
            logger.info("auth token near expired, re-create auth token")
            # 创建授权令牌
            start_timestamp = int(time.time())
            expiry_hours = 6
            next_expiry_timestamp = start_timestamp + expiry_hours * 3600
            logger.info(f"create new auth token, start_timestamp:{start_timestamp}, expiry_hours:{expiry_hours}")
            auth_token, error = self.signer_client.create_auth_token_with_expiry(
                deadline=next_expiry_timestamp
                # expiry_hours * 3600,
                # timestamp=start_timestamp
            )
            if error is not None:
                raise Exception(f"Failed to create auth token: {error}")

            self.auth_token, self.next_expiry_timestamp = (
                auth_token,
                next_expiry_timestamp,
            )
            logger.info(f"new token created:{self.auth_token}, expiry at {self.next_expiry_timestamp}")

    @retry_wrapper_async(retries=2, sleep_seconds=1, is_adapter_method=False)
    async def get_account_info_async(self) -> dict:
        api_response = await self.raw_query_account_async(by="l1_address", value=self.l1_address)
        if api_response.code == 200:
            if self.account_index < 0:
                self.account_index = api_response.accounts[0].index
                logger.warning(f"get_account_info success, set default main account_index: {self.account_index}")
            else:
                logger.info(f"get_account_info success, account_index unchanged: {self.account_index}")
        return api_response.to_dict()

    @retry_wrapper_async(retries=2, sleep_seconds=1, is_adapter_method=False)
    async def get_exchange_info_async(self):
        """获得交易所信息"""
        api_instance = lighter.OrderApi(self.client)
        api_response = await api_instance.order_book_details()
        if api_response.code == 200:
            order_book_details = api_response.to_dict()["order_book_details"]
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

            return (
                market_index_dic,
                price_decimal_dic,
                size_decimal_dic,
                min_base_amount_dic,
            )
        else:
            logger.error(f"get_exchange_info error: {api_response.message}")
            return {}, {}, {}, {}

    @retry_wrapper_async(retries=3, sleep_seconds=1, is_adapter_method=True)
    async def get_orderbook_ticker_async(self, symbol: str, limit: int = 100) -> AdapterResponse[BookTicker]:
        """
        获取盘口价格

        Args:
            symbol: 交易对 如ETHUSDT

        Returns:
            AdapterResponse: 包含错误信息的响应
        """
        market_id = self.market_index_dic[symbol]
        api_instance = lighter.OrderApi(self.client)
        api_response = await api_instance.order_book_orders(market_id, limit)
        if api_response.code == 200:
            js_data = api_response.to_dict()
            bids_dic = defaultdict(float)
            asks_dic = defaultdict(float)
            for bid_item in js_data["bids"]:
                bids_dic[float(bid_item["price"])] += float(bid_item["remaining_base_amount"])
            for ask_item in js_data["asks"]:
                asks_dic[float(ask_item["price"])] += float(ask_item["remaining_base_amount"])

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
            logger.error(f"获取盘口价格失败: {api_response.message}")
            return AdapterResponse(success=False, data=None, error_msg=str(api_response.message))

    @retry_wrapper_async(retries=3, sleep_seconds=1, is_adapter_method=True)
    async def get_depth_async(self, symbol: str, limit: int = 100) -> AdapterResponse[Depth]:
        """
        获取盘口价格

        Args:
            symbol: 交易对 如ETHUSDT

        Returns:
            AdapterResponse: 包含错误信息的响应
        """
        market_id = self.market_index_dic[symbol]
        api_instance = lighter.OrderApi(self.client)
        api_response = await api_instance.order_book_orders(market_id, limit)
        if api_response.code == 200:
            js_data = api_response.to_dict()
            bids_dic = defaultdict(float)
            asks_dic = defaultdict(float)
            for bid_item in js_data["bids"]:
                bids_dic[float(bid_item["price"])] += float(bid_item["remaining_base_amount"])
            for ask_item in js_data["asks"]:
                asks_dic[float(ask_item["price"])] += float(ask_item["remaining_base_amount"])

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
            logger.error(f"获取盘口价格失败: {api_response.message}")
            return AdapterResponse(success=False, data=None, error_msg=str(api_response.message))

    async def place_market_open_order_async(self, symbol: str, side: str, position_side: str, quantity: float, out_price_rate: float = 0.005, is_open: bool = True, retry_times: int = 10) -> AdapterResponse[OrderPlacementResult]:
        """
        下市价开仓单

        Args:
            symbol: 交易对
            side: 方向("BUY"或"SELL")
            position_side: 持仓方向("LONG"或"SHORT")
            quantity: 数量
            out_price_rate: 市价单挂单价格偏离盘口价格的比例，默认0.5%
            retry_times: 重试次数，默认10次
        Returns:
            AdapterResponse: 包含订单信息的响应
        """

        # 验证订单方向
        error_msg = self.validate_order_direction(side, position_side, is_open=is_open)
        if error_msg:
            return AdapterResponse(
                success=False,
                data=None,
                error_msg=error_msg,
            )

        bookticker_response = await self.get_orderbook_ticker_async(symbol)
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
        print(
            {
                "symbol": symbol,
                "side": side,
                "position_side": position_side,
                "quantity": quantity,
                "price": price,
            }
        )

        retry_flag = "invalid nonce".lower()
        for i in range(retry_times):
            result = await self.place_limit_order_async(symbol, side, position_side, quantity, price)
            if result.success:
                return result
            if not result.success and retry_flag not in result.error_msg.lower():
                return result
            if i == retry_times - 1:
                return result
            logger.info(f"place_market_open_order_async retrying {i+1}/{retry_times}...")
            await asyncio.sleep(1)

        return result

    async def place_market_close_order_async(self, symbol: str, side: str, position_side: str, quantity: float, out_price_rate: float = 0.005, retry_times: int = 10) -> AdapterResponse[OrderPlacementResult]:
        """
        下市价平仓单

        Args:
            symbol: 交易对
            side: 方向("BUY"或"SELL")
            position_side: 持仓方向("LONG"或"SHORT")
            quantity: 数量
            out_price_rate: 市价单挂单价格偏离盘口价格的比例，默认0.5%
            retry_times: 重试次数，默认10次

        Returns:
            AdapterResponse: 包含订单信息的响应
        """
        return await self.place_market_open_order_async(symbol, side, position_side, quantity, out_price_rate, is_open=False, retry_times=retry_times)

    async def raw_query_account_async(self, by, value):
        api_instance = lighter.AccountApi(self.client)
        api_response = await api_instance.account(by, str(value))
        return api_response

    async def raw_query_active_orders_async(self, market_id: int):
        await self.judge_auth_token_expired_async()
        api_instance = lighter.OrderApi(self.client)
        api_response = await api_instance.account_active_orders(self.account_index, market_id, authorization=self.auth_token)
        return api_response

    async def raw_query_inactive_orders_async(self, limit: int = 100, cursor: str = None):
        await self.judge_auth_token_expired_async()
        api_instance = lighter.OrderApi(self.client)
        api_response = await api_instance.account_inactive_orders(self.account_index, limit, authorization=self.auth_token, cursor=cursor)
        return api_response

    @retry_wrapper_async(retries=5, sleep_seconds=1, is_adapter_method=True)
    async def query_position_async(self, symbol: str) -> AdapterResponse[SymbolPosition]:
        """
        查询持仓

        Args:
            symbol: 交易对

        Returns:
            AdapterResponse: 包含持仓信息的响应
        """

        try:
            market_id = self.market_index_dic[symbol]
            api_response = await self.raw_query_account_async(by="index", value=self.account_index)
            if api_response.code == 200:
                data = api_response.to_dict()
                long_qty = 0
                short_qty = 0
                accounts = [account for account in data["accounts"] if account["account_index"] == self.account_index]
                if len(accounts) != 1:
                    return AdapterResponse(success=False, data=accounts, error_msg=f"Invalid account_index {self.account_index}: multiple or no accounts found: {accounts}")
                positions = accounts[0]["positions"]
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
                logger.error(f"查询持仓失败: {api_response.message}")
                return AdapterResponse(success=False, data=None, error_msg=str(api_response.message))
        except Exception as e:
            logger.error(f"查询持仓失败: {e}", exc_info=True)
            return AdapterResponse(success=False, data=None, error_msg=str(e))

    @retry_wrapper_async(retries=10, sleep_seconds=3, is_adapter_method=True)
    async def query_order_async(self, symbol: str, order_id: str, limit: int = 100) -> AdapterResponse[OrderInfo]:
        """
        查询订单

        Args:
            symbol: 交易对
            order_id: 订单ID

        Returns:
            AdapterResponse: 包含订单信息的响应
        """
        await self.judge_auth_token_expired_async(force=True)
        market_id = self.market_index_dic[symbol]
        try:
            # 1.先检查 open_orders 里面是否有这个订单
            active_order_response = await self.raw_query_active_orders_async(market_id)

            # api_instance = lighter.OrderApi(self.client)
            # active_order_response = await api_instance.account_active_orders(self.account_index, market_id, authorization=self.auth_token)
            if active_order_response.code == 200:
                data = active_order_response.to_dict()
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
                            api_resp=order_item,
                        )
                        return AdapterResponse(success=True, data=order_info, error_msg="")
            else:
                logger.error(f"查询订单失败: {active_order_response.message}", exc_info=True)
                return AdapterResponse(
                    success=False,
                    data=None,
                    error_msg=str(active_order_response.message),
                )

            # 2.再检查 完成的订单里面是否有这个订单
            # inactive_order_response = await api_instance.account_inactive_orders(self.account_index, limit, authorization=self.auth_token)
            inactive_order_response = await self.raw_query_inactive_orders_async(limit)
            if inactive_order_response.code == 200:
                data = inactive_order_response.to_dict()
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
                            api_resp=order_item,
                        )
                        return AdapterResponse(success=True, data=order_info, error_msg="")
            else:
                logger.error(f"查询订单失败: {inactive_order_response.message}", exc_info=True)
                return AdapterResponse(
                    success=False,
                    data=None,
                    error_msg=str(inactive_order_response.message),
                )

            msg = f"Not found this order:{order_id}"
            logger.error(f"查询订单失败: {msg}", exc_info=True)
            return AdapterResponse(success=False, data=None, error_msg=msg)
        except Exception as e:
            logger.error(f"查询订单失败: {e}", exc_info=True)
            return AdapterResponse(success=False, data=None, error_msg=str(e))

    async def cancel_order_async(self, symbol: str, order_id: str) -> AdapterResponse[OrderCancelResult]:
        """
        取消订单

        Args:
            symbol: 交易对
            order_id: 订单ID

        Returns:
            AdapterResponse: 包含取消结果的响应
        """
        # return await self.cancel_all_orders_async(symbol)
        try:
            market_id = self.market_index_dic[symbol]
            try:
                # 执行订单创建
                result = await self.signer_client.cancel_order(
                    market_index=market_id,
                    order_index=int(order_id),
                )
            except Exception as e:
                logger.error(f"取消{symbol}订单{order_id}失败: {e}")
                return AdapterResponse(
                    success=False,
                    data=None,
                    error_msg=str(e),
                )

            # 使用新的事件循环
            x, tx_hash, err = result

            if err is not None:
                logger.error(f"取消{symbol}订单{order_id}失败: {err}")
                return AdapterResponse(
                    success=False,
                    data=None,
                    error_msg=str(err),
                )

            order_cancel_result = OrderCancelResult(
                order_id=order_id,
                api_resp={"tx_hash": tx_hash.to_json(), "result": x.to_json()},
            )

            return AdapterResponse(success=True, data=order_cancel_result, error_msg="")
        except Exception as e:
            logger.error(f"取消{symbol}订单{order_id}失败: {e}")
            return AdapterResponse(
                success=False,
                data=None,
                error_msg=str(e),
            )

    async def place_limit_order_async(self, symbol: str, side: str, position_side: str, quantity: float, price: float) -> AdapterResponse[OrderPlacementResult]:
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

            send_price = int(price * (10**price_decimal))
            send_quantity = int(quantity * (10**size_decimal))

            if side == "BUY":
                is_ask = False
            else:
                is_ask = True

            position_side = "open"
            client_order_index = self.get_client_order_id()

            try:
                # 执行订单创建
                result = await self.signer_client.create_order(
                    market_index=market_id,
                    client_order_index=client_order_index,
                    base_amount=send_quantity,
                    price=send_price,
                    is_ask=is_ask,
                    order_type=lighter.SignerClient.ORDER_TYPE_LIMIT,
                    time_in_force=lighter.SignerClient.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME,
                )
            except Exception as e:
                logger.error(f"下限价单失败: {e}")
                return AdapterResponse(
                    success=False,
                    data=None,
                    error_msg=str(e),
                )

            # 使用新的事件循环
            x, tx_hash, err = result

            if err is not None:
                logger.error(f"下限价开仓单失败: {err}")
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
                api_resp={"tx_hash": tx_hash.to_json(), "result": x.to_json()},
            )

            return AdapterResponse(success=True, data=order_placement_result, error_msg="")
        except Exception as e:
            logger.error(f"下限价单失败: {e}")
            return AdapterResponse(
                success=False,
                data=None,
                error_msg=str(e),
            )

    @retry_wrapper_async(retries=3, sleep_seconds=1, is_adapter_method=True)
    async def get_net_value_async(self) -> AdapterResponse[float]:
        """
        获取净价值

        Returns:
            AdapterResponse: 包含净价值的响应
        """
        try:
            api_response = await self.raw_query_account_async(by="index", value=self.account_index)
            if api_response.code == 200:
                data = api_response.to_dict()
                for account in data["accounts"]:
                    if account["account_index"] == self.account_index:
                        net_value = account["collateral"]
                        return AdapterResponse(success=True, data=net_value, error_msg="")
                else:
                    return AdapterResponse(success=False, data=None, error_msg="Account not found")
            else:
                logger.error(f"获取净价值失败: {api_response.message}")
                return AdapterResponse(success=False, data=None, error_msg=str(api_response.message))
        except Exception as e:
            logger.error(f"获取净价值失败: {e}", exc_info=True)
            return AdapterResponse(
                success=False,
                data=None,
                error_msg=str(e),
            )

    async def get_account_position_equity_ratio_async(self) -> AdapterResponse[float]:
        """
        获取账户持仓价值占比

        Returns:
            AdapterResponse: 包含净价值的响应
        """
        try:
            api_response = await self.raw_query_account_async(by="index", value=self.account_index)
            if api_response.code == 200:
                data = api_response.to_dict()
                accounts = [account for account in data["accounts"] if account["account_index"] == self.account_index]
                if len(accounts) != 1:
                    return AdapterResponse(success=False, data=0.0, error_msg=f"Invalid account_index {self.account_index}: multiple or no accounts found: {accounts}")
                total_value = float(accounts[0]["collateral"])
                position_value = 0
                for position in accounts[0]["positions"]:
                    position_value += float(position["position_value"])
                if total_value == 0:
                    ratio = 9999
                else:
                    ratio = position_value / total_value
                return AdapterResponse(success=True, data=ratio, error_msg="")
            else:
                logger.error(f"获取账户持仓保证金率失败: {api_response.message}")
                return AdapterResponse(success=False, data=None, error_msg=str(api_response.message))
        except Exception as e:
            logger.error(f"获取账户持仓保证金率失败: {e}", exc_info=True)
            return AdapterResponse(
                success=False,
                data=None,
                error_msg=str(e),
            )

    async def cancel_all_orders_async(self, symbol: str) -> AdapterResponse[bool]:
        """
        取消所有订单
        """
        try:

            # 执行订单创建
            x, tx_hash, err = await self.signer_client.cancel_all_orders(
                time_in_force=self.signer_client.CANCEL_ALL_TIF_IMMEDIATE,
                timestamp_ms=0,
            )

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

    async def query_all_um_open_orders_async(self, symbol: str) -> AdapterResponse[list]:
        """
        查询所有未成交订单
        """
        await self.judge_auth_token_expired_async(force=True)
        market_id = self.market_index_dic[symbol]
        try:
            api_instance = lighter.OrderApi(self.client)
            active_order_response = await api_instance.account_active_orders(self.account_index, market_id, authorization=self.auth_token)
            if active_order_response.code == 200:
                data = active_order_response.to_dict()
                return AdapterResponse(success=True, data=data["orders"], error_msg="")
            else:
                logger.error(f"查询所有未成交订单失败: {active_order_response.message}")
                return AdapterResponse(
                    success=False,
                    data=None,
                    error_msg=str(active_order_response.message),
                )
        except Exception as e:
            logger.error(f"查询所有未成交订单失败: {e}", exc_info=True)
            return AdapterResponse(success=False, data=None, error_msg=str(e))

    async def set_symbol_leverage_async(self, symbol: str, leverage: int) -> AdapterResponse[bool]:
        """
        设置合约杠杆
        """
        msg = f"设置合约杠杆: {symbol}, {leverage}， 未找到api"
        logger.error(msg)
        return AdapterResponse(success=False, data=None, error_msg=msg)

    async def get_um_account_info_async(self) -> AdapterResponse[UmAccountInfo]:
        """
        获取账户信息
        """
        try:

            api_response = await self.raw_query_account_async(by="index", value=self.account_index)
            if api_response.code == 200:
                data = api_response.to_dict()
                accounts = [account for account in data["accounts"] if account["account_index"] == self.account_index]
                if len(accounts) != 1:
                    return AdapterResponse(success=False, data=0.0, error_msg=f"Invalid account_index {self.account_index}: multiple or no accounts found: {accounts}")
                account = accounts[0]

                # 1. 计算 margin_balance（保证金余额）
                margin_balance = float(account["available_balance"])

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
                        maint_margin_fraction = initial_margin_fraction * 0.5
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
                    initial_margin_rate=(margin_balance / initial_margin if initial_margin > 0 else 999),
                    maint_margin_rate=(margin_balance / maint_margin if maint_margin > 0 else 999),
                    api_resp=data,
                )
                return AdapterResponse(success=True, data=um_account_info, error_msg="")
            else:
                logger.error(f"获取账户信息失败: {api_response.message}")
                return AdapterResponse(success=False, data=None, error_msg=str(api_response.message))
        except Exception as e:
            logger.error(f"获取账户信息失败: {e}", exc_info=True)
            return AdapterResponse(success=False, data=None, error_msg=str(e))

    # 已弃用部分方法
    def cancel_all_orders(self, *args, **kwargs):
        raise NotImplementedError

    def cancel_order(self, *args, **kwargs):
        raise NotImplementedError

    def get_depth(self, *args, **kwargs):
        raise NotImplementedError

    def get_net_value(self, *args, **kwargs):
        raise NotImplementedError

    def get_orderbook_ticker(self, *args, **kwargs):
        raise NotImplementedError

    def get_um_account_info(self, *args, **kwargs):
        raise NotImplementedError

    def place_limit_order(self, *args, **kwargs):
        raise NotImplementedError

    def place_market_open_order(self, *args, **kwargs):
        raise NotImplementedError

    def place_market_close_order(self, *args, **kwargs):
        raise NotImplementedError

    def query_order(self, *args, **kwargs):
        raise NotImplementedError

    def query_position(self, *args, **kwargs):
        raise NotImplementedError

    def set_symbol_leverage(self, *args, **kwargs):
        raise NotImplementedError

    def query_all_um_open_orders(self, *args, **kwargs):
        raise NotImplementedError


# 核心：定义异步 main 函数
async def main():
    try:
        # 1. 创建 LightAdapter 实例
        lighter_adapter = LightAdapter(
            l1_address="0xCd3B989f0F582d52B785E51e189d072e272AaaaA",
            apikey_private_key="a7198c5f4fba98c14dec93ca2b5267ad4a32a8f2bd6856e44c6f425856c98430106975e306bf7766",
            api_key_index=4
        )

        # 2. 调用异步方法（必须加 await）
        result = await lighter_adapter.detect_account_index_async("SOLUSDT", 2)
        
        # 3. 处理返回结果（可选）
        print("异步方法返回结果：", result)

    except Exception as e:
        # 异常处理：捕获异步方法执行中的所有错误
        print(f"执行出错：{str(e)}")
        raise  # 可选：重新抛出异常，让程序退出并显示堆栈

if __name__ == "__main__":
    import sys
    import os 

    # sys.path.append(".")
    # from src.adapter_factory import AdapterFactory
    # exchange_factory = AdapterFactory()
    #lighter_adapter:LightAdapter  = exchange_factory.create_adapter(exchange_name="lighter", instance_name="lighter_3")
    

    asyncio.run(main())

    #lighter_adapter.judge_auth_token_expired()
    #print(lighter_adapter.get_exchange_info())

    #print(lighter_adapter.auth_token)

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

