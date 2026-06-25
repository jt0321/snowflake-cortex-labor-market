select
    series_id,
    year,
    period,
    period_name,
    value,
    -- reconstruct a date for easier joining
    date_from_parts(year, replace(period, 'M', '')::int, 1) as month_date
from {{ source('raw', 'RAW_BLS_JOLTS') }}
where period like 'M%'
  and value is not null
