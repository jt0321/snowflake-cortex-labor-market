# snowflake-cortex-labor-market

**Do the numbers back up the fear?**

An end-to-end data pipeline and analytics platform that uses Snowflake Cortex AI to investigate whether public anxiety about AI-driven job displacement is supported by actual economic data. Monthly BLS and FRED figures are joined with a news corpus, then analyzed using six Cortex AI functions to surface correlations, classify sentiment, and generate narrative digests — all surfaced in a Streamlit in Snowflake dashboard.

---

## What it does

- Ingests monthly labor data from the **BLS** (JOLTS layoffs by industry, CPS unemployment) and **FRED** (nonfarm payrolls, initial claims)
- Pulls news headlines matching AI + job-loss query terms from **NewsAPI**
- Runs the full corpus through **Snowflake Cortex AI** functions to classify, filter, embed, aggregate, and narrate
- Exposes findings in a **Streamlit in Snowflake** dashboard with four analytical views

---

## Cortex AI features

| Function | Application |
|---|---|
| `AI_CLASSIFY` | Labels each headline: `layoff`, `hiring`, `ai_fear`, `ai_positive`, `policy`, `neutral` |
| `AI_FILTER` | Boolean flag — is AI cited as a causal factor in job losses? |
| `AI_EMBED` | Vectorizes headlines using Arctic Embed for semantic similarity |
| `AI_AGG` | Rolls up monthly headline themes with no context-window limit |
| `AI_COMPLETE` | Generates a 3-sentence economic digest per month from structured + unstructured data |
| Cortex Search | Powers natural-language headline search in the dashboard |

---

## Architecture

```
[BLS API]       [FRED API]      [NewsAPI]
     │                │               │
     ▼                ▼               ▼
fetch_econ.py                  fetch_news.py
     │                               │
     └──────────────┬────────────────┘
                    │
          LABOR_MARKET.RAW (Snowflake)
          ├── RAW_BLS_JOLTS
          ├── RAW_BLS_CPS
          ├── RAW_FRED_SERIES
          └── RAW_NEWS_HEADLINES
                    │
          sql/02_cortex_transforms.sql
                    │
          LABOR_MARKET.CORTEX
          ├── NEWS_CLASSIFIED        (AI_CLASSIFY + AI_FILTER)
          ├── NEWS_EMBEDDINGS        (AI_EMBED)
          ├── MONTHLY_SENTIMENT_THEMES  (AI_AGG)
          ├── MONTHLY_DIGEST         (AI_COMPLETE)
          └── HEADLINE_SEARCH        (Cortex Search service)
                    │
          Streamlit in Snowflake
          ├── Fear vs. Reality       (time-series + correlation)
          ├── Monthly Digest         (AI-generated narrative)
          ├── Semantic Search        (Cortex Search)
          └── Sector Breakdown       (BLS JOLTS by industry)
```

---

## Data sources

| Source | Series | Description |
|---|---|---|
| BLS JOLTS | `JTS*LAY` | Monthly layoffs and discharges by industry |
| BLS CPS | `LNS14000000`, `LNS11300000` | Unemployment rate, labor force participation |
| FRED | `UNRATE`, `PAYEMS`, `ICSA` | Unemployment, nonfarm payrolls, initial claims |
| NewsAPI | Various | Headlines matching AI + labor market query terms |

---

## Setup

### 1. Snowflake environment

Run in order in a Snowflake worksheet:

```sql
sql/00_setup.sql      -- database, schemas, warehouse, stages
sql/01_raw_tables.sql -- raw layer DDL
```

### 2. Ingest economic data

```bash
pip install snowflake-connector-python pandas requests

export SNOWFLAKE_ACCOUNT=...
export SNOWFLAKE_USER=...
export SNOWFLAKE_PASSWORD=...
export BLS_API_KEY=...    # register free at bls.gov
export FRED_API_KEY=...   # register free at fred.stlouisfed.org

python ingestion/fetch_econ.py
```

### 3. Ingest news headlines

```bash
export NEWS_API_KEY=...   # newsapi.org — free tier covers last 30 days

# Default: last 30 days
python ingestion/fetch_news.py

# Historical range (paid/dev tier)
python ingestion/fetch_news.py --from 2022-01-01 --to 2024-12-31
```

### 4. Run Cortex transforms

```sql
-- In a Snowflake worksheet:
sql/02_cortex_transforms.sql
```

This creates all five Cortex AI-powered tables and the Cortex Search service. Expect it to take a few minutes on first run depending on corpus size.

### 5. Deploy the dashboard

In Snowflake → **Streamlit** → **+ Streamlit App**:
- Paste contents of `streamlit/app.py`
- Set database: `LABOR_MARKET`, warehouse: `LABOR_WH`

---

## Design notes

**Why `AI_AGG` for monthly themes?**  
A month of headlines easily exceeds the context window of a standard `AI_COMPLETE` call. `AI_AGG` handles arbitrarily large row sets natively — no chunking or batching logic required.

**Why `AI_FILTER` alongside `AI_CLASSIFY`?**  
Classification assigns a category label; `AI_FILTER` returns a boolean for use directly in `WHERE` clauses and `SUM()` aggregations. The combination makes it easy to compute the ratio of AI-causal headlines to total headlines per month, which is the core metric for the "Fear vs. Reality" view.

**Why Cortex Search instead of manual vector cosine similarity?**  
Cortex Search manages embedding generation, indexing, and ANN retrieval automatically. `AI_EMBED` is still demonstrated in `NEWS_EMBEDDINGS` to show the underlying mechanism, but the search UX uses the managed service.

---

## Possible extensions

- Add `GDELT` as a free news source with historical coverage back to 2013
- Wire up **Cortex Analyst** with a semantic model for natural-language SQL over the labor data
- Overlay FRED `USREC` recession indicator on the time-series charts
- Automate ingestion + transforms via **Snowflake Tasks**
- Expand sector coverage with additional BLS JOLTS series IDs

---

## Stack

Snowflake · Cortex AI · Streamlit in Snowflake · Python · BLS API · FRED API · NewsAPI