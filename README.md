# snowflake-cortex-labor-market

**Do the numbers back up the fear?**

![Platform architecture](assets/system_architecture_dashboard.svg)

An end-to-end data pipeline and analytics platform that uses Snowflake Cortex AI to investigate whether public anxiety about AI-driven job displacement is supported by actual economic data. BLS and FRED figures are joined with tech layoffs, stock market proxies, news sentiment, and Polymarket prediction-market odds, then analyzed using Cortex AI functions to surface correlations, classify sentiment, and generate narrative digests — orchestrated by **Dagster**, transformed by **dbt**, and surfaced in a **Streamlit in Snowflake** dashboard.

---

## What it does

- Ingests labor data from the **BLS** (JOLTS layoffs by industry **plus openings, hires, and quits** — the full hiring/firing cycle; CPS unemployment incl. **young workers 20–24**) and **FRED** (nonfarm payrolls, initial claims, **CPI + core CPI inflation**, **Fed funds rate**, **information-sector employment**) — monthly, since that's the source cadence
- Pulls the **Indeed Hiring Lab job postings index** (US total + software development) — the hiring side that layoff counts miss — weekly
- Scrapes tech industry layoffs directly from **Layoffs.fyi** (via Airtable shared view parsing) — daily
- Fetches daily stock closing prices for AI-exposed megacaps (**MSFT**, **GOOGL**, **AMZN**, **META**), **NVDA** as the purest public AI signal, **TSLA** (SpaceX comparable), **QQQ**, plus the **S&P 500** (`^GSPC`) as an overall-market baseline, from **Yahoo Finance** — daily
- Pulls news headlines matching AI, job-loss, and tech IPO targets (**OpenAI**, **Anthropic**, **SpaceX**) from **NewsAPI** — daily
- Backfills and refreshes the news corpus from **GDELT** and **Hacker News** — both free and keyless, with archives reaching **back to 2020**, so headline sentiment covers both sides of the ChatGPT moment (NewsAPI's free tier only reaches ~1 month back)
- Pulls implied probabilities from **Polymarket** for recession, unemployment, AI-jobs, and IPO-related prediction markets — a market-priced fear signal, distinct from news sentiment — daily
- Runs the corpus through **Snowflake Cortex AI** functions to classify, filter, embed, aggregate, and narrate
- Exposes findings in a **Streamlit in Snowflake** dashboard with five analytical views

---

## Orchestration & transformation

| Layer | Tool | Role |
|---|---|---|
| Orchestration | **Dagster** | Defines the asset graph and refresh bundles — spun up on demand to materialize, not deployed as a service |
| Transformation | **dbt** | All `RAW` → `CORTEX` schema modeling, including incremental Cortex AI models |
| AI compute | **Snowflake Cortex** | Classification, embedding, aggregation, narrative generation |

**Operating model: spin up, materialize, shut down.** Dagster is not left running as a deployed service here. When the data should be refreshed, start an instance with `dagster dev`, materialize the relevant job (or just "Materialize all"), and shut it down. The three jobs below bundle assets by the cadence each source actually supports — BLS and FRED publish monthly, while stocks, layoffs, and news move daily — so they double as a menu of *what's worth refreshing* depending on how long it's been. The cron schedules are defined in `dagster_project/schedules.py` and would take over unchanged if you ever did deploy Dagster persistently; on an ad-hoc instance they simply never fire, and you trigger the jobs yourself.

| Job | What it refreshes | Materialize when |
|---|---|---|
| `daily_ingest_and_transform` | Stocks, layoffs, news (NewsAPI + GDELT/HN), Polymarket → `tag:daily` dbt models (incremental Cortex classification on new rows only) → Cortex Search refresh | Any refresh session — this is the default bundle |
| `weekly_icsa_refresh` | FRED `ICSA` initial claims + Indeed Hiring Lab postings index | It's been a week+ (BLS releases Thursdays) |
| `monthly_econ_and_digest` | Full BLS + FRED ingestion → `tag:monthly` dbt models (`AI_AGG` theme rollups, `AI_COMPLETE` digest regeneration) | A new BLS/FRED month has landed (~the 2nd of the month) |

**Mind the news gap between sessions.** The `raw_news_history` asset only fetches the trailing 7 days (so a routine materialization can never accidentally re-crawl the archive). If more than a week has passed since your last session, fill the gap from the CLI before (or instead of) materializing it — GDELT and Hacker News archives make any gap recoverable:

```bash
uv run ingestion/fetch_news_history.py --from 2026-07-01   # since your last refresh
```

NewsAPI's free tier reaches ~1 month back, so its asset tolerates longer gaps on its own.

dbt's incremental materialization on `news_classified`, `news_embeddings`, and `news_ipo_classified` means Cortex AI functions only run against headlines that haven't been classified yet — repeated refresh sessions don't re-pay for already-processed rows.

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
[BLS API]  [FRED API]  [NewsAPI]  [GDELT + Hacker News]  [Indeed Hiring Lab]  [Layoffs.fyi]  [Yahoo Finance]  [Polymarket]
     │           │           │              │                     │                 │              │               │
     ▼           ▼           ▼              ▼                     ▼                 ▼              ▼               ▼
              Dagster assets (dagster_project/assets/ingestion.py)
     fetch_econ.py  fetch_news.py  fetch_news_history.py  fetch_job_postings.py  fetch_layoffs.py  fetch_stocks.py  fetch_polymarket.py
                                     │
                        LABOR_MARKET.RAW (Snowflake)
                        ├── RAW_BLS_JOLTS / RAW_BLS_CPS
                        ├── RAW_FRED_SERIES
                        ├── RAW_NEWS_HEADLINES
                        ├── RAW_LAYOFFS_FYI
                        ├── RAW_STOCK_PRICES
                        ├── RAW_JOB_POSTINGS
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
                        ├── MACRO_MONTHLY                        (inflation YoY, Fed funds, S&P 500 vs QQQ)
                        ├── MONTHLY_NEWS_FEAR_INDEX              (fear share per month × source group, 2020+)
                        ├── MONTHLY_PREDICTION_MARKET_SENTIMENT  (Polymarket odds by category)
                        ├── MONTHLY_SENTIMENT_THEMES             (AI_AGG)
                        ├── MONTHLY_IPO_SENTIMENT                (AI_AGG)
                        ├── MONTHLY_DIGEST                       (AI_COMPLETE)
                        ├── MONTHLY_INTEGRATED_DIGEST            (AI_COMPLETE)
                        └── HEADLINE_SEARCH                      (Cortex Search service, Dagster asset)
                                     │
                        Streamlit in Snowflake
                        ├── Fear vs. Reality   (BLS vs. Layoffs.fyi + fear-index verdict + inflation/market context)
                        ├── Monthly Digests    (macro vs. tech-integrated narrative)
                        ├── Semantic Search    (Cortex Search)
                        ├── Sector Breakdown   (JOLTS sectors + tech stages)
                        └── IPO & Tech Stocks  (Tech stock prices + IPO news + prediction market trends)
```

---

## Data sources

| Source | Series / Target | Cadence | Description |
|---|---|---|---|
| BLS JOLTS | `JTS*LDL`, `JTS*JOL/HIL/QUL` | Monthly | Layoffs by industry, plus total openings, hires, and quits — the full cycle |
| BLS CPS | `LNS14000000`, `LNS11300000`, `LNS14000036` | Monthly | Unemployment rate, labor force participation, young-worker (20–24) unemployment |
| FRED | `UNRATE`, `PAYEMS`, `USINFO` | Monthly | Unemployment, nonfarm payrolls, information-sector employment |
| FRED | `CPIAUCSL`, `CPILFESL`, `FEDFUNDS` | Monthly | Headline CPI, core CPI, effective Fed funds rate — the business-cycle controls |
| Indeed Hiring Lab | US total + by-sector postings index | Weekly | Job postings (Feb 2020 = 100) — hiring-side signal, incl. software development |
| FRED | `ICSA` | Weekly | Initial jobless claims |
| NewsAPI | Various | Daily | Fresh headlines matching AI + labor market + IPO targets (~1 month of history on the free tier) |
| GDELT DOC 2.0 | AI / layoffs / IPO queries | Daily + backfill | Global news headlines, searchable back to 2017 — provides the 2020+ archive NewsAPI can't |
| Hacker News (Algolia) | AI / layoffs / IPO queries | Daily + backfill | Tech community stories back to 2006 — practitioner-level sentiment |
| Layoffs.fyi | Airtable view | Daily | Specific tech company layoff dates and employee counts |
| Yahoo Finance | MSFT, GOOGL, AMZN, META, NVDA, TSLA, QQQ, ^GSPC | Daily | AI-exposed megacaps, NVDA, TSLA, tech index, and the S&P 500 baseline, daily closes since 2020 |
| Polymarket | Recession, unemployment, AI-jobs, IPO markets | Daily | Implied probability — what people are betting on, not just saying |

No API key is required for Yahoo Finance, Layoffs.fyi, GDELT, Hacker News, Indeed Hiring Lab, or Polymarket's Gamma API — all are public, unauthenticated endpoints. `NEWS_API_KEY` is now **optional**: NewsAPI only adds the trailing month on top of GDELT/HN, and `fetch_news.py` skips gracefully without it.

---

## Setup

**Sign up for a Snowflake trial first, if you don't already have an account.** As of writing, [Snowflake's trial signup](https://www.snowflake.com/en/snowflake-trial/) offers two options — to get Cortex AI access (which this whole project depends on), you must pick the **"Cortex Cloud CLI"** trial, not the plain one. It reserves $40 of Cortex inference credit out of the $400 total trial credit; the plain trial doesn't include Cortex access at all.

### 1. Snowflake environment

Add the `sql/` folder to a Snowflake **Workspace** (Projects → Workspaces) and run these two files in order — this is schema/table DDL only, no data yet:

```sql
sql/00_setup.sql      -- database, schemas, warehouse, stages
sql/01_raw_tables.sql -- raw layer DDL (all 7 RAW tables, including Polymarket)
```

`sql/02_cortex_transforms.sql` and `sql/03_ipo_market_transforms.sql` are also in that folder — see step 3 below for when (and when *not*) to run them.

### 2. Configure environment

```bash
uv sync

cp .env.example .env
# then fill in SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_TOKEN (programmatic access
# token, not your login password), and the BLS/FRED/NewsAPI keys
```

`uv run` reads env vars from the file named by `UV_ENV_FILE` (defaults to none — you must set it). Two ways to wire that up:

- **direnv (recommended)** — auto-exports `UV_ENV_FILE` whenever you `cd` into the repo:
  ```bash
  curl -sfL https://direnv.net/install.sh | bash   # or your package manager
  echo 'eval "$(direnv hook bash)"' >> ~/.bashrc && source ~/.bashrc   # or the zsh/fish equivalent
  echo 'export UV_ENV_FILE=.env' > .envrc
  direnv allow .
  ```
- **Manual export** — set it yourself each session:
  ```bash
  export UV_ENV_FILE=.env
  ```

All commands below run through `uv run` so they use the project's pinned virtualenv (`.venv`) rather than any globally installed dbt/Dagster.

### 3. Cortex AI smoke test (optional, one-time)

`sql/02_cortex_transforms.sql` and `sql/03_ipo_market_transforms.sql` are a standalone, pre-dbt reference implementation of the same `AI_CLASSIFY`/`AI_FILTER`/`AI_EMBED`/`AI_AGG` transforms dbt owns from step 4 onward. They're useful as a quick end-to-end check that Cortex actually works on your account/trial, without setting up dbt or Dagster first:

```bash
# seed RAW with a first batch of real data
uv run ingestion/fetch_econ.py
uv run ingestion/fetch_layoffs.py
uv run ingestion/fetch_stocks.py
uv run ingestion/fetch_news.py
uv run ingestion/fetch_news_history.py --backfill   # GDELT + HN archive since 2020 (one-time, ~30-40 min — GDELT rate-limits to ~1 req/5s; resumable with --from if interrupted)
uv run ingestion/fetch_job_postings.py
uv run ingestion/fetch_polymarket.py
```

Then run `sql/02_cortex_transforms.sql` and `sql/03_ipo_market_transforms.sql` in the Workspace (each needs the RAW tables above already populated — that's why they run after ingestion, not with `00`/`01`).

**Run this at most once, and never again after step 4.** Both scripts `CREATE OR REPLACE` tables — `NEWS_CLASSIFIED`, `LAYOFFS_FYI_CLEAN`, `MONTHLY_SENTIMENT_THEMES`, and six more — under the exact same names (Snowflake identifiers are case-insensitive) as the dbt models in `dbt/models/marts/`. Once dbt has run, it owns these tables incrementally, only reclassifying headlines it hasn't seen before; re-running the raw SQL scripts afterward silently wipes that incremental state and burns Cortex credits reclassifying the entire corpus from scratch on the next `dbt run`.

### 4a. Run via Dagster (recommended)

```bash
uv run dbt parse --project-dir dbt --profiles-dir dbt   # generates dbt/target/manifest.json
uv run dagster dev -m dagster_project.definitions
```

**First build:** run the news backfill from the CLI first (it's deliberately not part of any Dagster asset):

```bash
uv run ingestion/fetch_news_history.py --backfill   # GDELT + HN archive since 2020, one-time
```

then open the Dagster UI and **Materialize all**. Expect this first materialization to be the expensive one — it Cortex-classifies the entire backfilled 2020+ corpus in one pass. Every later run is incremental.

**Routine refresh:** spin up `dagster dev`, materialize `daily_ingest_and_transform` (plus `weekly_icsa_refresh` / `monthly_econ_and_digest` if they're due — see the job table above), and shut the instance down. If it's been more than 7 days since the last session, close the news gap from the CLI first with `fetch_news_history.py --from <last-refresh-date>`.

### 4b. Run manually (no orchestrator)

```bash
uv run ingestion/fetch_econ.py
uv run ingestion/fetch_layoffs.py
uv run ingestion/fetch_stocks.py
uv run ingestion/fetch_news.py
uv run ingestion/fetch_news_history.py   # last 7 days; add --backfill once for 2020+ history
uv run ingestion/fetch_job_postings.py
uv run ingestion/fetch_polymarket.py

uv run dbt run --project-dir dbt --profiles-dir dbt
```

### 5. Deploy the dashboard

In Snowflake → **Streamlit** → **+ Streamlit App**:
- Switch your active role to `SYSADMIN` *before* creating the app — a Streamlit-in-Snowflake app runs as whichever role owns it, and `ACCOUNTADMIN` doesn't automatically inherit `SYSADMIN`'s privileges on `LABOR_MARKET.CORTEX` objects (they're peers, not parent/child). Creating it under the wrong role hits the same "no privileges on it" error covered in [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md).
- Paste contents of `streamlit/app.py`
- Set database: `LABOR_MARKET`, warehouse: `LABOR_WH`

Hit a setup error? Check [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) — covers role/ownership mismatches, a dbt schema-naming footgun, and PAT/network-policy auth issues.

---

## Design notes

**Tech proxies for private companies** — OpenAI, Anthropic, and SpaceX are private, so MSFT, GOOGL/AMZN, TSLA, and QQQ stand in as rough public comparables. Imperfect by construction.

**Layoffs.fyi via Airtable scrape** — no public API, so the script extracts the shared view ID from the embed page and pulls the CSV directly.

**GDELT + Hacker News for history** — NewsAPI's free tier reaches ~1 month back; GDELT and HN are keyless with archives past 2020, giving the fear index a pre-ChatGPT baseline. Backfill writes into the same table, deduped by URL hash. First dbt run after a backfill classifies the whole new corpus — a one-time Cortex credit spend.

**Inflation, Fed funds, S&P 500** — business-cycle controls: layoffs that track rate hikes aren't an AI story, and a QQQ drawdown that matches the S&P isn't tech-specific.

**Polymarket** — an experimental side signal (what people bet vs. what they say). Relevant markets are sparse and sometimes illiquid; treat it as garnish, not evidence.

**dbt incremental for Cortex tables** — AI functions cost credits per row; `is_incremental()` limits daily runs to unclassified `article_id`s.

**Cortex Search as a Dagster asset** — `CREATE CORTEX SEARCH SERVICE` is DDL, not a `SELECT`, so it can't be a dbt model; a Python asset runs it after `news_embeddings`.

---

## Stack

Snowflake · Cortex AI · Dagster · dbt · Streamlit in Snowflake · Python · BLS API · FRED API · NewsAPI · GDELT · Hacker News · Indeed Hiring Lab · Yahoo Finance · Layoffs.fyi · Polymarket
