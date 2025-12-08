"""
Lighter DEX 深度数据接收器 - 记录到 CSV
"""

import logging
import argparse
import sys
import os

sys.path.append("/home/ec2-user/test_lighter_dex/adapter_exchanges/lighter_receiver")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lighter_receiver import LighterDepthReceiver, TardisL2Update

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

MARKET_SYMBOL_MAP = {
    0: "ETHUSDT",
    # 1: "BTCUSDT",
    # 2: "SOLUSDT",
}


def main():
    parser = argparse.ArgumentParser(description="Lighter DEX 深度数据接收器")
    parser.add_argument("-m", "--markets", type=str, default="0", help="市场ID，逗号分隔 (默认: 0)")
    parser.add_argument("-o", "--output", type=str, default="lighter_l2.csv", help="输出文件 (默认: lighter_l2.csv)")
    args = parser.parse_args()

    market_ids = [int(x.strip()) for x in args.markets.split(",")]
    market_symbol_map = {mid: MARKET_SYMBOL_MAP.get(mid, f"MARKET_{mid}") for mid in market_ids}

    csv_file = open(args.output, "w")
    csv_file.write("exchange,symbol,timestamp,local_timestamp,is_snapshot,side,price,amount\n")
    update_count = 0

    def on_update(update: TardisL2Update):
        nonlocal update_count
        csv_file.write(update.to_csv_row() + "\n")
        update_count += 1
        if update_count % 100 == 0:
            csv_file.flush()
            logger.info(f"已写入 {update_count} 条记录")

    receiver = LighterDepthReceiver(market_ids=market_ids, market_symbol_map=market_symbol_map)
    receiver.on_update = on_update

    try:
        logger.info(f"开始接收数据，市场: {market_ids}，输出: {args.output}")
        receiver.start()
    except KeyboardInterrupt:
        logger.info("用户中断")
    finally:
        receiver.stop()
        csv_file.close()
        logger.info(f"共写入 {update_count} 条记录到 {args.output}")


if __name__ == "__main__":
    main()
