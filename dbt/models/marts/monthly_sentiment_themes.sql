select
    date_trunc('month', published_at)::date as month,
    AI_AGG(
        full_text,
        'Identify the 3-5 dominant themes in these news headlines about jobs, employment, and AI. '
        'For each theme, note whether it suggests AI is causing displacement, creating opportunity, '
        'or is unrelated to employment outcomes. Be concise.'
    )                               as theme_summary,
    count(*)                        as headline_count,
    sum(ai_causal_flag::int)        as ai_causal_count
from {{ ref('news_classified') }}
group by 1
