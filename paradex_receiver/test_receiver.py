"""
测试 Paradex 接收器的简单脚本
"""

import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paradex_receiver import ParadexDepthReceiver, TardisL2Snapshot

def test_receiver():
    """测试接收器"""
    
    # 使用测试token (请替换为真实token)
    bearer_token = "JWcgwMbK0bx1uFFef0Lri35ZDwypmCG0isuBv"
    
    def on_snapshot(snapshot: TardisL2Snapshot):
        print(f"\n=== 快照 ===")
        print(f"交易对: {snapshot.symbol}")
        print(f"时间戳: {snapshot.timestamp}")
        print(f"买单档数: {len(snapshot.bids)}")
        print(f"卖单档数: {len(snapshot.asks)}")
        
        if snapshot.bids:
            print(f"最优买价: {snapshot.bids[0].price} 数量: {snapshot.bids[0].amount}")
        if snapshot.asks:
            print(f"最优卖价: {snapshot.asks[0].price} 数量: {snapshot.asks[0].amount}")
        
        # 打印 book_snapshot_15 格式
        print(f"CSV行: {snapshot.to_book_snapshot_15_row()[:100]}...")

    def on_error(error):
        print(f"错误: {error}")

    receiver = ParadexDepthReceiver(
        symbols=["PAXG-USD-PERP"],
        bearer_token=bearer_token,
        levels=15,
        frequency="50ms",
        min_delta="0_01"
    )
    
    receiver.on_snapshot = on_snapshot
    receiver.on_error = on_error
    
    try:
        print("开始测试 Paradex 接收器...")
        print("按 Ctrl+C 停止")
        receiver.start()
    except KeyboardInterrupt:
        print("\n测试结束")
    finally:
        receiver.stop()

if __name__ == "__main__":
    test_receiver()