select
    ticker,
    observation_date,
    close_val,
    loaded_at
from {{ source('raw', 'RAW_STOCK_PRICES') }}
where close_val is not null
  and observation_date >= '2020-01-01'
