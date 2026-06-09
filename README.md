# AI & the Labor Market — Snowflake Cortex AI Portfolio Project

A data pipeline and analytics platform that investigates whether AI-related fears about job displacement
are supported by public economic data and news sentiment.

## Architecture

```
[BLS API]    [FRED API]    [NewsAPI / RSS]
     │              │               │
     ▼              ▼               ▼
  ingestion/     ingestion/     ingestion/
  bls.py         fred.py        news.py
     │              │               │
     └──────────────┴───────────────┘
                    │
             [Snowflake Stage]
                    │
             [Raw Tables]
          RAW_BLS_JOLTS
          RAW_FRED_SERIES
          RAW_NEWS_HEADLINES
                    │
             [dbt / SQL transforms]
          LABOR_MONTHLY          ← BLS + FRED joined, monthly grain
          NEWS_CLASSIFIED        ← AI_CLASSIFY + AI_FILTER applied
          NEWS_EMBEDDINGS        ← AI_EMBED vectors
                    │
           [Cortex AI Layer]
          MONTHLY_DIGEST         ← AI_COMPLETE narrative per month
          SENTIMENT_THEMES       ← AI_AGG rollups by month
                    │
           [Streamlit in Snowflake]
          streamlit/app.py       ← Dashboard + semantic search
```

## Cortex features demonstrated

| Function       | Where used                                              |
|----------------|---------------------------------------------------------|
| AI_CLASSIFY    | Tag headlines: layoff / hiring / AI-fear / policy / neutral |
| AI_FILTER      | Filter headlines where AI is cited as causal factor     |
| AI_EMBED       | Vectorize headlines for semantic similarity search      |
| AI_AGG         | Roll up monthly themes across headline batches          |
| AI_COMPLETE    | Generate narrative digest per month                     |
| Cortex Search  | Power the semantic search pane in Streamlit             |

## Data sources

- **BLS JOLTS** — Job Openings and Labor Turnover Survey (monthly layoffs, openings, quits by sector)
- **BLS CPS** — Current Population Survey (unemployment rate, labor force participation)
- **FRED** — Federal Reserve Economic Data (UNRATE, PAYEMS, recession indicators)
- **NewsAPI** — Headlines mentioning AI + layoffs, filtered by date range

## Setup

See `sql/00_setup.sql` for Snowflake environment setup.
See `ingestion/` for data fetch scripts.
See `streamlit/app.py` for the dashboard.

## Output

A Streamlit-in-Snowflake dashboard with:
- Time-series: layoffs vs. AI headline volume (2020–present)
- AI-generated monthly digest (via AI_COMPLETE)
- Semantic search over news corpus (Cortex Search)
- "Fear vs. Reality" pane — AI sentiment vs. actual displacement metrics
- Sector breakdown heatmap
