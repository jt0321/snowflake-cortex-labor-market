from dagster import Definitions
from dagster_dbt import DbtCliResource

from dagster_project.resources import dbt_resource
from dagster_project.assets.ingestion import (
    raw_stock_prices, raw_layoffs_fyi, raw_news_headlines, raw_polymarket_markets,
    raw_fred_icsa, raw_econ_monthly,
)
from dagster_project.assets.dbt_assets import (
    daily_dbt_assets, monthly_dbt_assets, cortex_search_service,
)
from dagster_project.schedules import (
    daily_schedule, weekly_schedule, monthly_schedule,
)

defs = Definitions(
    assets=[
        # ingestion
        raw_stock_prices,
        raw_layoffs_fyi,
        raw_news_headlines,
        raw_polymarket_markets,
        raw_fred_icsa,
        raw_econ_monthly,
        # dbt transforms
        daily_dbt_assets,
        monthly_dbt_assets,
        # post-dbt DDL
        cortex_search_service,
    ],
    schedules=[
        daily_schedule,
        weekly_schedule,
        monthly_schedule,
    ],
    resources={
        "dbt": dbt_resource,
    },
)
