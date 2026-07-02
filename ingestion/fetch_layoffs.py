"""
ingestion/fetch_layoffs.py
Scrapes layoffs.fyi from its public Airtable shared view,
cleans the dataset, and inserts new records into Snowflake RAW.RAW_LAYOFFS_FYI.

Usage:
    python fetch_layoffs.py
"""

import os
import re
import hashlib
import urllib.parse
import requests
import pandas as pd
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

EMBED_URL = "https://airtable.com/embed/app1PaujS9zxVGUZ4/shroKsHx3SdYYOzeh?backgroundColor=green&viewControls=on"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Airtable's public "downloadCsv" endpoint now requires a logged-in session
# (it 302s to /login). The embed page instead prefetches row data via
# readSharedViewData, authorized by a short-lived signed accessPolicy token
# embedded in the page HTML. We extract and reuse that token.
COLUMN_NAME_MAP = {
    "Company": "company",
    "Location HQ": "location_hq",
    "Industry": "industry",
    "# Laid Off": "laid_off_count",
    "Date": "laid_off_date",
    "%": "percentage",
    "Stage": "stage",
    "$ Raised (mm)": "funds_raised_m",
    "Country": "country",
    "Source": "source_url",
}

TARGET_COLS = [
    "company", "location_hq", "industry", "laid_off_count",
    "percentage", "laid_off_date", "stage", "funds_raised_m",
    "country", "source_url",
]


def _resolve_cell(value, column):
    """Convert a raw Airtable cell value into a plain Python value."""
    if value is None:
        return None
    col_type = column["type"]
    if col_type == "select":
        choice = (column.get("typeOptions") or {}).get("choices", {}).get(value)
        return choice["name"] if choice else None
    if col_type == "multiSelect":
        choices = (column.get("typeOptions") or {}).get("choices", {})
        names = [choices[v]["name"] for v in value if v in choices]
        return ", ".join(names) if names else None
    if col_type == "date":
        return value[:10]
    return value


def _rows_to_dataframe(table: dict) -> pd.DataFrame:
    columns = {c["id"]: c for c in table["columns"]}
    field_by_col_id = {
        col_id: COLUMN_NAME_MAP[col["name"]]
        for col_id, col in columns.items()
        if col["name"] in COLUMN_NAME_MAP
    }

    records = []
    for row in table["rows"]:
        cells = row.get("cellValuesByColumnId", {})
        records.append({
            field: _resolve_cell(cells.get(col_id), columns[col_id])
            for col_id, field in field_by_col_id.items()
        })

    return pd.DataFrame.from_records(records, columns=list(COLUMN_NAME_MAP.values()))


def fetch_layoffs() -> pd.DataFrame:
    """Fetch shared view row data from Airtable's readSharedViewData endpoint."""
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    print("Requesting Airtable embed page...")
    resp = session.get(EMBED_URL, timeout=30)
    resp.raise_for_status()
    html = resp.text

    prefetch_match = re.search(r'urlWithParams:\s*"([^"]+)"', html)
    if not prefetch_match:
        raise ValueError("Could not find prefetch request in Airtable embed page HTML.")

    raw_url = prefetch_match.group(1).encode().decode("unicode_escape")
    parsed = urllib.parse.urlsplit(raw_url)
    params = urllib.parse.parse_qs(parsed.query)

    access_policy = params.get("accessPolicy", [None])[0]
    stringified_params = params.get("stringifiedObjectParams", [None])[0]
    request_id = params.get("requestId", [None])[0]
    if not (access_policy and stringified_params and request_id):
        raise ValueError("Could not extract accessPolicy token from Airtable embed page HTML.")

    query = urllib.parse.urlencode({
        "stringifiedObjectParams": stringified_params,
        "requestId": request_id,
    })
    data_url = f"https://airtable.com{parsed.path}?{query}"

    app_id_match = re.search(r"/embed/(app[a-zA-Z0-9]+)/", EMBED_URL)
    application_id = app_id_match.group(1) if app_id_match else ""

    print("Fetching shared view data...")
    data_resp = session.get(
        data_url,
        headers={
            "x-airtable-access-policy": access_policy,
            "x-airtable-application-id": application_id,
            "x-time-zone": "UTC",
            "x-user-locale": "en",
            "x-requested-with": "XMLHttpRequest",
            "Referer": EMBED_URL,
        },
        timeout=30,
    )
    data_resp.raise_for_status()
    payload = data_resp.json()

    return _rows_to_dataframe(payload["data"]["table"])


def clean_and_map_df(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce types and compute a stable dedup id for Snowflake loading."""
    print(f"Fetched columns: {list(df.columns)}")

    for col in TARGET_COLS:
        if col not in df.columns:
            df[col] = None

    # Clean types
    df["laid_off_count"] = pd.to_numeric(df["laid_off_count"], errors="coerce")
    df["percentage"] = pd.to_numeric(df["percentage"], errors="coerce")
    df["funds_raised_m"] = pd.to_numeric(df["funds_raised_m"], errors="coerce")

    # Handle dates
    df["laid_off_date"] = pd.to_datetime(df["laid_off_date"], errors="coerce")

    # Exclude rows without a company name
    df = df.dropna(subset=["company"])

    # Compute unique layoff_id (MD5 hash)
    def generate_id(row):
        d_str = str(row["laid_off_date"].date()) if pd.notna(row["laid_off_date"]) else ""
        c_str = str(row["laid_off_count"]) if pd.notna(row["laid_off_count"]) else ""
        p_str = str(row["percentage"]) if pd.notna(row["percentage"]) else ""
        text = f"{row['company']}_{d_str}_{c_str}_{p_str}"
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    df["layoff_id"] = df.apply(generate_id, axis=1)

    # Standardize date format for Snowflake insert
    df["laid_off_date"] = df["laid_off_date"].dt.strftime("%Y-%m-%d")

    # Convert Pandas NaN to None for db insertion. astype(object) first:
    # .where() on a float64 column re-coerces None back to NaN, since a numpy
    # float array has nowhere to put a Python None.
    df = df.astype(object).where(pd.notnull(df), None)

    return df[["layoff_id"] + TARGET_COLS]


def load_to_snowflake(df: pd.DataFrame, conn) -> int:
    """Insert rows only if they don't already exist."""
    cursor = conn.cursor()
    cols = list(df.columns)
    placeholders = ", ".join(["%s"] * len(cols))

    sql = f"""
        INSERT INTO RAW_LAYOFFS_FYI ({', '.join(cols)})
        SELECT {placeholders}
        WHERE NOT EXISTS (
          SELECT 1 FROM RAW_LAYOFFS_FYI WHERE layoff_id = %s
        )
    """

    inserted = 0
    for _, row in df.iterrows():
        vals = tuple(row[c] for c in cols)
        cursor.execute(sql, vals + (row["layoff_id"],))
        inserted += cursor.rowcount

    cursor.close()
    return inserted


def main():
    print("Connecting to Snowflake...")
    conn = snowflake.connector.connect(**SF)

    try:
        raw_df = fetch_layoffs()
        print(f"Fetched {len(raw_df)} records from Airtable shared view.")

        cleaned_df = clean_and_map_df(raw_df)
        print("Inserting records into Snowflake...")
        inserted = load_to_snowflake(cleaned_df, conn)
        print(f"Successfully inserted {inserted} new records (skipped existing duplicates).")
    finally:
        conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
