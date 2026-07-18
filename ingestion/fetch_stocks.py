"""
ingestion/fetch_stocks.py
Fetches daily closing prices for tech stocks (MSFT, GOOGL, AMZN, TSLA, QQQ)
plus the S&P 500 index (^GSPC) as an overall-market baseline, via the public
Yahoo Finance chart API, and writes them to Snowflake RAW.RAW_STOCK_PRICES.

Usage:
    python fetch_stocks.py
"""

import os
import requests
import pandas as pd
from datetime import datetime
from urllib.parse import quote
import snowflake.connector

# ── Config ─────────────────────────────────────────────────────────────────
SF = dict(
    account       = os.environ["SNOWFLAKE_ACCOUNT"],
    user          = os.environ["SNOWFLAKE_USER"],
    authenticator = "PROGRAMMATIC_ACCESS_TOKEN",
    token         = os.environ["SNOWFLAKE_TOKEN"],
    role          = os.getenv("SNOWFLAKE_ROLE", "SYSADMIN"),
    warehouse     = "LABOR_WH",
    database      = "LABOR_MARKET",
    schema        = "RAW",
)

# ^GSPC (S&P 500) anchors the tech proxies to the overall market — without
# it, a QQQ drawdown can't be read as tech-specific vs. market-wide.
TICKERS = ["MSFT", "GOOGL", "AMZN", "TSLA", "QQQ", "^GSPC"]

# Fixed history start rather than a rolling "5y" range: the analysis window
# begins in 2020 (pre-ChatGPT baseline), and a rolling range silently loses
# the front of that window as time passes.
HISTORY_START = datetime(2020, 1, 1)


def fetch_stock_data(ticker: str) -> pd.DataFrame:
    """Fetch daily close prices since HISTORY_START for a symbol from Yahoo Finance."""
    # quote() so index symbols like ^GSPC form a valid URL path
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(ticker)}"
    params = {
        "interval": "1d",
        "period1": int(HISTORY_START.timestamp()),
        "period2": int(datetime.now().timestamp()),
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    print(f"Requesting chart data for {ticker}...")
    resp = requests.get(url, params=params, headers=headers, timeout=30)
    resp.raise_for_status()
    
    json_data = resp.json()
    
    if not json_data.get("chart", {}).get("result"):
        raise ValueError(f"No chart results returned for symbol: {ticker}")
        
    result = json_data["chart"]["result"][0]
    timestamps = result.get("timestamp", [])
    quotes = result.get("indicators", {}).get("quote", [{}])[0]
    closes = quotes.get("close", [])
    
    rows = []
    for ts, val in zip(timestamps, closes):
        if val is not None and pd.notna(val):
            obs_date = datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
            rows.append({
                "ticker": ticker,
                "observation_date": obs_date,
                "close_val": float(val)
            })
            
    return pd.DataFrame(rows)


def load_to_snowflake(df: pd.DataFrame, conn) -> int:
    """Load stock price records, preventing duplicates by unique key checks."""
    cursor = conn.cursor()
    cols = list(df.columns)
    placeholders = ", ".join(["%s"] * len(cols))
    
    sql = f"""
        INSERT INTO RAW_STOCK_PRICES ({', '.join(cols)})
        SELECT {placeholders}
        WHERE NOT EXISTS (
          SELECT 1 
          FROM RAW_STOCK_PRICES 
          WHERE ticker = %s AND observation_date = %s
        )
    """
    
    inserted = 0
    for _, row in df.iterrows():
        vals = tuple(row[c] for c in cols)
        # Bind checking attributes (ticker, observation_date) to WHERE NOT EXISTS check
        cursor.execute(sql, vals + (row["ticker"], row["observation_date"]))
        inserted += cursor.rowcount
        
    cursor.close()
    return inserted


def main():
    print("Connecting to Snowflake...")
    conn = snowflake.connector.connect(**SF)
    
    try:
        all_dfs = []
        for ticker in TICKERS:
            try:
                df = fetch_stock_data(ticker)
                print(f"  Fetched {len(df)} price records for {ticker}.")
                all_dfs.append(df)
            except Exception as e:
                print(f"  Error fetching data for {ticker}: {e}")
                
        if all_dfs:
            combined = pd.concat(all_dfs, ignore_index=True)
            print("Loading prices to Snowflake...")
            inserted = load_to_snowflake(combined, conn)
            print(f"Successfully loaded {inserted} new price rows.")
        else:
            print("No stock data was fetched.")
    finally:
        conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
