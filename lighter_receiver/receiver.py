"""
Lighter DEX WebSocket 深度数据接收器 (同步模式)
"""

import json
import logging
import ssl
import time
import threading
from typing import Callable, Dict, List, Optional

from .data_types import TardisL2Update, TardisL2Snapshot, LighterOrderBookMessage
from .converter import LighterToTardisConverter

logger = logging.getLogger(__name__)

WS_URL = "wss://mainnet.zklighter.elliot.ai/stream"


class LighterDepthReceiver:
    """
    Lighter DEX 深度数据 WebSocket 接收器 (同步模式)

    使用示例:
        def on_update(update: TardisL2Update):
            print(f"Update: {update.price} {update.amount}")

        receiver = LighterDepthReceiver(
            market_ids=[0, 1],
            market_symbol_map={0: "ETHUSDT", 1: "BTCUSDT"}
        )
        receiver.on_update = on_update
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

        self.converter = LighterToTardisConverter(self.market_symbol_map)
        self._running = False
        self._ws = None
        self._last_message_time = 0
        self._heartbeat_thread = None

        # 回调函数
        self.on_snapshot: Optional[Callable[[TardisL2Snapshot], None]] = None
        self.on_update: Optional[Callable[[TardisL2Update], None]] = None
        self.on_error: Optional[Callable[[Exception], None]] = None

    def _handle_orderbook_update(self, market_id: int, order_book: dict, timestamp: int = 0, is_snapshot: bool = False):
        """处理订单簿更新

        Args:
            market_id: 市场ID
            order_book: 订单簿数据
            timestamp: 时间戳
            is_snapshot: 是否为快照消息(subscribed/order_book类型)
        """
        try:
            ws_data = {
                "channel": f"order_book:{market_id}",
                "offset": order_book.get("offset", 0),
                "order_book": order_book,
                "timestamp": timestamp,
            }

            message = LighterOrderBookMessage.from_ws_message(ws_data)

            if is_snapshot:
                # subscribed/order_book 消息作为快照处理
                snapshot = self.converter.convert_to_snapshot(message)

                # 快照回调
                if self.on_snapshot:
                    self.on_snapshot(snapshot)

                # 快照也需要转换为带 is_snapshot=True 的更新
                if self.on_update:
                    updates = snapshot.to_updates()
                    for update in updates:
                        self.on_update(update)
            else:
                # update/order_book 消息作为增量更新处理
                if self.on_update:
                    updates = self.converter.convert_to_incremental_updates(message, is_first_message=False)
                    for update in updates:
                        self.on_update(update)

        except Exception as e:
            logger.error(f"Error handling orderbook update: {e}", exc_info=True)
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
                subscribe_msg = {"type": "subscribe", "channel": f"order_book/{market_id}"}
                ws.send(json.dumps(subscribe_msg))
                logger.info(f"Subscribed to market {market_id}")

        def on_message(ws, message):
            self._last_message_time = time.time()
            try:
                data = json.loads(message)
                #print(data)
                msg_type = data.get("type", "")
                # 处理订阅确认消息(快照)和增量更新消息
                if msg_type in ("subscribed/order_book", "update/order_book"):
                    channel = data.get("channel", "")
                    market_id = int(channel.split(":")[1]) if ":" in channel else 0
                    order_book = data.get("order_book", {})
                    timestamp = data.get("timestamp", 0)
                    is_snapshot = (msg_type == "subscribed/order_book")
                    self._handle_orderbook_update(market_id, order_book, timestamp, is_snapshot)
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
        logger.info("Stopping receiver...")
        self._running = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
