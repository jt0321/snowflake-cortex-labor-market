"""
dbt asset group + Cortex Search DDL asset.

A single dbt_assets group covers the whole manifest — every dbt node maps to
exactly one Dagster asset, so there's no risk of two asset groups both
claiming the same node (e.g. monthly_integrated_digest depends on the
daily-tagged stock_monthly_performance, so a model can be an "ancestor" of
one cadence while being tagged for another). Cadence-specific runs
(daily_ingest_and_transform, monthly_econ_and_digest in schedules.py) select
a *subset* of this group via AssetSelection.tag(...).upstream(), rather than
splitting the manifest into separate dbt_assets functions.
"""
import snowflake.connector
from dagster import asset, AssetExecutionContext, AssetKey
from dagster_dbt import DbtCliResource, DagsterDbtTranslator, dbt_assets

from dagster_project.resources import dbt_project, SNOWFLAKE_CONFIG


class _CadenceGroupTranslator(DagsterDbtTranslator):
    """Groups each dbt asset in the Dagster UI by its dbt cadence tag."""

    def get_group_name(self, dbt_resource_props):
        tags = dbt_resource_props.get("tags", [])
        if "monthly" in tags:
            return "transforms_monthly"
        if "daily" in tags:
            return "transforms_daily"
        return "transforms_staging"


@dbt_assets(
    manifest=dbt_project.manifest_path,
    name="dbt_transforms",
    dagster_dbt_translator=_CadenceGroupTranslator(),
)
def dbt_transforms(context: AssetExecutionContext, dbt: DbtCliResource):
    yield from dbt.cli(["run"], context=context).stream()


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
