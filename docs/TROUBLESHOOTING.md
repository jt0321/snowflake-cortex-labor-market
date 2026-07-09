# Troubleshooting

## "Object ... already exists, but current role has no privileges on it" (RAW tables, `LABOR_WH`, etc.)

Every `sql/*.sql` script now opens with `USE ROLE SYSADMIN;`, so objects created by these scripts always land under SYSADMIN. But if an object was already created under a different role before you ran these scripts — e.g. you clicked through Snowsight's warehouse-creation wizard, or ran `01_raw_tables.sql`/`02_cortex_transforms.sql`/`03_ipo_market_transforms.sql` in a worksheet session that wasn't actually on SYSADMIN — `CREATE ... IF NOT EXISTS` is a no-op and silently leaves ownership on the original role. dbt/Dagster (which always connect as SYSADMIN) then can't see or write to it. Fix once, as `ACCOUNTADMIN`, for whichever objects are affected:

```sql
USE ROLE ACCOUNTADMIN;
GRANT OWNERSHIP ON ALL TABLES IN SCHEMA LABOR_MARKET.RAW TO ROLE SYSADMIN COPY CURRENT GRANTS;
GRANT OWNERSHIP ON FUTURE TABLES IN SCHEMA LABOR_MARKET.RAW TO ROLE SYSADMIN COPY CURRENT GRANTS;
GRANT OWNERSHIP ON ALL TABLES IN SCHEMA LABOR_MARKET.CORTEX TO ROLE SYSADMIN COPY CURRENT GRANTS;
GRANT OWNERSHIP ON FUTURE TABLES IN SCHEMA LABOR_MARKET.CORTEX TO ROLE SYSADMIN COPY CURRENT GRANTS;
GRANT OWNERSHIP ON WAREHOUSE LABOR_WH TO ROLE SYSADMIN COPY CURRENT GRANTS;
```

The same applies to the Cortex Search service (`cortex_search_service` in `dagster_project/assets/dbt_assets.py` runs `CREATE OR REPLACE CORTEX SEARCH SERVICE` directly, outside dbt) — if it was ever created under a different role, `COPY CURRENT GRANTS` ownership transfer isn't guaranteed to carry over cleanly for search services, so the simplest fix is to drop it and let the next run recreate it fresh under SYSADMIN:

```sql
USE ROLE ACCOUNTADMIN;
DROP CORTEX SEARCH SERVICE IF EXISTS LABOR_MARKET.CORTEX.HEADLINE_SEARCH;
```

## dbt objects end up in a `CORTEX_CORTEX` schema instead of `CORTEX`

`dbt/profiles.yml` sets the target `schema: CORTEX`. If `dbt/dbt_project.yml` *also* sets `+schema: CORTEX` per model, dbt's default `generate_schema_name` macro concatenates default + custom schema names into `CORTEX_CORTEX`. `dbt_project.yml` no longer sets a per-model `+schema` for this reason — the target schema from `profiles.yml` is sufficient. If you see a `CORTEX_CORTEX` schema in Snowflake, it's dead weight from before this fix and safe to drop.

## dbt/Dagster connection needs a temporary MFA bypass (`ALTER USER ... SET MINS_TO_BYPASS_MFA`)

Programmatic access tokens are designed to bypass MFA entirely — there's no documented link between MFA and PAT authentication. If dagster/dbt connections only work right after an MFA bypass, MFA likely isn't the actual gate. More likely: your Snowflake user has no **network policy** attached — human (`TYPE=PERSON`) users can *generate* a PAT without one, but need one attached to *authenticate* with it. As `ACCOUNTADMIN`, check:

```sql
SHOW NETWORK POLICIES;
DESC USER <your_user>;             -- look for NETWORK_POLICY
SHOW AUTHENTICATION POLICIES;      -- if one exists, confirm PROGRAMMATIC_ACCESS_TOKEN is in AUTHENTICATION_METHODS
```

Attaching a network policy (even a permissive one, for personal/trial use) is a one-time fix instead of a recurring bypass.
