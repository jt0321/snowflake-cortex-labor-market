import os
from pathlib import Path
from dagster_dbt import DbtCliResource, DbtProject

DBT_PROJECT_DIR = Path(__file__).resolve().parent.parent / "dbt"

dbt_project = DbtProject(project_dir=DBT_PROJECT_DIR)
dbt_project.prepare_if_dev()  # generates target/manifest.json in local dev

dbt_resource = DbtCliResource(project_dir=dbt_project)

SNOWFLAKE_CONFIG = {
    "account":   os.environ["SNOWFLAKE_ACCOUNT"],
    "user":      os.environ["SNOWFLAKE_USER"],
    "password":  os.environ["SNOWFLAKE_PASSWORD"],
    "role":      os.getenv("SNOWFLAKE_ROLE", "SYSADMIN"),
    "warehouse": "LABOR_WH",
    "database":  "LABOR_MARKET",
    "schema":    "RAW",
}
