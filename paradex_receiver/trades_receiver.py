"""
Paradex WebSocket 交易数据接收器
"""

import json
import logging
import ssl
import time
import threading
from typing import Callable, List, Optional

from .data_types import TardisTrade, ParadexTradeMessage

logger = logging.getLogger(__name__)

WS_URL = "wss://ws.api.prod.paradex.trade/v1"


class ParadexTradesReceiver:
    """
    Paradex WebSocket 交易数据接收器

    使用示例:
        def on_trade(trade: TardisTrade):
            print(f"Trade: {trade.symbol} {trade.side} {trade.price} {trade.amount}")

        receiver = ParadexTradesReceiver(
            symbols=["PAXG-USD-PERP"],
            bearer_token="your_token"
        )
        receiver.on_trade = on_trade
        receiver.start()
    """

    def __init__(
        self,
        symbols: List[str],
        bearer_token: str,
        reconnect_interval: float = 5.0,
        ping_interval: int = 30,  # 更频繁的 ping
        ping_timeout: int = 10,   # 更短的超时
        heartbeat_timeout: int = 120,  # 更短的心跳超时
    ):
        self.symbols = symbols
        self.bearer_token = bearer_token
        self.reconnect_interval = reconnect_interval
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        self.heartbeat_timeout = heartbeat_timeout

        self._running = False
        self._ws = None
        self._last_message_time = 0
        self._heartbeat_thread = None
        self._ping_thread = None
        self._ping_counter = 0

        # 回调函数
        self.on_trade: Optional[Callable[[TardisTrade], None]] = None
        self.on_error: Optional[Callable[[Exception], None]] = None

    def _handle_trade_data(self, data: dict):
        """处理交易数据"""
        try:
            # 检查是否是 trades 数据
            params = data.get("params", {})
            channel = params.get("channel", "")
            
            if not channel.startswith("trades."):
                return
                
            message = ParadexTradeMessage.from_ws_message(data)
            current_time_us = int(time.time() * 1_000_000)
            
            # 转换为 Tardis 交易格式
            trade = message.to_tardis_trade(current_time_us)

            # 交易回调
            if self.on_trade:
                self.on_trade(trade)

        except Exception as e:
            logger.error(f"Error handling trade data: {e}", exc_info=True)
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

    def _ping_loop(self, ws_ref):
        """定期发送应用层 ping 消息"""
        while self._running:
            time.sleep(30)  # 每30秒发送一次 ping
            # 检查 ws 是否还是同一个连接
            if not self._running or self._ws is not ws_ref:
                break
            try:
                self._ping_counter += 1
                ping_msg = {
                    "jsonrpc": "2.0",
                    "method": "ping",
                    "id": f"ping_{self._ping_counter}"
                }
                ws_ref.send(json.dumps(ping_msg))
                logger.debug(f"Sent application ping {self._ping_counter}")
            except Exception as e:
                logger.error(f"Failed to send ping: {e}")
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
            
            # 先进行认证
            auth_msg = {
                "jsonrpc": "2.0",
                "method": "auth",
                "params": {
                    "bearer": self.bearer_token
                },
                "id": 0
            }
            ws.send(json.dumps(auth_msg))
            logger.info("Sent authentication")
            
            # 订阅各个symbol的交易数据
            for i, symbol in enumerate(self.symbols, 1):
                channel = f"trades.{symbol}"
                subscribe_msg = {
                    "jsonrpc": "2.0",
                    "method": "subscribe",
                    "params": {
                        "channel": channel
                    },
                    "id": i
                }
                ws.send(json.dumps(subscribe_msg))
                logger.info(f"Subscribed to {symbol} trades with channel: {channel}")

        def on_message(ws, message):
            self._last_message_time = time.time()
            try:
                data = json.loads(message)
                
                # 检查消息类型
                if "method" in data and data["method"] == "subscription":
                    # 这是订阅数据
                    self._handle_trade_data(data)
                elif "method" in data and data["method"] == "ping":
                    # 服务器发送 ping，需要回复 pong
                    pong_msg = {
                        "jsonrpc": "2.0",
                        "method": "pong",
                        "id": data.get("id")
                    }
                    ws.send(json.dumps(pong_msg))
                    logger.debug("Received ping, sent pong")
                elif "method" in data and data["method"] == "pong":
                    logger.debug("Received pong")
                elif "result" in data:
                    # 这是认证或订阅确认响应
                    logger.info(f"Response: {data}")
                elif "error" in data:
                    # 错误响应
                    logger.error(f"Server error: {data}")
                    
            except Exception as e:
                logger.error(f"Error processing message: {e}", exc_info=True)
                if self.on_error:
                    self.on_error(e)

        def on_error(ws, error):
            logger.error(f"WebSocket error: {error}")
            if self.on_error:
                self.on_error(error)

        def on_ping(ws, message):
            logger.debug("Received WebSocket ping, sending pong")
            self._last_message_time = time.time()
            # websocket-client 会自动回复 pong

        def on_pong(ws, message):
            logger.debug("Received WebSocket pong")
            self._last_message_time = time.time()

        def on_close(ws, close_status_code, close_msg):
            logger.info(f"WebSocket closed: {close_status_code} - {close_msg}")

        # 创建 SSL context，使用更宽松的设置
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = True
        ssl_context.verify_mode = ssl.CERT_REQUIRED
        # 设置更长的超时
        ssl_context.timeout = 30

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
                
                # 启动 ping 线程
                self._ping_thread = threading.Thread(target=self._ping_loop, args=(self._ws,), daemon=True)
                self._ping_thread.start()

                # 运行 WebSocket 连接，使用更保守的设置
                self._ws.run_forever(
                    ping_interval=self.ping_interval,
                    ping_timeout=self.ping_timeout,
                    sslopt={"context": ssl_context},
                    skip_utf8_validation=True,
                    reconnect=5,  # 自动重连间隔
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
        logger.info("Stopping receiver...")
        self._running = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass