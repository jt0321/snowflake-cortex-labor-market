# snowflake-cortex-labor-market

**Do the numbers back up the fear?**

An end-to-end data pipeline and analytics platform that uses Snowflake Cortex AI to investigate whether public anxiety about AI-driven job displacement is supported by actual economic data. Monthly BLS and FRED figures are joined with tech layoffs, stock market proxies, and news sentiment, then analyzed using Cortex AI functions to surface correlations, classify sentiment, and generate narrative digests — all surfaced in a Streamlit in Snowflake dashboard.

---

## What it does

- Ingests monthly labor data from the **BLS** (JOLTS layoffs by industry, CPS unemployment) and **FRED** (nonfarm payrolls, initial claims)
- Scrapes tech industry layoffs directly from **Layoffs.fyi** (via Airtable shared view parsing)
- Fetches daily stock closing prices for AI/tech proxies (**MSFT**, **GOOGL**, **AMZN**, **TSLA**, and **QQQ**) from **Yahoo Finance**
- Pulls news headlines matching AI, job-loss, and tech IPO targets (**OpenAI**, **Anthropic**, **SpaceX**) from **NewsAPI**
- Runs the corpus through **Snowflake Cortex AI** functions to classify, filter, embed, aggregate, and narrate
- Exposes findings in a **Streamlit in Snowflake** dashboard with five analytical views

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
[BLS API]       [FRED API]      [NewsAPI]      [Layoffs.fyi]      [Yahoo Finance]
     │                │               │              │                  │
     ▼                ▼               ▼              ▼                  ▼
fetch_econ.py                  fetch_news.py   fetch_layoffs.py    fetch_stocks.py
     │                               │               │                  │
     └───────────────────────────────┼───────────────┴──────────────────┘
                                     │
                        LABOR_MARKET.RAW (Snowflake)
                        ├── RAW_BLS_JOLTS
                        ├── RAW_BLS_CPS
                        ├── RAW_FRED_SERIES
                        ├── RAW_NEWS_HEADLINES
                        ├── RAW_LAYOFFS_FYI
                        └── RAW_STOCK_PRICES
                                     │
                        sql/02_cortex_transforms.sql
                        sql/03_ipo_market_transforms.sql
                                     │
                        LABOR_MARKET.CORTEX
                        ├── NEWS_CLASSIFIED            (AI_CLASSIFY + AI_FILTER)
                        ├── NEWS_EMBEDDINGS            (AI_EMBED)
                        ├── NEWS_IPO_CLASSIFIED        (AI_CLASSIFY + AI_FILTER)
                        ├── MONTHLY_SENTIMENT_THEMES  (AI_AGG)
                        ├── MONTHLY_IPO_SENTIMENT      (AI_AGG)
                        ├── MONTHLY_DIGEST             (AI_COMPLETE)
                        ├── MONTHLY_INTEGRATED_DIGEST  (AI_COMPLETE)
                        └── HEADLINE_SEARCH            (Cortex Search service)
                                     │
                        Streamlit in Snowflake
                        ├── Fear vs. Reality           (BLS vs. Layoffs.fyi + correlations)
                        ├── Monthly Digests            (macro vs. tech-integrated narrative)
                        ├── Semantic Search            (Cortex Search)
                        ├── Sector Breakdown           (JOLTS sectors + tech stages)
                        └── IPO & Tech Stocks          (Tech stock prices + IPO news)
```

---

## Data sources

| Source | Series / Target | Description |
|---|---|---|
| BLS JOLTS | `JTS*LAY` | Monthly layoffs and discharges by industry |
| BLS CPS | `LNS14000000`, `LNS11300000` | Unemployment rate, labor force participation |
| FRED | `UNRATE`, `PAYEMS`, `ICSA` | Unemployment, nonfarm payrolls, initial claims |
| NewsAPI | Various | Headlines matching AI + labor market + IPO targets |
| Layoffs.fyi | Airtable view | Specific tech company layoff dates and employee counts |
| Yahoo Finance | MSFT, GOOGL, AMZN, TSLA, QQQ | Tech proxies and index daily close prices |

---

## Setup

### 1. Snowflake environment

Run in order in a Snowflake worksheet:

```sql
sql/00_setup.sql      -- database, schemas, warehouse, stages
sql/01_raw_tables.sql -- raw layer DDL (including layoffs & stocks)
```

### 2. Ingest data

```bash
pip install snowflake-connector-python pandas requests

export SNOWFLAKE_ACCOUNT=...
export SNOWFLAKE_USER=...
export SNOWFLAKE_PASSWORD=...
export BLS_API_KEY=...    # register free at bls.gov
export FRED_API_KEY=...   # register free at fred.stlouisfed.org
export NEWS_API_KEY=...   # newsapi.org — free tier covers last 30 days

# Ingest macro economy metrics
python ingestion/fetch_econ.py

# Ingest tech layoffs data
python ingestion/fetch_layoffs.py

# Ingest tech stock pricing histories
python ingestion/fetch_stocks.py

# Ingest news headlines
python ingestion/fetch_news.py
```

### 3. Run Cortex transforms

In a Snowflake worksheet, execute:

```sql
sql/02_cortex_transforms.sql
sql/03_ipo_market_transforms.sql
```

This builds all text classification, embedding, and narrative generation tables.

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

---

## Stack

Snowflake · Cortex AI · Streamlit in Snowflake · Python · BLS API · FRED API · NewsAPI · Yahoo Finance · Layoffs.fyi