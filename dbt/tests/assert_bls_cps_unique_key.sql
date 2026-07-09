-- Fails if RAW_BLS_CPS has duplicate (series_id, year, period) rows.
-- Catches ingestion regressions where a scheduled run re-inserts overlapping
-- history instead of deduping on load.
select series_id, year, period, count(*) as n
from {{ source('raw', 'RAW_BLS_CPS') }}
group by 1, 2, 3
having count(*) > 1
