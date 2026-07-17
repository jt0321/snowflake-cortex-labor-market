# AI & the Labor Market Streamlit dashboard with Cortex Search integration
# Co-authored with CoCo
"""
streamlit/app.py — AI & the Labor Market dashboard
Deploy as a Streamlit in Snowflake app (Container Runtime).

Integrates BLS macro data, layoffs.fyi tech sector data, stock market lines,
and OpenAI/Anthropic/SpaceX IPO sentiment news analyzed via Cortex AI.
"""

import os
import json
import datetime
import streamlit as st
import pandas as pd


# Get Snowflake connection (Container Runtime pattern)
conn = st.connection("snowflake", ttl=os.getenv("SNOWFLAKE_CONNECTION_TTL"))
session = conn.session()


def cortex_search(query, columns, filter_obj=None, limit=20):
    """Query Cortex Search service via SQL (works in Container Runtime)."""
    request = {"query": query, "columns": columns, "limit": limit}
    if filter_obj:
        request["filter"] = filter_obj
    request_json = json.dumps(request)

    result = session.sql(
        "SELECT PARSE_JSON(SNOWFLAKE.CORTEX.SEARCH_PREVIEW("
        "'LABOR_MARKET.CORTEX.HEADLINE_SEARCH', ?)) AS response",
        params=[request_json]
    ).collect()

    if result:
        response = json.loads(result[0]["RESPONSE"])
        return pd.DataFrame(response.get("results", []))
    return pd.DataFrame()


# Page Setup
st.set_page_config(
    page_title="AI, IPOs & the Labor Market",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Premium Styling
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&family=Inter:wght@300;400;500;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }

    h1, h2, h3, [class*="stHeading"] {
        font-family: 'Outfit', sans-serif;
        font-weight: 700;
        letter-spacing: -0.02em;
    }

    .stMetric {
        background: rgba(31, 41, 55, 0.4);
        border: 1px solid rgba(75, 85, 99, 0.3);
        border-radius: 12px;
        padding: 16px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    }

    .stMetric label {
        color: #9ca3af !important;
        font-size: 0.85rem !important;
        font-weight: 500 !important;
    }

    .stMetric div[data-testid="stMetricValue"] {
        color: #ffffff !important;
        font-size: 1.8rem !important;
        font-weight: 700 !important;
    }

    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }

    .stTabs [data-baseweb="tab"] {
        background-color: rgba(31, 41, 55, 0.2);
        border: 1px solid rgba(75, 85, 99, 0.2);
        border-radius: 8px 8px 0px 0px;
        padding: 10px 20px;
        color: #9ca3af;
        transition: all 0.2s ease;
    }

    .stTabs [data-baseweb="tab"]:hover {
        color: #ffffff;
        background-color: rgba(75, 85, 99, 0.2);
    }

    .stTabs [aria-selected="true"] {
        background-color: rgba(59, 130, 246, 0.15) !important;
        border-color: rgba(59, 130, 246, 0.5) !important;
        color: #3b82f6 !important;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

# ── Title & Header ──────────────────────────────────────────────────────────
st.title("🚀 AI, IPOs & the Labor Market")
st.caption(
    "A Cortex AI Analytics Dashboard linking broader economic indicators, tech sector layoffs, "
    "market trends, and OpenAI / Anthropic / SpaceX IPO sentiments."
)

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📈 Fear vs. Reality",
    "📰 Monthly Digests",
    "🔍 Semantic Search",
    "🏭 Sector Breakdown",
    "🚀 IPO & Tech Stocks"
])


# ── Tab 1: Fear vs. Reality ─────────────────────────────────────────────────
with tab1:
    st.subheader("Macro vs. Tech Layoff Trends")
    st.markdown(
        "Compare official **BLS Layoffs** (macroeconomy) against crowdsourced **Layoffs.fyi** data (tech-specific sector), "
        "broken out by industry, alongside the highest-frequency leading indicator available: weekly initial jobless claims."
    )

    # Fetch data — BLS/FYI/FRED all have years of overlapping history, so a
    # joined trend + correlation is meaningful here. News/Polymarket don't
    # (see below) and are deliberately kept out of this query.
    df_combined = session.sql("""
        SELECT
          d.month,
          d.bls_total_layoffs,
          d.fyi_tech_layoffs,
          d.unemployment_rate
        FROM LABOR_MARKET.CORTEX.MONTHLY_INTEGRATED_DIGEST d
        ORDER BY d.month
    """).to_pandas()

    df_combined["month"] = pd.to_datetime(df_combined["MONTH"])

    # st.line_chart has no built-in zoom/pan — the standard Streamlit pattern
    # for narrowing a time series is to filter the dataframe with a range
    # control before charting. COVID (Mar–Apr 2020) is a huge outlier that
    # otherwise dominates the y-axis on every chart below; default the window
    # to the ChatGPT era (Nov 2022 on) since that's what's actually relevant
    # to an "AI and the labor market" question, while leaving full history
    # selectable.
    min_month = df_combined["month"].min().date()
    max_month = df_combined["month"].max().date()
    default_start = max(min_month, datetime.date(2020, 1, 1))
    range_start, range_end = st.slider(
        "Date range",
        min_value=min_month,
        max_value=max_month,
        value=(default_start, max_month),
        format="MMM YYYY",
        key="tab1_date_range",
    )
    df_windowed = df_combined[
        (df_combined["month"].dt.date >= range_start) & (df_combined["month"].dt.date <= range_end)
    ]

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("### Broad Economy vs. Tech Layoffs")
        # BLS (whole economy) runs roughly 10x above tech-only layoffs.
        # We scale BLS down by 1/10 so both lines use comparable vertical space.
        toggle_col1, toggle_col2 = st.columns(2)
        show_bls = toggle_col1.checkbox("Show BLS Total Layoffs", value=True, key="tab1_show_bls")
        show_tech = toggle_col2.checkbox("Show Tech Layoffs", value=True, key="tab1_show_tech")

        # Scale BLS down by 1/10 so both series are comparable on one axis
        df_chart = df_windowed[["month"]].copy()
        plot_cols = []
        if show_tech:
            df_chart["Tech Layoffs (Layoffs.fyi)"] = df_windowed["FYI_TECH_LAYOFFS"]
            plot_cols.append("Tech Layoffs (Layoffs.fyi)")
        if show_bls:
            df_chart["BLS Total Layoffs (÷10)"] = df_windowed["BLS_TOTAL_LAYOFFS"] / 10
            plot_cols.append("BLS Total Layoffs (÷10)")

        if plot_cols:
            st.line_chart(df_chart.set_index("month")[plot_cols], height=350)
        st.caption(
            "Both series in persons. BLS (entire US economy) is scaled to 1/10 actual value "
            "so both lines are visually comparable — tech layoffs are roughly 1/10 of the national total."
        )

    with col2:
        st.markdown("### Layoffs by Industry (BLS JOLTS)")
        jolts_industry = session.sql("""
            SELECT
              month_date AS month,
              CASE series_id
                WHEN 'JTS510000000000000LDL' THEN 'Information (K)'
                WHEN 'JTS540099000000000LDL' THEN 'Professional & Business Services (K)'
                WHEN 'JTS600000000000000LDL' THEN 'Education & Health Services (K)'
              END AS industry,
              value AS layoffs_k
            FROM LABOR_MARKET.CORTEX.STG_BLS_JOLTS
            WHERE series_id != 'JTS000000000000000LDL'
            ORDER BY month
        """).to_pandas()
        jolts_industry["MONTH"] = pd.to_datetime(jolts_industry["MONTH"])
        jolts_windowed = jolts_industry[
            (jolts_industry["MONTH"].dt.date >= range_start) & (jolts_industry["MONTH"].dt.date <= range_end)
        ]
        jolts_pivot = jolts_windowed.pivot_table(index="MONTH", columns="INDUSTRY", values="LAYOFFS_K")
        st.line_chart(jolts_pivot, use_container_width=True)
        st.caption("Monthly layoffs & discharges, thousands of persons, by industry, not seasonally adjusted — BLS JOLTS.")

    st.markdown("### Weekly Initial Jobless Claims (FRED ICSA)")
    icsa_df = session.sql("""
        SELECT observation_date, value
        FROM LABOR_MARKET.RAW.RAW_FRED_SERIES
        WHERE series_id = 'ICSA'
        ORDER BY observation_date
    """).to_pandas()
    icsa_df["OBSERVATION_DATE"] = pd.to_datetime(icsa_df["OBSERVATION_DATE"])
    icsa_windowed = icsa_df[
        (icsa_df["OBSERVATION_DATE"].dt.date >= range_start) & (icsa_df["OBSERVATION_DATE"].dt.date <= range_end)
    ]
    st.line_chart(icsa_windowed.set_index("OBSERVATION_DATE")[["VALUE"]].rename(columns={"VALUE": "Initial Claims"}), use_container_width=True)
    st.caption("Weekly initial unemployment claims, not seasonally adjusted — the highest-frequency leading indicator available here.")

    st.divider()

    # Metrics row
    m1, m2, m3, m4 = st.columns(4)

    corr_bls_vs_fyi = df_windowed["BLS_TOTAL_LAYOFFS"].corr(df_windowed["FYI_TECH_LAYOFFS"])
    m1.metric(
        "BLS vs. Tech Layoffs Correlation",
        f"{corr_bls_vs_fyi:.2f}",
        help="Correlation between general U.S. layoffs (BLS JOLTS) and tech layoffs (Layoffs.fyi), over the selected date range. A high value indicates tech moves in lockstep with the broader market."
    )

    icsa_latest = icsa_df["VALUE"].iloc[-1] if not icsa_df.empty else None
    icsa_prior = icsa_df["VALUE"].iloc[-2] if len(icsa_df) > 1 else None
    m2.metric(
        "Latest Initial Claims",
        f"{icsa_latest:,.0f}" if icsa_latest is not None else "N/A",
        delta=f"{icsa_latest - icsa_prior:+,.0f} vs prior week" if icsa_latest is not None and icsa_prior is not None else None,
        delta_color="inverse",
        help="Most recent weekly initial jobless claims figure (FRED ICSA), and the change from the prior week."
    )

    unrate_latest = df_combined["UNEMPLOYMENT_RATE"].iloc[-1] if not df_combined.empty else 0.0
    m3.metric("Latest Unemployment Rate", f"{unrate_latest:.1f}%")

    # Sourced directly from the prediction-market mart's own latest month,
    # not joined through df_combined: that join is anchored to FRED's month
    # range, which lags real-time sources like Polymarket by design (FRED
    # publishes ~1 month behind) — so the join would show N/A indefinitely
    # even once Polymarket data exists for the current month.
    recession_latest = session.sql("""
        SELECT avg_probability
        FROM LABOR_MARKET.CORTEX.MONTHLY_PREDICTION_MARKET_SENTIMENT
        WHERE market_category = 'recession'
        ORDER BY month DESC
        LIMIT 1
    """).to_pandas()
    m4.metric(
        "Polymarket Recession Odds",
        f"{recession_latest['AVG_PROBABILITY'].iloc[0] * 100:.0f}%" if not recession_latest.empty else "N/A",
        help="Latest monthly average implied probability of a recession, from Polymarket prediction markets — a market-priced fear signal distinct from news sentiment."
    )


# ── Tab 2: Monthly Digests ──────────────────────────────────────────────────
with tab2:
    st.subheader("Cortex AI Monthly Economic Digests")
    st.markdown(
        "Select a month to read AI-synthesized market narratives. We compare the **Standard Economic Digest** "
        "(based on FRED + BLS + broad news themes) with the new **Integrated IPO & Market Digest** "
        "(incorporating tech stock prices, tech layoffs, and private market valuation/IPO headlines)."
    )

    months_df = session.sql("""
        SELECT DISTINCT month FROM LABOR_MARKET.CORTEX.MONTHLY_INTEGRATED_DIGEST ORDER BY month DESC
    """).to_pandas()

    selected_month = st.selectbox(
        "Select reporting month",
        options=months_df["MONTH"].astype(str).tolist(),
        key="digest_month_select"
    )

    digest_data = session.sql(
        "SELECT "
        "d.unemployment_rate, d.bls_total_layoffs_k, d.fyi_tech_layoffs, "
        "d.qqq_return, d.msft_return, d.ipo_market_digest, "
        "m.narrative_digest AS standard_digest, d.ipo_theme_summary "
        "FROM LABOR_MARKET.CORTEX.MONTHLY_INTEGRATED_DIGEST d "
        "LEFT JOIN LABOR_MARKET.CORTEX.MONTHLY_DIGEST m ON d.month = m.month "
        "WHERE d.month = ?",
        params=[selected_month]
    ).to_pandas()

    if not digest_data.empty:
        row = digest_data.iloc[0]

        # Stat cards
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Unemployment Rate", f"{row['UNEMPLOYMENT_RATE']:.1f}%")
        c2.metric("Tech Layoffs (Layoffs.fyi)", f"{int(row['FYI_TECH_LAYOFFS']):,}" if row['FYI_TECH_LAYOFFS'] else "0")
        c3.metric("QQQ Monthly Return", f"{row['QQQ_RETURN']:.2f}%" if row['QQQ_RETURN'] is not None else "N/A")
        c4.metric("MSFT (OpenAI Proxy)", f"{row['MSFT_RETURN']:.2f}%" if row['MSFT_RETURN'] is not None else "N/A")

        st.write(" ")

        col_std, col_ipo = st.columns(2)
        with col_std:
            st.markdown("### 📋 Standard Economic Digest (Mistral-7B)")
            st.info(row["STANDARD_DIGEST"] if row["STANDARD_DIGEST"] else "No digest generated for this period.")

        with col_ipo:
            st.markdown("### 🚀 Integrated IPO & Stock Digest (Mistral-7B)")
            st.success(row["IPO_MARKET_DIGEST"] if row["IPO_MARKET_DIGEST"] else "No IPO market digest generated for this period.")

        st.divider()
        st.subheader("Cortex AI IPO & Private Valuation Themes (AI_AGG)")
        if row["IPO_THEME_SUMMARY"]:
            st.markdown(row["IPO_THEME_SUMMARY"])
        else:
            st.caption("No private market or IPO headlines were captured during this month.")


# ── Tab 3: Semantic Search ──────────────────────────────────────────────────
with tab3:
    st.subheader("Semantic Headline Search")
    st.markdown(
        "Search the entire news corpus using natural language queries. Powered by Cortex Search and Arctic Embed."
    )

    search_q = st.text_input(
        "Enter search query",
        placeholder="e.g. OpenAI fundraising secondary sales or Anthropic valuation",
        key="semantic_search_input"
    )

    cat_filter = st.multiselect(
        "Filter categories",
        ["layoff", "hiring", "ai_fear", "ai_positive", "policy", "neutral"],
        default=[],
        key="semantic_search_categories"
    )

    if search_q:
        search_filter = None
        if cat_filter:
            search_filter = {"@or": [{"@eq": {"category": c}} for c in cat_filter]}

        results = cortex_search(
            query=search_q,
            columns=["full_text", "category", "published_at", "source_name", "ai_causal_flag"],
            filter_obj=search_filter,
            limit=20,
        )

        if results.empty:
            st.warning("No articles found matching that semantic description.")
        else:
            for _, r in results.iterrows():
                badge = "🔴 AI-causal" if r.get("ai_causal_flag") else ""
                st.markdown(
                    f"**{r['full_text'][:140]}...** {badge}  \n"
                    f"_{r['source_name']} · {str(r['published_at'])[:10]} · `{r['category']}`_"
                )
                st.divider()


# ── Tab 4: Sector Breakdown ─────────────────────────────────────────────────
with tab4:
    st.subheader("Tech Layoffs Breakdown (Layoffs.fyi)")

    layoffs_df = session.sql("""
        SELECT company, industry, laid_off_count, stage, country, laid_off_date
        FROM LABOR_MARKET.CORTEX.LAYOFFS_FYI_CLEAN
        ORDER BY laid_off_date DESC
    """).to_pandas()

    if layoffs_df.empty:
        st.warning("No Layoffs.fyi records loaded yet.")
    else:
        st.markdown("### Weekly Layoff Trend")
        weekly_df = layoffs_df.copy()
        weekly_df["WEEK"] = pd.to_datetime(weekly_df["LAID_OFF_DATE"]).dt.to_period("W").dt.start_time
        weekly_trend = weekly_df.groupby("WEEK")["LAID_OFF_COUNT"].sum()
        st.line_chart(weekly_trend, use_container_width=True)
        st.caption("Weekly total employees laid off, tech sector — Layoffs.fyi, 2020 to present.")

        col_l1, col_l2 = st.columns(2)
        with col_l1:
            st.markdown("### Top Industries Affected")
            ind_df = layoffs_df.groupby("INDUSTRY")["LAID_OFF_COUNT"].sum().reset_index()
            ind_df = ind_df.sort_values(by="LAID_OFF_COUNT", ascending=False).head(10)
            st.bar_chart(ind_df.set_index("INDUSTRY")["LAID_OFF_COUNT"])

        with col_l2:
            st.markdown("### Layoffs by Company Funding Stage")
            stage_df = layoffs_df.groupby("STAGE")["LAID_OFF_COUNT"].sum().reset_index()
            stage_df = stage_df.sort_values(by="LAID_OFF_COUNT", ascending=False).head(10)
            st.bar_chart(stage_df.set_index("STAGE")["LAID_OFF_COUNT"])

        st.divider()
        st.markdown("### Largest Individual Tech Layoff Events")
        top_events = layoffs_df.sort_values(by="LAID_OFF_COUNT", ascending=False).head(15)
        st.dataframe(
            top_events.rename(columns={
                "COMPANY": "Company",
                "INDUSTRY": "Industry",
                "LAID_OFF_COUNT": "Employees Laid Off",
                "STAGE": "Funding Stage",
                "COUNTRY": "Country",
                "LAID_OFF_DATE": "Date"
            }),
            use_container_width=True,
            hide_index=True
        )


# ── Tab 5: IPO & Tech Stocks ────────────────────────────────────────────────
with tab5:
    st.subheader("Private IPO Valuations & Public Stock Performance")
    st.markdown(
        "Track the performance of major public AI/Tech proxies alongside news and rumors regarding "
        "the highly anticipated private IPOs of **OpenAI**, **Anthropic**, and **SpaceX**."
    )

    # Stock Charts
    st.markdown("### Public Market Performance (Normalized Daily Trends)")
    daily_stocks = session.sql("""
        SELECT ticker, observation_date, close_val
        FROM LABOR_MARKET.RAW.RAW_STOCK_PRICES
        ORDER BY observation_date
    """).to_pandas()

    if daily_stocks.empty:
        st.caption("No daily stock prices found. Run the stock ingestion script.")
    else:
        daily_stocks["observation_date"] = pd.to_datetime(daily_stocks["OBSERVATION_DATE"])

        # Pivot and normalize to baseline (pct change from first date)
        stock_pivot = daily_stocks.pivot_table(
            index="observation_date", columns="TICKER", values="CLOSE_VAL"
        )

        # Normalize (percentage relative to first row value)
        normalized_stocks = (stock_pivot / stock_pivot.iloc[0] - 1) * 100

        st.line_chart(normalized_stocks, use_container_width=True)
        st.caption("Normalized price performance (%) of tech proxies over the entire period, relative to the starting date.")

    st.divider()

    # Prediction market sentiment
    st.markdown("### Prediction Market Odds (Polymarket)")
    st.caption(
        "Implied probability — what people are betting money on — for recession, unemployment, "
        "AI-jobs, and IPO-related questions. A market-priced complement to news sentiment."
    )
    pm_df = session.sql("""
        SELECT month, market_category, avg_probability
        FROM LABOR_MARKET.CORTEX.MONTHLY_PREDICTION_MARKET_SENTIMENT
        ORDER BY month
    """).to_pandas()

    if pm_df.empty:
        st.caption("No Polymarket data loaded yet. Run fetch_polymarket.py.")
    else:
        pm_df["MONTH"] = pd.to_datetime(pm_df["MONTH"])
        pm_pivot = pm_df.pivot_table(index="MONTH", columns="MARKET_CATEGORY", values="AVG_PROBABILITY")
        st.line_chart(pm_pivot, use_container_width=True)

    st.divider()

    # IPO news section
    col_news_left, col_news_right = st.columns([1, 2])

    with col_news_left:
        st.markdown("### IPO News Breakdown")
        ipo_news = session.sql("""
            SELECT target_company, category, full_text, published_at, source_name, ipo_flag
            FROM LABOR_MARKET.CORTEX.NEWS_IPO_CLASSIFIED
            ORDER BY published_at DESC
        """).to_pandas()

        if ipo_news.empty:
            st.caption("No IPO news matches found. Expand News query list or run fetch_news.py.")
        else:
            cat_counts = ipo_news.groupby(["TARGET_COMPANY", "CATEGORY"]).size().unstack(fill_value=0)
            st.bar_chart(cat_counts, stack=True)
            st.caption("Distribution of news sentiments/categories per target private company.")

    with col_news_right:
        st.markdown("### Latest IPO Rumors & Valuation Headlines")
        if ipo_news.empty:
            st.caption("No recent headlines loaded.")
        else:
            # Let user choose company
            comp = st.radio("Filter news by company:", ["All", "OpenAI", "Anthropic", "SpaceX"])

            filtered_news = ipo_news
            if comp != "All":
                filtered_news = ipo_news[ipo_news["TARGET_COMPANY"] == comp]

            for _, r in filtered_news.head(10).iterrows():
                badge_type = r["CATEGORY"]
                color_map = {
                    "ipo_optimism": "🟢",
                    "ipo_pessimism": "🔴",
                    "valuation_hype": "🚀",
                    "layoff_fear": "⚠️",
                    "neutral": "⚪"
                }
                icon = color_map.get(badge_type, "⚪")

                st.markdown(
                    f"**{r['TARGET_COMPANY']}** | {icon} `{r['CATEGORY']}`  \n"
                    f"**{r['FULL_TEXT']}**  \n"
                    f"_{r['SOURCE_NAME']} · {str(r['PUBLISHED_AT'])[:10]}_"
                )
                st.write(" ")
