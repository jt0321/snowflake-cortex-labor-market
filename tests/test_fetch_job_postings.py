"""
Offline tests for ingestion/fetch_job_postings.py.

Hiring Lab has renamed CSV columns across revisions, so _pick_columns and
_normalize are exercised against both the SA/NSA dual-column shape and a
single-index shape, plus the sector file. Run with:

    uv run pytest tests/test_fetch_job_postings.py -v
"""
import sys
import io
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ingestion"))

import fetch_job_postings as fjp


def test_pick_columns_prefers_seasonally_adjusted():
    df = pd.DataFrame({
        "date": ["2020-02-01"],
        "indeed_job_postings_index_NSA": [100.0],
        "indeed_job_postings_index_SA": [100.0],
    })
    date_col, value_col, sector_col = fjp._pick_columns(df)
    assert date_col == "date"
    assert value_col == "indeed_job_postings_index_SA"
    assert sector_col is None


def test_pick_columns_single_index_shape():
    df = pd.DataFrame({"date": ["2020-02-01"], "indeed_job_postings_index": [100.0]})
    _, value_col, _ = fjp._pick_columns(df)
    assert value_col == "indeed_job_postings_index"


def test_pick_columns_missing_date_raises():
    df = pd.DataFrame({"indeed_job_postings_index": [100.0]})
    with pytest.raises(RuntimeError, match="date"):
        fjp._pick_columns(df)


def test_normalize_aggregate_fixed_series():
    df = pd.DataFrame({
        "date": ["2020-02-01", "2020-02-02", "bad-date"],
        "indeed_job_postings_index_SA": [100.0, 101.5, 99.0],
    })
    out = fjp._normalize(df, fixed_series="US_TOTAL")
    assert list(out.columns) == ["series_id", "observation_date", "value"]
    assert len(out) == 2  # bad date row dropped
    assert set(out["series_id"]) == {"US_TOTAL"}
    assert out.iloc[1]["value"] == 101.5


def test_normalize_sector_file_uses_display_name():
    df = pd.DataFrame({
        "date": ["2020-02-01", "2020-02-01"],
        "display_name": ["Software Development", "Nursing"],
        "indeed_job_postings_index": [100.0, 100.0],
    })
    out = fjp._normalize(df, fixed_series=None)
    assert set(out["series_id"]) == {"SOFTWARE DEVELOPMENT", "NURSING"}


def test_normalize_sector_file_without_sector_column_raises():
    df = pd.DataFrame({"date": ["2020-02-01"], "indeed_job_postings_index": [100.0]})
    with pytest.raises(RuntimeError, match="sector"):
        fjp._normalize(df, fixed_series=None)


def test_fetch_csv_falls_back_across_branches(monkeypatch):
    calls = []

    class FakeResp:
        def __init__(self, ok):
            self.ok = ok
            self.text = "date,indeed_job_postings_index\n2020-02-01,100.0\n"

        def raise_for_status(self):
            if not self.ok:
                raise fjp.requests.HTTPError("404")

    def fake_get(url, timeout=None):
        calls.append(url)
        return FakeResp(ok="main" in url)  # master 404s, main succeeds

    monkeypatch.setattr(fjp.requests, "get", fake_get)
    df = fjp._fetch_csv(["US/aggregate_job_postings_US.csv"])
    assert len(calls) == 2 and "master" in calls[0] and "main" in calls[1]
    assert df.iloc[0]["indeed_job_postings_index"] == 100.0


def test_load_to_snowflake_bulk_merges_on_series_and_date():
    """~200K rows: must bulk-stage (executemany) and dedup with one MERGE
    keyed on (series_id, observation_date) — never per-row round-trips."""
    import inspect
    src = inspect.getsource(fjp.load_to_snowflake)
    assert "executemany" in src
    assert "MERGE INTO RAW_JOB_POSTINGS" in src
    assert "t.series_id = s.series_id" in src
    assert "t.observation_date = s.observation_date" in src
    # the old per-row guard must be gone from the executed SQL (the docstring
    # may still mention the pattern by name)
    assert "SELECT 1 FROM RAW_JOB_POSTINGS" not in src


def test_load_to_snowflake_stages_native_python_types():
    """The connector can't bind numpy scalars — staged rows must be
    plain str/date/float."""

    class RecordingCursor:
        def __init__(self):
            self.staged = []

        def execute(self, sql, *a):
            self.rowcount = 42
            return self

        def executemany(self, sql, rows):
            self.staged.extend(rows)

        def close(self):
            pass

    class FakeConn:
        def __init__(self):
            self._cursor = RecordingCursor()

        def cursor(self):
            return self._cursor

    import datetime
    df = pd.DataFrame({
        "series_id": ["US_TOTAL"],
        "observation_date": [datetime.date(2020, 2, 1)],
        "value": pd.to_numeric(pd.Series(["101.5"])),  # numpy float64
    })
    conn = FakeConn()
    inserted = fjp.load_to_snowflake(df, conn)
    assert inserted == 42
    (sid, obs, val), = conn._cursor.staged
    assert type(sid) is str and type(val) is float
    assert type(obs) is datetime.date
