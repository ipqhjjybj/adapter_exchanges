import pandas as pd
import time
import MetaTrader5 as mt5
from datetime import datetime, timedelta
from src.log_kit import logger


class MT5API:
    def __init__(self, login, password, server, path):
        self.login = login
        self.password = password
        self.server = server
        self.path = path
        self.logger = logger

    def connect(self):
        """连接到MT5服务器"""

        # 建立MetaTrader 5到指定交易账户的连接
        if not mt5.initialize(
            path=self.path,  # MT5程序路径
            login=self.login,
            password=self.password,
            server=self.server,
            timeout=60000,  # 超时时间设置为60秒
        ):
            print("initialize() failed, error code =", mt5.last_error())
            return False

        return True

    def get_account_info(self):
        """获取账户信息"""
        # 连接到指定密码和服务器的交易账户
        account_info = mt5.account_info()
        return {
            "login": account_info.login,  # 登录号
            "leverage": account_info.leverage,  # 账户杠杆
            "trade_allowed": account_info.trade_allowed,  # 交易权限
            "balance": account_info.balance,  # 基本不用
            "equity": account_info.equity,  # 净值
            "margin": account_info.margin,  # 保证金
            "margin_free": account_info.margin_free,  # 可用保证金
            "margin_level": account_info.margin_level,  # 保证金率, 单位是%
            "profit": account_info.profit,  # 浮动盈亏
        }

    def get_book_price(self, symbol):
        """获取指定交易对的最新价格和买卖盘信息"""
        try:
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                self.logger.error(f"获取{symbol}价格失败")
                return None

            # 获取订单簿信息
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info is None:
                self.logger.error(f"获取{symbol}信息失败")
                return None

            return {
                "symbol": symbol,
                "last": tick.last,  # 最新成交价
                "time": tick.time_msc,
                "bid_price": tick.bid,  # 最高买价
                "ask_price": tick.ask,  # 最低卖价
                "bid_volume": symbol_info.volume_min,  # 最小交易量
                "ask_volume": symbol_info.volume_max,  # 最大交易量
            }
        except Exception as e:
            self.logger.error(f"获取价格失败: {e}")
            return None

    def open_position_use_market_order(self, symbol, side, position_side, volume):
        """
        市价单开仓

        参数:
            symbol (str): 交易品种
            side (str): 交易方向 "BUY" 或 "SELL"
            position_side (str): 持仓方向 "LONG" 或 "SHORT"
            volume (float): 交易量

        返回:
            order: 订单结果，如果失败返回None
        """
        # 根据side和position_side确定开仓方向和价格
        if position_side == "LONG":
            if side == "BUY":
                order_type = mt5.ORDER_TYPE_BUY
                price = mt5.symbol_info_tick(symbol).ask  # 做多用ask价
            else:
                print("做多仓位不能用SELL指令开仓")
                return None
        else:  # SHORT
            if side == "SELL":
                order_type = mt5.ORDER_TYPE_SELL
                price = mt5.symbol_info_tick(symbol).bid  # 做空用bid价
            else:
                print("做空仓位不能用BUY指令开仓")
                return None

        # 准备开仓请求
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(volume),
            "type": order_type,
            "price": price,
            "deviation": 20,
            "magic": 234000,
            "comment": f"python script open {position_side}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        # 发送订单
        order = mt5.order_send(request)

        if order.retcode != mt5.TRADE_RETCODE_DONE:
            print(f"开仓失败，错误代码: {order.retcode}")
            return None

        return {
            "ticket": order.order,
            "volume": order.volume,
            "price": order.price,
            "side": side,
            "position_side": position_side,
            "request": request,
        }

    def get_positions(self, symbol=None, group=None, ticket=None):
        """
        获取未结持仓信息

        参数:
            symbol (str, optional): 交易品种名称
            group (str, optional): 交易品种组过滤器，例如 "*USD*"
            ticket (int, optional): 持仓单号

        返回:
            list: 持仓信息列表，每个持仓是一个字典
        """
        # 根据不同参数获取持仓
        if ticket is not None:
            positions = mt5.positions_get(ticket=ticket)
        elif symbol is not None:
            positions = mt5.positions_get(symbol=symbol)
        elif group is not None:
            positions = mt5.positions_get(group=group)
        else:
            positions = mt5.positions_get()

        if positions is None or len(positions) == 0:
            # self.logger.info("没有找到持仓")
            return []

        # return positions
        # 转换持仓信息为字典列表
        positions_list = []
        for position in positions:
            pos_dict = position._asdict()
            positions_list.append(
                {
                    "ticket": pos_dict["ticket"],  # 持仓单号
                    "time": pd.to_datetime(pos_dict["time"], unit="s"),  # 建仓时间
                    "type": (
                        "BUY" if pos_dict["type"] == mt5.ORDER_TYPE_BUY else "SELL"
                    ),  # 持仓类型
                    "volume": pos_dict["volume"],  # 持仓量
                    "symbol": pos_dict["symbol"],  # 交易品种
                    "price_open": pos_dict["price_open"],  # 开仓价格
                    "price_current": pos_dict["price_current"],  # 当前价格
                    "sl": pos_dict["sl"],  # 止损价格
                    "tp": pos_dict["tp"],  # 止盈价格
                    "profit": pos_dict["profit"],  # 浮动盈亏
                    "swap": pos_dict["swap"],  # 过夜费
                    "magic": pos_dict["magic"],  # EA编号
                    "comment": pos_dict["comment"],  # 注释
                    "identifier": pos_dict["identifier"],  # 持仓标识符
                }
            )

        return positions_list

    def get_position_ids(self, symbol=None):
        """
        获取指定品种或所有品种的持仓ID列表

        参数:
            symbol (str, optional): 交易品种名称，如果不指定则获取所有持仓

        返回:
            list: 持仓ID列表
        """
        try:
            positions = self.get_positions(symbol=symbol)
            if not positions:
                return []

            return [pos["ticket"] for pos in positions]

        except Exception as e:
            self.logger.error(f"获取持仓ID失败: {e}")
            return None

    def get_total_volume(self, symbol=None):
        """
        获取指定品种或所有品种的总持仓量

        参数:
            symbol (str, optional): 交易品种名称，如果不指定则获取所有持仓

        返回:
            dict: 按方向统计的持仓量，例如 {'BUY': 0.5, 'SELL': 0.3}
        """
        try:
            positions = self.get_positions(symbol=symbol)
            if not positions:
                return {"symbol": symbol, "BUY": 0.0, "SELL": 0.0}

            volumes = {"symbol": symbol, "BUY": 0.0, "SELL": 0.0}
            for pos in positions:
                volumes[pos["type"]] += pos["volume"]

            return volumes

        except Exception as e:
            self.logger.error(f"获取总持仓量失败: {e}")
            return None

    def place_order(
        self,
        symbol,
        order_type,
        volume,
        sl_points=100,
        tp_points=100,
        deviation=20,
        comment="python script",
    ):
        """
        下单函数，包含订单检查

        参数:
            symbol (str): 交易品种
            order_type (str): 订单类型 "BUY" 或 "SELL"
            volume (float): 交易量
            sl_points (int): 止损点数
            tp_points (int): 止盈点数
            deviation (int): 允许的滑点
            comment (str): 订单注释

        返回:
            dict: 订单结果信息，如果失败返回None
        """
        try:
            # 获取交易品种信息
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info is None:
                self.logger.error(f"{symbol} not found")
                return None

            # 如果市场报价中没有此交易品种，添加它
            if not symbol_info.visible:
                if not mt5.symbol_select(symbol, True):
                    self.logger.error(f"symbol_select({symbol}) failed")
                    return None

            point = symbol_info.point

            # 获取当前价格
            tick = mt5.symbol_info_tick(symbol)
            if order_type == "BUY":
                price = tick.ask
                sl = price - sl_points * point if sl_points else 0
                tp = price + tp_points * point if tp_points else 0
                mt5_order_type = mt5.ORDER_TYPE_BUY
            else:  # SELL
                price = tick.bid
                sl = price + sl_points * point if sl_points else 0
                tp = price - tp_points * point if tp_points else 0
                mt5_order_type = mt5.ORDER_TYPE_SELL

            # 准备交易请求
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": float(volume),
                "type": mt5_order_type,
                "price": price,
                "sl": sl,
                "tp": tp,
                "deviation": deviation,
                "magic": 234000,
                "comment": comment,
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }

            # 检查订单
            check_result = mt5.order_check(request)
            if check_result is None:
                self.logger.error(f"订单检查失败: {mt5.last_error()}")
                return None

            # 检查是否有足够的保证金
            if check_result.margin_free < check_result.margin:
                self.logger.error("保证金不足")
                return None

            # 发送订单
            result = mt5.order_send(request)
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                self.logger.error(f"下单失败，错误代码: {result.retcode}")
                return None

            return {
                "ticket": result.order,
                "volume": result.volume,
                "price": result.price,
                "comment": result.comment,
                "request": {
                    "symbol": symbol,
                    "type": order_type,
                    "volume": volume,
                    "price": price,
                    "sl": sl,
                    "tp": tp,
                },
            }

        except Exception as e:
            self.logger.error(f"下单失败: {e}")
            return None

    def close_position_by_id(
        self, position_id, deviation=20, comment="python script close"
    ):
        """
        平仓函数，包含订单检查

        参数:
            position_id (int): 需要平仓的持仓ID
            deviation (int): 允许的滑点
            comment (str): 平仓注释

        返回:
            dict: 平仓结果信息，如果失败返回None
        """
        try:
            # 获取持仓信息
            position = mt5.positions_get(ticket=position_id)
            if position is None or len(position) == 0:
                self.logger.error(f"未找到持仓 #{position_id}")
                return None

            position = position[0]
            symbol = position.symbol
            volume = position.volume

            # 确定平仓方向
            close_type = (
                mt5.ORDER_TYPE_SELL
                if position.type == mt5.ORDER_TYPE_BUY
                else mt5.ORDER_TYPE_BUY
            )

            # 获取当前价格
            price = (
                mt5.symbol_info_tick(symbol).bid
                if position.type == mt5.ORDER_TYPE_BUY
                else mt5.symbol_info_tick(symbol).ask
            )

            # 准备平仓请求
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": volume,
                "type": close_type,
                "position": position_id,
                "price": price,
                "deviation": deviation,
                "magic": 234000,
                "comment": comment,
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }

            # 检查订单
            check_result = mt5.order_check(request)
            if check_result is None:
                self.logger.error(f"平仓订单检查失败: {mt5.last_error()}")
                return None

            # 发送平仓请求
            result = mt5.order_send(request)
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                self.logger.error(f"平仓失败，错误代码: {result.retcode}")
                return None

            return {
                "ticket": result.order,
                "deal": result.deal,
                "volume": result.volume,
                "price": result.price,
                "comment": result.comment,
                "request": {
                    "symbol": symbol,
                    "volume": volume,
                    "price": price,
                    "position_id": position_id,
                },
            }

        except Exception as e:
            self.logger.error(f"平仓操作失败: {e}")
            return None

    def close_partial_position(
        self,
        position_id,
        volume_to_close,
        deviation=20,
        comment="python script partial close",
    ):
        """
        部分平仓函数，包含订单检查

        参数:
            position_id (int): 需要平仓的持仓ID
            volume_to_close (float): 需要平仓的数量
            deviation (int): 允许的滑点
            comment (str): 平仓注释

        返回:
            dict: 平仓结果信息，如果失败返回None
        """
        try:
            # 获取持仓信息
            position = mt5.positions_get(ticket=position_id)
            if position is None or len(position) == 0:
                self.logger.error(f"未找到持仓 #{position_id}")
                return None

            position = position[0]
            symbol = position.symbol
            total_volume = position.volume

            # 检查平仓量是否合法
            if volume_to_close > total_volume:
                self.logger.error(f"平仓量 {volume_to_close} 大于持仓量 {total_volume}")
                return None

            # 确定平仓方向
            close_type = (
                mt5.ORDER_TYPE_SELL
                if position.type == mt5.ORDER_TYPE_BUY
                else mt5.ORDER_TYPE_BUY
            )

            # 获取当前价格
            tick = mt5.symbol_info_tick(symbol)
            price = tick.bid if position.type == mt5.ORDER_TYPE_BUY else tick.ask

            # 准备平仓请求
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": float(volume_to_close),  # 转换为float以确保精度
                "type": close_type,
                "position": position_id,
                "price": price,
                "deviation": deviation,
                "magic": 234000,
                "comment": comment,
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }

            # 检查订单
            check_result = mt5.order_check(request)
            if check_result is None:
                self.logger.error(f"部分平仓订单检查失败: {mt5.last_error()}")
                return None

            # 发送平仓请求
            result = mt5.order_send(request)
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                self.logger.error(f"部分平仓失败，错误代码: {result.retcode}")
                return None

            return {
                "ticket": result.order,  # 平仓订单号
                "deal": result.deal,  # 成交号
                "volume_closed": result.volume,  # 平仓量
                "volume_remaining": total_volume - result.volume,  # 剩余持仓量
                "price": result.price,  # 平仓价格
                "comment": result.comment,  # 注释
                "request": {
                    "symbol": symbol,
                    "volume": volume_to_close,
                    "price": price,
                    "position_id": position_id,
                },
            }

        except Exception as e:
            self.logger.error(f"部分平仓操作失败: {e}")
            return None

    def close_positions_by_type(
        self,
        symbol,
        side,
        position_side,
        volume_to_close,
        deviation=20,
        comment="python script batch close",
    ):
        """
        按方向批量部分平仓

        参数:
            symbol (str): 交易品种
            side (str): 交易方向 "BUY" 或 "SELL"
            position_side (str): 持仓方向 "LONG" 或 "SHORT"
            volume_to_close (float): 需要平仓的总数量
            deviation (int): 允许的滑点
            comment (str): 平仓注释

        返回:
            dict: 平仓结果信息，如果失败返回None
        """
        try:
            # 获取指定品种的所有持仓
            positions = mt5.positions_get(symbol=symbol)
            if positions is None or len(positions) == 0:
                print(f"未找到{symbol}的持仓")
                return None

            # 根据side和position_side确定目标持仓方向
            if position_side == "LONG":
                mt5_position_type = mt5.ORDER_TYPE_BUY
                close_type = mt5.ORDER_TYPE_SELL  # 平多需要卖出
                price = mt5.symbol_info_tick(symbol).bid  # 平多用bid价
            else:  # SHORT
                mt5_position_type = mt5.ORDER_TYPE_SELL
                close_type = mt5.ORDER_TYPE_BUY  # 平空需要买入
                price = mt5.symbol_info_tick(symbol).ask  # 平空用ask价

            # 计算指定方向的总持仓量和持仓列表
            total_volume = 0
            target_positions = []

            for pos in positions:
                if pos.type == mt5_position_type:  # 匹配持仓方向
                    total_volume += pos.volume
                    target_positions.append(pos)

            if total_volume == 0:
                print(f"未找到{symbol}的{position_side}方向持仓")
                return None

            if volume_to_close > total_volume:
                print(f"平仓量 {volume_to_close} 大于总持仓量 {total_volume}")
                return None

            # 开始平仓
            remaining_to_close = volume_to_close
            results = []

            for position in target_positions:
                if remaining_to_close <= 0:
                    break

                # 计算当前持仓需要平仓的数量
                volume_for_this_position = min(remaining_to_close, position.volume)

                # 准备平仓请求
                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": symbol,
                    "volume": float(volume_for_this_position),
                    "type": close_type,
                    "position": position.ticket,
                    "price": price,
                    "deviation": deviation,
                    "magic": 234000,
                    "comment": comment,
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_IOC,
                }

                # 检查订单
                check_result = mt5.order_check(request)
                if check_result is None:
                    print(f"订单检查失败: {mt5.last_error()}")
                    continue

                # 发送平仓请求
                result = mt5.order_send(request)
                if result.retcode != mt5.TRADE_RETCODE_DONE:
                    print(
                        f"平仓失败，持仓ID: {position.ticket}, 错误代码: {result.retcode}"
                    )
                    continue

                results.append(
                    {
                        "ticket": result.order,
                        "deal": result.deal,
                        "volume": result.volume,
                        "price": result.price,
                        "position_id": position.ticket,
                    }
                )

                remaining_to_close -= volume_for_this_position

            if not results:
                return None

            return {
                "side": side,
                "position_side": position_side,
                "total_volume_closed": volume_to_close - remaining_to_close,
                "remaining_volume": total_volume
                - (volume_to_close - remaining_to_close),
                "trades": results,
            }

        except Exception as e:
            print(f"批量平仓操作失败: {e}")
            return None

    def place_market_order(self, symbol, side, position_side, volume):
        """
        统一的市价单交易函数，根据参数自动判断是开仓还是平仓

        交易规则：
        - 开多: BUY/LONG
        - 平多: SELL/LONG
        - 开空: SELL/SHORT
        - 平空: BUY/SHORT

        参数:
            symbol (str): 交易品种
            side (str): 交易方向 "BUY" 或 "SELL"
            position_side (str): 持仓方向 "LONG" 或 "SHORT"
            volume (float): 交易量

        返回:
            dict: 订单结果信息，如果失败返回None
        """
        try:
            # 根据side和position_side确定操作类型
            is_close = (position_side == "LONG" and side == "SELL") or (
                position_side == "SHORT" and side == "BUY"
            )

            if is_close:
                return self.close_market_position(symbol, side, position_side, volume)
            else:
                return self.open_market_position(symbol, side, position_side, volume)

        except Exception as e:
            print(f"交易操作失败: {e}")
            return None

    def open_market_position(self, symbol, side, position_side, volume):
        """
        市价单开仓函数

        参数:
            symbol (str): 交易品种
            side (str): 交易方向 "BUY" 或 "SELL"
            position_side (str): 持仓方向 "LONG" 或 "SHORT"
            volume (float): 交易量

        返回:
            dict: 订单结果信息，如果失败返回None
        """
        try:
            # 确定订单类型和价格
            if side == "BUY":
                order_type = mt5.ORDER_TYPE_BUY
                price = mt5.symbol_info_tick(symbol).ask
            else:  # SELL
                order_type = mt5.ORDER_TYPE_SELL
                price = mt5.symbol_info_tick(symbol).bid

            # 准备开仓请求
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": float(volume),
                "type": order_type,
                "price": price,
                "deviation": 20,
                "magic": 234000,
                "comment": f"python script open {position_side}",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }

            # 发送开仓请求
            result = mt5.order_send(request)
            retry_count = 0
            while result.retcode != mt5.TRADE_RETCODE_DONE and retry_count < 3:
                result = mt5.order_send(request)
                retry_count += 1
                time.sleep(0.5)
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                print(f"开仓失败，错误代码: {result.retcode}")
                return None

            return {
                "type": "open",
                "symbol": symbol,
                "ticket": result.order,  # 订单号
                "deal": result.deal,  # 成交号
                "volume": result.volume,
                "price": result.price,
                "side": side,
                "position_side": position_side,
                "request": request,
            }

        except Exception as e:
            print(f"开仓操作失败: {e}")
            return None

    def close_market_position(self, symbol, side, position_side, volume):
        """
        市价单平仓函数

        参数:
            symbol (str): 交易品种
            side (str): 交易方向 "BUY" 或 "SELL"
            position_side (str): 持仓方向 "LONG" 或 "SHORT"
            volume (float): 交易量

        返回:
            dict: 订单结果信息，如果失败返回None
        """
        try:
            # 确定订单类型和价格
            if side == "BUY":
                order_type = mt5.ORDER_TYPE_BUY
                price = mt5.symbol_info_tick(symbol).ask
            else:  # SELL
                order_type = mt5.ORDER_TYPE_SELL
                price = mt5.symbol_info_tick(symbol).bid

            # 获取要平仓的持仓
            positions = mt5.positions_get(symbol=symbol)
            if positions is None or len(positions) == 0:
                print(f"未找到{symbol}的持仓")
                return None

            # 计算指定方向的总持仓量和持仓列表
            total_volume = 0
            target_positions = []
            mt5_position_type = (
                mt5.ORDER_TYPE_BUY if position_side == "LONG" else mt5.ORDER_TYPE_SELL
            )

            for pos in positions:
                if pos.type == mt5_position_type:
                    total_volume += pos.volume
                    target_positions.append(pos)

            if total_volume == 0:
                print(f"未找到{symbol}的{position_side}方向持仓")
                return None

            if volume > total_volume:
                print(f"平仓量 {volume} 大于总持仓量 {total_volume}")
                return None

            # 开始平仓
            remaining_to_close = volume
            results = []

            for position in target_positions:
                if remaining_to_close <= 0:
                    break

                volume_for_this_position = min(remaining_to_close, position.volume)

                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": symbol,
                    "volume": float(volume_for_this_position),
                    "type": order_type,
                    "position": position.ticket,
                    "price": price,
                    "deviation": 20,
                    "magic": 234000,
                    "comment": f"python script close {position_side}",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_IOC,
                }

                # 发送平仓请求
                result = mt5.order_send(request)
                retry_count = 0
                while result.retcode != mt5.TRADE_RETCODE_DONE and retry_count < 3:
                    result = mt5.order_send(request)
                    retry_count += 1
                    time.sleep(0.5)
                if result.retcode != mt5.TRADE_RETCODE_DONE:
                    print(
                        f"平仓失败，持仓ID: {position.ticket}, 错误代码: {result.retcode}"
                    )
                    continue

                results.append(
                    {
                        "ticket": result.order,
                        "deal": result.deal,
                        "volume": result.volume,
                        "price": result.price,
                        "position_id": position.ticket,
                    }
                )

                remaining_to_close -= volume_for_this_position

            if not results:
                return None

            return {
                "type": "close",
                "side": side,
                "symbol": symbol,
                "position_side": position_side,
                "volume": volume - remaining_to_close,
                "total_volume_closed": volume - remaining_to_close,
                "remaining_volume": total_volume - (volume - remaining_to_close),
                "trades": results,
            }

        except Exception as e:
            print(f"平仓操作失败: {e}")
            return None

    def get_order_info(self, ticket=None, symbol=None, group=None):
        """
        获取订单信息，支持多种查询方式

        参数:
            ticket (int): 订单号，可选
            symbol (str): 交易品种，可选
            group (str): 订单组，可选

        返回:
            dict: 订单信息
        """
        try:
            if ticket:
                # 通过订单号查询
                orders = mt5.orders_get(ticket=ticket)
            elif symbol:
                # 通过交易品种查询
                orders = mt5.orders_get(symbol=symbol)
            elif group:
                # 通过订单组查询，例如 "*USD*" 查询所有美元相关订单
                orders = mt5.orders_get(group=group)
            else:
                # 获取所有活跃订单
                orders = mt5.orders_get()

            if orders is None or len(orders) == 0:
                return None

            # 将订单信息转换为易读格式
            orders_info = []
            for order in orders:
                orders_info.append(
                    {
                        "ticket": order.ticket,
                        "time_setup": order.time_setup,
                        "type": order.type,
                        "state": order.state,
                        "symbol": order.symbol,
                        "volume": order.volume_initial,
                        "price_open": order.price_open,
                        "price_current": order.price_current,
                        "comment": order.comment,
                    }
                )

            return orders_info

        except Exception as e:
            print(f"获取订单信息失败: {e}")
            return None

    def get_deals_info(
        self, ticket=None, position=None, symbol=None, from_date=None, to_date=None
    ):
        """
        获取成交历史，支持多种查询方式

        参数:
            ticket (int): 订单号，可选
            position (int): 持仓号，可选
            symbol (str): 交易品种，可选
            from_date (datetime): 起始时间，可选
            to_date (datetime): 结束时间，可选

        返回:
            dict: 成交历史信息
        """

        try:
            if ticket:
                # 通过订单号查询
                deals = mt5.history_deals_get(ticket=ticket)
            elif position:
                # 通过持仓号查询
                deals = mt5.history_deals_get(position=position)
            elif symbol and from_date and to_date:
                # 通过交易品种和时间范围查询
                deals = mt5.history_deals_get(
                    symbol=symbol, from_date=from_date, to_date=to_date
                )
            else:
                # 获取最近一天的成交历史
                from_date = datetime.now() - timedelta(days=1)
                deals = mt5.history_deals_get(from_date=from_date)

            if deals is None or len(deals) == 0:
                return None

            # 将成交历史转换为易读格式
            deals_info = []
            for deal in deals:
                deals_info.append(
                    {
                        "ticket": deal.ticket,
                        "order": deal.order,  # 对应的订单号
                        "position_id": deal.position_id,  # 对应的持仓号
                        "time": deal.time,
                        "type": deal.type,
                        "entry": deal.entry,  # 0-入场, 1-出场
                        "symbol": deal.symbol,
                        "volume": deal.volume,
                        "price": deal.price,
                        "profit": deal.profit,
                        "comment": deal.comment,
                    }
                )

            return deals_info

        except Exception as e:
            print(f"获取成交历史失败: {e}")
            return None

    def get_history_deals(
        self, from_date=None, to_date=None, group=None, ticket=None, position=None
    ):
        """
        获取历史成交记录，支持多种查询方式

        参数:
            from_date (datetime): 起始时间，可选
            to_date (datetime): 结束时间，可选
            group (str): 交易品种过滤器，例如 "*USD*" 或 "*,!*EUR*,!*GBP*"，可选
            ticket (int): 订单号，可选
            position (int): 持仓号，可选

        返回:
            pandas.DataFrame: 包含所有成交记录的DataFrame，如果没有数据返回None
        """
        try:
            # 根据不同的参数组合选择查询方式
            if ticket is not None:
                # 通过订单号查询
                deals = mt5.history_deals_get(ticket=ticket)
            elif position is not None:
                # 通过持仓号查询
                deals = mt5.history_deals_get(position=position)
            elif from_date and to_date:
                # 通过时间范围和组过滤查询
                if group:
                    deals = mt5.history_deals_get(from_date, to_date, group=group)
                else:
                    deals = mt5.history_deals_get(from_date, to_date)
            else:
                # 如果没有指定参数，默认查询最近一天的记录
                from_date = datetime.now() - timedelta(days=1)
                to_date = datetime.now()
                deals = mt5.history_deals_get(from_date, to_date)

            if deals is None or len(deals) == 0:
                print(f"未找到交易记录，错误代码: {mt5.last_error()}")
                return None

            # 将成交记录转换为DataFrame
            df = pd.DataFrame(list(deals), columns=deals[0]._asdict().keys())

            # 转换时间戳为datetime格式
            df["time"] = pd.to_datetime(df["time"], unit="s")
            df["time_msc"] = pd.to_datetime(df["time_msc"], unit="ms")

            # 添加类型说明
            df["type_desc"] = df["type"].map(
                {
                    mt5.DEAL_TYPE_BUY: "买入",
                    mt5.DEAL_TYPE_SELL: "卖出",
                    mt5.DEAL_TYPE_BALANCE: "余额",
                    mt5.DEAL_TYPE_CREDIT: "信用",
                    mt5.DEAL_TYPE_CHARGE: "手续费",
                    mt5.DEAL_TYPE_CORRECTION: "修正",
                    mt5.DEAL_TYPE_BONUS: "奖金",
                    mt5.DEAL_TYPE_COMMISSION: "佣金",
                    mt5.DEAL_TYPE_COMMISSION_DAILY: "每日佣金",
                    mt5.DEAL_TYPE_COMMISSION_MONTHLY: "每月佣金",
                    mt5.DEAL_TYPE_COMMISSION_AGENT_DAILY: "每日代理佣金",
                    mt5.DEAL_TYPE_COMMISSION_AGENT_MONTHLY: "每月代理佣金",
                    mt5.DEAL_TYPE_INTEREST: "利息",
                    mt5.DEAL_TYPE_BUY_CANCELED: "买入取消",
                    mt5.DEAL_TYPE_SELL_CANCELED: "卖出取消",
                }
            )

            # 添加入场/出场说明
            df["entry_desc"] = df["entry"].map(
                {
                    mt5.DEAL_ENTRY_IN: "入场",
                    mt5.DEAL_ENTRY_OUT: "出场",
                    mt5.DEAL_ENTRY_INOUT: "反向",
                }
            )

            return df

        except Exception as e:
            print(f"获取历史成交记录失败: {e}")
            return None
