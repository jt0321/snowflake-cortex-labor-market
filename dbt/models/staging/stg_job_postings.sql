select
    series_id,
    observation_date,
    value,
    date_trunc('month', observation_date)::date as month_date
from {{ source('raw', 'RAW_JOB_POSTINGS') }}
where value is not null
  and observation_date >= '2020-01-01'
