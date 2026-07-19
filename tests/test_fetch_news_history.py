"""
Offline tests for ingestion/fetch_news_history.py.

These don't hit the network — they exercise month_windows, rows_to_df, and the
GDELT / Hacker News response parsing against sample payloads shaped like each
API's documented JSON, including the failure modes both are known for (GDELT
returning plain-text errors with HTTP 200, HN stories with no external URL).
Run with:

    uv run pytest tests/test_fetch_news_history.py -v
"""
import sys
import hashlib
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ingestion"))

import fetch_news_history as fnh


class FakeResponse:
    def __init__(self, payload=None, text="", status_code=200, headers=None):
        self._payload = payload
        self.text = text
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise fnh.requests.HTTPError(f"{self.status_code} error")

    def json(self):
        if self._payload is None:
            raise ValueError("not JSON")
        return self._payload


# ── month_windows ─────────────────────────────────────────────────────────

def test_month_windows_partial_first_and_last():
    wins = list(fnh.month_windows(datetime(2020, 1, 15), datetime(2020, 3, 10)))
    assert wins == [
        (datetime(2020, 1, 15), datetime(2020, 2, 1)),
        (datetime(2020, 2, 1), datetime(2020, 3, 1)),
        (datetime(2020, 3, 1), datetime(2020, 3, 10)),
    ]


def test_month_windows_year_rollover():
    wins = list(fnh.month_windows(datetime(2025, 12, 1), datetime(2026, 2, 1)))
    assert wins == [
        (datetime(2025, 12, 1), datetime(2026, 1, 1)),
        (datetime(2026, 1, 1), datetime(2026, 2, 1)),
    ]


def test_month_windows_empty_when_start_not_before_end():
    assert list(fnh.month_windows(datetime(2026, 1, 1), datetime(2026, 1, 1))) == []


# ── rows_to_df ────────────────────────────────────────────────────────────

def _row(article_id="a", published=datetime(2020, 3, 1)):
    return {
        "article_id": article_id, "source_name": "x", "author": "",
        "title": "t", "description": "", "url": "u",
        "published_at": published, "full_text": "t",
    }


def test_rows_to_df_dedups_and_drops_missing_dates():
    df = fnh.rows_to_df([_row("a"), _row("a"), _row("b", published=None)])
    assert list(df["article_id"]) == ["a"]
    # native datetime, not pandas Timestamp — required by the connector's binding
    assert type(df.iloc[0]["published_at"]) is datetime


def test_rows_to_df_empty_input_keeps_schema():
    df = fnh.rows_to_df([])
    assert df.empty
    assert list(df.columns) == [
        "article_id", "source_name", "author", "title",
        "description", "url", "published_at", "full_text",
    ]


# ── fetch_gdelt ───────────────────────────────────────────────────────────

GDELT_PAYLOAD = {
    "articles": [
        {
            "url": "https://example.com/layoffs",
            "title": "Tech layoffs mount",
            "seendate": "20200315T103000Z",
            "domain": "example.com",
        },
        # no title → skipped
        {"url": "https://example.com/na", "title": "", "seendate": "20200316T000000Z", "domain": "example.com"},
        # malformed seendate → skipped
        {"url": "https://example.com/bad", "title": "Bad date", "seendate": "March 2020", "domain": "example.com"},
    ]
}


def test_fetch_gdelt_parses_articles(monkeypatch):
    monkeypatch.setattr(fnh.requests, "get", lambda *a, **kw: FakeResponse(GDELT_PAYLOAD))
    rows = fnh.fetch_gdelt('"tech layoffs"', datetime(2020, 3, 1), datetime(2020, 4, 1))
    assert len(rows) == 1
    r = rows[0]
    assert r["article_id"] == hashlib.md5(b"https://example.com/layoffs").hexdigest()
    assert r["source_name"] == "example.com"
    assert r["full_text"] == "Tech layoffs mount"
    assert r["published_at"] == datetime(2020, 3, 15, 10, 30)


def test_fetch_gdelt_tolerates_non_json_response(monkeypatch):
    """GDELT returns plain-text error messages with HTTP 200 — must not raise."""
    monkeypatch.setattr(
        fnh.requests, "get",
        lambda *a, **kw: FakeResponse(payload=None, text="Timespan too short."),
    )
    assert fnh.fetch_gdelt("q", datetime(2020, 1, 1), datetime(2020, 2, 1)) == []


def test_fetch_gdelt_retries_429_then_succeeds(monkeypatch):
    """A 429 must be retried, not swallowed — a skipped window is silently
    lost backfill data."""
    responses = [FakeResponse(status_code=429), FakeResponse(GDELT_PAYLOAD)]
    sleeps = []
    monkeypatch.setattr(fnh.requests, "get", lambda *a, **kw: responses.pop(0))
    monkeypatch.setattr(fnh.time, "sleep", sleeps.append)
    rows = fnh.fetch_gdelt("q", datetime(2020, 3, 1), datetime(2020, 4, 1))
    assert len(rows) == 1
    assert len(sleeps) == 1 and sleeps[0] > 0


def test_fetch_gdelt_honors_retry_after_header(monkeypatch):
    responses = [FakeResponse(status_code=429, headers={"Retry-After": "17"}),
                 FakeResponse(GDELT_PAYLOAD)]
    sleeps = []
    monkeypatch.setattr(fnh.requests, "get", lambda *a, **kw: responses.pop(0))
    monkeypatch.setattr(fnh.time, "sleep", sleeps.append)
    fnh.fetch_gdelt("q", datetime(2020, 3, 1), datetime(2020, 4, 1))
    assert sleeps == [17]


def test_fetch_gdelt_raises_after_exhausting_retries(monkeypatch):
    import pytest
    monkeypatch.setattr(fnh.requests, "get", lambda *a, **kw: FakeResponse(status_code=429))
    monkeypatch.setattr(fnh.time, "sleep", lambda s: None)
    with pytest.raises(fnh.requests.HTTPError):
        fnh.fetch_gdelt("q", datetime(2020, 3, 1), datetime(2020, 4, 1))


def test_fetch_gdelt_sends_window_params(monkeypatch):
    captured = {}

    def fake_get(url, params=None, **kw):
        captured.update(params)
        return FakeResponse({"articles": []})

    monkeypatch.setattr(fnh.requests, "get", fake_get)
    fnh.fetch_gdelt("q", datetime(2020, 1, 1), datetime(2020, 2, 1))
    assert captured["startdatetime"] == "20200101000000"
    assert captured["enddatetime"] == "20200201000000"
    assert captured["mode"] == "ArtList"
    assert captured["maxrecords"] == 250


# ── fetch_hn ──────────────────────────────────────────────────────────────

def _hn_payload(hits, nb_pages=1):
    return {"hits": hits, "nbPages": nb_pages}


def test_fetch_hn_parses_stories_and_ask_hn_fallback(monkeypatch):
    hits = [
        {
            "objectID": "100", "title": "Big Tech layoffs", "url": "https://example.com/hn",
            "author": "pg", "created_at_i": 1583059200,
        },
        # Ask HN: no external URL → falls back to the HN item link
        {"objectID": "101", "title": "Ask HN: layoffs?", "url": None, "author": "u2", "created_at_i": 1583059300},
        # no title → skipped
        {"objectID": "102", "title": None, "url": "https://x.com", "author": "u3", "created_at_i": 1583059400},
    ]
    monkeypatch.setattr(fnh.requests, "get", lambda *a, **kw: FakeResponse(_hn_payload(hits)))
    rows = fnh.fetch_hn("layoffs", datetime(2020, 3, 1), datetime(2020, 4, 1))
    assert len(rows) == 2
    assert rows[0]["source_name"] == "Hacker News"
    assert rows[0]["author"] == "pg"
    assert rows[1]["url"] == "https://news.ycombinator.com/item?id=101"


def test_fetch_hn_paginates_until_nb_pages(monkeypatch):
    calls = []

    def fake_get(url, params=None, **kw):
        calls.append(params["page"])
        return FakeResponse(_hn_payload(
            [{"objectID": str(params["page"]), "title": f"story {params['page']}",
              "url": f"https://x.com/{params['page']}", "author": "a", "created_at_i": 1583059200}],
            nb_pages=2,
        ))

    monkeypatch.setattr(fnh.requests, "get", fake_get)
    rows = fnh.fetch_hn("layoffs", datetime(2020, 3, 1), datetime(2020, 4, 1))
    assert calls == [0, 1]
    assert len(rows) == 2


def test_fetch_hn_respects_max_pages(monkeypatch):
    calls = []

    def fake_get(url, params=None, **kw):
        calls.append(params["page"])
        return FakeResponse(_hn_payload([], nb_pages=50))

    monkeypatch.setattr(fnh.requests, "get", fake_get)
    fnh.fetch_hn("layoffs", datetime(2020, 3, 1), datetime(2020, 4, 1), max_pages=3)
    assert calls == [0, 1, 2]


# ── load_to_snowflake dedup SQL shape ─────────────────────────────────────

def test_load_to_snowflake_dedups_on_article_id():
    """Backfill and daily runs overlap with NewsAPI's corpus — the INSERT must
    guard on article_id (the shared URL hash) so cross-source reruns stay
    idempotent."""
    import inspect
    src = inspect.getsource(fnh.load_to_snowflake)
    assert "WHERE NOT EXISTS" in src
    assert "article_id = %s" in src
