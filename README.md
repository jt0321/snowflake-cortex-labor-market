# snowflake-cortex-labor-market

**Do the numbers back up the fear?**

![Platform Architecture and Streamlit Dashboard](assets/system_architecture_dashboard.png)

An end-to-end data pipeline and analytics platform that uses Snowflake Cortex AI to investigate whether public anxiety about AI-driven job displacement is supported by actual economic data. BLS and FRED figures are joined with tech layoffs, stock market proxies, news sentiment, and Polymarket prediction-market odds, then analyzed using Cortex AI functions to surface correlations, classify sentiment, and generate narrative digests — orchestrated by **Dagster**, transformed by **dbt**, and surfaced in a **Streamlit in Snowflake** dashboard.

---

## What it does

- Ingests labor data from the **BLS** (JOLTS layoffs by industry, CPS unemployment) and **FRED** (nonfarm payrolls, initial claims) — monthly, since that's the source cadence
- Scrapes tech industry layoffs directly from **Layoffs.fyi** (via Airtable shared view parsing) — daily
- Fetches daily stock closing prices for AI/tech proxies (**MSFT**, **GOOGL**, **AMZN**, **TSLA**, and **QQQ**) from **Yahoo Finance** — daily
- Pulls news headlines matching AI, job-loss, and tech IPO targets (**OpenAI**, **Anthropic**, **SpaceX**) from **NewsAPI** — daily
- Pulls implied probabilities from **Polymarket** for recession, unemployment, AI-jobs, and IPO-related prediction markets — a market-priced fear signal, distinct from news sentiment — daily
- Runs the corpus through **Snowflake Cortex AI** functions to classify, filter, embed, aggregate, and narrate
- Exposes findings in a **Streamlit in Snowflake** dashboard with five analytical views

---

## Orchestration & transformation

| Layer | Tool | Role |
|---|---|---|
| Orchestration | **Dagster** | Schedules ingestion + transforms at the cadence each source actually supports |
| Transformation | **dbt** | All `RAW` → `CORTEX` schema modeling, including incremental Cortex AI models |
| AI compute | **Snowflake Cortex** | Classification, embedding, aggregation, narrative generation |

**Why three cadences, not one.** BLS and FRED publish monthly — there's no way to make labor market surveys update faster. But stocks, layoffs, and news change daily, and Polymarket prices update continuously. Forcing everything onto a monthly refresh buries fresher signals behind the slowest one.

| Schedule | Cron | What runs |
|---|---|---|
| **Daily** (6 AM UTC) | `0 6 * * *` | Ingest stocks, layoffs, news, Polymarket → `dbt run --select tag:daily` (incremental Cortex classification on new rows only) → refresh Cortex Search service |
| **Weekly** (Thursday 8 AM UTC) | `0 8 * * 4` | FRED `ICSA` initial claims refresh — matches the BLS weekly release schedule |
| **Monthly** (2nd, 9 AM UTC) | `0 9 2 * *` | Full BLS + FRED ingestion → `dbt run --select tag:monthly` (`AI_AGG` theme rollups, `AI_COMPLETE` digest regeneration) |

dbt's incremental materialization on `news_classified`, `news_embeddings`, and `news_ipo_classified` means Cortex AI functions only run against headlines that haven't been classified yet — daily re-runs don't re-pay for already-processed rows.

---

## Cortex AI features

| Function | Application |
|---|---|
| `AI_CLASSIFY` | Labels each headline (e.g. `layoff`, `hiring`, `ai_fear`, `ipo_optimism`, `valuation_hype`) |
| `AI_FILTER` | Boolean flags — does the article cite AI for job loss, or discuss IPO/private valuations? |
| `AI_EMBED` | Vectorizes headlines using Arctic Embed for semantic similarity |
| `AI_AGG` | Rolls up monthly headline themes with no context-window limit |
| `AI_COMPLETE` | Generates a monthly economic digest and IPO market narrative from structured + unstructured data |
| Cortex Search | Powers natural-language headline search in the dashboard |

---

## Architecture

```
[BLS API]  [FRED API]  [NewsAPI]  [Layoffs.fyi]  [Yahoo Finance]  [Polymarket]
     │           │           │           │              │               │
     ▼           ▼           ▼           ▼              ▼               ▼
              Dagster assets (dagster_project/assets/ingestion.py)
     fetch_econ.py  fetch_news.py  fetch_layoffs.py  fetch_stocks.py  fetch_polymarket.py
                                     │
                        LABOR_MARKET.RAW (Snowflake)
                        ├── RAW_BLS_JOLTS / RAW_BLS_CPS
                        ├── RAW_FRED_SERIES
                        ├── RAW_NEWS_HEADLINES
                        ├── RAW_LAYOFFS_FYI
                        ├── RAW_STOCK_PRICES
                        └── RAW_POLYMARKET_MARKETS
                                     │
                        dbt (dbt/models/) — orchestrated by Dagster's @dbt_assets
                        ├── staging/   (clean + type RAW tables)
                        └── marts/     (Cortex AI transforms, incremental where AI cost applies)
                                     │
                        LABOR_MARKET.CORTEX
                        ├── NEWS_CLASSIFIED                      (AI_CLASSIFY + AI_FILTER, incremental)
                        ├── NEWS_EMBEDDINGS                      (AI_EMBED, incremental)
                        ├── NEWS_IPO_CLASSIFIED                  (AI_CLASSIFY + AI_FILTER, incremental)
                        ├── LAYOFFS_FYI_CLEAN
                        ├── STOCK_MONTHLY_PERFORMANCE
                        ├── MONTHLY_PREDICTION_MARKET_SENTIMENT  (Polymarket odds by category)
                        ├── MONTHLY_SENTIMENT_THEMES             (AI_AGG)
                        ├── MONTHLY_IPO_SENTIMENT                (AI_AGG)
                        ├── MONTHLY_DIGEST                       (AI_COMPLETE)
                        ├── MONTHLY_INTEGRATED_DIGEST            (AI_COMPLETE)
                        └── HEADLINE_SEARCH                      (Cortex Search service, Dagster asset)
                                     │
                        Streamlit in Snowflake
                        ├── Fear vs. Reality   (BLS vs. Layoffs.fyi + correlations + Polymarket recession odds)
                        ├── Monthly Digests    (macro vs. tech-integrated narrative)
                        ├── Semantic Search    (Cortex Search)
                        ├── Sector Breakdown   (JOLTS sectors + tech stages)
                        └── IPO & Tech Stocks  (Tech stock prices + IPO news + prediction market trends)
```

---

## Data sources

| Source | Series / Target | Cadence | Description |
|---|---|---|---|
| BLS JOLTS | `JTS*LAY` | Monthly | Layoffs and discharges by industry |
| BLS CPS | `LNS14000000`, `LNS11300000` | Monthly | Unemployment rate, labor force participation |
| FRED | `UNRATE`, `PAYEMS` | Monthly | Unemployment, nonfarm payrolls |
| FRED | `ICSA` | Weekly | Initial jobless claims |
| NewsAPI | Various | Daily | Headlines matching AI + labor market + IPO targets |
| Layoffs.fyi | Airtable view | Daily | Specific tech company layoff dates and employee counts |
| Yahoo Finance | MSFT, GOOGL, AMZN, TSLA, QQQ | Daily | Tech proxies and index daily close prices |
| Polymarket | Recession, unemployment, AI-jobs, IPO markets | Daily | Implied probability — what people are betting on, not just saying |

No API key is required for Yahoo Finance, Layoffs.fyi, or Polymarket's Gamma API — all are public, unauthenticated endpoints.

---

## Setup

### 1. Snowflake environment

Run in order in a Snowflake worksheet:

```sql
sql/00_setup.sql      -- database, schemas, warehouse, stages
sql/01_raw_tables.sql -- raw layer DDL (all 7 RAW tables, including Polymarket)
```

### 2. Configure environment

```bash
uv sync

# .env (loaded automatically by dbt-snowflake and Dagster)
export SNOWFLAKE_ACCOUNT=...
export SNOWFLAKE_USER=...
export SNOWFLAKE_PASSWORD=...
export SNOWFLAKE_ROLE=SYSADMIN
export BLS_API_KEY=...    # register free at bls.gov
export FRED_API_KEY=...   # register free at fred.stlouisfed.org
export NEWS_API_KEY=...   # newsapi.org — free tier covers last 30 days
```

All commands below run through `uv run` so they use the project's pinned virtualenv (`.venv`) rather than any globally installed dbt/Dagster.

### 3a. Run via Dagster (recommended)

```bash
uv run dbt parse --project-dir dbt --profiles-dir dbt   # generates dbt/target/manifest.json
uv run dagster dev -m dagster_project.definitions
```

Open the Dagster UI, materialize assets manually for a first backfill, then let the three schedules (`daily_ingestion_and_transform`, `weekly_icsa_refresh`, `monthly_econ_and_digest`) take over.

### 3b. Run manually (no orchestrator)

```bash
uv run ingestion/fetch_econ.py
uv run ingestion/fetch_layoffs.py
uv run ingestion/fetch_stocks.py
uv run ingestion/fetch_news.py
uv run ingestion/fetch_polymarket.py

uv run dbt run --project-dir dbt --profiles-dir dbt
```

### 4. Deploy the dashboard

In Snowflake → **Streamlit** → **+ Streamlit App**:
- Paste contents of `streamlit/app.py`
- Set database: `LABOR_MARKET`, warehouse: `LABOR_WH`

---

## Design notes

**Why use tech proxies for private companies?**
OpenAI, Anthropic, and SpaceX are private. We use key public investor stocks (MSFT for OpenAI, GOOGL/AMZN for Anthropic) and related tech stock indicators (TSLA, QQQ) to serve as public market comparables and baseline indicators of valuation sentiment.

**Why scrape the Airtable view for Layoffs.fyi?**
Layoffs.fyi is managed in an Airtable base. Since there is no public API key provided, we dynamically query their embed page, extract the dynamic view identifier (`viw*`), and fetch the raw CSV directly to ensure data fidelity.

**Why Polymarket?**
News sentiment captures what people *say*; prediction markets capture what people are willing to *bet money on*. Adding implied probabilities for recession, unemployment, and AI-jobs questions gives the "fear vs. reality" thesis a market-priced data point alongside stock returns and headline classification.

**Why dbt incremental models for Cortex AI tables?**
`AI_CLASSIFY`, `AI_FILTER`, and `AI_EMBED` cost Cortex credits per row. Daily re-runs would re-classify the entire headline history every time without incremental materialization — `is_incremental()` filters to only unclassified `article_id`s.

**Why is the Cortex Search service creation a Dagster asset instead of a dbt model?**
`CREATE OR REPLACE CORTEX SEARCH SERVICE` is DDL, not a `SELECT` statement, so it can't be a dbt model. It runs as a plain Python asset (`dagster_project/assets/dbt_assets.py::cortex_search_service`) that depends on `news_embeddings` completing first.

---

## Stack

Snowflake · Cortex AI · Dagster · dbt · Streamlit in Snowflake · Python · BLS API · FRED API · NewsAPI · Yahoo Finance · Layoffs.fyi · Polymarket
