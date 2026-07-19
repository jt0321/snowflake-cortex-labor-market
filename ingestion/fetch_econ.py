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
# JOLTS: layoffs & discharges level, not seasonally adjusted.
# Data element code is LDL (not LAY, which doesn't exist), and professional
# & business services uses industry code 540099 (not 540000).
BLS_JOLTS_SERIES = [
    "JTS000000000000000LDL",   # total layoffs, all industries
    "JTS510000000000000LDL",   # information sector
    "JTS540099000000000LDL",   # professional & business services
    "JTS600000000000000LDL",   # education & health services
    # The other side of the cycle — layoffs alone miss a frozen market
    # (normal firing, collapsed hiring), which is where AI displacement
    # would show up first.
    "JTS000000000000000JOL",   # total job openings
    "JTS000000000000000HIL",   # total hires
    "JTS000000000000000QUL",   # total quits (worker confidence)
]
# CPS: unemployment rate + labor force participation + young workers
# (20-24) — the canonical "AI eats entry-level work" indicator
BLS_CPS_SERIES = ["LNS14000000", "LNS11300000", "LNS14000036"]

# FRED series — labor market plus the broader macro picture: without
# inflation and the policy rate alongside unemployment, layoffs can't be
# separated from ordinary business-cycle noise (e.g. the 2022-23 rate-hike
# cycle) when asking whether AI is what's moving the labor market.
FRED_SERIES = [
    "UNRATE",     # unemployment rate
    "PAYEMS",     # nonfarm payrolls
    "ICSA",       # weekly initial jobless claims
    "CPIAUCSL",   # CPI, all items (headline inflation)
    "CPILFESL",   # CPI less food & energy (core inflation)
    "FEDFUNDS",   # effective federal funds rate
    "USINFO",     # information-sector employment — direct tech-jobs measure
]


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
def load_to_snowflake(df: pd.DataFrame, table: str, key_cols: list[str], conn) -> int:
    """Insert rows only if they don't already exist (matched on key_cols).

    Runs repeat on daily/weekly/monthly schedules over overlapping date
    ranges, so a plain INSERT would re-duplicate rows on every run.
    """
    cursor = conn.cursor()
    # NaN floats bind as an unquoted NAN literal, which Snowflake parses as an
    # invalid identifier — convert to None so it binds as NULL instead.
    # astype(object) first: .where() on a float64 column re-coerces None back
    # to NaN, since a numpy float array has nowhere to put a Python None.
    df = df.astype(object).where(pd.notnull(df), None)
    cols = list(df.columns)
    placeholders = ", ".join(["%s"] * len(cols))
    key_match = " AND ".join(f"{k} = %s" for k in key_cols)

    sql = f"""
        INSERT INTO {table} ({', '.join(cols)})
        SELECT {placeholders}
        WHERE NOT EXISTS (
          SELECT 1 FROM {table} WHERE {key_match}
        )
    """

    inserted = 0
    for row in df.itertuples(index=False, name=None):
        vals = dict(zip(cols, row))
        cursor.execute(sql, tuple(vals[c] for c in cols) + tuple(vals[k] for k in key_cols))
        inserted += cursor.rowcount

    cursor.close()
    return inserted


# ── Main ───────────────────────────────────────────────────────────────────
def main():
    conn = snowflake.connector.connect(**SF)

    # BLS JOLTS
    print("Fetching BLS JOLTS...")
    jolts = fetch_bls(BLS_JOLTS_SERIES)
    n = load_to_snowflake(jolts, "RAW_BLS_JOLTS", ["series_id", "year", "period"], conn)
    print(f"  Loaded {n} JOLTS rows")

    # BLS CPS — RAW_BLS_CPS has no footnotes column (unlike RAW_BLS_JOLTS)
    print("Fetching BLS CPS...")
    cps = fetch_bls(BLS_CPS_SERIES).drop(columns=["footnotes"])
    n = load_to_snowflake(cps, "RAW_BLS_CPS", ["series_id", "year", "period"], conn)
    print(f"  Loaded {n} CPS rows")

    # FRED
    print("Fetching FRED series...")
    fred_dfs = [fetch_fred(s) for s in FRED_SERIES]
    fred_df  = pd.concat(fred_dfs, ignore_index=True)
    n = load_to_snowflake(fred_df, "RAW_FRED_SERIES", ["series_id", "observation_date"], conn)
    print(f"  Loaded {n} FRED rows")

    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
