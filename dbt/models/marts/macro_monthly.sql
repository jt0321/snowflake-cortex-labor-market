-- One row per month of broad macro context: unemployment, headline & core
-- inflation (YoY), the Fed funds rate, and overall-market (S&P 500) vs. tech
-- (QQQ) returns. Gives the fear-vs-reality question a control panel — if
-- layoffs track rate hikes and inflation rather than AI adoption, that's a
-- business-cycle story, not an AI story.

with fred as (
    -- Read RAW directly (not stg_fred_series) because YoY inflation for
    -- Jan-Dec 2020 needs the 2019 CPI baseline, and staging clips at 2020.
    -- The final select re-applies the 2020 analysis window.
    select
        series_id,
        date_trunc('month', observation_date)::date as month,
        avg(value) as value
    from {{ source('raw', 'RAW_FRED_SERIES') }}
    where value is not null
      and observation_date >= '2019-01-01'
      and series_id in ('UNRATE', 'PAYEMS', 'FEDFUNDS', 'CPIAUCSL', 'CPILFESL', 'USINFO')
    group by 1, 2
),

pivoted as (
    select
        month,
        max(case when series_id = 'UNRATE'   then value end) as unemployment_rate,
        max(case when series_id = 'PAYEMS'   then value end) as nonfarm_payroll_k,
        max(case when series_id = 'FEDFUNDS' then value end) as fed_funds_rate,
        max(case when series_id = 'CPIAUCSL' then value end) as cpi_index,
        max(case when series_id = 'CPILFESL' then value end) as core_cpi_index,
        max(case when series_id = 'USINFO'   then value end) as info_employment_k
    from fred
    group by 1
),

-- young workers (20-24) — where entry-level displacement shows up first
cps_youth as (
    select month_date as month, value as youth_unemployment_rate
    from {{ ref('stg_bls_cps') }}
    where series_id = 'LNS14000036'
),

-- Indeed postings index (Feb 2020 = 100) — the hiring side layoffs miss
postings as (
    select
        month_date as month,
        avg(case when series_id = 'US_TOTAL' then value end)                as postings_total_idx,
        avg(case when series_id like 'SOFTWARE%' then value end)            as postings_software_idx
    from {{ ref('stg_job_postings') }}
    group by 1
),

with_inflation as (
    select
        *,
        (cpi_index      / lag(cpi_index, 12)      over (order by month) - 1) * 100 as cpi_yoy_pct,
        (core_cpi_index / lag(core_cpi_index, 12) over (order by month) - 1) * 100 as core_cpi_yoy_pct
    from pivoted
),

market as (
    select
        month,
        max(case when ticker = '^GSPC' then close_val          end) as sp500_close,
        max(case when ticker = '^GSPC' then monthly_return_pct end) as sp500_return_pct,
        max(case when ticker = 'QQQ'   then close_val          end) as qqq_close,
        max(case when ticker = 'QQQ'   then monthly_return_pct end) as qqq_return_pct
    from {{ ref('stock_monthly_performance') }}
    group by 1
)

select
    i.month,
    i.unemployment_rate,
    y.youth_unemployment_rate,
    i.nonfarm_payroll_k,
    i.info_employment_k,
    i.fed_funds_rate,
    i.cpi_yoy_pct,
    i.core_cpi_yoy_pct,
    p.postings_total_idx,
    p.postings_software_idx,
    m.sp500_close,
    m.sp500_return_pct,
    m.qqq_close,
    m.qqq_return_pct
from with_inflation i
left join cps_youth y on i.month = y.month
left join postings  p on i.month = p.month
left join market    m on i.month = m.month
where i.month >= '2020-01-01'
