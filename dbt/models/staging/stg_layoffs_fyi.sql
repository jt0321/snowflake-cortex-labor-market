select
    layoff_id,
    company,
    location_hq,
    industry,
    laid_off_count,
    percentage,
    laid_off_date,
    stage,
    funds_raised_m,
    country,
    source_url
from {{ source('raw', 'RAW_LAYOFFS_FYI') }}
where company is not null
  and laid_off_date >= '2020-01-01'
