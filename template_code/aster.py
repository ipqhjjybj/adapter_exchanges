import time, hmac, hashlib, types, requests
from urllib.parse import urlencode
from typing import Literal
import pandas as pd

import sys

sys.path.append("/Users/jianxunzhai/Desktop/workspace/allen/github/dex-arbitrage")

from dex_arbitrage.models import BookTicker, LatestPrice, build_symbol_info_dict


# ========= ccxt风格 Entry =========
class Entry:
    def __init__(self, path, api, method, config):
        self.name = None
        self.path = path
        self.api = api
        self.method = method
        self.config = config

        def unbound_method(_self, params={}):
            return _self.request(
                self.path, self.api, self.method, params, config=self.config
            )

        self.unbound_method = unbound_method

    def __get__(self, instance, owner):
        if instance is None:
            return self.unbound_method
        else:
            return types.MethodType(self.unbound_method, instance)

    def __set_name__(self, owner, name):
        self.name = name


# ========= 基础 Exchange =========
class ExchangeBase:
    def __init__(self, api_key=None, secret=None, proxies=None, timeout=5):
        self.api_key = api_key
        self.secret = secret
        self.session = requests.Session()
        self.session.proxies.update(proxies or {})
        self.timeout = timeout
        self.proxies = proxies

    def fetch(self, url, method="GET", headers=None, body=None):
        response = self.session.request(
            method,
            url,
            data=body,
            headers=headers or {},
            timeout=self.timeout / 1000,
            proxies=self.proxies,
        )
        response.raise_for_status()
        try:
            return response.json()
        except Exception:
            return response.text

    def sign(self, path, api, method, params={}, headers=None, body=None, config={}):
        raise NotImplementedError

    def fetch2(self, path, api, method, params={}, headers=None, body=None, config={}):
        request = self.sign(path, api, method, params, headers, body)
        return self.fetch(
            request["url"], request["method"], request["headers"], request["body"]
        )

    def request(self, path, api, method, params={}, headers=None, body=None, config={}):
        return self.fetch2(path, api, method, params, headers, body, config)


# ========= Aster =========
class ImplicitAPI:
    fapiPublicGetPing = Entry("ping", "fapiPublicV1", "GET", {"cost": 1})
    fapiPrivateGetBalance = Entry("balance", "fapiPrivateV2", "GET", {"cost": 1})
    fapiPrivateGetPositionSideDual = Entry(
        "positionSide/dual", "fapiPrivateV1", "GET", {"cost": 30}
    )
    fapiPrivateGetPositionRisk = Entry(
        "positionRisk", "fapiPrivateV1", "GET", {"cost": 5}
    )
    fapiPrivatePostOrder = Entry("order", "fapiPrivateV1", "POST", {"cost": 1})
    fapiPrivatePostCancelOrder = Entry("order", "fapiPrivateV1", "DELETE", {"cost": 1})
    fapiPrivateGetOrder = Entry("order", "fapiPrivateV1", "GET", {"cost": 1})
    fapiPublicGetOrderBook = Entry("orderBook", "fapiPublicV1", "GET", {"cost": 2})
    fapiPublicGetKlines = Entry("klines", "fapiPublicV1", "GET", {"cost": 2})
    fapiPrivateGetUserAccount = Entry("account", "fapiPrivateV4", "GET", {"cost": 1})
    fapiPublicGetExchangeInfo = Entry(
        "exchangeInfo", "fapiPublicV1", "GET", {"cost": 1}
    )
    fapiPublicGetBookTicker = Entry(
        "ticker/bookTicker", "fapiPublicV1", "GET", {"cost": 1}
    )
    fapiPublicGetTickerPrice = Entry(
        "ticker/price", "fapiPublicV1", "GET", {"cost": 1}
    )
    fapiPrivateGetIncomeHistory = Entry(
        "income", "fapiPrivateV1", "GET", {"cost": 30}
    )
    fapiPublicGetIndexPriceKlines = Entry(
        "indexPriceKlines", "fapiPublicV1", "GET", {"cost": 1}
    )
    fapiPrivatePostMultiAssetsMargin = Entry(
        "multiAssetsMargin", "fapiPrivateV1", "POST", {"cost": 1}
    )
    fapiPrivatePostPositionSideDual = Entry(
        "positionSide/dual", "fapiPrivateV1", "POST", {"cost": 1}
    )
    fapiPrivatePostCancelAllOpenOrders = Entry(
        "allOpenOrders", "fapiPrivateV1", "DELETE", {"cost": 1}
    )

class AsterExchange(ExchangeBase, ImplicitAPI):
    def __init__(self, api_key=None, secret=None, proxies=None, timeout=5000):
        super().__init__(api_key, secret, proxies, timeout)
        self.urls = {
            "fapiPublicV1": "https://fapi.asterdex.com/fapi/v1",
            "fapiPrivateV1": "https://fapi.asterdex.com/fapi/v1",
            "fapiPublicV2": "https://fapi.asterdex.com/fapi/v2",
            "fapiPrivateV2": "https://fapi.asterdex.com/fapi/v2",
            "fapiPrivateV4": "https://fapi.asterdex.com/fapi/v4",
            "fapiPrivateV3": "https://fapi.asterdex.com/fapi/v3",
        }
        self.symbol_info_dict = self.fetch_futures_exchange_info()

    def sign(
        self,
        path,
        api="fapiPublicV1",
        method="GET",
        params={},
        headers=None,
        body=None,
        config={},
    ):
        base = self.urls[api]
        url = f"{base}/{path}"
        headers = {}
        if "Private" in api:  # 私有接口签名
            ts = int(time.time() * 1000)
            recv_window = params.pop("recvWindow", 10000)
            query = urlencode({**params, "timestamp": ts, "recvWindow": recv_window})
            sig = hmac.new(
                self.secret.encode(), query.encode(), hashlib.sha256
            ).hexdigest()
            url += f"?{query}&signature={sig}"
            headers["X-MBX-APIKEY"] = self.api_key
        else:  # 公共接口
            if params:
                url += "?" + urlencode(params)
        return {"url": url, "method": method, "headers": headers, "body": None}

    def futures_ping(self):
        return self.fapiPublicGetPing()

    def fetch_futures_position_risk(self, symbol=None, params={}):
        if symbol:
            params["symbol"] = symbol
        return self.fapiPrivateGetPositionRisk(params)

    def place_futures_order(self, symbol, side, quantity, price, order_type, time_in_force="IOC", params={}):
        params["symbol"] = symbol
        params["side"] = side
        params["quantity"] = quantity
        params["price"] = price
        params["type"] = order_type
        params["timeInForce"] = time_in_force
        return self.fapiPrivatePostOrder(params)

    def cancel_futures_order(self, symbol, order_id=None, orig_client_order_id=None, params={}):
        params["symbol"] = symbol
        if order_id:
            params["orderId"] = order_id
        if orig_client_order_id:
            params["origClientOrderId"] = orig_client_order_id
        return self.fapiPrivatePostCancelOrder(params)

    def query_futures_order(self, symbol, order_id=None, orig_client_order_id=None, params={}):
        params["symbol"] = symbol
        if order_id:
            params["orderId"] = order_id
        if orig_client_order_id:
            params["origClientOrderId"] = orig_client_order_id
        return self.fapiPrivateGetOrder(params)

    def fetch_futures_order_book(self, symbol, limit=50, params={}):
        params["symbol"] = symbol
        params["limit"] = limit
        return self.fapiPublicGetOrderBook(params)

    def fetch_balance(self, params={}):
        return self.fapiPrivateGetBalance(params)

    def fetch_futures_klines(self, symbol, interval, limit=500, params={}):
        params["symbol"] = symbol
        params["interval"] = interval
        params["limit"] = limit
        return self.fapiPublicGetKlines(params)

    def fetch_user_account(self, params={}):
        return self.fapiPrivateGetUserAccount(params)

    def fetch_balance(self, params={}):
        return self.fapiPrivateGetBalance(params)

    def fetch_futures_exchange_info(self, params={}):
        data = self.fapiPublicGetExchangeInfo(params)
        return build_symbol_info_dict(data['symbols'])
    
    def fetch_futures_book_ticker(self, symbol, params={}):
        params["symbol"] = symbol
        data = self.fapiPublicGetBookTicker(params)
        return BookTicker(
            timestamp=int(data["time"]),
            symbol=symbol,
            bid_price=float(data["bidPrice"]),
            ask_price=float(data["askPrice"]),
            bid_quantity=float(data["bidQty"]),
            ask_quantity=float(data["askQty"]),
        )
        
    def fetch_futures_lastest_price(self, symbol, params={}):
        params["symbol"] = symbol
        data = self.fapiPublicGetTickerPrice(params)
        return LatestPrice(
            timestamp=int(data["time"]),
            symbol=symbol,
            price=float(data["price"]),
        )
        
    def fetch_income_history(self,startTime=None, endTime=None, limit=1000, params={}):
        if startTime:
            params["startTime"] = startTime
        if endTime:
            params["endTime"] = endTime
        if limit:
            params["limit"] = limit
        data = self.fapiPrivateGetIncomeHistory(params)
        return data 
    
    def fetch_futures_index_price_klines(self, pair, interval, start_time=None, end_time=None, limit=499, params={}):
        params["pair"] = pair
        params["interval"] = interval
        params["limit"] = limit
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time
        return self.fapiPublicGetIndexPriceKlines(params)
    
    def change_multi_assets_mode(self, multi_assets_margin: bool = True, params={}):
        if multi_assets_margin:
            params["multiAssetsMargin"] = "true"
        else:
            params["multiAssetsMargin"] = "false"
        data = self.fapiPrivatePostMultiAssetsMargin(params)
        return data
    
    def change_position_side_dual(self, dual_side_position: bool = True, params={}):
        if dual_side_position:
            params["dualSidePosition"] = "true"
        else:
            params["dualSidePosition"] = "false"
        data = self.fapiPrivatePostPositionSideDual(params)
        return data
    
    def cancel_all_futures_open_orders(self, symbol, params={}):
        params["symbol"] = symbol
        data = self.fapiPrivatePostCancelAllOpenOrders(params)
        return data
    
    def change_margin_type(self, margin_mode: Literal["ISOLATED", "CROSSED"] = "CROSSED", params={}):
        if margin_mode == "ISOLATED":
            params["marginType"] = "ISOLATED"
        else:
            params["marginType"] = "CROSSED"
        data = self.fapiPrivatePostMarginMode(params)
        return data
    
    # def place_slippage_order(self, symbol, side, quantity, price, params={}):

# ========= 测试 =========
if __name__ == "__main__":
    from dotenv import load_dotenv
    import os
    load_dotenv()
    aster = AsterExchange(
        api_key=os.getenv("ASTER_API_KEY"),
        secret=os.getenv("ASTER_SECRET"),
    )
    
    print("=== fetch_lastest_price ===")
    print(aster.fetch_futures_lastest_price("BTCUSDT"))
    
    print("=== fetch_income_history ===")
    print(aster.fetch_income_history())
    # print("=== fetch_klines ===")
    # print(aster.fetch_klines("JLPUSDT", "1m"))
    # print("=== fetch_book_ticker ===")
    # print(aster.fetch_futures_book_ticker("BTCUSDT"))

    # print("=== fetch_exchange_info ===")
    # exchange_info = aster.fetch_futures_exchange_info()
    # print(exchange_info.get_symbol("BTCUSDT").price_tick)

    # print("=== fetch_user_account ===")
    # account_info = aster.fetch_user_account()

    # print("=== fetch_balance ===")
    # balances = aster.fetch_balance()
    # print(aster.fetch_balance())
    # print("=== ping ===")
    # # print(aster.fapiPublicGetPing())  # should return {}
    # # print(aster.ping())
    # # print("=== positionSide/dual ===")
    # # print(aster.fapiPrivateGetPositionSideDual())
    # print("=== fetch_position_risk ===")
    # print(aster.fetch_position_risk("BTCUSDT"))

    # print("=== place_order ===")
    # print(aster.place_order("BTCUSDT", "BUY", 0.001, 10000, "LIMIT", params={"timeInForce": "GTC", "newClientOrderId": "test_order_id"}))

    # print("=== query_order ===")
    # print(aster.query_order("BTCUSDT", orig_client_order_id="test_order_id"))

    # print("=== cancel_order ===")
    # print(aster.cancel_order("BTCUSDT", orig_client_order_id="test_order_id"))

    # print("=== query_order ===")
    # print(aster.query_order("BTCUSDT", orig_client_order_id="test_order_id"))
