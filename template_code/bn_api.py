import ccxt
import pandas as pd
from decimal import Decimal
from datetime import datetime
import sys

sys.path.append("..")
from src.utils import (
    adjust_to_price_filter,
    adjust_to_lot_size,
    redirect,
    load_config_yaml,
)
from src.utils import SigningBinance

class BinanceApi:
    def __init__(self, api_key, api_secret, proxy_url=None, use_signing=False, secret_name=None, signing_endpoint=None):
        self.proxies = self._setup_proxies(proxy_url)
        self.exchange = self._create_exchange(api_key, api_secret, use_signing, secret_name, signing_endpoint)
        self.um_exchange_info_df = self.get_um_exchange_info()
        self.set_um_position_mode(dual_side_position=True)

    def _setup_proxies(self, proxy_url):
        """设置代理配置"""
        if proxy_url:
            return {"http": proxy_url, "https": proxy_url}
        return {}

    def _create_exchange(self, api_key, api_secret, use_signing, secret_name, signing_endpoint):
        """创建交易所实例"""
        config_yaml = load_config_yaml()
        use_aws_proxy = config_yaml.get("aws_proxy", {}).get("use_aws_proxy", "false")
        
        if use_aws_proxy == "true":
            return self._create_aws_exchange(api_key, api_secret, config_yaml)
        else:
            return self._create_standard_exchange(api_key, api_secret, use_signing, secret_name, signing_endpoint)

    def _create_aws_exchange(self, api_key, api_secret, config_yaml):
        """创建使用AWS代理的交易所实例"""
        headers = {
            "CF-Access-Client-Id": config_yaml["aws_proxy"]["CF_ACCESS_CLIENT_ID"],
            "CF-Access-Client-Secret": config_yaml["aws_proxy"]["CF_ACCESS_CLIENT_SECRET"],
        }
        
        bn_config = self._get_base_config(api_key, api_secret)
        bn_config["headers"] = headers
        
        exchange = ccxt.binance(config=bn_config)
        return redirect(exchange, "binance", config_yaml["aws_proxy"]["binance_proxy_map"])

    def _create_standard_exchange(self, api_key, api_secret, use_signing, secret_name, signing_endpoint):
        """创建标准交易所实例"""
        bn_config = self._get_base_config(api_key, api_secret)
        bn_config["proxies"] = self.proxies
        if use_signing:
            return SigningBinance(secret_name, signing_endpoint, config=bn_config)
        else:
            return ccxt.binance(config=bn_config)

    def _get_base_config(self, api_key, api_secret):
        """获取基础配置"""
        return {
            "timeout": 30000,
            "rateLimit": 30,
            "enableRateLimit": False,
            "options": {
                "adjustForTimeDifference": True,
                "recvWindow": 10000,
            },
            "apiKey": api_key,
            "secret": api_secret,
        }

    def get_um_balance(self):
        """
        获取U本位合约余额
        """
        return self.exchange.fapiprivatev3_get_account()

    def get_um_exchange_info(self):
        """
        获取U本位合约交易所信息
        """
        return pd.DataFrame(self.exchange.fapipublic_get_exchangeinfo()["symbols"])

    def query_um_position_mode(self):
        """
        查询U本位持仓模式
        """
        return self.exchange.fapiprivate_get_positionside_dual()

    def set_um_position_mode(self, dual_side_position=True):
        """
        设置U本位持仓模式, 双仓模式(dual_side_position=True)或单仓模式(dual_side_position=False)
        """
        if self.query_um_position_mode()["dualSidePosition"] == dual_side_position:
            print(
                f"U本位持仓模式已设置为dual_side_position：{dual_side_position}, 无需重复设置"
            )
            return
        if dual_side_position:
            params = {"dualSidePosition": "true"}
        else:
            params = {"dualSidePosition": "false"}
        data = self.exchange.fapiprivate_post_positionside_dual(params=params)
        print(f"设置U本位持仓模式成功, 当前持仓模式为dual_side_position: {data}")
        return

    def set_leverage(self, symbol: str, symbol_type: str, leverage: int):
        """设置合约杠杆倍数

        Args:
            symbol (str): 合约代码，例如 "BTCUSDT"
            symbol_type (str): 合约类型，只能为 "um"(U本位合约) 或 "cm"(币本位合约)
            leverage (int): 杠杆倍数，范围 1-125

        Returns:
            dict: 交易所返回的杠杆设置结果

        Raises:
            ValueError: 当杠杆不在有效范围内或合约类型不正确时抛出
        """
        if leverage < 1 or leverage > 125:
            raise ValueError(f"杠杆倍数必须在 1 到 125 之间")

        params = {"symbol": symbol, "leverage": leverage}

        if symbol_type == "um":
            response = self.exchange.fapiprivate_post_leverage(params=params)
            return response
        elif symbol_type == "cm":
            response = self.exchange.dapiprivate_post_leverage(params=params)
            return response
        else:
            raise ValueError(f"合约类型 symbol_type 只能为 'um'(U本位) 或 'cm'(币本位)")

    def place_um_limit_order(
        self,
        symbol: str,
        side: str,
        position_side: str,
        quantity: float,
        price: float,
        params: dict = {},
    ):
        """
        下U本位限价单

        Args:
            symbol (str): 合约代码，例如 "BTCUSDT"
            side (str): 买卖方向，只能为 "BUY" 或 "SELL"
            position_side (str): 持仓方向，只能为 "LONG" 或 "SHORT"
            quantity (float): 下单数量
            price (float): 下单价格
            params (dict): 其他参数
        """

        _params = {
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "price": price,
            "timeInForce": "GTX",
            "type": "LIMIT",
            "positionSide": position_side,
        }
        if params:
            _params.update(params)
        return self.exchange.fapiprivate_post_order(params=_params)

    def place_um_market_order(
        self, symbol, side, position_side, quantity, out_price_rate=0.005, params={}
    ):
        """
        下U本位市价单

        Args:
            symbol (str): 合约代码，例如 "BTCUSDT"
            side (str): 买卖方向，只能为 "BUY" 或 "SELL"
            position_side (str): 持仓方向，只能为 "LONG" 或 "SHORT"
            quantity (float): 下单数量
            params (dict): 其他参数

        Returns:
            dict: 交易所返回的下单结果

        Raises:
            ValueError: 当时间类型不是 IOC 时抛出
        """
        price = self.get_out_limit_price(
            symbol, "um", side, position_side, out_price_rate
        )
        _params = {
            "timeInForce": "IOC",
        }
        if params:
            _params.update(params)
        if _params.get("timeInForce") != "IOC":
            raise ValueError("timeInForce 只能为 IOC")
        return self.place_um_limit_order(
            symbol, side, position_side, quantity, price, _params
        )

    def query_um_order(self, symbol: str, order_id: str, params: dict = {}):
        """
        查询U本位订单

        Args:
            symbol (str): 合约代码，例如 "BTCUSDT"
            order_id (str): 订单ID
            params (dict): 其他参数

        Returns:
            dict: 交易所返回的订单信息
        """
        _params = {"symbol": symbol, "orderId": order_id}
        if params:
            _params.update(params)
        return self.exchange.fapiprivate_get_order(params=_params)

    def cancel_um_order(self, symbol: str, order_id: str, params: dict = {}):
        """
        取消U本位订单

        Args:
            symbol (str): 合约代码，例如 "BTCUSDT"
            order_id (str): 订单ID
            params (dict): 其他参数

        Returns:
            dict: 交易所返回的取消结果
        """
        _params = {"symbol": symbol, "orderId": order_id}
        if params:
            _params.update(params)
        return self.exchange.fapiprivate_delete_order(params=_params)

    def cancel_all_um_orders(self, symbol: str, params: dict = {}):
        """
        取消U本位所有订单

        Args:
            symbol (str): 合约代码，例如 "BTCUSDT"
            params (dict): 其他参数

        Returns:
            dict: 交易所返回的取消结果
        """
        _params = {"symbol": symbol}
        if params:
            _params.update(params)
        return self.exchange.fapiprivate_delete_allopenorders(params=_params)

    # ================================ 行情 ================================
    def get_depth(self, symbol, symbol_type, limit=5):
        _params = {
            "symbol": symbol,
            "limit": limit,
        }
        if symbol_type == "um":
            return self.exchange.fapipublic_get_depth(params=_params)
        elif symbol_type == "cm":
            return self.exchange.dapipublic_get_depth(params=_params)
        elif symbol_type == "margin":
            return self.exchange.public_get_depth(params=_params)
        elif symbol_type == "spot":
            return self.exchange.public_get_depth(params=_params)
        else:
            raise ValueError(f"Invalid symbol type: {symbol_type}")

    def get_book_ticker(self, symbol, symbol_type):
        _params = {
            "symbol": symbol,
        }
        if symbol_type == "um":
            return self.exchange.fapipublic_get_ticker_bookticker(params=_params)
        elif symbol_type == "cm":
            return self.exchange.dapipublic_get_ticker_bookticker(params=_params)
        elif symbol_type == "margin":
            return self.exchange.public_get_ticker_bookticker(params=_params)
        elif symbol_type == "spot":
            return self.exchange.public_get_ticker_bookticker(params=_params)
        else:
            raise ValueError(f"Invalid symbol type: {symbol_type}")

    def get_ticker_price(self, symbol: str, symbol_type: str):
        """
        获取U本位合约最新价格

        Args:
            symbol (str): 合约代码，例如 "BTCUSDT"
            symbol_type (str): 合约类型，只能为 "um"(U本位合约) 或 "cm"(币本位合约) 或 "margin"(杠杆) 或 "spot"(现货)

        Returns:
            float: 最新价格
        """
        if symbol_type == "um":
            return self.exchange.fapipublic_get_ticker_price(params={"symbol": symbol})
        elif symbol_type == "cm":
            return self.exchange.dapipublic_get_ticker_price(params={"symbol": symbol})
        elif symbol_type == "margin":
            return self.exchange.public_get_ticker_price(params={"symbol": symbol})
        elif symbol_type == "spot":
            return self.exchange.public_get_ticker_price(params={"symbol": symbol})
        else:
            raise ValueError(f"Invalid symbol type: {symbol_type}")

    def get_out_limit_price(
        self, symbol, symbol_type, side, position_side, out_price_rate=0.005
    ):
        """
        获取超价限价价格, 在下市价单的时候使用

        Args:
            symbol (str): 合约代码，例如 "BTCUSDT"
            symbol_type (str): 合约类型，只能为 "um"(U本位合约) 或 "cm"(币本位合约)
            side (str): 买卖方向，只能为 "BUY" 或 "SELL"
            position_side (str): 持仓方向，只能为 "LONG" 或 "SHORT"
            out_price_rate (float): 价格偏移比例，默认0.03，表示3%

        Returns:
            float: 超价限价价格
        """
        data = self.get_ticker_price(symbol, symbol_type)
        if isinstance(data, list):
            tick_price = Decimal(data[0]["price"])
        else:
            tick_price = Decimal(data["price"])

        rate_decimal = Decimal(str(out_price_rate))
        up_rate = Decimal("1") + rate_decimal
        down_rate = Decimal("1") - rate_decimal

        if side == "BUY" and position_side == "LONG":
            # 开多
            round_direction = "DOWN"
            out_limit_price = tick_price * up_rate
        elif side == "SELL" and position_side == "LONG":
            # 平多
            round_direction = "UP"
            out_limit_price = tick_price * down_rate
        elif side == "SELL" and position_side == "SHORT":
            # 开空，价格更高点好
            round_direction = "UP"
            out_limit_price = tick_price * down_rate
        elif side == "BUY" and position_side == "SHORT":
            # 平空，价格更低点好
            round_direction = "DOWN"
            out_limit_price = tick_price * up_rate
        else:
            raise ValueError(f"Invalid side: {side}, position_side: {position_side}")

        # 获取price filter 规则
        if symbol_type == "um":
            symbol_filter = self.um_exchange_info_df[
                self.um_exchange_info_df["symbol"] == symbol
            ]["filters"].iloc[0]
        elif symbol_type == "cm":
            symbol_filter = self.cm_exchange_info_df[
                self.cm_exchange_info_df["symbol"] == symbol
            ]["filters"].iloc[0]
        elif symbol_type == "margin":
            symbol_filter = self.margin_exchange_info_df[
                self.margin_exchange_info_df["symbol"] == symbol
            ]["filters"].iloc[0]
        elif symbol_type == "spot":
            symbol_filter = self.spot_exchange_info_df[
                self.spot_exchange_info_df["symbol"] == symbol
            ]["filters"].iloc[0]
        else:
            raise ValueError(f"Invalid symbol type: {symbol_type}")

        for filter in symbol_filter:
            if filter["filterType"] == "PRICE_FILTER":
                min_price = Decimal(filter["minPrice"])
                max_price = Decimal(filter["maxPrice"])
                tick_size = Decimal(filter["tickSize"])
                if symbol_type == "cm":
                    adjust_out_limit_price = adjust_to_price_filter(
                        out_limit_price,
                        min_price,
                        max_price,
                        tick_size,
                        round_direction,
                    )
                    print(out_limit_price, adjust_out_limit_price)
                    return adjust_out_limit_price
                return adjust_to_price_filter(
                    out_limit_price, min_price, max_price, tick_size, round_direction
                )

    def get_ajusted_quantity(self, symbol, symbol_type, qty):
        # 获取lot size filter 规则
        if symbol_type == "um":
            symbol_filter = self.um_exchange_info_df[
                self.um_exchange_info_df["symbol"] == symbol
            ]["filters"].iloc[0]
        elif symbol_type == "cm":
            symbol_filter = self.cm_exchange_info_df[
                self.cm_exchange_info_df["symbol"] == symbol
            ]["filters"].iloc[0]
        elif symbol_type == "margin":
            symbol_filter = self.margin_exchange_info_df[
                self.margin_exchange_info_df["symbol"] == symbol
            ]["filters"].iloc[0]
        else:
            raise ValueError(f"Invalid symbol type: {symbol_type}")

        for filter in symbol_filter:
            if filter["filterType"] == "LOT_SIZE":
                min_qty = Decimal(filter["minQty"])
                max_qty = Decimal(filter["maxQty"])
                step_size = Decimal(filter["stepSize"])
                if symbol_type == "cm":
                    org_qty = qty
                    ajust_qty = adjust_to_lot_size(
                        qty,
                        min_qty,
                        max_qty,
                        step_size,
                    )
                    print(org_qty, ajust_qty)
                    return ajust_qty
                else:
                    return adjust_to_lot_size(
                        qty,
                        min_qty,
                        max_qty,
                        step_size,
                    )

    def get_price_filter(self, symbol, symbol_type):
        if symbol_type == "um":
            symbol_filter = self.um_exchange_info_df[
                self.um_exchange_info_df["symbol"] == symbol
            ]["filters"].iloc[0]
        else:
            raise ValueError(f"Invalid symbol type: {symbol_type}")

        for filter in symbol_filter:
            if filter["filterType"] == "PRICE_FILTER":
                return {
                    "minPrice": Decimal(filter["minPrice"]),
                    "maxPrice": Decimal(filter["maxPrice"]),
                    "tickSize": Decimal(filter["tickSize"]),
                }
        raise ValueError(f"No price filter found for symbol: {symbol}")

    def get_lot_size_filter(self, symbol, symbol_type):
        if symbol_type == "um":
            symbol_filter = self.um_exchange_info_df[
                self.um_exchange_info_df["symbol"] == symbol
            ]["filters"].iloc[0]
        else:
            raise ValueError(f"Invalid symbol type: {symbol_type}")

        for filter in symbol_filter:
            if filter["filterType"] == "LOT_SIZE":
                return {
                    "minQty": Decimal(filter["minQty"]),
                    "maxQty": Decimal(filter["maxQty"]),
                    "stepSize": Decimal(filter["stepSize"]),
                }
        raise ValueError(f"No lot size filter found for symbol: {symbol}")

    def query_um_trades(
        self,
        symbol,
        order_id=None,
        start_time=None,
        end_time=None,
        from_id=None,
        limit=1000,
    ):
        """
        获取某交易对的成交历史

        参数:
            symbol (str): 交易对，例如 'BTCUSDT'
            order_id (int, optional): 订单编号
            start_time (int/datetime, optional): 起始时间 (时间戳或datetime对象)
            end_time (int/datetime, optional): 结束时间 (时间戳或datetime对象)
            from_id (int, optional): 返回该fromId及之后的成交
            limit (int, optional): 返回的结果集数量，默认1000，最大1000

        返回:
            pandas.DataFrame: 包含成交历史的DataFrame
        """
        all_trades = []
        while True:
            # 处理参数
            params = {"symbol": symbol, "limit": min(limit, 1000)}

            if order_id:
                params["orderId"] = order_id

            # 处理datetime对象
            if start_time:
                if isinstance(start_time, datetime):
                    start_time = int(start_time.timestamp() * 1000)
                params["startTime"] = start_time

            if end_time:
                if isinstance(end_time, datetime):
                    end_time = int(end_time.timestamp() * 1000)
                params["endTime"] = end_time

            if from_id:
                params["fromId"] = from_id

            try:
                # 调用币安API
                trades = self.exchange.fapiprivate_get_usertrades(params=params)

                if not trades:
                    break

                all_trades.extend(trades)

                # 如果返回的记录数少于limit，说明已经获取完毕
                if len(trades) < limit:
                    break

                # 更新from_id为最后一条记录的id
                from_id = trades[-1]["id"]

            except Exception as e:
                print(f"获取成交历史时出错: {e}")
                break

        # 转换为DataFrame并处理
        if all_trades:
            df = pd.DataFrame(all_trades)
            # 转换时间戳为datetime
            df["time"] = pd.to_datetime(df["time"].astype(int), unit="ms")
            # 将数值字段转换为浮点数
            numeric_columns = ["price", "qty", "quoteQty", "realizedPnl", "commission"]
            for col in numeric_columns:
                if col in df.columns:
                    df[col] = df[col].astype(float)
            return df
        else:
            return pd.DataFrame()

    def get_um_position_risk(self, symbol=None):
        """
        获取币安U本位期货账户的持仓风险信息

        参数:
            symbol (str, optional): 交易对，例如 'BTCUSDT'

        返回:
            pandas.DataFrame: 包含持仓风险信息的DataFrame
        """
        params = {}

        if symbol:
            params["symbol"] = symbol

        position_risk = self.exchange.fapiprivatev2_get_positionrisk(params=params)

        if position_risk:
            df = pd.DataFrame(position_risk)

            # 将数值字段转换为适当的数据类型
            numeric_columns = [
                "entryPrice",
                "breakEvenPrice",
                "isolatedMargin",
                "leverage",
                "liquidationPrice",
                "markPrice",
                "maxNotionalValue",
                "positionAmt",
                "notional",
                "isolatedWallet",
                "unRealizedProfit",
                "notionalValue",
            ]

            for col in numeric_columns:
                if col in df.columns:
                    df[col] = df[col].astype(float)
            df = df[df["positionAmt"] != 0]
            return df
        else:
            return pd.DataFrame()

    def get_um_account_info(self):
        """
        获取U本位账户信息
        """
        return self.exchange.fapiprivatev3_get_account()

    def query_all_um_open_orders(self, symbol: str):
        """
        查询U本位所有未成交订单
        """
        return self.exchange.fapiprivate_get_openorders(params={"symbol": symbol})
