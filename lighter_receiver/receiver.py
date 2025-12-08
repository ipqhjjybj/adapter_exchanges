"""
Lighter DEX WebSocket 深度数据接收器 (同步模式)
"""

import json
import logging
import time
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
        ping_interval: int = 30,
        ping_timeout: int = 10,
    ):
        self.market_ids = market_ids
        self.market_symbol_map = market_symbol_map or {}
        self.reconnect_interval = reconnect_interval
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout

        self.converter = LighterToTardisConverter(self.market_symbol_map)
        self._running = False

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
            for market_id in self.market_ids:
                subscribe_msg = {"type": "subscribe", "channel": f"order_book/{market_id}"}
                ws.send(json.dumps(subscribe_msg))
                logger.info(f"Subscribed to market {market_id}")

        def on_message(ws, message):
            try:
                data = json.loads(message)
                msg_type = data.get("type", "")
                # 处理订阅确认消息(快照)和增量更新消息
                if msg_type in ("subscribed/order_book", "update/order_book"):
                    channel = data.get("channel", "")
                    market_id = int(channel.split(":")[1]) if ":" in channel else 0
                    order_book = data.get("order_book", {})
                    timestamp = data.get("timestamp", 0)
                    is_snapshot = (msg_type == "subscribed/order_book")
                    self._handle_orderbook_update(market_id, order_book, timestamp, is_snapshot)
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

        while self._running:
            try:
                ws = websocket.WebSocketApp(
                    WS_URL,
                    on_open=on_open,
                    on_message=on_message,
                    on_error=on_error,
                    on_close=on_close,
                )
                ws.run_forever(ping_interval=self.ping_interval, ping_timeout=self.ping_timeout)
            except Exception as e:
                logger.error(f"WebSocket connection failed: {e}", exc_info=True)

            if self._running:
                logger.info(f"Reconnecting in {self.reconnect_interval}s...")
                time.sleep(self.reconnect_interval)
                self.converter.reset_state()  # 重连时重置状态

    def stop(self):
        """停止接收器"""
        logger.info("Stopping receiver...")
        self._running = False
