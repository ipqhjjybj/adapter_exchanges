import lighter
import requests

import logging
from logging.handlers import RotatingFileHandler
import os
import time

def setup_logger():
    """配置日志记录器"""
    # 1. 创建日志器（logger），设置全局日志级别（DEBUG是最低级别，会捕获所有更高等级的日志）
    logger = logging.getLogger("MyAppLogger")
    logger.setLevel(logging.DEBUG)  # 全局级别：DEBUG < INFO < WARNING < ERROR < CRITICAL
    logger.handlers.clear()  # 避免重复添加处理器

    # 2. 定义日志格式（可自定义）
    # 格式说明：时间 - 日志器名 - 日志级别 - 文件名:行号 - 日志内容
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"  # 时间格式
    )

    # 3. 控制台处理器（输出到终端）
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)  # 控制台只输出INFO及以上级别
    console_handler.setFormatter(formatter)

    # 4. 文件处理器（输出到文件，支持轮转避免文件过大）
    # 创建logs目录（如果不存在）
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    log_file = os.path.join(log_dir, "my_app.log")

    # 轮转文件处理器：单个文件最大10MB，最多保留5个备份
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding="utf-8"  # 确保中文正常显示
    )
    file_handler.setLevel(logging.DEBUG)  # 文件记录DEBUG及以上所有级别
    file_handler.setFormatter(formatter)

    # 5. 将处理器添加到日志器
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger

# 初始化日志器
logger = setup_logger()

class LightAdapter(object):
    """
    lighter交易所适配器实现
    """
    
    def __init__(self, l1_address: str, apikey_private_key: str, api_key_index: int):
        self.base_url = "https://mainnet.zklighter.elliot.ai"

        self.l1_address = l1_address
        self.apikey_private_key = apikey_private_key
        self.api_key_index = api_key_index
        self.headers = {"accept": "application/json"}
        self.account_index = -1

        # 获得账户信息
        self.get_account_info()

        assert self.account_index >= 0, "get_account_info error"

    def get_account_info(self):
        """
        获得账户信息
        """
        url = f"{self.base_url}/api/v1/account?by=l1_address&value={self.l1_address}"
        data = requests.get(url, headers=self.headers, timeout=60)
        if data.status_code == 200:
            js_data = data.json()
            if js_data["code"] == 200:
                self.account_index = js_data["accounts"][0]["index"]
                logger.info(f"get_account_info success, account_index: {self.account_index}")
            else:
                raise Exception("get_account_info error")
        else:
            return None
        pass
        
        
    


if __name__ == "__main__":
    import sys
    import os 
    
    lighter_adapter = LightAdapter(
        l1_address="0xA2C9f815302d32757688eB0D6466466105682F54",
        apikey_private_key="9d0a9b5f993c919fd8c2b63598be0753f05dc00ae6fbc2081a180a991bfd360822bcf95322e6e50a",
        api_key_index=2
    )

    #lighter_adapter.get_account_info()

