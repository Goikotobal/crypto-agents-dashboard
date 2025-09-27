from copy import deepcopy

def filter_args(cfg):
    cfg = deepcopy(cfg)
    cfg.pop("enabled", None)
    return cfg   
from trading_agents.shared import last_price, place_order
from datetime import datetime, timedelta

class MinerAgent:
    """
    Agent that simulates a miner selling small amounts of BTC regularly,
    regardless of market conditions.
    """
    def __init__(self, symbol, interval_minutes, base_fee):
        self.symbol = symbol
        self.interval_minutes = interval_minutes
        self.base_fee = base_fee
        self.sell_amount = 0.0001  # or whatever small amount the miner should sell
        self.last_sell_time = None
        self.sell_interval = timedelta(minutes=interval_minutes)



    def should_sell(self, now):
        return (
            self.last_sell_time is None
            or (now - self.last_sell_time) >= self.sell_interval
        )

    def step(self):
        now = datetime.utcnow()

        if not self.should_sell(now):
            return None

        px = last_price(self.symbol)
        if px <= 0:
            print(f"[miner] Skipping: bad price for {self.symbol}: {px}")
            return None

        qty = self.sell_amount
        order = place_order(self.symbol, "sell", px, qty)
        self.last_sell_time = now

        print(f"[miner] Sold {qty} {self.symbol} at {px}")
        return order