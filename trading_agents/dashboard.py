import streamlit as st
import sqlite3

st.title("Crypto Agent Dashboard")

conn = sqlite3.connect("ledger.sqlite")
c = conn.cursor()

c.execute("SELECT timestamp, agent, symbol, side, qty, price FROM trades ORDER BY timestamp DESC LIMIT 10")
rows = c.fetchall()

for row in rows:
    st.write(f"{row[0]} | [{row[1]}] {row[2]} {row[3]} {row[4]} @ {row[5]}")
