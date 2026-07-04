"""
streamlit/app.py — AI & the Labor Market dashboard
Deploy as a Streamlit in Snowflake app.

Integrates BLS macro data, layoffs.fyi tech sector data, stock market lines,
and OpenAI/Anthropic/SpaceX IPO sentiment news analyzed via Cortex AI.
"""

import streamlit as st
import pandas as pd
from snowflake.snowpark.context import get_active_session
from snowflake.core import Root

# Get active session
session = get_active_session()
root = Root(session)
headline_search_service = (
    root.databases["LABOR_MARKET"]
    .schemas["CORTEX"]
    .cortex_search_services["HEADLINE_SEARCH"]
)

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
        "Compare official **BLS Layoffs** (macroeconomy) against crowdsourced **Layoffs.fyi** data (tech-specific sector) "
        "alongside news volume citing AI as a job loss factor."
    )
    
    # Fetch data
    df_combined = session.sql("""
        SELECT
          d.month,
          d.bls_total_layoffs_k,
          d.fyi_tech_layoffs,
          d.unemployment_rate,
          d.recession_probability,
          COALESCE(m.ai_causal_count, 0) AS ai_causal_count
        FROM LABOR_MARKET.CORTEX.MONTHLY_INTEGRATED_DIGEST d
        LEFT JOIN LABOR_MARKET.CORTEX.MONTHLY_DIGEST m ON d.month = m.month
        ORDER BY d.month
    """).to_pandas()
    
    df_combined["month"] = pd.to_datetime(df_combined["MONTH"])
    
    col1, col2 = st.columns(2)
    with col1:
        # Normalize to allow dual plotting
        st.markdown("### Broad Economy vs. Tech Layoffs")
        chart_data = df_combined.set_index("month")[["BLS_TOTAL_LAYOFFS_K", "FYI_TECH_LAYOFFS"]].copy()
        chart_data = chart_data.rename(columns={
            "BLS_TOTAL_LAYOFFS_K": "BLS Total Layoffs (K)",
            "FYI_TECH_LAYOFFS": "Tech Layoffs (Actual Count)"
        })
        st.line_chart(chart_data, use_container_width=True)
        st.caption("Comparison of macro economy layoffs (BLS, thousands) and specific tech layoffs (Layoffs.fyi, raw count).")
        
    with col2:
        st.markdown("### AI-Causal News Volume")
        st.line_chart(
            df_combined.set_index("month")[["AI_CAUSAL_COUNT"]].rename(columns={"AI_CAUSAL_COUNT": "AI Job Loss Headlines"}),
            use_container_width=True,
            color="#ec4899"
        )
        st.caption("Number of news articles per month explicitly citing AI as a cause for worker displacement.")
        
    st.divider()
    
    # Metrics row
    m1, m2, m3, m4 = st.columns(4)

    # Calculate correlations
    corr_bls_vs_fyi = df_combined["BLS_TOTAL_LAYOFFS_K"].corr(df_combined["FYI_TECH_LAYOFFS"])
    corr_fyi_vs_news = df_combined["FYI_TECH_LAYOFFS"].corr(df_combined["AI_CAUSAL_COUNT"])

    m1.metric(
        "BLS vs. Tech Layoffs Correlation",
        f"{corr_bls_vs_fyi:.2f}",
        help="Correlation between general U.S. layoffs (BLS JOLTS) and tech layoffs (Layoffs.fyi). A high value indicates tech moves in lockstep with the broader market."
    )
    m2.metric(
        "Tech Layoffs vs. AI News Correlation",
        f"{corr_fyi_vs_news:.2f}",
        help="Correlation between tech layoffs and news articles blaming AI for job cuts. High correlation suggests news volume tracks actual tech layoffs."
    )

    unrate_latest = df_combined["UNEMPLOYMENT_RATE"].iloc[-1] if not df_combined.empty else 0.0
    m3.metric("Latest Unemployment Rate", f"{unrate_latest:.1f}%")

    recession_prob = df_combined["RECESSION_PROBABILITY"].dropna()
    m4.metric(
        "Polymarket Recession Odds",
        f"{recession_prob.iloc[-1] * 100:.0f}%" if not recession_prob.empty else "N/A",
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
    
    digest_data = session.sql(f"""
        SELECT 
          d.unemployment_rate,
          d.bls_total_layoffs_k,
          d.fyi_tech_layoffs,
          d.qqq_return,
          d.msft_return,
          d.ipo_market_digest,
          m.narrative_digest AS standard_digest,
          d.ipo_theme_summary
        FROM LABOR_MARKET.CORTEX.MONTHLY_INTEGRATED_DIGEST d
        LEFT JOIN LABOR_MARKET.CORTEX.MONTHLY_DIGEST m ON d.month = m.month
        WHERE d.month = '{selected_month}'
    """).to_pandas()
    
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

        response = headline_search_service.search(
            query=search_q,
            columns=["full_text", "category", "published_at", "source_name", "ai_causal_flag"],
            filter=search_filter,
            limit=20,
        )
        results = pd.DataFrame(response.results)

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
