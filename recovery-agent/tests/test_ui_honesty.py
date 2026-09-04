"""
tests/test_ui_honesty.py — the UI must never show a number it did not compute.

`api/ui_mock.evaluate_ui_context` used to return a hardcoded snapshot of a real
seed-42 run (advantage 107137, ours 489604, baseline 382467) and hand it to the
templates whenever the database had no stored run. The values were real once,
which made it worse: a reader had no way to tell a measured figure from a
remembered one.

These tests pin the contract: with no stored run, no rupee value renders.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("APP_ENV", "dev")

from api.ui_mock import evaluate_ui_context  # noqa: E402
from eval.run_store import EvalRunStore  # noqa: E402
from main import app  # noqa: E402

# The exact figures that used to be hardcoded.
STALE_SNAPSHOT = [b"107,137", b"489,604", b"382,467", b"74.7", b"59.8"]

MONEY_FIELDS = [
    "ours_inr",
    "baseline_inr",
    "advantage_inr",
    "recovery_rate_ours",
    "recovery_rate_baseline",
    "cost_per_rupee_ours",
    "cost_per_rupee_baseline",
    "wasted_ours",
    "wasted_baseline",
    "gate_blocks_ours",
    "gate_blocks_baseline",
    "n_cases",
]


@pytest.fixture(autouse=True)
def _empty_run_store(tmp_path, monkeypatch):
    """Point the eval store at an empty directory — simulates a clean clone."""
    d = tmp_path / "eval_runs"
    d.mkdir()
    monkeypatch.setenv("EVAL_RUN_DIR", str(d))
    import eval.run_store as rs

    rs._STORE = EvalRunStore(directory=d)
    yield


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_context_has_no_numbers_without_a_run():
    ctx = evaluate_ui_context()
    assert ctx["has_run"] is False
    for field in MONEY_FIELDS:
        assert ctx[field] is None, f"{field} must be None with no stored run"
    assert ctx["run_history"] == []


def test_stats_page_shows_empty_state_not_stale_numbers(client: TestClient):
    page = client.get("/ui")
    assert page.status_code == 200
    assert b"No evaluation run stored yet" in page.content
    for stale in STALE_SNAPSHOT:
        assert stale not in page.content, f"stale hardcoded value {stale!r} rendered"


def test_stats_page_shows_real_numbers_after_a_run(client: TestClient):
    run = client.post("/eval/run", json={"seed": 42, "n": 40})
    assert run.status_code == 200

    page = client.get("/ui")
    assert page.status_code == 200
    assert b"No evaluation run stored yet" not in page.content
    # Provenance must be on screen next to the money.
    assert b"seeded simulation" in page.content
    assert b"LIMITATIONS.md" in page.content


def test_context_reports_measured_values_after_a_run(client: TestClient):
    client.post("/eval/run", json={"seed": 42, "n": 40})
    from api.ui_mock import _run_history_rows

    history = _run_history_rows()
    assert len(history) == 1
    assert history[0]["seed"] == 42
    assert history[0]["n"] == 40


@pytest.mark.parametrize(
    "path",
    [
        "/ui/cases",
        "/ui/intelligence",
        "/ui/intelligence/strategies",
        "/ui/intelligence/historical",
    ],
)
def test_illustrative_screens_are_labelled(client: TestClient, path: str):
    """Mock-driven product screens must say so, on the page."""
    page = client.get(path)
    assert page.status_code == 200
    assert b"Illustrative data" in page.content
