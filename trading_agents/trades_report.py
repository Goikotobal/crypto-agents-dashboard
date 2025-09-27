import sqlite3
from tabulate import tabulate

DB_PATH = "ledger.sqlite"


def fetch_trades():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    try:
        c.execute("SELECT symbol, side, qty, price, timestamp FROM trades ORDER BY timestamp DESC")
        rows = c.fetchall()
        if not rows:
            print("No trades found.")
            return

        print("\n=== Trades Summary ===\n")
        print(tabulate(rows, headers=["Symbol", "Side", "Qty", "Price", "Timestamp"], floatfmt=".4f"))

    except sqlite3.Error as e:
        print(f"[DB ERROR] {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    fetch_trades()
