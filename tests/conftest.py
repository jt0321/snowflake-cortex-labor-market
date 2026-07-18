# The ingestion scripts build their Snowflake config dict at import time from
# os.environ, so importing them in tests requires these to exist. Dummy values
# keep the offline test suite runnable without a .env (CI, fresh clones);
# setdefault means a real .env still wins when present.
import os

for var in ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_TOKEN"):
    os.environ.setdefault(var, "test-placeholder")
