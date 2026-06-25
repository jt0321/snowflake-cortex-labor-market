with daily_prices as (
    select
        ticker,
        observation_date,
        close_val,
        row_number() over (
            partition by ticker, date_trunc('month', observation_date)
            order by observation_date desc
        ) as rn_desc,
        row_number() over (
            partition by ticker, date_trunc('month', observation_date)
            order by observation_date asc
        ) as rn_asc
    from {{ ref('stg_stock_prices') }}
),
month_ends as (
    select
        ticker,
        date_trunc('month', observation_date)::date as month,
        close_val as end_close
    from daily_prices
    where rn_desc = 1
),
month_starts as (
    select
        ticker,
        date_trunc('month', observation_date)::date as month,
        close_val as start_close
    from daily_prices
    where rn_asc = 1
)
select
    me.ticker,
    me.month,
    me.end_close                                                          as close_val,
    ms.start_close,
    ((me.end_close - ms.start_close) / ms.start_close) * 100            as monthly_return_pct
from month_ends me
join month_starts ms on me.ticker = ms.ticker and me.month = ms.month
