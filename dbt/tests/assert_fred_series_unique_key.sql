-- Fails if RAW_FRED_SERIES has duplicate (series_id, observation_date) rows.
-- Catches ingestion regressions where a scheduled run re-inserts overlapping
-- history instead of deduping on load.
select series_id, observation_date, count(*) as n
from {{ source('raw', 'RAW_FRED_SERIES') }}
group by 1, 2
having count(*) > 1
