# Paradex WebSocket 连接稳定性改进

针对 WebSocket 连接频繁断开的问题，我们对 Paradex 接收器进行了以下改进：

## 🔧 主要改进

### 1. 应用层 Ping/Pong 处理

**问题**: Paradex 服务器可能需要特定的应用层心跳保持
**解决方案**: 
- 添加了对 `ping`/`pong` JSON-RPC 消息的处理
- 自动响应服务器发送的 ping 消息
- 定期发送应用层 ping 消息保持连接活跃

```python
# 接收到服务器 ping 时自动回复 pong
elif "method" in data and data["method"] == "ping":
    pong_msg = {
        "jsonrpc": "2.0",
        "method": "pong", 
        "id": data.get("id")
    }
    ws.send(json.dumps(pong_msg))
```

### 2. 更频繁的心跳检测

**变化**:
- `ping_interval`: 60秒 → 30秒 (更频繁的 WebSocket ping)
- `ping_timeout`: 30秒 → 10秒 (更快的超时检测)
- `heartbeat_timeout`: 180秒 → 120秒 (更敏感的断线检测)

### 3. 双重心跳机制

**新增功能**:
- **WebSocket 层心跳**: 使用 websocket-client 库的内置 ping/pong
- **应用层心跳**: 每30秒发送 JSON-RPC ping 消息

```python
def _ping_loop(self, ws_ref):
    """定期发送应用层 ping 消息"""
    while self._running:
        time.sleep(30)
        ping_msg = {
            "jsonrpc": "2.0",
            "method": "ping",
            "id": f"ping_{self._ping_counter}"
        }
        ws_ref.send(json.dumps(ping_msg))
```

### 4. 改进的 WebSocket 参数

**优化设置**:
- 添加了 `on_ping`/`on_pong` 回调处理
- 增加了自动重连参数 `reconnect=5`
- 优化了 SSL 上下文超时设置

### 5. 更好的错误处理

**改进**:
- 更详细的连接状态日志
- ping 发送失败时的错误处理
- 更精确的连接超时检测

## 📊 连接稳定性提升

### 改进前的问题
```
2025-12-11 05:05:39,582 - ERROR - WebSocket error: Connection to remote host was lost.
2025-12-11 05:05:39,582 - INFO - WebSocket closed: None - None
2025-12-11 05:05:44,600 - INFO - Reconnecting in 5.0s...
```

### 改进后的预期效果
- 连接断开频率显著降低
- 更快的断线检测和重连
- 主动的连接保活机制
- 更稳定的长时间运行

## 🎯 使用建议

### 1. 生产环境配置
```python
receiver = ParadexDepthReceiver(
    symbols=["PAXG-USD-PERP"],
    bearer_token="YOUR_TOKEN",
    ping_interval=30,      # 30秒 WebSocket ping
    ping_timeout=10,       # 10秒 ping 超时
    heartbeat_timeout=120, # 2分钟心跳超时
    reconnect_interval=3.0 # 3秒重连间隔
)
```

### 2. 监控连接状态
- 观察日志中的 ping/pong 消息（debug级别）
- 监控重连频率
- 检查心跳超时警告

### 3. 网络环境优化
- 确保网络稳定
- 考虑使用代理或负载均衡
- 监控网络延迟和丢包率

## 🔍 调试选项

如需查看详细的连接调试信息：

```python
import logging
logging.getLogger("paradex_receiver.receiver").setLevel(logging.DEBUG)
logging.getLogger("paradex_receiver.trades_receiver").setLevel(logging.DEBUG)
```

这将显示：
- WebSocket ping/pong 消息
- 应用层 ping/pong 消息
- 连接状态变化
- 心跳检测详情

## ⚠️ 注意事项

1. **频繁 ping 的影响**: 虽然增加了 ping 频率，但都是轻量级消息，不会显著增加带宽使用
2. **服务器限制**: 某些服务器可能对 ping 频率有限制，如遇问题可适当调整间隔
3. **资源使用**: 新增的 ping 线程会略微增加资源使用，但影响微小

这些改进应该能显著提升 Paradex WebSocket 连接的稳定性，减少 "Connection to remote host was lost" 错误的发生频率。