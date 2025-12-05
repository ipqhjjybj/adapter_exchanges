
import asyncio
import websockets
import json

# 异步WebSocket客户端函数
async def websocket_client():
    # 连接WebSocket服务器（示例使用公共测试服务器，也可替换为自己的服务器地址）
    uri = "wss://mainnet.zklighter.elliot.ai/stream"  # 回声服务器：发送什么返回什么
    async with websockets.connect(uri) as websocket:
        # 1. 发送消息到服务器
        market_id = 48
        message = json.dumps({"type": "subscribe", "channel": f"order_book/{market_id}"})
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