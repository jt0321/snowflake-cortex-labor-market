-- Reduce each market to its "primary" outcome (Yes, for binary markets;
-- otherwise the highest-probability outcome) so averaging across markets
-- in a category isn't diluted by Yes+No always summing to ~1.
with primary_outcome as (
    select
        *,
        row_number() over (
            partition by market_id, snapshot_date
            order by case when lower(outcome) = 'yes' then 0 else 1 end, probability desc
        ) as rn
    from {{ ref('stg_polymarket') }}
)
select
    month_date                          as month,
    market_category,
    avg(probability)                    as avg_probability,
    max(probability)                    as max_probability,
    count(distinct market_id)           as market_count,
    sum(volume)                         as total_volume
from primary_outcome
where rn = 1
group by 1, 2
