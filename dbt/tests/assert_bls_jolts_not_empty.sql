-- Fails if RAW_BLS_JOLTS has zero rows. The BLS API returns an empty
-- observation list (not an error) for invalid/discontinued series IDs, so an
-- ingestion misconfiguration here fails silently unless something checks for it.
select 1 as failure
from (select count(*) as n from {{ source('raw', 'RAW_BLS_JOLTS') }})
where n = 0
