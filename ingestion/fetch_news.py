"""
ingestion/fetch_news.py
Fetches AI + layoff news headlines from NewsAPI, writes to Snowflake RAW.

Free tier: 100 requests/day, 1 month of history.
Paid/dev tier: full archive access.

Usage:
    python fetch_news.py --from 2024-01-01 --to 2024-12-31

Environment variables:
    NEWS_API_KEY          (https://newsapi.org)
    SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_TOKEN, SNOWFLAKE_ROLE
"""

import os
import hashlib
import argparse
import requests
import pandas as pd
from datetime import datetime, timedelta
import snowflake.connector

NEWS_API_KEY = os.environ["NEWS_API_KEY"]
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

# Query clusters — run each separately to maximize coverage
QUERIES = [
    "layoffs AI automation",
    "artificial intelligence job displacement",
    "tech layoffs unemployment",
    "AI fear jobs workforce",
    "automation workers economy",
    "Anthropic IPO valuation",
    "OpenAI IPO valuation",
    "SpaceX IPO valuation",
    "tech IPO market Anthropic OpenAI SpaceX"
]



def fetch_headlines(query: str, from_date: str, to_date: str) -> list[dict]:
    """Fetch up to 100 articles per query from NewsAPI /everything endpoint."""
    resp = requests.get(
        "https://newsapi.org/v2/everything",
        params={
            "q":        query,
            "from":     from_date,
            "to":       to_date,
            "language": "en",
            "sortBy":   "publishedAt",
            "pageSize": 100,
            "apiKey":   NEWS_API_KEY,
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if data["status"] != "ok":
        raise RuntimeError(f"NewsAPI error: {data.get('message')}")
    return data.get("articles", [])


def articles_to_df(articles: list[dict]) -> pd.DataFrame:
    rows = []
    for a in articles:
        url   = a.get("url", "")
        title = a.get("title") or ""
        desc  = a.get("description") or ""
        rows.append({
            "article_id":   hashlib.md5(url.encode()).hexdigest(),
            "source_name":  (a.get("source") or {}).get("name", ""),
            "author":       a.get("author", ""),
            "title":        title,
            "description":  desc,
            "url":          url,
            "published_at": a.get("publishedAt", ""),
            # full_text is what Cortex AI functions will operate on
            "full_text":    f"{title}. {desc}".strip(". "),
        })
    df = pd.DataFrame(rows).drop_duplicates("article_id")
    df["published_at"] = pd.to_datetime(df["published_at"], utc=True, errors="coerce").dt.tz_localize(None)
    df = df.dropna(subset=["published_at"])
    # snowflake-connector's pyformat binding doesn't accept pandas Timestamp objects.
    # Assigning datetime.datetime values back into a column lets pandas re-infer
    # and silently convert them right back to datetime64[ns] — wrap them in an
    # explicit object-dtype Series so they actually stick as native datetimes.
    # Per-scalar conversion (not .dt.to_pydatetime()) to avoid that accessor's
    # FutureWarning.
    df["published_at"] = pd.Series(
        [ts.to_pydatetime() for ts in df["published_at"]], index=df.index, dtype=object
    )
    return df


def load_to_snowflake(df: pd.DataFrame, conn) -> int:
    cursor = conn.cursor()
    cols = list(df.columns)
    placeholders = ", ".join(["%s"] * len(cols))
    sql = f"""
        INSERT INTO RAW_NEWS_HEADLINES ({', '.join(cols)})
        SELECT {placeholders}
        WHERE NOT EXISTS (
          SELECT 1 FROM RAW_NEWS_HEADLINES WHERE article_id = %s
        )
    """
    inserted = 0
    for _, row in df.iterrows():
        vals = tuple(row[c] for c in cols)
        cursor.execute(sql, vals + (row["article_id"],))
        inserted += cursor.rowcount
    cursor.close()
    return inserted


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="from_date",
                        default=(datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"))
    parser.add_argument("--to",   dest="to_date",
                        default=datetime.now().strftime("%Y-%m-%d"))
    args = parser.parse_args(argv)

    print(f"Fetching headlines {args.from_date} → {args.to_date}")
    conn = snowflake.connector.connect(**SF)

    all_dfs = []
    for q in QUERIES:
        print(f"  Query: {q!r}")
        articles = fetch_headlines(q, args.from_date, args.to_date)
        df = articles_to_df(articles)
        print(f"    {len(df)} articles fetched")
        all_dfs.append(df)

    combined = pd.concat(all_dfs).drop_duplicates("article_id")
    print(f"Total unique articles: {len(combined)}")

    n = load_to_snowflake(combined, conn)
    print(f"Inserted {n} new rows (skipped duplicates)")
    conn.close()


if __name__ == "__main__":
    main()
