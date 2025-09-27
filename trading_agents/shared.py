import os
import ccxt

# Configure Binance with keys from .env
binance = ccxt.binance({
    'apiKey': os.getenv("BINANCE_API_KEY"),
    'secret': os.getenv("BINANCE_API_SECRET"),
    'enableRateLimit': True,
    'timeout': 5000,
})

def place_order(symbol, side, price, qty):
    try:
        order = binance.create_market_order(symbol, side.lower(), qty)
        print(f"[LIVE ORDER] {side.upper()} {qty} {symbol} @ market price")
        return order
    except Exception as e:
        print(f"[ORDER ERROR] {e}")
        return None

def last_price(symbol):
    """
    Fetches the last price using ccxt (authenticated or public)
    """
    print(f"[DEBUG] Fetching price for {symbol}")
    try:
        ticker = binance.fetch_ticker(symbol)
        print(f"[DEBUG] Ticker response: {ticker}")
        return ticker['last']
    except Exception as e:
        print(f"[PRICE ERROR] {e}")
        return 0.0