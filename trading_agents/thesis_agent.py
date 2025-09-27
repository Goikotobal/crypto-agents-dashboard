# CryptoAgents/trading_agents/thesis_agent.py
from copy import deepcopy

def filter_args(cfg):
    cfg = deepcopy(cfg)
    cfg.pop("enabled", None)
    return cfg

from trading_agents.shared import last_price, place_order
from datetime import datetime

class ThesisAgent:
    """
    Thesis-Based Agent:
    - Buys in Q4 if BTC is below 140k.
    - Starts selling aggressively after 2nd week of December.
    """
    def __init__(self, symbol, bet_direction, active_after):
        self.symbol = symbol
        self.bet_direction = bet_direction
        self.sell_after = datetime.strptime(active_after, "%Y-%m-%d").date()
        self.bought = False
        self.buy_threshold = 140000  # or whatever limit you want
        self.sell_pct = 0.5  # % of position to sell after date


    def is_q4(self, now):
        return now.month >= 10

    def is_after_thesis(self, now):
        return now.date().month > self.sell_after.month or (
            now.date().month == self.sell_after.month and now.date().day >= self.sell_after.day
        )

    def step(self):
        now = datetime.now()
        px = last_price(self.symbol)
        if px <= 0:
            print(f"[thesis] Skipping: bad price for {self.symbol}: {px}")
            return None

        # Buy thesis (October/November < 140k)
        if self.is_q4(now) and not self.bought and px < self.buy_threshold:
            qty = 0.01
            self.bought = True
            order = place_order(self.symbol, "buy", px, qty)
            print(f"[thesis] Bought {qty} {self.symbol} at {px} (Q4 thesis)")
            return order

        # Sell thesis (after December 15)
        if self.bought and self.is_after_thesis(now):
            qty = self.sell_pct
            order = place_order(self.symbol, "sell", px, qty)
            print(f"[thesis] Sold {qty} {self.symbol} at {px} (after Dec 15)")
            return order

        return None