import streamlit as st
import sqlite3
import pandas as pd
import altair as alt
from tabulate import tabulate
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="CryptoAgents Report", layout="wide")

DB_PATH = "ledger.sqlite"

def load_trades():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("""
        SELECT timestamp, agent, symbol, side, qty, price 
        FROM trades ORDER BY timestamp DESC LIMIT 100
    """)
    rows = c.fetchall()
    conn.close()

    df = pd.DataFrame(rows, columns=["Timestamp", "Agent", "Symbol", "Side", "Qty", "Price"])
    df["Timestamp"] = pd.to_datetime(df["Timestamp"], unit="s")
    return df

# Load data
df = load_trades()

st.title("📊 Crypto Agents Dashboard")
# Refresh the app every 60 seconds (60000 ms)
st_autorefresh(interval=60000, key="dashboardrefresh")

# Summary Table
st.subheader("📋 Trades Summary Table")
st.dataframe(df.style.format({"Qty": "{:.6f}", "Price": "{:.2f}"}), use_container_width=True)

# Chart
st.subheader("📈 Trades Over Time")
chart = alt.Chart(df).mark_circle(size=60).encode(
    x="Timestamp:T",
    y="Price:Q",
    color="Side:N",
    tooltip=["Timestamp", "Agent", "Symbol", "Side", "Qty", "Price"]
).interactive()
st.altair_chart(chart, use_container_width=True)

# Recent Trades Log Style
st.subheader("🧾 Recent Trades")
for _, row in df.head(10).iterrows():
    st.write(f"{row['Timestamp']} | [{row['Agent']}] {row['Side']} {row['Qty']} {row['Symbol']} @ {row['Price']:.2f}")

