"""
ingestion/fetch_job_postings.py
Fetches the Indeed Hiring Lab job postings tracker (free CSVs on GitHub) and
writes it to Snowflake RAW.RAW_JOB_POSTINGS.

Job postings are the hiring side of the cycle that layoff counts miss — the
post-2022 collapse in software-development postings is the most-cited AI
job-displacement chart, and it never appears in layoff data at all. The index
is normalized to Feb 1, 2020 = 100, which matches this project's analysis
window exactly.

Series written:
    US_TOTAL             aggregate US postings index
    <SECTOR NAME>        one series per Hiring Lab sector (e.g. SOFTWARE
                         DEVELOPMENT), from the by-sector file

Usage:
    python fetch_job_postings.py

Environment variables:
    SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_TOKEN, SNOWFLAKE_ROLE
    (no API key — public GitHub-hosted CSVs)
"""

import os
import io
import requests
import pandas as pd
import snowflake.connector

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

REPO_RAW = "https://raw.githubusercontent.com/hiring-lab/job_postings_tracker"
AGGREGATE_PATHS = ["US/aggregate_job_postings_US.csv"]
SECTOR_PATHS    = ["US/job_postings_by_sector_US.csv"]
BRANCHES        = ["master", "main"]


def _fetch_csv(paths: list[str]) -> pd.DataFrame:
    """Try each path across known branches; Hiring Lab has moved files before."""
    last_err = None
    for branch in BRANCHES:
        for path in paths:
            url = f"{REPO_RAW}/{branch}/{path}"
            try:
                resp = requests.get(url, timeout=60)
                resp.raise_for_status()
                return pd.read_csv(io.StringIO(resp.text))
            except (requests.RequestException, pd.errors.ParserError) as e:
                last_err = e
    raise RuntimeError(f"Could not fetch Hiring Lab CSV from any known location: {last_err}")


def _pick_columns(df: pd.DataFrame) -> tuple[str, str, str | None]:
    """Locate (date_col, value_col, sector_col) without pinning exact names —
    Hiring Lab has renamed columns across revisions. Prefer the seasonally
    adjusted index when both SA and NSA are published."""
    cols = {c.lower(): c for c in df.columns}

    date_col = next((cols[c] for c in cols if c == "date" or c.endswith("_date")), None)
    if date_col is None:
        raise RuntimeError(f"No date column found in {list(df.columns)}")

    index_cols = [c for c in df.columns if "index" in c.lower()]
    if not index_cols:
        raise RuntimeError(f"No postings-index column found in {list(df.columns)}")
    sa = [c for c in index_cols if "sa" in c.lower().split("_") or c.lower().endswith("_sa")]
    nsa = [c for c in index_cols if "nsa" in c.lower()]
    value_col = (sa or [c for c in index_cols if c not in nsa] or index_cols)[0]

    sector_col = next(
        (cols[c] for c in cols if c in ("display_name", "sector", "sector_name")), None
    )
    return date_col, value_col, sector_col


def _normalize(df: pd.DataFrame, fixed_series: str | None) -> pd.DataFrame:
    """Melt a Hiring Lab CSV into (series_id, observation_date, value) rows."""
    date_col, value_col, sector_col = _pick_columns(df)
    out = pd.DataFrame({
        "observation_date": pd.to_datetime(df[date_col], errors="coerce").dt.date,
        "value": pd.to_numeric(df[value_col], errors="coerce"),
    })
    if fixed_series is not None:
        out["series_id"] = fixed_series
    elif sector_col is not None:
        out["series_id"] = df[sector_col].astype(str).str.strip().str.upper()
    else:
        raise RuntimeError("Sector file has no recognizable sector column")
    out = out.dropna(subset=["observation_date", "value"])
    return out[["series_id", "observation_date", "value"]]


STAGE_CHUNK = 10000


def load_to_snowflake(df: pd.DataFrame, conn) -> int:
    """Bulk-load via a temp table + one MERGE.

    The per-row INSERT ... WHERE NOT EXISTS pattern the smaller fetchers use
    is one network round-trip per row — fine for hundreds of rows, hours for
    this source (~200K rows across 41 sectors). executemany bulk-binds the
    staging inserts and the MERGE dedups in a single statement.
    """
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TEMPORARY TABLE IF NOT EXISTS TMP_JOB_POSTINGS
          (series_id VARCHAR, observation_date DATE, value FLOAT)
    """)
    cursor.execute("TRUNCATE TABLE TMP_JOB_POSTINGS")

    # native Python types — the connector doesn't bind numpy scalars
    rows = [(str(r.series_id), r.observation_date, float(r.value))
            for r in df.itertuples(index=False)]
    for i in range(0, len(rows), STAGE_CHUNK):
        cursor.executemany(
            "INSERT INTO TMP_JOB_POSTINGS (series_id, observation_date, value) VALUES (%s, %s, %s)",
            rows[i:i + STAGE_CHUNK],
        )
        print(f"  staged {min(i + STAGE_CHUNK, len(rows)):,}/{len(rows):,} rows")

    cursor.execute("""
        MERGE INTO RAW_JOB_POSTINGS t
        USING (
            SELECT series_id, observation_date, value
            FROM TMP_JOB_POSTINGS
            QUALIFY row_number() OVER (
              PARTITION BY series_id, observation_date ORDER BY value
            ) = 1
        ) s
        ON t.series_id = s.series_id AND t.observation_date = s.observation_date
        WHEN NOT MATCHED THEN
          INSERT (series_id, observation_date, value)
          VALUES (s.series_id, s.observation_date, s.value)
    """)
    inserted = cursor.rowcount or 0
    cursor.close()
    return inserted


def main():
    conn = snowflake.connector.connect(**SF)
    try:
        print("Fetching Hiring Lab aggregate US postings index...")
        agg = _normalize(_fetch_csv(AGGREGATE_PATHS), fixed_series="US_TOTAL")
        print(f"  {len(agg)} rows ({agg['observation_date'].min()} → {agg['observation_date'].max()})")

        print("Fetching Hiring Lab by-sector postings index...")
        sectors = _normalize(_fetch_csv(SECTOR_PATHS), fixed_series=None)
        print(f"  {len(sectors)} rows across {sectors['series_id'].nunique()} sectors")

        combined = pd.concat([agg, sectors], ignore_index=True)
        n = load_to_snowflake(combined, conn)
        print(f"Inserted {n} new rows (duplicates skipped).")
    finally:
        conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
