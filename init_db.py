# init_db.py
import sqlite3

conn = sqlite3.connect("ledger.sqlite")
c = conn.cursor()

c.execute("""
CREATE TABLE IF NOT EXISTS trades (
    timestamp TEXT,
    agent TEXT,
    symbol TEXT,
    side TEXT,
    qty REAL,
    price REAL
)
""")

conn.commit()
conn.close()

print("✅ Trades table created.")
