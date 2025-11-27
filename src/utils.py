import functools
import time
import traceback
from decimal import Decimal, ROUND_DOWN, ROUND_UP
import logging
import uuid
import time
#from src.slack_msg import send_slack_webhook_message
import os
import dotenv
from src.log_kit import logger
from datetime import datetime, timezone, time as dt_time
import json
import hashlib
import requests
#import ccxt
#from ccxt import binance

dotenv.load_dotenv()
MONITOR_WEBHOOK_URL = os.getenv("monitor_webhook_url")
MONITOR_CHANNEL_ID = os.getenv("monitor_channel_id")
STRATEGY_WEBHOOK_URL = os.getenv("strategy_webhook_url")
STRATEGY_CHANNEL_ID = os.getenv("strategy_channel_id")


class SlackMessage:
    def __init__(self, webhook_url: str, channel_id: str, is_debug: bool = False):
        self.webhook_url = webhook_url
        self.channel_id = channel_id
        self.is_debug = is_debug

    def send(self, message: str):
        if not self.is_debug:
            send_slack_webhook_message(self.webhook_url, message)
        else:
            logger.info(f"debug模式跳过发送: {message}")


monitor_slack_sender = SlackMessage(
    MONITOR_WEBHOOK_URL, MONITOR_CHANNEL_ID, is_debug=True
)
strategy_slack_sender = SlackMessage(
    STRATEGY_WEBHOOK_URL, STRATEGY_CHANNEL_ID, is_debug=True
)


def float_is_close(a, b, rel_tol=1e-6, abs_tol=1e-6):
    """
    判断两个浮点数是否近似相等
    a, b: 要比较的两个数
    rel_tol: 相对容差
    abs_tol: 绝对容差
    """
    if a == b:  # 处理完全相等的情况
        return True

    # 处理接近零的情况，直接使用绝对误差比较
    if abs(a) < abs_tol and abs(b) < abs_tol:
        return True

    # 正常情况使用相对误差和绝对误差的组合
    return abs(a - b) <= max(rel_tol * max(abs(a), abs(b)), abs_tol)


def check_price_filter_valid(
    price: Decimal, min_price: Decimal, max_price: Decimal, tick_size: Decimal
) -> bool:
    """
    检查订单价格是否符合PRICE_FILTER过滤器规则

    参数:
        price: 订单价格
        min_price: 允许的最小价格
        max_price: 允许的最大价格
        tick_size: 允许的价格步进值

    返回:
        bool: 如果价格有效则返回True，否则返回False
    """
    # 检查最小值条件
    if price < min_price:
        return False

    # 检查最大值条件
    if price > max_price:
        return False

    # 检查步进值条件
    # 计算与最小值的差距，然后检查是否是步进值的整数倍
    if tick_size == Decimal("0"):
        # 如果tick_size为0，则不限制步进值
        return True

    remainder = (price - min_price) % tick_size

    # 由于浮点数精度问题，使用一个小的容差值
    tolerance = Decimal("0.0000000001")

    # 如果余数非常接近0或非常接近步进值，则认为是有效的
    if remainder <= tolerance or (tick_size - remainder) <= tolerance:
        return True

    return False


def adjust_to_price_filter(
    price: Decimal,
    min_price: Decimal,
    max_price: Decimal,
    tick_size: Decimal,
    round_direction: str = "DOWN",
) -> Decimal:
    """
    将价格调整为符合PRICE_FILTER过滤器规则的最接近有效值

    参数:
        price: 原始订单价格
        min_price: 允许的最小价格
        max_price: 允许的最大价格
        tick_size: 允许的价格步进值
        round_direction: 舍入方向，'UP'向上取整，'DOWN'向下取整(默认)

    返回:
        Decimal: 调整后的有效价格
    """
    # 首先确保价格在最小和最大值范围内
    price = max(min_price, min(price, max_price))

    # 如果tick_size为0，则不需要调整步进值
    if tick_size == Decimal("0"):
        return price

    # 计算需要调整的步数
    steps = (price - min_price) / tick_size

    # 根据指定方向舍入步数
    if round_direction.upper() == "UP":
        steps = steps.quantize(Decimal("1"), rounding=ROUND_UP)
    else:  # 默认向下舍入
        steps = steps.quantize(Decimal("1"), rounding=ROUND_DOWN)

    # 计算调整后的价格
    adjusted_price = min_price + steps * tick_size

    # 确保结果不超过最大值
    adjusted_price = min(adjusted_price, max_price)

    # 获取tick_size的小数位数，用于格式化
    decimal_places = abs(tick_size.as_tuple().exponent)
    format_str = f"{{:.{decimal_places}f}}"

    # 格式化并转回Decimal，确保精度正确
    return Decimal(format_str.format(adjusted_price))


def check_lot_size_valid(
    quantity: Decimal, min_qty: Decimal, max_qty: Decimal, step_size: Decimal
) -> bool:
    """
    检查订单数量是否符合LOT_SIZE过滤器规则

    参数:
        quantity: 订单数量
        min_qty: 允许的最小数量
        max_qty: 允许的最大数量
        step_size: 允许的步进值

    返回:
        bool: 如果数量有效则返回True，否则返回False
    """
    # 检查最小值条件
    if quantity < min_qty:
        return False

    # 检查最大值条件
    if quantity > max_qty:
        return False

    # 检查步进值条件
    # 计算与最小值的差距，然后检查是否是步进值的整数倍
    remainder = (quantity - min_qty) % step_size

    # 由于浮点数精度问题，使用一个小的容差值
    tolerance = Decimal("0.0000000001")

    # 如果余数非常接近0或非常接近步进值，则认为是有效的
    if remainder <= tolerance or (step_size - remainder) <= tolerance:
        return True

    return False


def adjust_to_lot_size(
    quantity: Decimal,
    min_qty: Decimal,
    max_qty: Decimal,
    step_size: Decimal,
    round_direction: str = "DOWN",
) -> Decimal:
    """
    将数量调整为符合LOT_SIZE过滤器规则的最接近有效值

    参数:
        quantity: 原始订单数量
        min_qty: 允许的最小数量
        max_qty: 允许的最大数量
        step_size: 允许的步进值
        round_direction: 舍入方向，'UP'向上取整，'DOWN'向下取整(默认)

    返回:
        Decimal: 调整后的有效数量
    """
    # 首先确保数量在最小和最大值范围内
    quantity = max(min_qty, min(quantity, max_qty))

    # 计算需要调整的步数
    steps = (quantity - min_qty) / step_size

    # 根据指定方向舍入步数
    if round_direction.upper() == "UP":
        steps = steps.quantize(Decimal("1"), rounding=ROUND_UP)
    else:  # 默认向下舍入
        steps = steps.quantize(Decimal("1"), rounding=ROUND_DOWN)

    # 计算调整后的数量
    adjusted_quantity = min_qty + steps * step_size

    # 确保结果不超过最大值
    adjusted_quantity = min(adjusted_quantity, max_qty)

    # 使用字符串格式化来避免小数精度问题
    # 获取step_size的小数位数
    decimal_places = abs(step_size.as_tuple().exponent)
    format_str = f"{{:.{decimal_places}f}}"

    # 格式化并转回Decimal
    return Decimal(format_str.format(adjusted_quantity))


def retry_wrapper(retries=3, sleep_seconds=1.0, is_adapter_method=False):
    """
    最简单的重试装饰器

    Args:
        retries: 最大重试次数
        sleep_seconds: 重试间隔(秒)
        is_adapter_method: 是否为返回AdapterResponse的方法
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            func_name = func.__name__

            for attempt in range(retries):
                try:
                    # 调用原始函数
                    result = func(*args, **kwargs)

                    # 处理AdapterResponse
                    if (
                        is_adapter_method
                        and hasattr(result, "success")
                        and not result.success
                    ):
                        if attempt < retries - 1:
                            logger.warning(
                                f"{func_name} 返回失败，准备重试 ({attempt+1}/{retries})"
                            )
                            time.sleep(sleep_seconds)
                            continue

                    # 正常结果直接返回
                    return result

                except Exception as e:
                    # 如果是最后一次尝试，记录错误并重新抛出
                    if attempt >= retries - 1:
                        logger.error(
                            f"{func_name} 重试{retries}次后失败: {e}", exc_info=True
                        )
                        raise

                    # 记录并等待重试
                    logger.warning(
                        f"{func_name} 失败，准备重试 ({attempt+1}/{retries}): {e}",
                        exc_info=True,
                    )
                    time.sleep(sleep_seconds)

            return None  # 这行代码实际上不会执行到

        return wrapper

    return decorator


# 添加市场时间检查的实现
def check_market_hours(exchange_name, before_buffer_min=10, after_buffer_min=10):
    """
    检查市场是否在交易时段
    
    参数:
        exchange_name: 交易所名称
        before_buffer_min: 收盘前的缓冲时间（分钟）
        after_buffer_min: 开盘后的缓冲时间（分钟）
        
    返回:
        bool: True表示市场已关闭，False表示市场开放
    """
    # 对于加密货币交易所，通常是24/7开放的
    if exchange_name.lower() in ["binance", "okx", "bybit", "bitget"]:
        return False  # 市场不会关闭
    
    # 对于传统交易所（如IBKR），需要检查交易时间
    now = datetime.now(timezone.utc)
    current_weekday = now.weekday()  # 0=周一，6=周日
    current_time = now.time()

    # 定义交易时间
    # 使用dt_time而不是time，确保正确处理缓冲时间计算
    close_time = (
        dt_time(20, 58 - before_buffer_min)
        if 58 >= before_buffer_min
        else dt_time(19, 60 - (before_buffer_min - 58))
    )
    open_time = dt_time(22, 1 + after_buffer_min)

    # 检查周末
    # 周五收盘后到周日开盘前，市场关闭
    if (
        (current_weekday == 4 and current_time >= close_time)  # 周五收盘后
        or current_weekday == 5  # 周六全天
        or (current_weekday == 6 and current_time < dt_time(22, 5 + after_buffer_min))  # 周日开盘前
    ):
        return True  # 市场关闭

    # 检查每日交易时间
    # 日常收盘时间到开盘时间之间，市场关闭
    if close_time <= current_time < open_time:
        return True  # 市场关闭

    # 其他情况，市场开放
    return False


# 添加缺少的函数实现
def save_json(data, file_path):
    """保存数据为JSON文件"""
    try:
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"保存JSON失败: {e}")
        return False

def load_json(file_path):
    """从JSON文件加载数据"""
    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"加载JSON失败: {e}")
        return None
    
    
def get_compute_os():
    """
    获取当前操作系统类型
    
    返回:
        str: 操作系统类型，如'windows', 'darwin' (MacOS), 'linux'等
    """
    import platform
    return platform.system().lower()


def is_windows():
    """
    判断当前操作系统是否为Windows
    
    返回:
        bool: 如果是Windows返回True，否则返回False
    """
    return get_compute_os() == 'windows'


def get_unique_id():
    """
    生成一个唯一的ID
    
    返回:
        str: 唯一的ID
    """
    return f"{int(time.time())}_{uuid.uuid4().hex[:8]}"


def redirect(exchange, exchange_name:str, mappings:dict):
    import ccxt
    if exchange_name == 'binance':
        exchange:ccxt.binance = exchange
        keys = list(exchange.urls['api'].keys())
        for key in keys:
            for src, target in mappings.items():
                exchange.urls['api'][key] = exchange.urls['api'][key].replace(src, target)
    elif exchange_name == 'bitget':
        exchange:ccxt.bitget = exchange
        exchange.urls['api']=mappings
    elif exchange_name == 'bybit':
        exchange:ccxt.bybit = exchange
        exchange.urls['api']=mappings
    elif exchange_name == 'okx':
        exchange:ccxt.okx = exchange
        exchange.urls['api']['rest'] = mappings['rest']
    return exchange

def load_config_yaml():
    import yaml
    with open('config.yaml', 'r', encoding='utf-8') as f:
        config_yaml= yaml.safe_load(f)
    return config_yaml


# class SigningBinance(binance):
#     def __init__(self, secret_name: str, signing_endpoint: str, *args, **kwargs):
#         super(SigningBinance, self).__init__(*args, **kwargs)
#         self.secret_name = secret_name
#         self.signing_endpoint = signing_endpoint

#     def hmac(self, request, secret, algorithm=hashlib.sha256, digest='hex'):
#         signing_response = requests.post(
#             self.signing_endpoint,
#             json={
#                 "request": ccxt.Exchange.decode(request),
#                 "secret_name": self.secret_name,
#                 "api_key": self.apiKey,
#             },
#             headers={"X-API-KEY": "b5Js7QX5NGNHvHXnCyxK-SNQL9_OV2OiZpWnH-bsQ9Y"}
#         )
#         signed = signing_response.json()
#         return signed["signature"]
