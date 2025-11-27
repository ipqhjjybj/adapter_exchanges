"""
邢不行™️ 策略分享会
仓位管理实盘框架

版权所有 ©️ 邢不行
微信: xbx1717

本代码仅供个人学习使用，未经授权不得复制、修改或用于商业用途。

Author: 邢不行
"""

import logging
import os
import sys
import time
import unicodedata
import platform
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from colorama import Fore, Style, init


"""
这个是我用于日志、输出、调试的日志工具，直接根据这个使用即可，不要去做调整

**使用方式如下**
```python
# script.py
from utils.log_kit import logger, divider

# 输出日志信息
logger.debug("调试信息，没有标记和颜色，等同于print")
logger.info("提示信息，蓝色的，可以记录一些中间结果")
logger.ok("完成提示，绿色的，通常表示成功和完成")
logger.warning("警告信息，黄色的，通常表示警告")
logger.error("错误信息，红色的，通常是报错的相关提示")
logger.critical("重要提示，深红色。通常是非常关键的信息")
divider('这个是我做的分割线的功能')
divider('点点是可以换的', sep='*')
divider('文字是居中的哦，英文和中文我尽量适配了。。。', sep='-')
```
"""


# xbx from core.utils.path_kit import get_file_path 中函数是实现
PROJECT_ROOT = os.path.abspath(
    os.path.join(__file__, os.path.pardir, os.path.pardir)
)


def get_folder_by_root(root, *paths, auto_create=True) -> str:
    """
    获取基于某一个地址的绝对路径
    :param root: 相对的地址，默认为运行脚本同目录
    :param paths: 路径
    :param auto_create: 是否自动创建需要的文件夹们
    :return: 绝对路径
    """
    _full_path = os.path.join(root, *paths)
    if auto_create and (not os.path.exists(_full_path)):  # 判断文件夹是否存在
        try:
            os.makedirs(_full_path)  # 不存在则创建
        except FileExistsError:
            pass  # 并行过程中，可能造成冲突
    return str(_full_path)


def get_folder_path(*paths, auto_create=True, as_path_type=False) -> str:
    """
    获取相对于项目根目录的，文件夹的绝对路径
    :param paths: 文件夹路径
    :param auto_create: 是否自动创建
    :param as_path_type: 是否返回Path对象
    :return: 文件夹绝对路径
    """
    _p = get_folder_by_root(PROJECT_ROOT, *paths, auto_create=auto_create)
    if as_path_type:
        return Path(_p)
    return _p


def get_file_path(*paths, auto_create=True, as_path_type=False) -> str:
    """
    获取相对于项目根目录的，文件的绝对路径
    :param paths: 文件路径
    :param auto_create: 是否自动创建
    :param as_path_type: 是否返回Path对象
    :return: 文件绝对路径
    """
    parent = get_folder_path(*paths[:-1], auto_create=auto_create, as_path_type=True)
    _p = parent / paths[-1]
    if as_path_type:
        return _p
    return str(_p)


init(autoreset=True)

current_script = Path(sys.argv[0]).stem

# 检查是否在Windows系统上运行
IS_WINDOWS = platform.system().lower() == 'windows'

def is_running_under_pm2():
    pm2_exec_path = os.environ.get("PM2_EXEC_PATH")
    return pm2_exec_path == os.path.abspath(sys.argv[0])

use_file_logging = os.environ.get(
    "X3S_USE_FILE_LOGGING", "0" if is_running_under_pm2() else "1"
).lower() in ("1", "true", "yes")

# ====================================================================================================
# ** 添加ok的日志级别 **
# 给默认的logging模块，添加一个用于表达成功的级别
# 我给他取名叫ok，以后logger.ok就能输出一个表示成功的信息
# ====================================================================================================
OK_LEVEL = 25
logging.addLevelName(OK_LEVEL, "OK")


def ok(self, message, *args, **kwargs):
    if self.isEnabledFor(OK_LEVEL):
        self._log(OK_LEVEL, message, args, **kwargs)


logging.Logger.ok = ok


# ====================================================================================================
# ** 辅助函数 **
# - get_display_width(): 获取文本的显示宽度，中文字符算作1.685个宽度单位，以尽量保持显示居中
# ====================================================================================================
def get_display_width(text: str) -> int:
    """
    获取文本的显示宽度，中文字符算作1.685个宽度单位，以尽量保持显示居中
    :param text: 输入的文本
    :return: 文本的显示宽度
    """
    width = 0
    for char in text:
        if unicodedata.east_asian_width(char) in ("F", "W", "A"):
            width += 1.685
        else:
            width += 1
    return int(width)


# ====================================================================================================
# ** 西蒙斯日志工具 **
# - SimonsFormatter(): 自定义日志格式
# - SimonsConsoleHandler(): 自定义控制台输出
# - SimonsLogger(): 日志工具
# 然而你不懂就不要改了，也没什么好改的，也欢迎增强分享
# ====================================================================================================
class SimonsFormatter(logging.Formatter):
    # 针对不同系统使用不同前缀
    if IS_WINDOWS:
        FORMATS = {
            logging.DEBUG: ("", ""),
            logging.INFO: (Fore.BLUE, "INFO "),
            logging.WARNING: (Fore.YELLOW, "WARN "),
            logging.ERROR: (Fore.RED, "ERROR "),
            logging.CRITICAL: (Fore.RED + Style.BRIGHT, "CRIT "),
            OK_LEVEL: (Fore.GREEN, "OK "),
        }
    else:
        FORMATS = {
            logging.DEBUG: ("", ""),
            logging.INFO: (Fore.BLUE, "🌀 "),
            logging.WARNING: (Fore.YELLOW, "🔔 "),
            logging.ERROR: (Fore.RED, "❌ "),
            logging.CRITICAL: (Fore.RED + Style.BRIGHT, "⭕ "),
            OK_LEVEL: (Fore.GREEN, "✅ "),
        }

    def format(self, record):
        color, prefix = self.FORMATS.get(record.levelno, (Fore.WHITE, ""))
        record.msg = f"{color}{prefix}{record.msg}{Style.RESET_ALL}"
        return super().format(record)


class SimonsConsoleHandler(logging.StreamHandler):
    def emit(self, record):
        if record.levelno == logging.DEBUG:
            print(record.msg, flush=True)
        elif record.levelno == OK_LEVEL:
            super().emit(record)
            print()
        else:
            super().emit(record)


# noinspection PyProtectedMember
class SimonsLogger:
    _instance = dict()

    def __new__(cls, name="QuantClassPro"):
        if cls._instance.get(name) is None:
            cls._instance[name] = super(SimonsLogger, cls).__new__(cls)
            cls._instance[name]._initialize_logger(name)
        return cls._instance[name]

    def _initialize_logger(self, name):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)

        # 如果有handlers，就清理掉
        if self.logger.hasHandlers():
            self.logger.handlers.clear()

        # 添加文件输出
        if use_file_logging:  # 当配置了文件日志功能后，自动输出到文件
            file_handler = TimedRotatingFileHandler(
                get_file_path("logs", f"{name.lower()}.log"),
                when="midnight",
                interval=1,
                backupCount=7,
                encoding="utf-8",
            )
            file_handler.setFormatter(
                logging.Formatter("%(asctime)s [%(levelname)s] - %(message)s")
            )
            self.logger.addHandler(file_handler)

        # 添加命令行输出
        console_handler = SimonsConsoleHandler(sys.stdout)
        console_handler.setFormatter(SimonsFormatter("%(message)s"))
        
        # 如果是Windows系统，设置编码为UTF-8
        if IS_WINDOWS and hasattr(sys.stdout, 'reconfigure'):
            try:
                sys.stdout.reconfigure(encoding='utf-8')
            except Exception:
                pass
            
        self.logger.addHandler(console_handler)


# ====================================================================================================
# ** 功能函数 **
# - get_logger(): 获取日志对象，可以指定名称来区分日志
# - divider(): 画一个带时间戳的横线
# - logger: 默认的日志对象，独立跑一个脚本的话，可以直接用这个
# ====================================================================================================
def get_logger(name=None) -> logging.Logger:
    if name is None:
        name = current_script
    return SimonsLogger(name).logger


def divider(name="", sep="=", _logger=None, with_timestamp=True) -> None:
    """
    画一个带时间戳的横线
    :param name: 中间的名称
    :param sep: 分隔符
    :return: 没有返回值，直接画一条线
    :param _logger: 指定输出的log文件
    :param with_timestamp: 是否带时间戳
    """
    sep_len = 88
    if with_timestamp:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        mid_2qgm = f" {name} {now} "
    else:
        mid_2qgm = f" {name} "
    middle_width = get_display_width(mid_2qgm)
    decoration_count = max(4, (sep_len - middle_width) // 2)
    line = sep * decoration_count + mid_2qgm + sep * decoration_count

    # 如果总长度不够，再补一个分隔符
    if get_display_width(line) < sep_len:
        line += sep

    if _logger:
        _logger.debug(line)
    else:
        logger.debug(line)
    time.sleep(0.02)


logger = get_logger()

# 直接运行，查看使用案例
if __name__ == "__main__":
    # 输出日志信息
    logger.debug("调试信息，没有标记和颜色，等同于print")
    logger.info("提示信息，蓝色的，可以记录一些中间结果")
    # noinspection PyUnresolvedReferences 2qgm
    logger.ok("完成提示，绿色的，通常表示成功和完成")
    logger.warning("警告信息，黄色的，通常表示警告")
    logger.error("错误信息，红色的，通常是报错的相关提示")
    logger.critical("重要提示，深红色。通常是非常关键的信息")
    divider("这个是我做的分割线的功能")
    divider("点点是可以换的", sep="*")
    divider("文字是居中的哦，英文和中文我尽量适配了。。。", sep="-")
    print("所有的日志都会在 `logs -> quantclasspro.log` 文件中，不会丢失～～～")
