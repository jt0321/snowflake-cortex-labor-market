-- Monthly "fear index" from the classified news corpus, at month × source
-- group grain: what share of headlines each month read as fear (layoff /
-- ai_fear), and how many cite AI as a cause of job losses. This is the news
-- half of the project's main question — with GDELT + Hacker News backfill to
-- 2020, it spans both sides of the Nov 2022 ChatGPT moment.
--
-- Split by source group because the corpus mix shifts over time: GDELT and
-- Hacker News span the whole window, but NewsAPI only covers the trailing
-- month. A single aggregate would bend wherever the mix changes; consumers
-- that want an overall line should re-aggregate from the count columns
-- (sum(fear_headline_count) / sum(headline_count)), not average the shares.
--
-- Share-of-headlines (not raw counts) because corpus size varies by source
-- mix and month: absolute counts measure our ingestion, shares measure tone.

select
    date_trunc('month', published_at)::date              as month,
    case when source_name = 'Hacker News'
         then 'tech_community'
         else 'mainstream_press' end                     as source_group,
    count(*)                                             as headline_count,
    count_if(category in ('layoff', 'ai_fear'))          as fear_headline_count,
    count_if(category in ('layoff', 'ai_fear')) * 100.0
        / nullif(count(*), 0)                            as fear_share_pct,
    sum(ai_causal_flag::int)                             as ai_causal_count,
    sum(ai_causal_flag::int) * 100.0
        / nullif(count(*), 0)                            as ai_causal_share_pct
from {{ ref('news_classified') }}
group by 1, 2
