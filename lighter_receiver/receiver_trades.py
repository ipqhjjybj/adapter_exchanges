"""
Lighter DEX WebSocket 交易数据接收器 (同步模式)
"""

import json
import logging
import ssl
import time
import threading
from typing import Callable, Dict, List, Optional

from .data_types import LighterTrade

logger = logging.getLogger(__name__)

WS_URL = "wss://mainnet.zklighter.elliot.ai/stream"


class LighterTradesReceiver:
    """
    Lighter DEX 交易数据 WebSocket 接收器 (同步模式)

    使用示例:
        def on_trade(trade: LighterTrade):
            print(f"Trade: {trade.price} {trade.amount}")

        receiver = LighterTradesReceiver(
            market_ids=[0, 1],
            market_symbol_map={0: "ETHUSDT", 1: "BTCUSDT"}
        )
        receiver.on_trade = on_trade
        receiver.start()
    """

    def __init__(
        self,
        market_ids: List[int],
        market_symbol_map: Optional[Dict[int, str]] = None,
        reconnect_interval: float = 5.0,
        ping_interval: int = 60,
        ping_timeout: int = 30,
        heartbeat_timeout: int = 180,
    ):
        self.market_ids = market_ids
        self.market_symbol_map = market_symbol_map or {}
        self.reconnect_interval = reconnect_interval
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        self.heartbeat_timeout = heartbeat_timeout

        self._running = False
        self._ws = None
        self._last_message_time = 0
        self._heartbeat_thread = None

        # 回调函数
        self.on_trade: Optional[Callable[[LighterTrade], None]] = None
        self.on_error: Optional[Callable[[Exception], None]] = None

    def _get_symbol(self, market_id: int) -> str:
        """获取市场符号"""
        return self.market_symbol_map.get(market_id, f"MARKET_{market_id}")

    def _handle_trade(self, market_id: int, trade_data: dict, local_timestamp: int):
        """处理单笔交易

        Args:
            market_id: 市场ID
            trade_data: 交易数据
            local_timestamp: 本地时间戳(微秒)
        """
        try:
            # is_maker_ask: 如果为 true，说明 ask 方是 maker，taker 是 buyer
            # is_maker_ask: 如果为 false，说明 bid 方是 maker，taker 是 seller
            is_maker_ask = trade_data.get("is_maker_ask", False)
            side = "buy" if is_maker_ask else "sell"

            # timestamp 是秒级时间戳 (如 1722339648)，需要转换为微秒
            raw_timestamp = trade_data.get("timestamp", 0)
            # 判断时间戳是秒还是毫秒/微秒：秒级时间戳约为 10 位数
            if raw_timestamp > 1e15:  # 微秒
                timestamp_us = raw_timestamp
            elif raw_timestamp > 1e12:  # 毫秒
                timestamp_us = raw_timestamp * 1_000
            else:  # 秒
                timestamp_us = raw_timestamp * 1_000_000

            trade = LighterTrade(
                exchange="lighter",
                symbol=self._get_symbol(market_id),
                timestamp=timestamp_us,
                local_timestamp=local_timestamp,
                trade_id=trade_data.get("trade_id", 0),
                side=side,
                price=trade_data.get("price", "0"),
                amount=trade_data.get("size", "0"),
            )

            if self.on_trade:
                self.on_trade(trade)

        except Exception as e:
            logger.error(f"Error handling trade: {e}", exc_info=True)
            if self.on_error:
                self.on_error(e)

    def _heartbeat_loop(self, ws_ref):
        """心跳检测线程：检查是否长时间没收到消息"""
        while self._running:
            time.sleep(60)
            # 检查 ws 是否还是同一个连接
            if not self._running or self._ws is not ws_ref:
                break
            # 如果超过 heartbeat_timeout 秒没收到消息，主动关闭连接触发重连
            if self._last_message_time > 0:
                elapsed = time.time() - self._last_message_time
                if elapsed > self.heartbeat_timeout:
                    logger.warning(f"No message received for {elapsed:.1f}s (timeout: {self.heartbeat_timeout}s), closing connection...")
                    try:
                        ws_ref.close()
                    except Exception:
                        pass
                    break

    def start(self):
        """启动接收器 (阻塞)"""
        try:
            import websocket
        except ImportError:
            logger.error("websocket-client not installed: pip install websocket-client")
            raise

        self._running = True

        def on_open(ws):
            logger.info("WebSocket connected")
            self._last_message_time = time.time()
            for market_id in self.market_ids:
                subscribe_msg = {"type": "subscribe", "channel": f"trade/{market_id}"}
                ws.send(json.dumps(subscribe_msg))
                logger.info(f"Subscribed to trades for market {market_id}")

        def on_message(ws, message):
            self._last_message_time = time.time()
            local_timestamp = int(time.time() * 1_000_000)  # 微秒
            try:
                data = json.loads(message)
                msg_type = data.get("type", "")

                # 处理交易更新消息
                if msg_type == "update/trade":
                    channel = data.get("channel", "")
                    market_id = int(channel.split(":")[1]) if ":" in channel else 0
                    trades = data.get("trades", [])
                    for trade_data in trades:
                        self._handle_trade(market_id, trade_data, local_timestamp)
                elif msg_type == "ping":
                    # 服务器发送应用层 ping，需要回复 pong
                    ws.send(json.dumps({"type": "pong"}))
                    logger.debug("Received ping, sent pong")
                elif msg_type == "pong":
                    logger.debug("Received pong")
                elif msg_type == "error":
                    logger.error(f"Server error: {data}")
            except Exception as e:
                logger.error(f"Error processing message: {e}", exc_info=True)
                if self.on_error:
                    self.on_error(e)

        def on_error(ws, error):
            logger.error(f"WebSocket error: {error}")
            if self.on_error:
                self.on_error(error)

        def on_close(ws, close_status_code, close_msg):
            logger.info(f"WebSocket closed: {close_status_code} - {close_msg}")

        def on_ping(ws, message):
            logger.debug("Received ping, sending pong")
            self._last_message_time = time.time()
            # websocket-client 会自动回复 pong

        def on_pong(ws, message):
            logger.debug("Received pong")
            self._last_message_time = time.time()

        # 创建 SSL context，放宽一些限制
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = True
        ssl_context.verify_mode = ssl.CERT_REQUIRED

        while self._running:
            try:
                self._ws = websocket.WebSocketApp(
                    WS_URL,
                    on_open=on_open,
                    on_message=on_message,
                    on_error=on_error,
                    on_close=on_close,
                    on_ping=on_ping,
                    on_pong=on_pong,
                )

                # 启动心跳检测线程
                self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, args=(self._ws,), daemon=True)
                self._heartbeat_thread.start()

                # 使用更宽松的 ping 设置，并添加 skip_utf8_validation 提高性能
                self._ws.run_forever(
                    ping_interval=self.ping_interval,
                    ping_timeout=self.ping_timeout,
                    sslopt={"context": ssl_context},
                    skip_utf8_validation=True,
                )
            except websocket.WebSocketException as e:
                logger.error(f"WebSocket exception: {e}")
            except ssl.SSLError as e:
                logger.error(f"SSL error: {e}")
            except Exception as e:
                logger.error(f"WebSocket connection failed: {e}", exc_info=True)
            finally:
                self._ws = None

            if self._running:
                logger.info(f"Reconnecting in {self.reconnect_interval}s...")
                time.sleep(self.reconnect_interval)

    def stop(self):
        """停止接收器"""
        logger.info("Stopping trades receiver...")
        self._running = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
