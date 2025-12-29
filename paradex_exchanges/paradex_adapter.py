import sys
import os

# 修复 crypto_cpp_py DLL 加载问题（仅 Windows 系统）
if sys.platform == 'win32':
    print("修复 crypto_cpp_py DLL 加载问题（仅 Windows 系统）")
    try:
        site_packages = [p for p in sys.path if 'site-packages' in p][0]
        env_path = os.path.dirname(os.path.dirname(site_packages))
        mingw_bin = os.path.join(env_path, 'Library', 'bin')
        if os.path.exists(mingw_bin):
            if hasattr(os, 'add_dll_directory'):
                os.add_dll_directory(mingw_bin)
            os.environ['PATH'] = f'{mingw_bin};{os.environ.get("PATH", "")}'
    except:
        pass


import aiohttp
import asyncio
import hashlib
import random
import math
import re
import time
from enum import IntEnum
from typing import Callable, Dict, Optional, Tuple
import requests
import asyncio
import sys
import time

from decimal import Decimal
import os
import time
from collections import defaultdict


# from eth_account.messages import encode_structured_data
from eth_account.messages import encode_typed_data
from eth_account.signers.local import LocalAccount
from web3.auto import Web3, w3
# from web3.middleware import construct_sign_and_send_raw_middleware

from starknet_py.common import int_from_bytes
from starknet_py.constants import RPC_CONTRACT_ERROR
from starknet_py.hash.address import compute_address
from starknet_py.hash.selector import get_selector_from_name
from starknet_py.net.client import Client
from starknet_py.net.client_errors import ClientError
from starknet_py.net.client_models import Call, Hash, TransactionExecutionStatus, TransactionFinalityStatus
from starknet_py.net.full_node_client import FullNodeClient
from starknet_py.net.models import Address
from starknet_py.net.signer.stark_curve_signer import KeyPair
from starknet_py.proxy.contract_abi_resolver import ProxyConfig
from starknet_py.proxy.proxy_check import ArgentProxyCheck, OpenZeppelinProxyCheck, ProxyCheck
from starknet_py.transaction_errors import (
    TransactionRevertedError,
    TransactionNotReceivedError,
)
from starknet_py.utils.typed_data import TypedData
from starkware.crypto.signature.signature import EC_ORDER

sys.path.append(r".")

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

# from src.adapters.paradex_utils import build_auth_message, get_account
# from src.adapters.paradex_shared import order_sign_message, flatten_signature, Order, OrderType, OrderSide
from paradex_utils import build_auth_message, get_account
from paradex_shared import order_sign_message, flatten_signature, Order, OrderType, OrderSide


class ParadexAdapter(ExchangeAdapter):
    """
    lighter交易所适配器实现
    该类实现了与Lighter交易所的交互功能，包括订单管理、持仓查询、账户信息获取等
    """
    
    def __init__(self, paradex_account_address, paradex_account_private_key, paradex_account_public_key="",proxy_url=None):
        # 初始化基础URL
        self.base_url = "https://api.prod.paradex.trade/v1"
        self.headers = {"accept": "application/json"}
        self.exchange_name = "paradex"

        if proxy_url is not None:
            self.proxies = {
                "http": proxy_url,
                "https": proxy_url
            }
        else:
            self.proxies = None
        
        self.paradex_account_address = paradex_account_address
        self.paradex_account_private_key = paradex_account_private_key
        self.paradex_account_public_key = paradex_account_public_key

        # 创建token
        self.next_expiry_timestamp = 0
        self.jwt_token = None

        # 系统config
        self.paradex_config = self.get_paradex_config_sync()
        assert self.paradex_config is not None, "get_paradex_config_sync error"
        assert len(self.paradex_config) > 0, "get_paradex_config_sync error"

        # 更新交易所信息
        price_decimal_dic, size_decimal_dic, min_notional_dic = self.get_exchange_info()
        self.price_decimal_dic = price_decimal_dic
        self.size_decimal_dic = size_decimal_dic
        self.min_notional_dic = min_notional_dic

        assert len(price_decimal_dic) > 0, "get_exchange_info error"
        assert len(size_decimal_dic) > 0, "get_exchange_info error"
    
    def get_paradex_config_sync(self) -> Dict:
        """
        Synchronous version of get_paradex_config
        """
        logger.info("Getting config...")
        path: str = "/system/config"
        
        headers = dict()
        
        response = requests.get(self.base_url + path, headers=headers, proxies=self.proxies, timeout=60)
        status_code: int = response.status_code
        response_json: Dict = response.json()
        
        logger.info(response_json)
        if status_code != 200:
            message: str = "Unable to [GET] /system/config"
            logger.error(message)
            logger.error(f"Status Code: {status_code}")
            logger.error(f"Response Text: {response_json}")
        
        return response_json
    
    def get_jwt_token(
        self, paradex_config: Dict, paradex_http_url: str, account_address: str, private_key: str
    ) -> str:
        token = ""

        chain_id = int_from_bytes(paradex_config["starknet_chain_id"].encode())
        account = get_account(account_address, private_key, paradex_config)

        now = int(time.time())
        expiry = now + 24 * 60 * 60 * 7
        message = build_auth_message(chain_id, now, expiry)
        sig = account.sign_message(message)

        headers: Dict = {
            "PARADEX-STARKNET-ACCOUNT": account_address,
            "PARADEX-STARKNET-SIGNATURE": f'["{sig[0]}","{sig[1]}"]',
            "PARADEX-TIMESTAMP": str(now),
            "PARADEX-SIGNATURE-EXPIRATION": str(expiry),
        }

        # url = paradex_http_url + '/auth'
        if len(self.paradex_account_public_key) > 0:
            url =  paradex_http_url + f'/auth/{self.paradex_account_public_key}?token_usage=interactive'
        else:
            url = paradex_http_url + '/auth?token_usage=interactive'

        logger.info(f"POST {url}")
        logger.info(f"Headers: {headers}")

        response = requests.post(url, headers=headers, proxies=self.proxies, timeout=60)
        status_code: int = response.status_code
        response_json: Dict = response.json()
        
        if status_code == 200:
            logger.info(f"Success: {response_json}")
            logger.info("Get JWT successful")
        else:
            logger.error(f"Status Code: {status_code}")
            logger.error(f"Response Text: {response_json}")
            logger.error("Unable to POST /auth")
        
        token = response_json["jwt_token"]
        return token, expiry

    def check_error(self, response_json):
        if response_json.get("error", "unknown") == "INVALID_TOKEN":
            self.reset_token()
            logger.error("Token失效，重置token")
            return True
        return False
    
    def reset_token(self):
        """
        重置token
        """
        self.jwt_token = None
        self.next_expiry_timestamp = 0
    
    def judge_auth_token_expired(self):
        t1 = time.time()
        if t1 > self.next_expiry_timestamp - 60 * 60:
            logger.info("auth token near expired, re-create auth token")
            
            try:
                # Call the synchronous get_jwt_token function
                logger.info("Getting JWT token...")
                jwt_token, expiry = self.get_jwt_token(
                    self.paradex_config,
                    self.base_url,
                    self.paradex_account_address,
                    self.paradex_account_private_key,
                )
                logger.info(f"JWT Token: {jwt_token} next_expiry_timestamp:{expiry}")
                self.next_expiry_timestamp = expiry
                self.jwt_token = jwt_token
            except Exception as e:
                logger.error(f"Error getting JWT token: {e}")
                import traceback
                traceback.print_exc()
    
    def get_exchange_info(self):
        url = f"{self.base_url}/markets"
        data = requests.get(url, headers=self.headers, proxies=self.proxies, timeout=60)
        if data.status_code == 200:
            js_data = data.json()
            results = js_data["results"]

            price_decimal_dic = {}
            size_decimal_dic = {}
            min_notional_dic = {}
            for dic in results:
                symbol = dic["symbol"]
                base_currency = dic["base_currency"]
                quote_currency = dic["quote_currency"]
                asset_kind = dic["asset_kind"]
                order_size_increment = dic["order_size_increment"]
                price_tick_size = dic["price_tick_size"]
                min_notional = dic["min_notional"]
                if asset_kind == "PERP" and quote_currency == "USD":
                    price_decimal_dic[symbol] = -math.log10(float(price_tick_size))
                    size_decimal_dic[symbol] = -math.log10(float(order_size_increment))
                    min_notional_dic[symbol] = float(min_notional)
            return price_decimal_dic, size_decimal_dic, min_notional_dic
        else:
            return {}, {}, {}
    
    def get_client_order_id(self):
        """获得client_order_id"""
        return str(time.time() * 1000)
    

    @retry_wrapper(retries=3, sleep_seconds=1, is_adapter_method=True)
    def get_orderbook_ticker(self, symbol: str) -> AdapterResponse[BookTicker]:
        """
        获取盘口价格

        Args:
            symbol: 交易对 如ETHUSDT

        Returns:
            AdapterResponse: 包含错误信息的响应
        """
        url = f"{self.base_url}/orderbook/{symbol}"
        data = requests.get(url, headers=self.headers, proxies=self.proxies, timeout=60)
        if data.status_code == 200:
            js_data = data.json()
            
            bids = js_data["bids"]
            asks = js_data["asks"]

            bids_arr = sorted(bids, key=lambda x: float(x[0]), reverse=True)
            asks_arr = sorted(asks, key=lambda x: float(x[0]))
            if len(bids_arr) == 0 or len(asks_arr) == 0:
                return AdapterResponse(success=False, data=None, error_msg="bids or asks is empty")
            else:
                return AdapterResponse(
                    success=True,
                    data=BookTicker(
                        symbol=symbol,
                        time=js_data["last_updated_at"],
                        bid_price=float(bids_arr[0][0]),
                        ask_price=float(asks_arr[0][0]),
                        ask_size=float(asks_arr[0][1]),
                        bid_size=float(bids_arr[0][1]),
                    ),
                    error_msg=None,
                )
        else:
            e = data.text
            logger.error(f"获取盘口价格失败: {e}")
            return AdapterResponse(success=False, data=None, error_msg=str(e))
        
    
    @retry_wrapper(retries=3, sleep_seconds=1, is_adapter_method=True)
    def get_depth(self, symbol: str, limit: int=20) -> AdapterResponse[BookTicker]:
        """
        获取盘口价格

        Args:
            symbol: 交易对 如ETHUSDT

        Returns:
            AdapterResponse: 包含错误信息的响应
        """
        url = f"{self.base_url}/orderbook/{symbol}?depth={limit}"
        data = requests.get(url, headers=self.headers, proxies=self.proxies, timeout=60)
        if data.status_code == 200:
            js_data = data.json()
            
            bids = js_data["bids"]
            asks = js_data["asks"]
            bids = [[float(x[0]), float(x[1])] for x in bids]
            asks = [[float(x[0]), float(x[1])] for x in asks]
            bids_arr = sorted(bids, key=lambda x: float(x[0]), reverse=True)
            asks_arr = sorted(asks, key=lambda x: float(x[0]))
            if len(bids_arr) == 0 or len(asks_arr) == 0:
                return AdapterResponse(success=False, data=None, error_msg="bids or asks is empty")
            else:
                return AdapterResponse(
                    success=True,
                    data=Depth(
                        symbol=symbol,
                        time=js_data["last_updated_at"],
                        bids=bids_arr,
                        asks=asks_arr,
                    ),
                    error_msg=None,
                )
        else:
            e = data.text
            logger.error(f"获取盘口价格失败: {e}")
            return AdapterResponse(success=False, data=None, error_msg=str(e))
    
    def place_market_open_order(
        self, symbol: str, side: str, position_side: str, quantity: float, out_price_rate: float = 0.005, is_open: bool = True
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
        error_msg = self.validate_order_direction(side, position_side, is_open=is_open)
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
        return self.place_market_open_order(symbol, side, position_side, quantity, out_price_rate, is_open=False)
    
    
    @retry_wrapper(retries=3, sleep_seconds=1, is_adapter_method=True)
    def query_position(self, symbol: str) -> AdapterResponse[SymbolPosition]:
        """
        查询持仓

        Args:
            symbol: 交易对

        Returns:
            AdapterResponse: 包含持仓信息的响应
        """
        self.judge_auth_token_expired()
        try:
            headers = {"Authorization": f"Bearer {self.jwt_token}"}
            url = f"{self.base_url}/positions"

            response = requests.get(url, headers=headers, proxies=self.proxies, timeout=60)
            status_code = response.status_code
            
            if status_code == 200:
                response_json = response.json()
                results = response_json["results"]

                long_qty = 0
                short_qty = 0
                for result in results:
                    if result["market"] == symbol:
                        if result["side"] == "LONG":
                            long_qty = abs(float(result["size"]))
                        else:
                            short_qty = abs(float(result["size"]))
                symbol_position = SymbolPosition(
                    symbol=symbol,
                    long_qty=long_qty,
                    short_qty=short_qty,
                    api_resp=response_json,
                )
                return AdapterResponse(success=True, data=symbol_position, error_msg="")
            else:
                logger.error(f"查询持仓失败: {response.text}")
                self.check_error(response.json())
                return AdapterResponse(success=False, data=None, error_msg=response.text)

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
        self.judge_auth_token_expired()
        try:
            headers = {"Authorization": f"Bearer {self.jwt_token}"}
            url = f"{self.base_url}/orders/{order_id}"

            response = requests.get(url, proxies=self.proxies, headers=headers)
            status_code = response.status_code
            
            if status_code == 200:
                response_json = response.json()
                status_text = response_json["status"]
                if status_text in ["NEW", "OPEN", "remaining_size"]:
                    status = OrderStatus.NEW
                    if float(response_json["remaining_size"]) < float(response_json["size"]):
                        status = OrderStatus.PARTIALLY_FILLED
                elif status_text in ["CLOSED"]:
                    if float(response_json["remaining_size"]) > 0:
                        status = OrderStatus.CANCELED
                    else:
                        status = OrderStatus.FILLED
                else:
                    raise ValueError(f"未知订单状态: {status_text}")
                
                side = response_json["side"]
                position_side = "open"
                avg_fill_price = 0
                if len(response_json["avg_fill_price"]) > 0:
                    avg_fill_price = float(response_json["avg_fill_price"])
            
                order_info = OrderInfo(
                    order_id=response_json["id"],
                    timestamp=response_json["timestamp"],
                    symbol=symbol,
                    status=status,
                    side=side,
                    position_side=position_side,
                    filled_qty=float(response_json["size"]) - float(response_json["remaining_size"]),
                    avg_price=avg_fill_price,
                    order_qty=float(response_json["size"]),
                    order_price=float(response_json["price"]),
                    api_resp=response_json,
                )
                return AdapterResponse(success=True, data=order_info, error_msg="")
            else:
                logger.error(f"查询订单失败: {response.text}", exc_info=True)
                self.check_error(response.json())
                return AdapterResponse(success=False, data=None, error_msg=str(response.text))

        except Exception as e:
            logger.error(f"查询订单失败: {e}", exc_info=True)
            return AdapterResponse(success=False, data=None, error_msg=str(e))
    
    @retry_wrapper(retries=3, sleep_seconds=1, is_adapter_method=True)
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
        self.judge_auth_token_expired()
        try:
            headers = {"Authorization": f"Bearer {self.jwt_token}"}
            url = f"{self.base_url}/orders/{order_id}"
            response = requests.delete(url, proxies=self.proxies, headers=headers)
            status_code = response.status_code
            
            if status_code == 204:
                cancel_dict = {
                    "order_id": order_id,
                    "api_resp": response.text,
                }
                return AdapterResponse(success=True, data=cancel_dict, error_msg="")
            else:
                logger.error(f"撤销订单失败: {response.text}", exc_info=True)
                self.check_error(response.json())
                return AdapterResponse(success=False, data=None, error_msg=str(response.text))

        except Exception as e:
            logger.error(f"取消所有订单失败: {e}", exc_info=True)
            return AdapterResponse(success=False, data=None, error_msg=str(e))
    
    def sign_order_sync(self, paradex_config: Dict, account_address: str, private_key: str, order: Order) -> Tuple[str, str]:
        """
        Synchronous version of sign_order
        """
        chain_id = int_from_bytes(paradex_config["starknet_chain_id"].encode())
        account = get_account(account_address, private_key, paradex_config)
        message = order_sign_message(chain_id, order)
        
        sig = account.sign_message(message)
        flat_sig = flatten_signature(sig)
        return flat_sig
    
    def build_limit_order_sync(self, market: str, order_side: OrderSide, size: Decimal,  price: Decimal, client_id: str = "sync_order") -> Order:
        """
        Build a limit order
        """
        order = Order(
            market=market,
            order_type=OrderType.Limit,
            order_side=order_side,
            size=size,
            limit_price=price,
            client_id=client_id,
            signature_timestamp=int(time.time() * 1000),
        )
        return order
    
    


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
        # self.judge_auth_token_expired()
        try:
            for i in range(2):
                self.judge_auth_token_expired()
                if side == "BUY":
                    order_side = OrderSide.Buy
                else:
                    order_side = OrderSide.Sell
                
                size = Decimal(str(quantity))
                price = Decimal(str(price))
                client_id = self.get_client_order_id()

                # Build the order
                order = self.build_limit_order_sync(symbol, order_side, size, price, client_id)
                # Sign the order
                signature = self.sign_order_sync(self.paradex_config, self.paradex_account_address, self.paradex_account_private_key, order)
                order.signature = signature

                # Convert order to dict
                order_dict = order.dump_to_dict()
                
                # Prepare headers
                headers = {
                    "Authorization": f"Bearer {self.jwt_token}",
                    "Content-Type": "application/json"
                }
                url = self.base_url + "/orders"

                response = requests.post(url, headers=headers, json=order_dict, proxies=self.proxies,  timeout=60)
                status_code = response.status_code
                response_json = response.json()
                response_json["status_code"] = status_code
                
                if status_code == 201:
                    logger.info(f"Order Created: {status_code} | Response: {response_json}")

                    order_placement_result = OrderPlacementResult(
                        symbol=symbol,
                        order_id=response_json["id"],
                        order_qty=quantity,
                        order_price=price,
                        side=side,
                        position_side=position_side,
                        api_resp=response_json,
                    )

                    result =  AdapterResponse(
                        success=True, data=order_placement_result, error_msg=""
                    )
                    return result
                else:
                    logger.warning(f"Unable to [POST] /orders Status Code:{status_code}")
                    logger.warning(f"Response: {response_json}")
                    self.check_error(response_json)
                    result = AdapterResponse(
                        success=False,
                        data=None,
                        error_msg=f"Response: {response_json}",
                    )
                    if i == 1:
                        return result
                    else:
                        continue
            
        except Exception as e:
            logger.error(f"下限价单失败: {e}")
            return AdapterResponse(
                success=False,
                data=None,
                error_msg=str(e),
            )
        
    def updates_accont_referred_code(self):
        """
        psst 单
        """
        self.judge_auth_token_expired()
        try:
            headers = {"Authorization": f"Bearer {self.jwt_token}"}

            url = self.base_url + '/account/referrer'

            data = {
                "referred_by": "shrewdog98"
            }
            response = requests.post(url, proxies=self.proxies, json=data, headers=headers)
            status_code = response.status_code
            
            if status_code == 200:
                return AdapterResponse(success=True, data=response.json(), error_msg="")
            else:
                logger.error(f"邀请码: {response.text}", exc_info=True)
                return AdapterResponse(success=False, data=None, error_msg=str(response.text))

    
        except Exception as ex:
            logger.error(f"获取净价值失败: {ex}", exc_info=True)
            #self.check_error(response_json)
            return AdapterResponse(
                success=False,
                data=None,
                error_msg=str("abc"),
            )
        
        
    @retry_wrapper(retries=3, sleep_seconds=1, is_adapter_method=True)
    def get_net_value(self) -> AdapterResponse[float]:
        """
        获取净价值

        Returns:
            AdapterResponse: 包含净价值的响应
        """
        self.judge_auth_token_expired()
        try:
            headers = {"Authorization": f"Bearer {self.jwt_token}"}

            url = self.base_url + '/account'

            logger.info(f"GET {url}")
            logger.info(f"Headers: {headers}")

            response = requests.get(url, headers=headers, proxies=self.proxies, timeout=60)
            status_code: int = response.status_code
            response_json: Dict = response.json()
            
            if status_code == 200:
                logger.info(f"Success: {response_json}")
                logger.info("Get Account successful")

                net_value = response_json["account_value"]
                return AdapterResponse(success=True, data=float(net_value), error_msg="")
            else:
                logger.error(f"Status Code: {status_code}")
                logger.error("Unable to GET /account")
                logger.error(f"获取净价值失败: {response_json}")
                self.check_error(response_json)
                return AdapterResponse(success=False, data=None, error_msg=f"{response_json}")
        except Exception as e:
            logger.error(f"获取净价值失败: {e}", exc_info=True)
            self.check_error(response_json)
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
        priceDecimal = int(self.price_decimal_dic[symbol])
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
        sizeDecial = int(self.size_decimal_dic[symbol])
        minQty = round(0.1 ** sizeDecial, sizeDecial)
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
    
    @retry_wrapper(retries=3, sleep_seconds=1, is_adapter_method=True)
    def get_account_position_equity_ratio(self) -> AdapterResponse[float]:
        """
        获取账户持仓价值占比

        Returns:
            AdapterResponse: 包含净价值的响应
        """
        self.judge_auth_token_expired()
        try:
            net_value = self.get_net_value()
            total_value = float(net_value.data)

            headers = {"Authorization": f"Bearer {self.jwt_token}"}
            url = f"{self.base_url}/positions"

            response = requests.get(url, headers=headers, proxies=self.proxies, timeout=60)
            status_code = response.status_code
            
            position_value = 0
            if status_code == 200:
                response_json = response.json()
                results = response_json["results"]
                for result in results: 
                    position_value += abs(float(result["average_entry_price"]) * float(result['size']))
            
            if total_value == 0:
                ratio = 9999
            else:
                ratio = position_value / total_value
            
            return AdapterResponse(success=True, data=ratio, error_msg="")
            
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
        if symbol=="PAXG-USD-PERP":
            return AdapterResponse(success=True, data=1, error_msg="")
        else:
            return AdapterResponse(success=False, data=None, error_msg="不支持的交易对")


    def cancel_all_orders(self, symbol: str) -> AdapterResponse[bool]:
        """
        取消所有订单
        """
        self.judge_auth_token_expired()
        try:
            headers = {"Authorization": f"Bearer {self.jwt_token}"}
            url = f"{self.base_url}/orders"
            response = requests.delete(url, proxies=self.proxies, headers=headers)
            status_code = response.status_code

            return AdapterResponse(success=True, data=response.json(), error_msg="")

        except Exception as e:
            logger.error(f"取消所有订单失败: {e}", exc_info=True)
            return AdapterResponse(success=False, data=None, error_msg=str(e))
    
    def query_all_um_open_orders(self, symbol: str) -> AdapterResponse[list]:
        """
        查询所有未成交订单
        """
        self.judge_auth_token_expired()
        try:
            headers = {"Authorization": f"Bearer {self.jwt_token}"}
            url = f"{self.base_url}/orders"
            response = requests.get(url, headers=headers, proxies=self.proxies, timeout=60)
            status_code = response.status_code
            return AdapterResponse(success=True, data=response.json()["results"], error_msg="")
        except Exception as e:
            logger.error(f"查询所有未成交订单失败: {e}", exc_info=True)
            return AdapterResponse(success=False, data=None, error_msg=str(e))
    
    def set_symbol_leverage(self, symbol: str, leverage: int) -> AdapterResponse[bool]:
        """
        设置合约杠杆
        """
        raise NotImplementedError("Paradex交易所不支持设置合约杠杆-先不实现")
    
    @retry_wrapper(retries=3, sleep_seconds=1, is_adapter_method=True)
    def get_um_account_info(self) -> AdapterResponse[UmAccountInfo]:
        """
        获取账户信息
        """
        self.judge_auth_token_expired()
        try:
            headers = {"Authorization": f"Bearer {self.jwt_token}"}

            url = self.base_url + '/account'

            logger.info(f"GET {url}")
            logger.info(f"Headers: {headers}")

            response = requests.get(url, headers=headers, proxies=self.proxies, timeout=60)
            status_code: int = response.status_code
            response_json: Dict = response.json()
            self.check_error(response_json)
            
            if status_code == 200:
                
                initial_margin = float(response_json['initial_margin_requirement'])
                maint_margin = float(response_json['maintenance_margin_requirement'])
                margin_balance = float(response_json['total_collateral'])
                timenow = int(time.time() * 1000)
                um_account_info = UmAccountInfo(
                    timestamp=timenow,
                    initial_margin=initial_margin,
                    maint_margin=maint_margin,
                    margin_balance=margin_balance,
                    initial_margin_rate=margin_balance /initial_margin  if initial_margin > 0 else 999,
                    maint_margin_rate=margin_balance /maint_margin if maint_margin > 0 else 999,
                    api_resp=response_json,
                )
                return AdapterResponse(success=True, data=um_account_info, error_msg="")
            else:
                logger.error(f"Status Code: {status_code}")
                logger.error("Unable to GET /account")
                logger.error(f"获取净价值失败: {response_json}")
                return AdapterResponse(success=False, data=None, error_msg=f"{response_json}")
        except Exception as e:
            logger.error(f"获取净价值失败: {e}", exc_info=True)
            return AdapterResponse(
                success=False,
                data=None,
                error_msg=str(e),
            )
            
    def set_symbol_leverage(self, symbol: str, leverage: int) -> AdapterResponse[bool]:
            """
            设置合约杠杆
            """
            self.judge_auth_token_expired()
            try:
                headers = {"Authorization": f"Bearer {self.jwt_token}", "Content-Type": "application/json"}
                url = f"{self.base_url}/account/margin/{symbol}"

                data = {
                    "margin_type": "CROSS",
                    "leverage": leverage,
                }
                response = requests.post(url, proxies=self.proxies, json=data, headers=headers)
                status_code = response.status_code
                
                if status_code == 200:
                    return AdapterResponse(success=True, data=response.json(), error_msg="")
                else:
                    logger.error(f"设置杠杠: {response.text}", exc_info=True)
                    return AdapterResponse(success=False, data=None, error_msg=str(response.text))

            except Exception as e:
                logger.error(f"设置杠杠失败: {e}", exc_info=True)
                return AdapterResponse(success=False, data=None, error_msg=str(e))


if __name__ == "__main__":
    import sys
    import os 


    # 这是我的账户
    paradex_account_address = "0x58419d41b2986d4f6267ccbb7a53a73bcdd95868771648064eea1d205d56408"
    #paradex_account_private_key = ""
    # sub_key
    paradex_account_private_key = "0x0044ae9b363847e54509e3b3f6ba53b946b78a8ddcc27874feabfc7a0a450bd7"
    paradex_account_public_key = "0x7e17ec180717664faeff3f3e907a29f027727ea24e662881442dd5c66c9ed8f"

    # 这是zjx 的账户
    # paradex_account_address = "0x587967a921d0ad97590689a36f38595862c5ed997c40890d5f4a8b44a65a37e"
    # paradex_account_private_key = "0x058e1d3af54540935be8e9454af9e53c6dd0eb96c0461fb230a5520f8ec76729"
    # paradex_account_public_key = "0x51740ff6abaa75b7ea18ce4c81e1dcc02df21aca6a3f26d8f0c42db0df6a7d6"
    
    api = ParadexAdapter(paradex_account_address, paradex_account_private_key, paradex_account_public_key)
    
    symbol = "PAXG-USD-PERP"
    # t1=time.time()
    # for i in range(1000):
    #     try:
    #         print(api.get_net_value())
    #         api.reset_token() 

    #         t2 = time.time()
    #         print("use time:", (t2 - t1) / (i+1))
    #     except Exception as e:
    #         print(e)
    #data = api.get_orderbook_ticker(symbol)
    # data = api.get_depth(symbol)
    # print(data)
    #print(api.get_account_info())
    # print(api.get_net_value())

    data = api.updates_accont_referred_code()
    print(data)

    # data = api.place_limit_order(symbol=symbol, side="BUY", position_side="LONG", quantity=0.004, price=3000)
    # print(data)

    pass
    # data = api.place_limit_order(symbol=symbol, side="BUY", position_side="LONG", quantity=0.004, price=3000)
    # print(data)

    # data = api.place_market_open_order(symbol=symbol, side="BUY", position_side="LONG", quantity=0.003)
    # print(data)

    # data = api.place_market_open_order(symbol=symbol, side="SELL", position_side="SHORT", quantity=0.003)
    # print(data)


    # data = api.query_position(symbol=symbol)
    # print(data)
    # data = api.place_market_close_order(symbol=symbol, side="SELL", position_side="LONG", quantity=0.1)
    # print(data)


    
    # data = api.query_order(symbol=symbol, order_id="1765331364580201709274590000")
    # print(data)

    # data = api.cancel_order(symbol=symbol, order_id="1765342177860201709197200001")
    # print(data)

    # data = api.cancel_all_orders(symbol=symbol)
    # print(data)

    # data = api.get_account_position_equity_ratio()
    # print(data)

    # data = api.get_contract_trade_unit(symbol)
    # print(data)

    # data = api.query_all_um_open_orders(symbol)
    # print(data)

    # data = api.get_um_account_info()
    # print(data)
    pass
    

