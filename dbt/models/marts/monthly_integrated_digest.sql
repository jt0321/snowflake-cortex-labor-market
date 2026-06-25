with econ as (
    select
        month_date as month,
        max(case when series_id = 'UNRATE'  then value end) as unemployment_rate,
        max(case when series_id = 'PAYEMS'  then value end) as nonfarm_payroll_k
    from {{ ref('stg_fred_series') }}
    group by 1
),
bls_layoffs as (
    select
        month_date as month,
        sum(value) as bls_total_layoffs_k
    from {{ ref('stg_bls_jolts') }}
    where series_id like '%LAY%'
    group by 1
),
fyi_layoffs as (
    select
        date_trunc('month', laid_off_date)::date as month,
        sum(laid_off_count)                       as fyi_tech_layoffs
    from {{ ref('layoffs_fyi_clean') }}
    group by 1
),
stocks as (
    select
        month,
        max(case when ticker = 'QQQ'   then close_val          end) as qqq_close,
        max(case when ticker = 'QQQ'   then monthly_return_pct end) as qqq_return,
        max(case when ticker = 'MSFT'  then close_val          end) as msft_close,
        max(case when ticker = 'MSFT'  then monthly_return_pct end) as msft_return,
        max(case when ticker = 'GOOGL' then close_val          end) as googl_close,
        max(case when ticker = 'GOOGL' then monthly_return_pct end) as googl_return
    from {{ ref('stock_monthly_performance') }}
    group by 1
),
news as (
    select month, ipo_theme_summary, ipo_headline_count, ipo_flag_count
    from {{ ref('monthly_ipo_sentiment') }}
)
select
    e.month,
    e.unemployment_rate,
    e.nonfarm_payroll_k,
    coalesce(l.bls_total_layoffs_k, 0)  as bls_total_layoffs_k,
    coalesce(f.fyi_tech_layoffs, 0)      as fyi_tech_layoffs,
    s.qqq_close,
    s.qqq_return,
    s.msft_close,
    s.msft_return,
    s.googl_close,
    s.googl_return,
    n.ipo_theme_summary,
    coalesce(n.ipo_headline_count, 0)    as ipo_headline_count,
    coalesce(n.ipo_flag_count, 0)        as ipo_flag_count,
    AI_COMPLETE(
        'mistral-7b',
        concat(
            'Write a 3-sentence economic and market digest for ', e.month::varchar, '. ',
            'Broader economy: Unemployment is ', coalesce(e.unemployment_rate::varchar, 'N/A'), '%, ',
            'Nonfarm payrolls: ', coalesce(e.nonfarm_payroll_k::varchar, 'N/A'), 'K, ',
            'Total layoffs (BLS): ', coalesce(l.bls_total_layoffs_k::varchar, 'N/A'), 'K. ',
            'Tech Sector Layoffs (layoffs.fyi): ', coalesce(f.fyi_tech_layoffs::varchar, '0'), '. ',
            'Market performance: QQQ return is ', coalesce(round(s.qqq_return, 1)::varchar, 'N/A'), '%, ',
            'MSFT (OpenAI proxy) return is ', coalesce(round(s.msft_return, 1)::varchar, 'N/A'), '%. ',
            'IPO headlines (', coalesce(n.ipo_headline_count::varchar, '0'), ' total): ',
            coalesce(n.ipo_theme_summary, 'No news on Anthropic, OpenAI, or SpaceX IPOs.'), ' ',
            'Synthesize how tech stock trends and private company valuation/IPO news relate to labor layoffs this month.'
        )
    ) as ipo_market_digest
from econ e
left join bls_layoffs l on e.month = l.month
left join fyi_layoffs f on e.month = f.month
left join stocks      s on e.month = s.month
left join news        n on e.month = n.month
