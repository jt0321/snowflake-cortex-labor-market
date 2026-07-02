select
    date_trunc('month', published_at)::date as month,
    AI_AGG(
        full_text,
        'Summarize the monthly sentiment, valuation rumors, and IPO discussion trends regarding OpenAI, Anthropic, and SpaceX. ' ||
        'Highlight key themes like optimism, pessimism, private funding rounds, or valuation changes. Be extremely concise.'
    )          as ipo_theme_summary,
    count(*)   as ipo_headline_count,
    sum(ipo_flag::int) as ipo_flag_count
from {{ ref('news_ipo_classified') }}
group by 1
