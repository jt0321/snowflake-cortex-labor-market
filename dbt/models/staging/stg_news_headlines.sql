select
    article_id,
    source_name,
    author,
    title,
    description,
    url,
    published_at,
    full_text,
    loaded_at
from {{ source('raw', 'RAW_NEWS_HEADLINES') }}
where full_text is not null
  and published_at >= '2020-01-01'
