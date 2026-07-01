"""
ingestion/fetch_econ.py
Fetches BLS JOLTS + CPS and FRED series, writes to Snowflake RAW schema.

Usage:
    python fetch_econ.py

Environment variables required:
    SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_TOKEN, SNOWFLAKE_ROLE
    BLS_API_KEY   (optional but recommended — raises rate limit)
    FRED_API_KEY  (free at https://fred.stlouisfed.org/docs/api/api_key.html)
"""

import os
import json
import hashlib
import requests
import pandas as pd
from datetime import datetime
import snowflake.connector

# ── Config ─────────────────────────────────────────────────────────────────
BLS_API_KEY  = os.getenv("BLS_API_KEY", "")
FRED_API_KEY = os.getenv("FRED_API_KEY")
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

# BLS series IDs
# JOLTS: total layoffs/discharges not seasonally adjusted
BLS_JOLTS_SERIES = [
    "JTS000000000000000LAY",   # total layoffs, all industries
    "JTS510000000000000LAY",   # information sector
    "JTS540000000000000LAY",   # professional & business services
    "JTS600000000000000LAY",   # education & health services
]
# CPS: unemployment rate + labor force participation
BLS_CPS_SERIES = ["LNS14000000", "LNS11300000"]

# FRED series
FRED_SERIES = ["UNRATE", "PAYEMS", "ICSA"]   # unemployment, payrolls, initial claims


# ── BLS ────────────────────────────────────────────────────────────────────
def fetch_bls(series_ids: list[str], start_year: int = 2019) -> pd.DataFrame:
    """Fetch multiple BLS series via v2 API."""
    end_year = datetime.now().year
    payload = {
        "seriesid": series_ids,
        "startyear": str(start_year),
        "endyear": str(end_year),
        "registrationkey": BLS_API_KEY,
    }
    resp = requests.post(
        "https://api.bls.gov/publicAPI/v2/timeseries/data/",
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if data["status"] != "REQUEST_SUCCEEDED":
        raise RuntimeError(f"BLS API error: {data['message']}")

    rows = []
    for series in data["Results"]["series"]:
        sid = series["seriesID"]
        for obs in series["data"]:
            rows.append({
                "series_id":   sid,
                "year":        int(obs["year"]),
                "period":      obs["period"],
                "period_name": obs["periodName"],
                "value":       float(obs["value"]) if obs["value"] != "-" else None,
                "footnotes":   ", ".join(f["text"] for f in obs.get("footnotes", []) if f),
            })
    return pd.DataFrame(rows)


# ── FRED ───────────────────────────────────────────────────────────────────
def fetch_fred(series_id: str, start: str = "2019-01-01") -> pd.DataFrame:
    resp = requests.get(
        "https://api.stlouisfed.org/fred/series/observations",
        params={
            "series_id":        series_id,
            "observation_start": start,
            "api_key":          FRED_API_KEY,
            "file_type":        "json",
        },
        timeout=30,
    )
    resp.raise_for_status()
    obs = resp.json()["observations"]
    df = pd.DataFrame(obs)[["date", "value"]]
    df["series_id"] = series_id
    df = df.rename(columns={"date": "observation_date"})
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df[["series_id", "observation_date", "value"]]


# ── Snowflake load ──────────────────────────────────────────────────────────
def load_to_snowflake(df: pd.DataFrame, table: str, conn) -> int:
    cursor = conn.cursor()
    rows = [tuple(r) for r in df.itertuples(index=False)]
    placeholders = ", ".join(["%s"] * len(df.columns))
    sql = f"INSERT INTO {table} ({', '.join(df.columns)}) VALUES ({placeholders})"
    cursor.executemany(sql, rows)
    cursor.close()
    return len(rows)


# ── Main ───────────────────────────────────────────────────────────────────
def main():
    conn = snowflake.connector.connect(**SF)

    # BLS JOLTS
    print("Fetching BLS JOLTS...")
    jolts = fetch_bls(BLS_JOLTS_SERIES)
    n = load_to_snowflake(jolts, "RAW_BLS_JOLTS", conn)
    print(f"  Loaded {n} JOLTS rows")

    # BLS CPS
    print("Fetching BLS CPS...")
    cps = fetch_bls(BLS_CPS_SERIES)
    n = load_to_snowflake(cps, "RAW_BLS_CPS", conn)
    print(f"  Loaded {n} CPS rows")

    # FRED
    print("Fetching FRED series...")
    fred_dfs = [fetch_fred(s) for s in FRED_SERIES]
    fred_df  = pd.concat(fred_dfs, ignore_index=True)
    n = load_to_snowflake(fred_df, "RAW_FRED_SERIES", conn)
    print(f"  Loaded {n} FRED rows")

    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
