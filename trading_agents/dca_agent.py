# CryptoAgents/trading_agents/dca_agent.py
from copy import deepcopy

def filter_args(cfg):
    cfg = deepcopy(cfg)
    cfg.pop("enabled", None)
    return cfg

from trading_agents.shared import last_price, place_order
import datetime as dt

class DCAAgent:
    """
    Dollar-Cost Averaging (DCA) Agent:
    - Buys a fixed amount at fixed time intervals.
    - Ignores price.
    """

    def __init__(self, symbol="BTC/EUR", interval_minutes=1440, buy_amount=0.01):
        self.symbol = symbol
        self.buy_amount = buy_amount
        self.interval = dt.timedelta(minutes=interval_minutes)
        self.last_buy_time = None

    def should_buy(self, now):
        return (
            self.last_buy_time is None or
            (now - self.last_buy_time) >= self.interval
        )

    def step(self):
        now = dt.datetime.utcnow()
        if not self.should_buy(now):
            return None

        px = last_price(self.symbol)
        if px <= 0:
            print(f"[dca] Skipping: bad price for {self.symbol}: {px}")
            return None

        qty = self.buy_amount
        order = place_order(self.symbol, "buy", px, qty)
        self.last_buy_time = now

        print(f"[dca] Bought {qty} {self.symbol} at {px}")
        return order
