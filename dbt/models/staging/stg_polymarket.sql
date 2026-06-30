select
    market_id,
    question,
    outcome,
    probability,
    volume,
    liquidity,
    end_date,
    snapshot_date,
    date_trunc('month', snapshot_date)::date as month_date,
    case
        when lower(question) like '%recession%'                 then 'recession'
        when lower(question) like '%unemployment%'               then 'unemployment'
        when lower(question) like '%layoff%'                     then 'layoffs'
        when lower(question) like '%openai%'                     then 'openai_ipo'
        when lower(question) like '%anthropic%'                  then 'anthropic_ipo'
        when lower(question) like '%spacex%'                     then 'spacex_ipo'
        when lower(question) like '%ai job%' or lower(question) like '%artificial intelligence job%'
                                                                  then 'ai_jobs'
        else 'other'
    end as market_category
from {{ source('raw', 'RAW_POLYMARKET_MARKETS') }}
where probability is not null
