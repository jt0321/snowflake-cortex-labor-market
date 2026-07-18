-- Monthly "fear index" from the classified news corpus: what share of
-- headlines each month read as fear (layoff / ai_fear), and how many cite AI
-- as a cause of job losses. This is the news half of the project's main
-- question — with GDELT + Hacker News backfill to 2020, it spans both sides
-- of the Nov 2022 ChatGPT moment, so headline fear can finally be compared
-- against BLS layoffs over the same window.
--
-- Share-of-headlines (not raw counts) because corpus size varies by source
-- mix and month: absolute counts measure our ingestion, shares measure tone.

select
    date_trunc('month', published_at)::date              as month,
    count(*)                                             as headline_count,
    count_if(category in ('layoff', 'ai_fear'))          as fear_headline_count,
    count_if(category in ('layoff', 'ai_fear')) * 100.0
        / nullif(count(*), 0)                            as fear_share_pct,
    sum(ai_causal_flag::int)                             as ai_causal_count,
    sum(ai_causal_flag::int) * 100.0
        / nullif(count(*), 0)                            as ai_causal_share_pct
from {{ ref('news_classified') }}
group by 1
