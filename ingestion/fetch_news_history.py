"""
ingestion/fetch_news_history.py
Fetches AI + labor-market + IPO headlines from two free, keyless sources with
deep archives, and writes them to the same RAW_NEWS_HEADLINES table as NewsAPI:

  - GDELT DOC 2.0 API   — global news coverage, full-text search back to 2017
  - Hacker News (Algolia) — tech community stories back to 2006

NewsAPI's free tier only reaches ~1 month back, which makes a pre-ChatGPT
baseline impossible. These two sources close that gap: `--backfill` walks
month-by-month windows from 2020-01-01 so the fear-vs-reality comparison has
history on both sides of Nov 2022.

GDELT rate-limits per IP (~1 request / 5 s), so the full backfill takes on the
order of 30-40 minutes; 429s are retried with backoff. Runs are idempotent
(URL-hash dedup on insert), so an interrupted backfill can be resumed with
--from set to wherever the last run's per-month progress output stopped.

Usage:
    python fetch_news_history.py                 # incremental: last 7 days
    python fetch_news_history.py --backfill      # full history since 2020-01-01
    python fetch_news_history.py --from 2021-01-01 --to 2021-12-31

Environment variables:
    SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_TOKEN, SNOWFLAKE_ROLE
    (no API keys needed — both sources are public, unauthenticated endpoints)
"""

import os
import time
import hashlib
import argparse
import requests
import pandas as pd
from datetime import datetime, timedelta
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

BACKFILL_START = "2020-01-01"

# GDELT DOC query syntax: quoted phrases, plain terms are ANDed, OR groups
# must be parenthesized. sourcelang:english keeps the corpus classifiable.
# Consolidated into 3 OR-group queries (not one per topic): GDELT throttles
# per-IP at roughly 1 request / 5 seconds, so a 2020+ backfill at 7 queries
# per month-window would take hours and draw constant 429s. The cost is the
# shared 250-records-per-request cap across each group's topics.
GDELT_QUERIES = [
    '("tech layoffs" OR "AI layoffs" OR "job displacement") sourcelang:english',
    '"artificial intelligence" (layoffs OR jobs OR workers OR automation) sourcelang:english',
    '("OpenAI" OR "Anthropic" OR "SpaceX") (IPO OR valuation) sourcelang:english',
]

# ~1 request / 5 s is the safe per-IP rate for the GDELT DOC API
GDELT_DELAY_SECONDS = 5
GDELT_MAX_RETRIES = 4

# HN full-text search matches title + story text; keep queries targeted so
# downstream Cortex classification credits aren't spent on noise.
HN_QUERIES = [
    "layoffs",
    "hiring freeze",
    "AI jobs",
    "job market",
    "OpenAI IPO",
    "Anthropic valuation",
    "SpaceX valuation",
]


# ── GDELT ──────────────────────────────────────────────────────────────────
def _gdelt_get(params: dict) -> requests.Response:
    """GET with backoff on 429/5xx — a skipped window is silently lost
    backfill data, so rate limiting must be retried, not swallowed."""
    for attempt in range(GDELT_MAX_RETRIES + 1):
        resp = requests.get(
            "https://api.gdeltproject.org/api/v2/doc/doc",
            params=params, timeout=60,
        )
        if resp.status_code == 429 or resp.status_code >= 500:
            if attempt == GDELT_MAX_RETRIES:
                resp.raise_for_status()
            retry_after = resp.headers.get("Retry-After", "")
            wait = int(retry_after) if retry_after.isdigit() else GDELT_DELAY_SECONDS * (2 ** (attempt + 1))
            print(f"    GDELT {resp.status_code}, backing off {wait}s "
                  f"(attempt {attempt + 1}/{GDELT_MAX_RETRIES})")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp


def fetch_gdelt(query: str, start: datetime, end: datetime) -> list[dict]:
    """Fetch up to 250 articles for one query over one datetime window."""
    resp = _gdelt_get({
        "query":         query,
        "mode":          "ArtList",
        "format":        "json",
        "maxrecords":    250,
        "sort":          "DateDesc",
        "startdatetime": start.strftime("%Y%m%d%H%M%S"),
        "enddatetime":   end.strftime("%Y%m%d%H%M%S"),
    })
    # GDELT returns plain-text error messages with HTTP 200 for malformed
    # queries or rate limiting — treat non-JSON as an empty (but logged) window.
    try:
        data = resp.json()
    except ValueError:
        print(f"    GDELT non-JSON response for {query!r}: {resp.text[:120]!r}")
        return []

    rows = []
    for a in data.get("articles", []):
        url   = a.get("url", "")
        title = (a.get("title") or "").strip()
        if not url or not title:
            continue
        # seendate format: 20200315T103000Z
        try:
            published = datetime.strptime(a.get("seendate", ""), "%Y%m%dT%H%M%SZ")
        except ValueError:
            continue
        rows.append({
            "article_id":   hashlib.md5(url.encode()).hexdigest(),
            "source_name":  a.get("domain", "gdelt"),
            "author":       "",
            "title":        title,
            "description":  "",
            "url":          url,
            "published_at": published,
            "full_text":    title,
        })
    return rows


# ── Hacker News (Algolia) ──────────────────────────────────────────────────
def fetch_hn(query: str, start: datetime, end: datetime, max_pages: int = 5) -> list[dict]:
    """Fetch stories matching a query within a created-at window."""
    rows = []
    for page in range(max_pages):
        resp = requests.get(
            "https://hn.algolia.com/api/v1/search_by_date",
            params={
                "query":          query,
                "tags":           "story",
                "numericFilters": f"created_at_i>={int(start.timestamp())},"
                                  f"created_at_i<{int(end.timestamp())}",
                "hitsPerPage":    100,
                "page":           page,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        for h in data.get("hits", []):
            title = (h.get("title") or "").strip()
            if not title:
                continue
            # Ask HN / Show HN posts have no external URL — link the thread itself
            url = h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}"
            try:
                published = datetime.fromtimestamp(h["created_at_i"])
            except (KeyError, TypeError, ValueError):
                continue
            rows.append({
                "article_id":   hashlib.md5(url.encode()).hexdigest(),
                "source_name":  "Hacker News",
                "author":       h.get("author") or "",
                "title":        title,
                "description":  "",
                "url":          url,
                "published_at": published,
                "full_text":    title,
            })

        if page + 1 >= data.get("nbPages", 0):
            break
    return rows


# ── Shared load path (same dedup pattern as fetch_news.py) ────────────────
def rows_to_df(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=[
            "article_id", "source_name", "author", "title",
            "description", "url", "published_at", "full_text",
        ])
    df = pd.DataFrame(rows).drop_duplicates("article_id")
    df["published_at"] = pd.to_datetime(df["published_at"], errors="coerce")
    df = df.dropna(subset=["published_at"])
    # snowflake-connector's pyformat binding doesn't accept pandas Timestamp
    # objects — and DataFrame construction converts datetimes to Timestamps.
    # Same workaround as fetch_news.py: an explicit object-dtype Series of
    # native datetimes, which pandas can't re-coerce. Per-scalar conversion
    # (not .dt.to_pydatetime()) to avoid that accessor's FutureWarning.
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


def month_windows(start: datetime, end: datetime):
    """Yield (window_start, window_end) month-sized windows covering [start, end)."""
    cur = start
    while cur < end:
        if cur.month == 12:
            nxt = cur.replace(year=cur.year + 1, month=1, day=1)
        else:
            nxt = cur.replace(month=cur.month + 1, day=1)
        yield cur, min(nxt, end)
        cur = nxt


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--backfill", action="store_true",
                        help=f"fetch full history since {BACKFILL_START}")
    parser.add_argument("--from", dest="from_date",
                        default=(datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"))
    parser.add_argument("--to", dest="to_date",
                        default=datetime.now().strftime("%Y-%m-%d"))
    args = parser.parse_args(argv)

    from_date = BACKFILL_START if args.backfill else args.from_date
    start = datetime.strptime(from_date, "%Y-%m-%d")
    end   = datetime.strptime(args.to_date, "%Y-%m-%d") + timedelta(days=1)

    print(f"Fetching GDELT + Hacker News headlines {from_date} → {args.to_date}")
    conn = snowflake.connector.connect(**SF)

    total_inserted = 0
    for win_start, win_end in month_windows(start, end):
        window_rows = []
        for q in GDELT_QUERIES:
            try:
                window_rows += fetch_gdelt(q, win_start, win_end)
            except requests.RequestException as e:
                print(f"    GDELT error for {q!r} (after retries): {e}")
            time.sleep(GDELT_DELAY_SECONDS)
        for q in HN_QUERIES:
            try:
                window_rows += fetch_hn(q, win_start, win_end)
            except requests.RequestException as e:
                print(f"    HN error for {q!r}: {e}")

        df = rows_to_df(window_rows)
        n = load_to_snowflake(df, conn) if not df.empty else 0
        total_inserted += n
        print(f"  {win_start:%Y-%m}: {len(df)} unique articles fetched, {n} new rows inserted")

    print(f"Done. Inserted {total_inserted} new rows total (duplicates skipped).")
    conn.close()


if __name__ == "__main__":
    main()
