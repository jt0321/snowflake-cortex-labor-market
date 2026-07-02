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
    AI_CLASSIFY(
        full_text,
        ['layoff', 'hiring', 'ai_fear', 'ai_positive', 'policy', 'neutral']
    ):labels[0]::VARCHAR as category,
    AI_FILTER(
        PROMPT('The article mentions artificial intelligence, automation, or machine learning as a contributing factor to job losses, layoffs, or unemployment: {0}', full_text)
    ) as ai_causal_flag
from {{ ref('stg_news_headlines') }}

{% if is_incremental() %}
  -- only classify rows not yet in the table; avoids re-paying Cortex credits
  where article_id not in (select article_id from {{ this }})
{% endif %}
