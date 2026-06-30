"""
Offline tests for ingestion/fetch_polymarket.py parsing logic.

These don't hit the network — they exercise _parse_listlike, filter_by_keyword,
and markets_to_df against sample payloads shaped like Polymarket's documented
Gamma API response, including both the stringified-JSON and native-list forms
the API has used historically. Run with:

    uv run pytest tests/test_fetch_polymarket.py -v
"""
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ingestion"))

import fetch_polymarket as fp


# ── _parse_listlike ──────────────────────────────────────────────────────

def test_parse_listlike_stringified_json():
    assert fp._parse_listlike('["Yes", "No"]') == ["Yes", "No"]


def test_parse_listlike_native_list():
    assert fp._parse_listlike(["Yes", "No"]) == ["Yes", "No"]


def test_parse_listlike_none():
    assert fp._parse_listlike(None) == []


def test_parse_listlike_malformed_json():
    assert fp._parse_listlike("not json") == []


def test_parse_listlike_empty_string():
    assert fp._parse_listlike("") == []


# ── filter_by_keyword ─────────────────────────────────────────────────────

def test_filter_by_keyword_matches_case_insensitive():
    markets = [
        {"question": "Will the US enter a RECESSION in 2026?"},
        {"question": "Will the Lakers win the championship?"},
        {"question": "OpenAI IPO before end of 2026?"},
    ]
    matched = fp.filter_by_keyword(markets)
    assert len(matched) == 2
    questions = [m["question"] for m in matched]
    assert "Will the Lakers win the championship?" not in questions


def test_filter_by_keyword_no_question_field():
    markets = [{"id": "123"}]  # missing 'question' key entirely
    assert fp.filter_by_keyword(markets) == []


# ── markets_to_df ─────────────────────────────────────────────────────────

def test_markets_to_df_binary_market_stringified():
    markets = [
        {
            "id": "0x1",
            "question": "Will the US enter a recession in 2026?",
            "outcomes": '["Yes", "No"]',
            "outcomePrices": '["0.23", "0.77"]',
            "volume": "150000.5",
            "liquidity": "42000",
            "endDate": "2026-12-31T00:00:00Z",
        }
    ]
    df = fp.markets_to_df(markets)
    assert len(df) == 2
    assert set(df["outcome"]) == {"Yes", "No"}
    yes_row = df[df["outcome"] == "Yes"].iloc[0]
    assert yes_row["probability"] == 0.23
    assert yes_row["market_id"] == "0x1"
    assert yes_row["end_date"] == "2026-12-31"
    assert yes_row["volume"] == 150000.5
    assert yes_row["snapshot_date"] == datetime.now(timezone.utc).strftime("%Y-%m-%d")


def test_markets_to_df_native_list_form():
    markets = [
        {
            "id": "0x2",
            "question": "AI jobs displacement above threshold by Q4?",
            "outcomes": ["Yes", "No"],
            "outcomePrices": [0.41, 0.59],
            "volume": 1000,
            "liquidity": 500,
            "endDate": None,
        }
    ]
    df = fp.markets_to_df(markets)
    assert len(df) == 2
    assert df[df["outcome"] == "Yes"].iloc[0]["probability"] == 0.41
    assert df.iloc[0]["end_date"] is None


def test_markets_to_df_skips_mismatched_outcomes_and_prices():
    markets = [
        {
            "id": "0x3",
            "question": "Recession in 2026?",
            "outcomes": '["Yes", "No", "Maybe"]',
            "outcomePrices": '["0.5", "0.5"]',  # length mismatch
            "volume": "10",
            "liquidity": "10",
            "endDate": "2026-01-01T00:00:00Z",
        }
    ]
    df = fp.markets_to_df(markets)
    assert df.empty


def test_markets_to_df_skips_non_numeric_price():
    markets = [
        {
            "id": "0x4",
            "question": "Unemployment above 5% by EOY?",
            "outcomes": '["Yes", "No"]',
            "outcomePrices": '["N/A", "0.6"]',
            "volume": "10",
            "liquidity": "10",
            "endDate": "2026-01-01T00:00:00Z",
        }
    ]
    df = fp.markets_to_df(markets)
    # only the valid "No" row should survive
    assert len(df) == 1
    assert df.iloc[0]["outcome"] == "No"


def test_markets_to_df_empty_input():
    df = fp.markets_to_df([])
    assert df.empty


# ── load_to_snowflake dedup SQL shape ──────────────────────────────────────

def test_load_to_snowflake_dedup_key_columns():
    """The INSERT...WHERE NOT EXISTS guard must key on
    (market_id, outcome, snapshot_date) — not just market_id — since each
    market yields multiple outcome rows per snapshot."""
    import inspect
    src = inspect.getsource(fp.load_to_snowflake)
    assert "market_id = %s" in src
    assert "outcome = %s" in src
    assert "snapshot_date = %s" in src
