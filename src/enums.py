from enum import Enum


class OrderStatus(Enum):

    NEW = "new"  # 新建订单
    CANCELED = "canceled"  # 取消状态
    LIVE = "live"  # 挂单状态
    PARTIALLY_FILLED = "partially_filled"  # 部分成交
    FILLED = "filled"  # 完全成交
    MMP_CANCELED = "mmp_canceled"  # 做市商保护机制导致的自动撤单
    REJECTED = "rejected"  # 订单被拒绝
    EXPIRED = "expired"  # 订单过期(根据timeInForce参数规则)
    EXPIRED_IN_MATCH = "expired_in_match"  # 订单被STP过期

    # ibkr
    PENDING_SUBMIT = "pending_submit"
    PENDING_CANCEL = "pending_cancel"
    PRE_SUBMITTED = "pre_submitted"
    SUBMITTED = "submitted"
    API_PENDING = "api_pending"
    API_CANCELED = "api_cancelled"
    INACTIVE = "inactive"
    
    PARTIALLY_FILLED_CANCELED = "partially_filled_canceled"
    TRIGGERED = "triggered" # bybit已觸發, 條件單從未觸發到變成New的一個中間態
    DEACTIVATED = "deactivated" # 統一帳戶下期貨、現貨的盈止損單、條件單、OCO訂單觸發前取消

    @staticmethod
    def from_exchange_status(status: str, exchange_name: str):
        exchange_mappings = {
            "okx": {
                "canceled": OrderStatus.CANCELED,  # 撤单成功
                "live": OrderStatus.LIVE,  # 等待成交
                "partially_filled": OrderStatus.PARTIALLY_FILLED,  # 部分成交
                "filled": OrderStatus.FILLED,  # 完全成交
                "mmp_canceled": OrderStatus.MMP_CANCELED,  # 做市商保护机制导致的自动撤单
            },
            "binance": {
                "NEW": OrderStatus.NEW,
                "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
                "FILLED": OrderStatus.FILLED,
                "CANCELED": OrderStatus.CANCELED,
                "REJECTED": OrderStatus.REJECTED,
                "EXPIRED": OrderStatus.EXPIRED,
                "EXPIRED_IN_MATCH": OrderStatus.EXPIRED_IN_MATCH,
            },
            "binance_pmpro": {
                "NEW": OrderStatus.NEW,
                "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
                "FILLED": OrderStatus.FILLED,
                "CANCELED": OrderStatus.CANCELED,
                "REJECTED": OrderStatus.REJECTED,
                "EXPIRED": OrderStatus.EXPIRED,
                "EXPIRED_IN_MATCH": OrderStatus.EXPIRED_IN_MATCH,
            },
            "ibkr": {
                "PendingSubmit": OrderStatus.PENDING_SUBMIT,
                "PendingCancel": OrderStatus.PENDING_CANCEL,
                "PreSubmitted": OrderStatus.PRE_SUBMITTED,
                "Submitted": OrderStatus.SUBMITTED,
                "ApiPending": OrderStatus.API_PENDING,
                "ApiCancelled": OrderStatus.API_CANCELED,
                "Cancelled": OrderStatus.CANCELED,
                "Filled": OrderStatus.FILLED,
                "Inactive": OrderStatus.INACTIVE,
            },
            "bitget": {
                "canceled": OrderStatus.CANCELED,  # 撤单成功
                "live": OrderStatus.LIVE,  # 等待成交
                "partially_filled": OrderStatus.PARTIALLY_FILLED,  # 部分成交
                "filled": OrderStatus.FILLED,  # 完全成交
            },
            "bybit":{
                "New": OrderStatus.NEW,
                "PartiallyFilled": OrderStatus.PARTIALLY_FILLED,
                "Filled": OrderStatus.FILLED,
                "Cancelled": OrderStatus.CANCELED,
                "Canceled": OrderStatus.CANCELED,
                "Rejected": OrderStatus.REJECTED,
                "PartiallyFilledCanceled": OrderStatus.PARTIALLY_FILLED_CANCELED,
                "Triggered": OrderStatus.TRIGGERED,
                "Deactivated": OrderStatus.DEACTIVATED,
            }
        }
        if exchange_name not in exchange_mappings:
            raise ValueError(f"不支持的交易所: {exchange_name}")

        # 判断status是否在exchange_mappings[exchange_name]中
        if status not in exchange_mappings[exchange_name]:
            raise ValueError(f"不支持的订单状态: {status}")
        return exchange_mappings[exchange_name][status]

    @staticmethod
    def get_cancel_status_lst():
        return [
            OrderStatus.CANCELED,
            OrderStatus.MMP_CANCELED,
            OrderStatus.API_CANCELLED,
        ]
