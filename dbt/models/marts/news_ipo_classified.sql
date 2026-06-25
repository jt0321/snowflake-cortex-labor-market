{{
  config(
    materialized = 'incremental',
    unique_key   = 'article_id',
    on_schema_change = 'sync_all_columns'
  )
}}

select
    article_id,
    source_name,
    published_at,
    full_text,
    case
        when lower(full_text) like '%openai%'   then 'OpenAI'
        when lower(full_text) like '%anthropic%' then 'Anthropic'
        when lower(full_text) like '%spacex%'   then 'SpaceX'
        else 'Tech Sector'
    end as target_company,
    AI_CLASSIFY(
        full_text,
        ['ipo_optimism', 'ipo_pessimism', 'valuation_hype', 'layoff_fear', 'neutral']
    ) as category,
    AI_FILTER(
        full_text,
        'The article mentions valuations, private funding rounds, investments, or discussions about an IPO or secondary sale'
    ) as ipo_flag
from {{ ref('stg_news_headlines') }}
where (
    lower(full_text) like '%openai%'
    or lower(full_text) like '%anthropic%'
    or lower(full_text) like '%spacex%'
    or lower(full_text) like '%ipo%'
)

{% if is_incremental() %}
  and article_id not in (select article_id from {{ this }})
{% endif %}
