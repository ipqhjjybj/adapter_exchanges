import time
from mt5linux import MetaTrader5
mt5 = MetaTrader5(host='localhost',port=8001)

server_name = "Exness-MT5Trial5"
login_account = 277301702
password = "d-x7FVTeCpf"

init_result = mt5.initialize(login=login_account, server=server_name, password=password)
print("初始化结果：", init_result)
# time.sleep(2)  # 给终端 2 秒加载交易环境

symbol = "XAUUSDz"

sl_points=100
tp_points=100
deviation = 20
comment="python script"
symbol_info = mt5.symbol_info(symbol)
tick = mt5.symbol_info_tick(symbol)
print("当前报价：", tick)
print("品种精度：", symbol_info.digits)
print("最小交易量：", symbol_info.volume_min)



volume = 0.02
price = tick.ask
point = symbol_info.point
sl = price - sl_points * point if sl_points else 0
tp = price + tp_points * point if tp_points else 0


request = {
    "action": mt5.TRADE_ACTION_DEAL,
    "symbol": symbol,
    "volume": float(volume),
    "type": mt5.ORDER_TYPE_BUY,
    "price": price,
    "sl": sl,
    "tp": tp,
    "deviation": deviation,
    "magic": 234000,
    "comment": comment,
    "type_time": mt5.ORDER_TIME_GTC,
    "type_filling": mt5.ORDER_FILLING_IOC,
}

# print(request)
# # 检查订单
check_result = mt5.order_check(request)
print(check_result)
print(mt5.last_error())

# 发送交易请求
# result = mt5.order_send(request)
print(mt5.last_error())

pass