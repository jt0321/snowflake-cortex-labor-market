"""
ingestion/fetch_polymarket.py
Fetches prediction-market probabilities from Polymarket's public Gamma API
for markets matching labor-market / AI / recession / IPO keywords, and
writes a daily snapshot to Snowflake RAW.RAW_POLYMARKET_MARKETS.

Polymarket markets are continuously priced — token price == implied
probability. We don't need to "search" because the Gamma API has no
reliable full-text search across all deployments, so we pull active
markets and filter client-side by keyword, matching the QUERIES pattern
used in fetch_news.py.

No API key required — Gamma API is public, read-only.

Usage:
    python fetch_polymarket.py

Environment variables required:
    SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_PASSWORD, SNOWFLAKE_ROLE
"""

import os
import json
import requests
import pandas as pd
from datetime import datetime, timezone
import snowflake.connector

# ── Config ─────────────────────────────────────────────────────────────────
SF = dict(
    account   = os.environ["SNOWFLAKE_ACCOUNT"],
    user      = os.environ["SNOWFLAKE_USER"],
    password  = os.environ["SNOWFLAKE_PASSWORD"],
    role      = os.getenv("SNOWFLAKE_ROLE", "SYSADMIN"),
    warehouse = "LABOR_WH",
    database  = "LABOR_MARKET",
    schema    = "RAW",
)

GAMMA_API = "https://gamma-api.polymarket.com/markets"

# Keywords to match against market questions — mirrors fetch_news.py's QUERIES
KEYWORDS = [
    "unemployment",
    "recession",
    "layoffs",
    "artificial intelligence jobs",
    "AI jobs",
    "openai ipo",
    "anthropic ipo",
    "spacex ipo",
]

PAGE_LIMIT = 100
MAX_PAGES = 10  # cap pagination — Gamma API defaults to 100/page


def _parse_listlike(value):
    """Gamma API sometimes returns outcomes/outcomePrices as a JSON string,
    sometimes as a native list, depending on endpoint version. Handle both."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return []
    return []


def fetch_active_markets() -> list[dict]:
    """Paginate through active, open markets on Polymarket."""
    markets = []
    offset = 0
    for _ in range(MAX_PAGES):
        resp = requests.get(
            GAMMA_API,
            params={
                "active": "true",
                "closed": "false",
                "limit": PAGE_LIMIT,
                "offset": offset,
            },
            timeout=30,
        )
        resp.raise_for_status()
        page = resp.json()
        if not page:
            break
        markets.extend(page)
        if len(page) < PAGE_LIMIT:
            break
        offset += PAGE_LIMIT
    return markets


def filter_by_keyword(markets: list[dict]) -> list[dict]:
    matched = []
    for m in markets:
        question = (m.get("question") or "").lower()
        if any(kw in question for kw in KEYWORDS):
            matched.append(m)
    return matched


def markets_to_df(markets: list[dict]) -> pd.DataFrame:
    """Normalize one row per (market, outcome) — binary markets yield 2 rows
    (e.g. Yes/No), each with its own implied probability."""
    snapshot_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = []
    for m in markets:
        outcomes = _parse_listlike(m.get("outcomes"))
        prices   = _parse_listlike(m.get("outcomePrices"))
        if not outcomes or not prices or len(outcomes) != len(prices):
            continue

        end_date = m.get("endDate")
        if end_date:
            end_date = end_date[:10]  # truncate ISO timestamp to date

        for outcome, price in zip(outcomes, prices):
            try:
                probability = float(price)
            except (TypeError, ValueError):
                continue
            rows.append({
                "market_id":     str(m.get("id", "")),
                "question":      m.get("question", ""),
                "outcome":       outcome,
                "probability":   probability,
                "volume":        float(m.get("volume") or 0),
                "liquidity":     float(m.get("liquidity") or 0),
                "end_date":      end_date,
                "snapshot_date": snapshot_date,
            })
    return pd.DataFrame(rows)


def load_to_snowflake(df: pd.DataFrame, conn) -> int:
    """Insert one snapshot row per (market_id, outcome, snapshot_date),
    skipping if already loaded today."""
    cursor = conn.cursor()
    cols = list(df.columns)
    placeholders = ", ".join(["%s"] * len(cols))

    sql = f"""
        INSERT INTO RAW_POLYMARKET_MARKETS ({', '.join(cols)})
        SELECT {placeholders}
        WHERE NOT EXISTS (
          SELECT 1 FROM RAW_POLYMARKET_MARKETS
          WHERE market_id = %s AND outcome = %s AND snapshot_date = %s
        )
    """
    inserted = 0
    for _, row in df.iterrows():
        vals = tuple(row[c] for c in cols)
        cursor.execute(sql, vals + (row["market_id"], row["outcome"], row["snapshot_date"]))
        inserted += cursor.rowcount
    cursor.close()
    return inserted


def main():
    print("Fetching active Polymarket markets...")
    markets = fetch_active_markets()
    print(f"  {len(markets)} active markets fetched")

    matched = filter_by_keyword(markets)
    print(f"  {len(matched)} markets match keywords: {KEYWORDS}")

    df = markets_to_df(matched)
    print(f"  {len(df)} outcome rows to load")

    if df.empty:
        print("No matching markets with valid pricing found. Done.")
        return

    conn = snowflake.connector.connect(**SF)
    try:
        n = load_to_snowflake(df, conn)
        print(f"Inserted {n} new rows (skipped duplicates already snapshotted today)")
    finally:
        conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
