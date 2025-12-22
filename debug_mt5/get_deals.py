
import time
from datetime import datetime
from mt5linux import MetaTrader5
mt5 = MetaTrader5(host='localhost',port=8001)

server_name = "Exness-MT5Trial5"
login_account = 277301702
password = "d-x7FVTeCpf"

init_result = mt5.initialize(login=login_account, server=server_name, password=password)
print("初始化结果：", init_result)

symbol = "XAUUSDz"

from_date=datetime(2025,12,11)
to_date=datetime.now()


deals = mt5.history_deals_get(symbol=symbol, from_date=from_date, to_date=to_date)

print(deals)
pass