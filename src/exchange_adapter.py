

class ExchangeAdapter:
    def __init__(self, exchange):
        self.exchange = exchange

    def validate_order_direction(self, side, position_side, is_open=False):
        return None