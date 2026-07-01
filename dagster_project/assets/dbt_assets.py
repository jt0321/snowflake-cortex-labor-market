"""
dbt asset groups + Cortex Search DDL asset.

Three dbt asset groups mirror the schedule cadence:
  daily_dbt_assets   — incremental Cortex classification + stock/layoff transforms
  weekly_dbt_assets  — nothing today; hook point if weekly-tagged models are added
  monthly_dbt_assets — AI_AGG theme rollups + AI_COMPLETE digest generation
"""
import snowflake.connector
from dagster import asset, AssetExecutionContext, AssetKey
from dagster_dbt import DbtCliResource, DagsterDbtTranslator, dbt_assets

from dagster_project.resources import dbt_project, SNOWFLAKE_CONFIG
from dagster_project.assets.ingestion import (
    raw_stock_prices, raw_layoffs_fyi, raw_news_headlines,
    raw_fred_icsa, raw_econ_monthly,
)


class _StaticGroupTranslator(DagsterDbtTranslator):
    """Assigns every asset in a dbt_assets group to one fixed Dagster group name."""

    def __init__(self, group_name: str):
        self._group_name = group_name
        super().__init__()

    def get_group_name(self, dbt_resource_props):
        return self._group_name


@dbt_assets(
    manifest=dbt_project.manifest_path,
    select="tag:daily",
    name="daily_dbt_assets",
    dagster_dbt_translator=_StaticGroupTranslator("transforms_daily"),
)
def daily_dbt_assets(context: AssetExecutionContext, dbt: DbtCliResource):
    yield from dbt.cli(["run", "--select", "tag:daily"], context=context).stream()


@dbt_assets(
    manifest=dbt_project.manifest_path,
    select="tag:monthly",
    name="monthly_dbt_assets",
    dagster_dbt_translator=_StaticGroupTranslator("transforms_monthly"),
)
def monthly_dbt_assets(context: AssetExecutionContext, dbt: DbtCliResource):
    yield from dbt.cli(["run", "--select", "tag:monthly"], context=context).stream()


@asset(
    group_name="transforms_daily",
    description="Cortex Search service over classified headlines — recreated after embeddings refresh",
    deps=[AssetKey(["LABOR_MARKET", "CORTEX", "news_embeddings"])],
    tags={"schedule": "daily"},
)
def cortex_search_service(context: AssetExecutionContext) -> None:
    ddl = """
        CREATE OR REPLACE CORTEX SEARCH SERVICE LABOR_MARKET.CORTEX.HEADLINE_SEARCH
          ON full_text
          ATTRIBUTES category, published_at, source_name, ai_causal_flag
          WAREHOUSE = LABOR_WH
          TARGET_LAG = '1 day'
          AS (
            SELECT full_text, category, published_at, source_name, ai_causal_flag, article_id
            FROM LABOR_MARKET.CORTEX.NEWS_EMBEDDINGS
          )
    """
    cfg = {**SNOWFLAKE_CONFIG, "schema": "CORTEX"}
    conn = snowflake.connector.connect(**cfg)
    conn.cursor().execute(ddl)
    conn.close()
    context.log.info("Cortex Search service recreated")
