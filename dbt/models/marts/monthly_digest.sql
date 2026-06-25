with econ as (
    select
        month_date                                                    as month,
        max(case when series_id = 'UNRATE'  then value end)          as unemployment_rate,
        max(case when series_id = 'PAYEMS'  then value end)          as nonfarm_payroll_k
    from {{ ref('stg_fred_series') }}
    group by 1
),
layoffs as (
    select
        month_date                  as month,
        sum(value)                  as total_layoffs_k
    from {{ ref('stg_bls_jolts') }}
    where series_id like '%LAY%'
    group by 1
),
joined as (
    select
        e.month,
        e.unemployment_rate,
        e.nonfarm_payroll_k,
        l.total_layoffs_k,
        t.theme_summary,
        t.headline_count,
        t.ai_causal_count
    from econ e
    left join layoffs                     l on e.month = l.month
    left join {{ ref('monthly_sentiment_themes') }} t on e.month = t.month
)
select
    month,
    unemployment_rate,
    nonfarm_payroll_k,
    total_layoffs_k,
    headline_count,
    ai_causal_count,
    AI_COMPLETE(
        'mistral-7b',
        concat(
            'Write a 3-sentence economic digest for ', month::varchar, '. ',
            'Unemployment rate: ', coalesce(unemployment_rate::varchar, 'N/A'), '%. ',
            'Nonfarm payrolls: ', coalesce(nonfarm_payroll_k::varchar, 'N/A'), 'K. ',
            'Total layoffs: ', coalesce(total_layoffs_k::varchar, 'N/A'), 'K. ',
            'News headlines this month (', coalesce(headline_count::varchar, '0'), ' total, ',
            coalesce(ai_causal_count::varchar, '0'), ' citing AI as a cause): ',
            coalesce(theme_summary, 'No headlines captured this month.'), ' ',
            'Assess whether the data supports or contradicts the fear that AI is driving displacement.'
        )
    ) as narrative_digest
from joined
