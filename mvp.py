# mvp.py — Crypto (spot) paper-trading MVP
from trading_agents.dca_agent import DCAAgent
from trading_agents.miner_agent import MinerAgent
from trading_agents.momentum_agent import should_buy as momentum_buy, should_sell as momentum_sell
from trading_agents.thesis_agent import ThesisAgent
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

import os, time, math, json, datetime as dt
from pathlib import Path

# --- disable numba JIT before any potential vectorbt import
os.environ["NUMBA_DISABLE_JIT"] = "1"

import pandas as pd
import numpy as np
import ccxt
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import yaml

# --- force urllib3/requests to use IPv4 (WSL/VPN IPv6 flakiness)
import socket
import urllib3.util.connection as _urllib3_cn
_urllib3_cn.allowed_gai_family = lambda: socket.AF_INET  # IPv4 only

# set True if you want to skip vectorbt backtests for now
SKIP_BACKTESTS = True

from copy import deepcopy

def filter_args(d: dict, allowed_keys: list) -> dict:
    return {k: v for k, v in d.items() if k in allowed_keys}

def _fmt_qty(x: float) -> str:
    return f"{x:.8f}"   # 8 decimals is plenty for qty

def _fmt_px(x: float) -> str:
    return f"{x:.6f}"   # 6 decimals is plenty for price

# ---------- bootstrap ----------
ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")                      # load API keys, etc.

# Load YAML config
cfg_path = ROOT / "config.yaml"
cfg = yaml.safe_load(cfg_path.read_text())

AGENTS = []

AGENT_CFG = cfg.get("agents", {})

if AGENT_CFG.get("dca", {}).get("enabled", False):
    AGENTS.append(DCAAgent(**filter_args(AGENT_CFG["dca"], ["symbol", "interval_minutes", "buy_amount"])))

if AGENT_CFG.get("miner", {}).get("enabled", False):
    AGENTS.append(MinerAgent(**filter_args(AGENT_CFG["miner"], ["symbol", "interval_minutes", "base_fee"])))

if AGENT_CFG.get("thesis", {}).get("enabled", False):
    AGENTS.append(ThesisAgent(**filter_args(AGENT_CFG["thesis"], ["symbol", "bet_direction", "active_after"])))

# Wrap momentum strategy
class MomentumAgent:
    def __init__(self, symbol):
        self.symbol = symbol

    def step(self):
        sig = signal_ma(self.symbol)
        if sig != "buy":
            return
        px = last_price(self.symbol)
        qty = 0.01  # test size
        place_order(self.symbol, "buy", px, qty)
        print(f"[momentum] Bought {qty} {self.symbol} @ {px}")

if AGENT_CFG.get("momentum", {}).get("enabled", False):
    for sym in AGENT_CFG["momentum"].get("symbols", []):
        AGENTS.append(MomentumAgent(sym))

# --- trading setup ---
EXCHANGE   = cfg.get("exchange", "kraken")      # "kraken" | "cryptocom" | "binance"
TIMEFRAME  = cfg.get("timeframe", "1h")
SYMBOLS    = cfg.get("symbols", ["BTC/USDT", "ETH/USDT"])
PAPER      = bool(cfg.get("paper", True))
FEE        = float(cfg.get("fee_pct", 0.10)) / 100.0
POLL       = int(cfg.get("poll_seconds", 30))   # seconds between loop ticks

# Paper-mode starting balances (quote currency buckets)
# e.g. { "EUR": 10000 } or { "USDT": 10000 }
PAPER_BAL  = cfg.get("paper_balances", {}) or {}

# --- risk controls ---
RISK_CFG        = cfg.get("risk", {})                      # dict
MAX_POS_PCT     = float(RISK_CFG.get("max_position_pct", 20))
DAILY_LOSS_CAP  = float(RISK_CFG.get("daily_loss_cap_pct", 2.0))
MIN_NOTIONAL    = float(RISK_CFG.get("min_order_notional_quote", 10))

# --- strategy params ---
STRAT_CFG   = cfg.get("strategy", {})
MA_FAST     = int(STRAT_CFG.get("ma_fast", 20))
MA_SLOW     = int(STRAT_CFG.get("ma_slow", 100))
DCA_SIZE_Q  = float(STRAT_CFG.get("dca_size_quote", 25))

# --- database (SQLite) ---
DB      = ROOT / "ledger.sqlite"
engine  = create_engine(f"sqlite:///{DB}", future=True)

# (used in exec_driver_sql later)
from sqlalchemy import text as sql

def _ensure_control_table():
    with engine.begin() as cx:
        cx.exec_driver_sql("""
        CREATE TABLE IF NOT EXISTS control(
            k TEXT PRIMARY KEY,
            v TEXT NOT NULL
        )
        """)
        # seed default pause=false
        cx.exec_driver_sql("""
        INSERT OR IGNORE INTO control(k,v) VALUES('paused','false')
        """)

def is_paused() -> bool:
    with engine.begin() as cx:
        row = cx.execute(sql("SELECT v FROM control WHERE k='paused'")).fetchone()
        return (row and str(row[0]).lower() == "true")

_ensure_control_table()
# --- database schema ---
with engine.begin() as cx:
    cx.exec_driver_sql("""
        CREATE TABLE IF NOT EXISTS orders(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts      TEXT,
            symbol  TEXT,
            side    TEXT,
            px      REAL,
            qty     REAL,
            notional REAL,
            fee     REAL,
            paper   INTEGER,
            status  TEXT,
            raw     TEXT
        );
    """)

    cx.exec_driver_sql("""
        CREATE TABLE IF NOT EXISTS fills(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts      TEXT,
            symbol  TEXT,
            side    TEXT,
            px      REAL,
            qty     REAL,
            notional REAL,
            fee     REAL,
            paper   INTEGER,
            raw     TEXT
        );
    """)

    cx.exec_driver_sql("""
        CREATE TABLE IF NOT EXISTS pnl(
            date       PRIMARY KEY,
            realized   REAL DEFAULT 0,
            unrealized REAL DEFAULT 0
        );
    """)

# --- exchange factory ---
def make_ex(exchange: str):
    common = {"enableRateLimit": True, "timeout": 15000, "options": {"fetchCurrencies": False}}
    if exchange == "cryptocom":
        # public-only in paper; keys only for live later
        return ccxt.cryptocom(common) if PAPER else ccxt.cryptocom({
            **common,
            "apiKey": os.getenv("CRYPTOCOM_API_KEY", ""),
            "secret": os.getenv("CRYPTOCOM_API_SECRET", ""),
        })
    if exchange == "kraken":
        return ccxt.kraken(common)
    if exchange == "binance":
        return ccxt.binance(common)
    raise ValueError("Unsupported exchange")

ex = make_ex(EXCHANGE)

# --- robust retries for HTTPS session ---
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

_retry = Retry(
    total=5, connect=5, read=5, status=5,
    backoff_factor=0.5,
    status_forcelist=[429, 500, 502, 503, 504],
    raise_on_status=False,
)
ex.session.mount("https://", HTTPAdapter(max_retries=_retry))

def load_markets_with_retry(ex, tries: int = 5, base: float = 0.5):
    for i in range(tries):
        try:
            return ex.load_markets()
        except Exception as e:
            if i == tries - 1:
                raise
            time.sleep(base * (2 ** i))

try:
    MARKETS = load_markets_with_retry(ex)
except Exception:
    if EXCHANGE == "cryptocom":
        print("⚠️ Crypto.com public API reset; falling back to Kraken for paper mode.")
        EXCHANGE = "kraken"
        ex = make_ex(EXCHANGE)
        ex.session.mount("https://", HTTPAdapter(max_retries=_retry))
        MARKETS = load_markets_with_retry(ex)
    else:
        raise

# ========== market helpers ==========
def mkt(symbol: str):
    return MARKETS[symbol]

def quote_ccy(symbol: str) -> str:
    return mkt(symbol)["quote"]

def base_ccy(symbol: str) -> str:
    return mkt(symbol)["base"]

def round_price(symbol: str, px: float) -> float:
    prec = mkt(symbol).get("precision", {}).get("price")
    if prec is not None:
        return float(f"{px:.{prec}f}")
    tick = (mkt(symbol).get("limits", {}) or {}).get("price", {}) or {}
    pmin = tick.get("min")
    return px if not pmin else max(pmin, px)

def round_amount(symbol: str, qty: float) -> float:
    prec = mkt(symbol).get("precision", {}).get("amount")
    if prec is not None:
        return float(f"{qty:.{prec}f}")
    lims = (mkt(symbol).get("limits", {}) or {}).get("amount", {}) or {}
    amin = lims.get("min")
    return qty if not amin else max(amin, qty)

def min_notional(symbol: str) -> float | None:
    return ((mkt(symbol).get("limits", {}) or {}).get("cost", {}) or {}).get("min") or MIN_NOTIONAL

def last_price(symbol: str) -> float:
    t = ex.fetch_ticker(symbol)
    return float(t["last"])

def fetch_ohlcv(symbol: str, timeframe: str = TIMEFRAME, limit: int = 1000) -> pd.DataFrame:
    ohlcv = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns="ts o h l c v".split())
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True).dt.tz_convert(None)
    return df

# ========== paper balances & risk ==========
_balances = PAPER_BAL.copy()  # quote balances only for MVP, e.g., {"EUR": 10000}

def equity_quote(quote: str) -> float:
    return float(_balances.get(quote, 0.0))

def quote_balance(symbol: str) -> float:
    return equity_quote(quote_ccy(symbol))

def size_by_risk(symbol: str, side: str, px: float) -> float:
    q = quote_ccy(symbol)
    quote_bal = equity_quote(q)
    if quote_bal <= 0:
        return 0.0

    # Max position allocation in quote
    max_alloc = quote_bal * (MAX_POS_PCT / 100.0)
    # DCA size or max_alloc, whichever smaller (for buy-only MVP)
    desired_notional = min(DCA_SIZE_Q, max_alloc)
    desired_notional = max(desired_notional, 0.0)

    # Exchange min notional
    mn = min_notional(symbol) or 0.0
    if desired_notional < mn:
        desired_notional = 0.0

    qty = desired_notional / px if px > 0 else 0.0
    qty = round_amount(symbol, qty)
    return max(qty, 0.0)

def risk_okay(symbol: str, side: str, px: float, qty: float, quote_bal: float) -> tuple[bool, str]:
    notional = px * qty
    if qty <= 0 or notional <= 0:
        return False, "qty_or_notional_zero"
    mn = min_notional(symbol) or 0.0
    if notional < mn:
        return False, f"below_min_notional({mn})"
    # naive daily loss cap placeholder (no MTM yet in MVP)
    # could read realized from pnl and compare against DAILY_LOSS_CAP * starting_equity
    return True, "ok"

# ========== strategies ==========
def signal_ma(symbol: str) -> str | None:
    df = fetch_ohlcv(symbol, TIMEFRAME, limit=max(200, MA_SLOW + 2))
    price = df["c"]
    fast = price.rolling(MA_FAST).mean()
    slow = price.rolling(MA_SLOW).mean()
    if len(price) < max(MA_FAST, MA_SLOW) + 1:
        return None
    cross_up   = fast.iloc[-1] > slow.iloc[-1] and fast.iloc[-2] <= slow.iloc[-2]
    cross_down = fast.iloc[-1] < slow.iloc[-1] and fast.iloc[-2] >= slow.iloc[-2]
    if cross_up:
        return "buy"
    if cross_down:
        return "sell"
    return None

# ========= order placement (paper) =========

from math import floor

# --- tiny helpers (display + exchange step rounding) ---

def _fmt_qty(x: float) -> str:
    return f"{x:.8f}"

def _fmt_px(x: float) -> str:
    return f"{x:.6f}"

def _amount_step(symbol: str) -> float | None:
    """Best-effort amount step (may be a float like 1e-08 on some exchanges)."""
    return (mkt(symbol).get("precision", {}) or {}).get("amount")

def _price_step(symbol: str) -> float | None:
    return (mkt(symbol).get("precision", {}) or {}).get("price")

def _round_to_step(value: float, step: float | None, fallback_decimals: int) -> float:
    """
    If `step` is a positive float (e.g., 1e-08), quantize by step.
    Otherwise round to a fixed number of decimals for display/consistency.
    """
    if step is not None:
        try:
            s = float(step)
            if s > 0:
                return floor(value / s) * s
        except Exception:
            pass
    # fallback (no dynamic precision!)
    return float(f"{value:.{fallback_decimals}f}")

def _round_qty(symbol: str, qty: float) -> float:
    return _round_to_step(qty, _amount_step(symbol), fallback_decimals=8)

def _round_px(symbol: str, px: float) -> float:
    return _round_to_step(px, _price_step(symbol), fallback_decimals=6)


def place_order(symbol: str, side: str, px: float, qty: float) -> dict:
    """
    Paper-mode order placement: writes to DB (orders + fills), updates paper balances.
    Returns a lightweight dict with 'status' etc. (good for logging).
    """
    ts = dt.datetime.now(dt.timezone.utc).isoformat()
    status = "filled"  # simulate immediate fill in paper
    notional = px * qty
    fee = notional * FEE

    if PAPER:
        q = quote_ccy(symbol)
        if side == "buy":
            # spend quote, receive base (we only track quote buckets for PnL)
            _balances[q] = _balances.get(q, 0.0) - (notional + fee)
        else:
            _balances[q] = _balances.get(q, 0.0) + (notional - fee)

    raw = {
        "ts": ts,
        "symbol": symbol,
        "side": side,
        "px": px,
        "qty": qty,
        "notional": notional,
        "fee": fee,
        "paper": PAPER,
        "status": status,
    }

    with engine.begin() as cx:
        cx.execute(text("""
            INSERT INTO orders(ts, symbol, side, px, qty, notional, fee, paper, status, raw)
            VALUES(:ts, :symbol, :side, :px, :qty, :notional, :fee, :paper, :status, :raw)
        """), {**raw, "raw": json.dumps(raw)})
        cx.execute(text("""
            INSERT INTO fills(ts, symbol, side, px, qty, notional, fee, paper, raw)
            VALUES(:ts, :symbol, :side, :px, :qty, :notional, :fee, :paper, :raw)
        """), {**raw, "raw": json.dumps(raw)})

    return {"status": status}


# ========== one pass across symbols ==========
def trade_once():
    for agent in AGENTS:
        try:
            agent.step()
        except Exception as e:
            print(f"[AGENT ERROR] {agent.__class__.__name__}: {e}")

# ========== optional: quick stats (Milestone 3) ==========
def print_symbol_info():
    for s in SYMBOLS:
        info = mkt(s)
        print(
            s,
            "limits:", info.get("limits"),
            "precision:", info.get("precision"),
        )


# --- seed one paper order if DB empty (for smoke-test/UI wiring) ---
def seed_if_empty():
    try:
        print(f"[seed] SYMBOLS = {SYMBOLS}")
        with engine.begin() as cx:
            n = cx.scalar(text("SELECT COUNT(*) FROM orders")) or 0
            print(f"[seed] orders in DB: {n}")
            if n == 0 and PAPER:
                for sym in SYMBOLS:
                    px = last_price(sym) or 0.0
                    print(f"[seed] last_price({sym}) = {px}")
                    print(f"[seed] checking {sym}...")
                    try:
                        px = last_price(sym)
                        print(f"[seed] last_price({sym}) = {px}")
                    except Exception as e:
                        print(f"[seed] ERROR in last_price({sym}): {e!r}")
                        px = 0.0

                    if px > 0:
                        qty = _round_qty(sym, max(DCA_SIZE_Q / px, 0.0))
                        print(f"[seed] placing {sym} qty={qty} @ px={px}")
                        place_order(sym, "buy", _round_px(sym, px), qty)
                        print(f"[seed] placed paper order in {sym}")
                    else:
                        print(f"[seed] skipped {sym}: price <= 0")
    except Exception as e:
        print(f"[seed] error: {e!r}")


# ========== main ==========
if __name__ == "__main__":
    print("-- Paper trading loop (Ctrl+C to stop) --")
    
    seed_if_empty()  # ← Make sure this is here!
    
    while True:
        try:
            if is_paused():
                print("[paused] trading paused; sleeping...")
                time.sleep(POLL)
                continue

            trade_once()
            time.sleep(POLL)

        except KeyboardInterrupt:
            print("\nbye")
            break
        except Exception as e:
            print("loop error:", repr(e))
            time.sleep(POLL)