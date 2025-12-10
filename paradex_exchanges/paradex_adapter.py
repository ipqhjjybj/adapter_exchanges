import aiohttp
import asyncio
import hashlib
import random
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


from eth_account.messages import encode_structured_data
from eth_account.signers.local import LocalAccount
from web3.auto import Web3, w3
from web3.middleware import construct_sign_and_send_raw_middleware

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

sys.path.append("/Users/shenzhuoheng/quant_yz/git/adapter_exchanges")
sys.path.append("/home/ec2-user/test_lighter_dex/adapter_exchanges")

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

from paradex_utils import build_auth_message, get_account



class ParadexAdapter(ExchangeAdapter):
    """
    lighter交易所适配器实现
    该类实现了与Lighter交易所的交互功能，包括订单管理、持仓查询、账户信息获取等
    """
    
    def __init__(self, paradex_account_address, paradex_account_private_key):
        # 初始化基础URL
        self.base_url = "https://api.prod.paradex.trade/v1"
        
        self.paradex_account_address = paradex_account_address
        self.paradex_account_private_key = paradex_account_private_key

        # 创建token
        self.next_expiry_timestamp = 0
        self.jwt_token = None
    
    def get_paradex_config_sync(self) -> Dict:
        """
        Synchronous version of get_paradex_config
        """
        logger.info("Getting config...")
        path: str = "/system/config"
        
        headers = dict()
        
        response = requests.get(self.base_url  + path, headers=headers, timeout=60)
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

        url = paradex_http_url + '/auth'

        logger.info(f"POST {url}")
        logger.info(f"Headers: {headers}")

        response = requests.post(url, headers=headers, timeout=60)
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
    
    def judge_auth_token_expired(self):
        t1 = time.time()
        if t1 > self.next_expiry_timestamp - 60 * 60:
            logger.info("auth token near expired, re-create auth token")
            
            try:
                paradex_config = self.get_paradex_config_sync()

                # Call the synchronous get_jwt_token function
                logger.info("Getting JWT token...")
                jwt_token, expiry = self.get_jwt_token(
                    paradex_config,
                    self.base_url,
                    paradex_account_address,
                    paradex_account_private_key,
                )
                logger.info(f"JWT Token: {jwt_token} next_expiry_timestamp:{expiry}")
                self.next_expiry_timestamp = expiry
                self.jwt_token = jwt_token
            except Exception as e:
                logger.error(f"Error getting JWT token: {e}")
                import traceback
                traceback.print_exc()

            
    # @retry_wrapper(retries=3, sleep_seconds=1, is_adapter_method=True)
    # def get_account_info(self):
    #     """
    #     获得账户信息
    #     """
        
    
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
        self.judge_auth_token_expired()
        try:
            headers = {"Authorization": f"Bearer {self.jwt_token}"}

            url = self.base_url + '/account'

            logger.info(f"GET {url}")
            logger.info(f"Headers: {headers}")

            response = requests.get(url, headers=headers, timeout=60)
            status_code: int = response.status_code
            response_json: Dict = response.json()
            
            if status_code == 200:
                logger.info(f"Success: {response_json}")
                logger.info("Get Account successful")

                net_value = response_json["total_collateral"]
                return AdapterResponse(success=True, data=net_value, error_msg="")
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


    paradex_account_address = "0x58419d41b2986d4f6267ccbb7a53a73bcdd95868771648064eea1d205d56408"
    paradex_account_private_key = "0x7fcc70496c609c985e7033692896f838f161e1f4205990d9ad51e1c114fbf70"
    api = ParadexAdapter(paradex_account_address, paradex_account_private_key)
    
    #print(api.get_account_info())
    print(api.get_net_value())

