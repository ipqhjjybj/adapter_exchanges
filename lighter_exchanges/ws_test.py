import websocket
import threading
import time

# 全局标识：是否保持连接
is_connected = False

def on_open(ws):
    """连接成功后的回调函数"""
    global is_connected
    is_connected = True
    print("✅ WebSocket 连接已建立")
    # 连接成功后立即发送一条测试消息
    ws.send("Hello WebSocket! (from websocket-client)")
    print(f"📤 已发送初始消息: Hello WebSocket! (from websocket-client)")

def on_message(ws, message):
    """接收服务器消息的回调函数"""
    print(f"📥 收到服务器回复: {message}")

def on_error(ws, error):
    """发生错误时的回调函数"""
    print(f"❌ WebSocket 错误: {error}")

def on_close(ws, close_status_code, close_msg):
    """连接关闭时的回调函数"""
    global is_connected
    is_connected = False
    print(f"🔌 WebSocket 连接已关闭 | 状态码: {close_status_code} | 关闭信息: {close_msg}")

def send_continuous_message(ws):
    """独立线程：持续输入并发送消息（避免阻塞接收线程）"""
    while True:
        if not is_connected:
            break
        # 等待用户输入
        user_input = input("请输入要发送的消息（输入 exit 退出）：")
        if user_input.lower() == "exit":
            # 主动关闭连接
            ws.close()
            break
        
        user_input = f"Client: {user_input}"
        if is_connected:
            ws.send(user_input)
            print(f"📤 已发送: {user_input}")
        else:
            print("⚠️ 连接已断开，无法发送消息")

if __name__ == "__main__":
    # 1. 配置 WebSocket 服务器地址（公共回声测试服务器，发送啥返回啥）
    ws_url = "ws://echo.websocket.events"
    
    # 2. 创建 WebSocket 客户端实例，并绑定回调函数
    ws = websocket.WebSocketApp(
        ws_url,
        on_open=on_open,        # 连接成功回调
        on_message=on_message,  # 接收消息回调
        on_error=on_error,      # 错误回调
        on_close=on_close       # 关闭回调
    )

    # 3. 启动独立线程处理用户输入（避免阻塞接收逻辑）
    send_thread = threading.Thread(target=send_continuous_message, args=(ws,))
    send_thread.daemon = True  # 主线程退出时，该线程也退出
    send_thread.start()

    # 4. 运行 WebSocket 客户端（阻塞式，直到连接关闭）
    # run_forever() 会持续监听服务器消息，自动重连可加参数：ping_interval=30, ping_timeout=10
    ws.run_forever(ping_interval=30, ping_timeout=10)

    # 5. 等待输入线程结束
    send_thread.join()
    print("👋 客户端已退出")