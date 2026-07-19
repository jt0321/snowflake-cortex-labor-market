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
import altair as alt


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


# Key dates for reading the time series: the first Fed hike tests the
# business-cycle explanation for the 2023 layoff wave; the AI milestones
# test the AI-fear explanation.
EVENT_MARKERS = [
    ("2022-03-16", "First Fed hike"),
    ("2022-11-30", "ChatGPT"),
    ("2023-03-14", "GPT-4"),
]


def line_chart_with_events(df_long, x_col, y_col, color_col, y_title, height=320):
    """Altair multi-series line chart with dashed vertical rules at
    EVENT_MARKERS (st.line_chart can't draw event annotations)."""
    base = alt.Chart(df_long).mark_line().encode(
        x=alt.X(f"{x_col}:T", title=None),
        y=alt.Y(f"{y_col}:Q", title=y_title),
        color=alt.Color(f"{color_col}:N", title=None, legend=alt.Legend(orient="bottom")),
        tooltip=[
            alt.Tooltip(f"{x_col}:T", format="%b %Y", title="Month"),
            alt.Tooltip(f"{y_col}:Q", format=",.1f", title=y_title),
            alt.Tooltip(f"{color_col}:N", title="Series"),
        ],
    ).properties(height=height)

    lo, hi = df_long[x_col].min(), df_long[x_col].max()
    events = pd.DataFrame(
        [{"date": pd.Timestamp(d), "label": lbl} for d, lbl in EVENT_MARKERS]
    )
    events = events[(events["date"] >= lo) & (events["date"] <= hi)]
    if events.empty:
        return base

    rules = alt.Chart(events).mark_rule(strokeDash=[4, 3], color="#9ca3af").encode(x="date:T")
    labels = alt.Chart(events).mark_text(
        angle=270, align="left", baseline="middle", dx=4, dy=-7,
        color="#9ca3af", fontSize=11,
    ).encode(x="date:T", y=alt.value(6), text="label:N")
    return base + rules + labels


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
            layoffs_long = df_chart.melt("month", value_vars=plot_cols,
                                         var_name="series", value_name="persons")
            st.altair_chart(
                line_chart_with_events(layoffs_long, "month", "persons", "series",
                                       "Persons", height=350),
                use_container_width=True,
            )
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

    # ── The main question: does headline fear track actual layoffs? ──────
    st.divider()
    st.subheader("Does the data back up the fear?")
    st.markdown(
        "The share of headlines each month that Cortex classifies as fear (`layoff` / `ai_fear`), "
        "plotted against what actually happened to jobs. The news corpus reaches back to 2020 via "
        "GDELT and Hacker News, so both sides of the ChatGPT moment (Nov 2022) are covered."
    )

    fear_df = session.sql("""
        SELECT month, source_group, headline_count, fear_headline_count,
               fear_share_pct, ai_causal_count, ai_causal_share_pct
        FROM LABOR_MARKET.CORTEX.MONTHLY_NEWS_FEAR_INDEX
        ORDER BY month
    """).to_pandas()

    if fear_df.empty:
        st.caption(
            "No classified headlines yet. Run `fetch_news_history.py --backfill` for 2020+ "
            "history, then a dbt run to classify it."
        )
    else:
        fear_df["MONTH"] = pd.to_datetime(fear_df["MONTH"])

        # Overall fear line, re-aggregated from counts (never averaged from the
        # per-source shares): the source mix shifts over time — NewsAPI only
        # covers the trailing month — and count-weighting keeps mix changes
        # from bending the aggregate.
        overall = fear_df.groupby("MONTH", as_index=False)[
            ["HEADLINE_COUNT", "FEAR_HEADLINE_COUNT", "AI_CAUSAL_COUNT"]
        ].sum()
        overall["FEAR_SHARE_PCT"] = overall["FEAR_HEADLINE_COUNT"] * 100.0 / overall["HEADLINE_COUNT"]
        overall["AI_CAUSAL_SHARE_PCT"] = overall["AI_CAUSAL_COUNT"] * 100.0 / overall["HEADLINE_COUNT"]

        # ── Pre vs. post ChatGPT — the direct answer to the main question ──
        # Fixed full-history windows on purpose (the slider doesn't apply):
        # the comparison only means something over the complete 2020+ record.
        chatgpt_month = pd.Timestamp(2022, 11, 1)
        # drop df_combined's own MONTH column so the merge doesn't suffix ours
        full = overall.merge(df_combined.drop(columns=["MONTH"]),
                             left_on="MONTH", right_on="month", how="inner")
        pre, post = full[full["MONTH"] < chatgpt_month], full[full["MONTH"] >= chatgpt_month]

        if not pre.empty and not post.empty:
            def _pct(d, num_col):
                return d[num_col].sum() * 100.0 / max(d["HEADLINE_COUNT"].sum(), 1)

            pre_fear,   post_fear   = _pct(pre, "FEAR_HEADLINE_COUNT"), _pct(post, "FEAR_HEADLINE_COUNT")
            pre_causal, post_causal = _pct(pre, "AI_CAUSAL_COUNT"),     _pct(post, "AI_CAUSAL_COUNT")
            pre_lay,    post_lay    = pre["FYI_TECH_LAYOFFS"].mean(),   post["FYI_TECH_LAYOFFS"].mean()
            pre_un,     post_un     = pre["UNEMPLOYMENT_RATE"].mean(),  post["UNEMPLOYMENT_RATE"].mean()

            st.markdown("#### Pre- vs. post-ChatGPT (Nov 2022), full 2020+ record")
            p1, p2, p3, p4 = st.columns(4)
            p1.metric(
                "Fear headlines", f"{post_fear:.1f}%",
                delta=f"{post_fear - pre_fear:+.1f} pts vs pre", delta_color="inverse",
                help="Share of headlines classified layoff/ai_fear, post-ChatGPT era vs Jan 2020–Oct 2022.",
            )
            p2.metric(
                "Cite AI as job-loss cause", f"{post_causal:.1f}%",
                delta=f"{post_causal - pre_causal:+.1f} pts vs pre", delta_color="inverse",
                help="Share of headlines where AI/automation is cited as a contributing factor to job losses.",
            )
            p3.metric(
                "Tech layoffs / month", f"{post_lay:,.0f}",
                delta=f"{(post_lay / pre_lay - 1) * 100:+.0f}% vs pre" if pre_lay else None,
                delta_color="inverse",
                help="Average monthly Layoffs.fyi headcount. The pre window includes the 2020 COVID shock.",
            )
            p4.metric(
                "Unemployment rate", f"{post_un:.1f}%",
                delta=f"{post_un - pre_un:+.1f} pts vs pre", delta_color="inverse",
                help="Average monthly unemployment rate. The pre window includes the 2020 COVID spike.",
            )

            if pre_fear > 0 and pre_lay and pre_lay > 0:
                fear_ratio, lay_ratio = post_fear / pre_fear, post_lay / pre_lay
                if fear_ratio > lay_ratio * 1.25:
                    st.markdown(
                        f"**Verdict: the fear has outrun the data.** Fear-toned coverage is "
                        f"{fear_ratio:.1f}× its pre-ChatGPT level while actual tech layoffs are "
                        f"{lay_ratio:.1f}× — the anxiety grew faster than the layoffs did."
                    )
                elif lay_ratio > fear_ratio * 1.25:
                    st.markdown(
                        f"**Verdict: reality moved more than the headlines.** Tech layoffs run "
                        f"{lay_ratio:.1f}× their pre-ChatGPT level while fear-toned coverage is "
                        f"only {fear_ratio:.1f}× — the numbers back up (and exceed) the fear."
                    )
                else:
                    st.markdown(
                        f"**Verdict: the fear roughly tracks reality.** Fear-toned coverage "
                        f"({fear_ratio:.1f}× pre-ChatGPT) and actual tech layoffs ({lay_ratio:.1f}×) "
                        f"moved broadly in step."
                    )
            st.caption(
                "Both windows are affected by confounders — the pre window contains the COVID shock, "
                "and the post window contains the tail of the 2022–23 rate-hike cycle (see the Fed "
                "hike marker on the charts). Averages are count-weighted across the full corpus."
            )

        st.write(" ")
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            st.markdown("### News Fear Share by Source (% of headlines)")
            src_windowed = fear_df[
                (fear_df["MONTH"].dt.date >= range_start) & (fear_df["MONTH"].dt.date <= range_end)
            ].copy()
            src_windowed["series"] = src_windowed["SOURCE_GROUP"].map({
                "mainstream_press": "Mainstream press",
                "tech_community": "Tech community (HN)",
            }).fillna(src_windowed["SOURCE_GROUP"])
            st.altair_chart(
                line_chart_with_events(src_windowed.rename(columns={"FEAR_SHARE_PCT": "fear_share"}),
                                       "MONTH", "fear_share", "series",
                                       "Fear share (%)", height=320),
                use_container_width=True,
            )
            st.caption(
                "Split by source group because the corpus mix shifts over time (NewsAPI only covers "
                "the trailing month). Shares, not raw counts, so volume swings don't read as tone. "
                "GDELT and Hacker News rows are classified from titles only."
            )

        with col_f2:
            st.markdown("### Fear vs. Reality Correlation")
            overall_windowed = overall[
                (overall["MONTH"].dt.date >= range_start) & (overall["MONTH"].dt.date <= range_end)
            ]
            # Months with a thin corpus produce unstable shares — keep them on
            # the chart but out of the correlation.
            merged = overall_windowed[overall_windowed["HEADLINE_COUNT"] >= 20].merge(
                df_windowed, left_on="MONTH", right_on="month", how="inner"
            )
            corr_fear_bls = merged["FEAR_SHARE_PCT"].corr(merged["BLS_TOTAL_LAYOFFS"])
            corr_fear_fyi = merged["FEAR_SHARE_PCT"].corr(merged["FYI_TECH_LAYOFFS"])

            v1, v2 = st.columns(2)
            v1.metric(
                "Fear vs. BLS Layoffs",
                f"{corr_fear_bls:.2f}" if pd.notna(corr_fear_bls) else "N/A",
                help="Correlation between monthly fear-headline share (all sources) and economy-wide BLS layoffs, over the selected range (months with ≥20 classified headlines).",
            )
            v2.metric(
                "Fear vs. Tech Layoffs",
                f"{corr_fear_fyi:.2f}" if pd.notna(corr_fear_fyi) else "N/A",
                help="Correlation between monthly fear-headline share (all sources) and Layoffs.fyi tech layoffs, over the selected range (months with ≥20 classified headlines).",
            )
            st.caption(
                "Correlations respond to the date-range slider above; the pre/post verdict "
                "always uses the full record. High correlation = headline fear moves with "
                "actual layoffs; low = tone and numbers are decoupled in this window."
            )

    # ── Broader macro context: inflation, rates, overall market ──────────
    st.divider()
    st.subheader("Inflation, Rates & the Overall Market")
    st.markdown(
        "Control variables for the AI story: if layoffs move with **inflation and the Fed funds "
        "rate** (the 2022–23 tightening cycle), that's a business-cycle explanation. And if tech "
        "(**QQQ**) simply moves with the whole market (**S&P 500**), weakness isn't tech-specific."
    )

    macro_df = session.sql("""
        SELECT month, cpi_yoy_pct, core_cpi_yoy_pct, fed_funds_rate,
               sp500_close, qqq_close, sp500_return_pct
        FROM LABOR_MARKET.CORTEX.MACRO_MONTHLY
        ORDER BY month
    """).to_pandas()

    if macro_df.empty:
        st.caption("No macro data yet — run fetch_econ.py and fetch_stocks.py, then a dbt run.")
    else:
        macro_df["MONTH"] = pd.to_datetime(macro_df["MONTH"])
        macro_windowed = macro_df[
            (macro_df["MONTH"].dt.date >= range_start) & (macro_df["MONTH"].dt.date <= range_end)
        ]

        col_m1, col_m2 = st.columns(2)
        with col_m1:
            st.markdown("### Inflation & the Policy Rate (%)")
            st.line_chart(
                macro_windowed.set_index("MONTH")[
                    ["CPI_YOY_PCT", "CORE_CPI_YOY_PCT", "FED_FUNDS_RATE"]
                ].rename(columns={
                    "CPI_YOY_PCT": "CPI YoY",
                    "CORE_CPI_YOY_PCT": "Core CPI YoY",
                    "FED_FUNDS_RATE": "Fed Funds Rate",
                }),
                height=320,
            )
            st.caption("Headline and core CPI year-over-year, with the effective Fed funds rate — FRED.")

        with col_m2:
            st.markdown("### Overall Market vs. Tech (indexed)")
            idx = macro_windowed.set_index("MONTH")[["SP500_CLOSE", "QQQ_CLOSE"]].dropna()
            if idx.empty:
                st.caption("No index prices in this range yet.")
            else:
                normalized = (idx / idx.iloc[0] - 1) * 100
                st.line_chart(
                    normalized.rename(columns={
                        "SP500_CLOSE": "S&P 500 (%)",
                        "QQQ_CLOSE": "QQQ (%)",
                    }),
                    height=320,
                )
                st.caption("Cumulative return since the start of the selected range — Yahoo Finance month-end closes.")

        latest_macro = macro_windowed.dropna(subset=["CPI_YOY_PCT"]).tail(1)
        mm1, mm2, mm3, mm4 = st.columns(4)
        if not latest_macro.empty:
            lm = latest_macro.iloc[0]
            mm1.metric("CPI YoY", f"{lm['CPI_YOY_PCT']:.1f}%")
            mm2.metric("Core CPI YoY", f"{lm['CORE_CPI_YOY_PCT']:.1f}%" if pd.notna(lm["CORE_CPI_YOY_PCT"]) else "N/A")
            mm3.metric("Fed Funds Rate", f"{lm['FED_FUNDS_RATE']:.2f}%" if pd.notna(lm["FED_FUNDS_RATE"]) else "N/A")
        sp_latest = macro_windowed.dropna(subset=["SP500_RETURN_PCT"]).tail(1)
        mm4.metric(
            "S&P 500 Monthly Return",
            f"{sp_latest['SP500_RETURN_PCT'].iloc[0]:+.2f}%" if not sp_latest.empty else "N/A",
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

    fcol1, fcol2, fcol3 = st.columns([2, 1, 1])
    cat_filter = fcol1.multiselect(
        "Filter categories",
        ["layoff", "hiring", "ai_fear", "ai_positive", "policy", "neutral"],
        default=[],
        key="semantic_search_categories"
    )
    source_pick = fcol2.radio(
        "Source",
        ["All", "Press & blogs", "Hacker News"],
        key="semantic_search_source",
        help="Press & blogs = GDELT + NewsAPI outlets; Hacker News = tech community stories.",
    )
    date_window = fcol3.date_input(
        "Published between",
        value=(datetime.date(2020, 1, 1), datetime.date.today()),
        min_value=datetime.date(2020, 1, 1),
        key="semantic_search_dates",
    )

    if search_q:
        # Compose all active filters with @and — Cortex Search takes one
        # filter object, not a list.
        clauses = []
        if cat_filter:
            clauses.append({"@or": [{"@eq": {"category": c}} for c in cat_filter]})
        if source_pick == "Hacker News":
            clauses.append({"@eq": {"source_name": "Hacker News"}})
        elif source_pick == "Press & blogs":
            clauses.append({"@not": {"@eq": {"source_name": "Hacker News"}}})
        if isinstance(date_window, (list, tuple)) and len(date_window) == 2:
            d_from, d_to = date_window
            clauses.append({"@gte": {"published_at": d_from.isoformat()}})
            # end date is inclusive of the whole day
            clauses.append({"@lte": {"published_at": (d_to + datetime.timedelta(days=1)).isoformat()}})
        search_filter = clauses[0] if len(clauses) == 1 else ({"@and": clauses} if clauses else None)

        try:
            results = cortex_search(
                query=search_q,
                columns=["full_text", "category", "published_at", "source_name", "ai_causal_flag"],
                filter_obj=search_filter,
                limit=20,
            )
        except Exception as e:
            st.error(f"Search failed: {e}")
            results = pd.DataFrame()

        if results.empty:
            st.warning("No articles found matching that semantic description and filters.")
        else:
            st.caption(f"Top {len(results)} matches")
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
        st.caption(
            "Normalized price performance (%) relative to the starting date. "
            "^GSPC (S&P 500) is the overall-market baseline — divergence between it and the "
            "tech proxies is what makes a move tech-specific."
        )

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
