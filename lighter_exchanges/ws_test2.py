
import asyncio
import websockets
import json

# 异步WebSocket客户端函数
async def websocket_client():
    # 连接WebSocket服务器（示例使用公共测试服务器，也可替换为自己的服务器地址）
    uri = "wss://mainnet.zklighter.elliot.ai/stream"  # 回声服务器：发送什么返回什么
    async with websockets.connect(uri) as websocket:

        message = json.dumps({
            "type": "jsonapi/sendtx",
            "data": {
                "tx_type": 0,
                "tx_info": {
                    "hash": "0xabc123456789def",
                    "type": 56,
                    "info": "{\"AccountIndex\":1,\"ApiKeyIndex\":2,\"MarketIndex\":3,\"Index\":404,\"ExpiredAt\":1700000000000,\"Nonce\":1234,\"Sig\":\"0xsigexample\"}",
                    "event_info": "{\"a\":1,\"i\":404,\"u\":123,\"ae\":\"\"}",
                    "status": 2,
                    "transaction_index": 10,
                    "l1_address": "0x123abc456def789",
                    "account_index": 101,
                    "nonce": 12345,
                    "expire_at": 1700000000000,
                    "block_height": 1500000,
                    "queued_at": 1699999990000,
                    "executed_at": 1700000000005,
                    "sequence_index": 5678,
                    "parent_hash": "0xparenthash123456"
                }
            }
        })
        # 1. 发送消息到服务器
        # market_id = 48
        # message = json.dumps({"type": "subscribe", "channel": f"order_book/{market_id}"})
        await websocket.send(message)
        print(f"已发送: {message}")

        # 2. 接收服务器返回的消息
        response = await websocket.recv()
        print(f"收到回复: {response}")

        # 可选：持续收发消息（示例）
        while True:
            user_input = input("请输入要发送的消息（输入exit退出）：")
            if user_input.lower() == "exit":
                break
            await websocket.send(user_input)
            res = await websocket.recv()
            print(f"服务器回复: {res}")

# 运行客户端
if __name__ == "__main__":
    asyncio.run(websocket_client())