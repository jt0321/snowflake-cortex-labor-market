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
import requests
import pandas as pd
from io import StringIO
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

EMBED_URL = "https://airtable.com/embed/app1PaujS9zxVGUZ4/shroKsHx3SdYYOzeh?backgroundColor=green&viewControls=on"


def fetch_layoffs() -> pd.DataFrame:
    """Fetch CSV directly from Airtable's public downloadCsv endpoint."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    print("Requesting Airtable embed page...")
    resp = requests.get(EMBED_URL, headers=headers, timeout=30)
    resp.raise_for_status()
    
    # Extract viewId (starts with viw)
    match = re.search(r'"viewId"\s*:\s*"([^"]+)"', resp.text)
    if not match:
        match = re.search(r'(viw[a-zA-Z0-9]{14})', resp.text)
        if not match:
            raise ValueError("Could not extract viewId from Airtable embed page HTML.")
            
    view_id = match.group(1)
    print(f"Parsed viewId: {view_id}")
    
    csv_url = f"https://airtable.com/v0.3/view/{view_id}/downloadCsv"
    print("Downloading CSV data...")
    csv_resp = requests.get(csv_url, headers=headers, timeout=30)
    csv_resp.raise_for_status()
    
    df = pd.read_csv(StringIO(csv_resp.text))
    return df


def clean_and_map_df(df: pd.DataFrame) -> pd.DataFrame:
    """Standardize fields and prepare dataset for Snowflake loading."""
    print(f"Raw CSV columns: {list(df.columns)}")
    
    # Normalize headers
    norm_cols = {col: col.strip().lower().replace(" ", "_").replace("-", "_") for col in df.columns}
    df = df.rename(columns=norm_cols)
    
    # Map standard source fields to target table columns
    mapping = {
        'company': 'company',
        'location_hq': 'location_hq',
        'location': 'location_hq',
        'industry': 'industry',
        'laid_off_count': 'laid_off_count',
        'percentage': 'percentage',
        'percentage_laid_off': 'percentage',
        'date': 'laid_off_date',
        'laid_off_date': 'laid_off_date',
        'stage': 'stage',
        'funds_raised': 'funds_raised_m',
        'funds_raised_millions': 'funds_raised_m',
        'funds_raised_m': 'funds_raised_m',
        'country': 'country',
        'source': 'source_url',
        'source_url': 'source_url',
    }
    
    mapped_df = pd.DataFrame()
    for src, dest in mapping.items():
        if src in df.columns and dest not in mapped_df.columns:
            mapped_df[dest] = df[src]
            
    # Add any missing target fields as None
    target_cols = [
        'company', 'location_hq', 'industry', 'laid_off_count', 
        'percentage', 'laid_off_date', 'stage', 'funds_raised_m', 
        'country', 'source_url'
    ]
    for col in target_cols:
        if col not in mapped_df.columns:
            mapped_df[col] = None
            
    # Clean types
    mapped_df['laid_off_count'] = pd.to_numeric(mapped_df['laid_off_count'], errors='coerce')
    mapped_df['percentage'] = pd.to_numeric(mapped_df['percentage'], errors='coerce')
    mapped_df['funds_raised_m'] = pd.to_numeric(mapped_df['funds_raised_m'], errors='coerce')
    
    # Handle dates
    mapped_df['laid_off_date'] = pd.to_datetime(mapped_df['laid_off_date'], errors='coerce')
    
    # Exclude rows without a company name
    mapped_df = mapped_df.dropna(subset=['company'])
    
    # Compute unique layoff_id (MD5 hash)
    def generate_id(row):
        d_str = str(row['laid_off_date'].date()) if pd.notna(row['laid_off_date']) else ""
        c_str = str(row['laid_off_count']) if pd.notna(row['laid_off_count']) else ""
        p_str = str(row['percentage']) if pd.notna(row['percentage']) else ""
        text = f"{row['company']}_{d_str}_{c_str}_{p_str}"
        return hashlib.md5(text.encode('utf-8')).hexdigest()
        
    mapped_df['layoff_id'] = mapped_df.apply(generate_id, axis=1)
    
    # Standardize date format for Snowflake insert
    mapped_df['laid_off_date'] = mapped_df['laid_off_date'].dt.strftime('%Y-%m-%d')
    
    # Convert Pandas NaN to None for db insertion
    mapped_df = mapped_df.where(pd.notnull(mapped_df), None)
    
    return mapped_df[['layoff_id'] + target_cols]


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
