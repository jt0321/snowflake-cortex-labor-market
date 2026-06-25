select
    layoff_id,
    company,
    location_hq,
    industry,
    coalesce(laid_off_count, 0)  as laid_off_count,
    coalesce(percentage, 0.0)    as percentage,
    laid_off_date,
    stage,
    coalesce(funds_raised_m, 0.0) as funds_raised_m,
    country,
    source_url
from {{ ref('stg_layoffs_fyi') }}
