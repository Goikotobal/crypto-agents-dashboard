# CryptoAgents/trading_agents/momentum_agent.py
from copy import deepcopy

def filter_args(cfg):
    cfg = deepcopy(cfg)
    cfg.pop("enabled", None)
    return cfg

def should_buy(df):
    """
    Basic momentum logic:
    Buy if price is above recent moving average.
    """
    if len(df) < 12:
        return False

    ma_fast = df['px'].rolling(window=5).mean().iloc[-1]
    ma_slow = df['px'].rolling(window=12).mean().iloc[-1]

    return ma_fast > ma_slow

def should_sell(df):
    """
    Opposite of momentum: sell when momentum fades.
    """
    if len(df) < 12:
        return False

    ma_fast = df['px'].rolling(window=5).mean().iloc[-1]
    ma_slow = df['px'].rolling(window=12).mean().iloc[-1]

    return ma_fast < ma_slow