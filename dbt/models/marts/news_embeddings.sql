{{
  config(
    materialized = 'incremental',
    unique_key   = 'article_id',
    on_schema_change = 'sync_all_columns'
  )
}}

select
    article_id,
    full_text,
    published_at,
    category,
    source_name,
    ai_causal_flag,
    AI_EMBED('snowflake-arctic-embed-m-v1.5', full_text) as embedding
from {{ ref('news_classified') }}

{% if is_incremental() %}
  where article_id not in (select article_id from {{ this }})
{% endif %}
