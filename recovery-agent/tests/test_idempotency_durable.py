"""
tests/test_idempotency_durable.py — action idempotency survives separate requests.

Before this, `GuardContext.executed_fingerprints` was an in-memory set and every
HTTP request built a fresh context, so posting the same action twice executed it
twice. The fingerprint set is now rebuilt from the append-only ledger, so these
tests exercise the thing that actually matters in a payments system: the second
identical call must be refused, and the refusal must be visible in the trail.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("APP_ENV", "dev")

from ledger import reader  # noqa: E402
from ledger.db import SessionLocal  # noqa: E402
from ledger.models import CaseRow  # noqa: E402
from ledger.schemas import CaseStatus  # noqa: E402
from main import app  # noqa: E402


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _reopen(case_id: str) -> None:
    """
    Force the case back to `open`.

    The sim executor recovers a case stochastically, and a recovered case is
    short-circuited by `is_case_stopped` before gates ever run. That is correct
    behaviour but it is a *different* protection, and letting it fire here would
    make these tests pass for the wrong reason (and flake, since recovery is
    random). Reopening isolates the idempotency gate as the thing under test.
    """
    session = SessionLocal()
    try:
        case = session.get(CaseRow, case_id)
        assert case is not None
        case.status = CaseStatus.open.value
        case.stop_reason = None
        session.add(case)
        session.commit()
    finally:
        session.close()


def _run(client: TestClient, **overrides) -> dict:
    body = {
        "raw_error_reason": "insufficient_funds",
        "verb": "schedule_retry",
        "mode": "sim",
        "amount_paise": 49900,
        "day_offset": 0,
    }
    body.update(overrides)
    r = client.post("/execute/run", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_first_execution_is_allowed(client: TestClient):
    first = _run(client)
    assert first["allowed"] is True
    assert first["executed"] is True


def test_duplicate_action_on_same_case_is_blocked(client: TestClient):
    """The whole point: a second identical request must not execute again."""
    first = _run(client)
    case_id = first["case_id"]
    assert first["executed"] is True
    _reopen(case_id)

    second = _run(client, case_id=case_id)
    assert second["allowed"] is False
    assert second["blocked_by"] == "idempotency"
    assert second["executed"] is False


def test_duplicate_block_is_recorded_in_ledger(client: TestClient):
    first = _run(client)
    case_id = first["case_id"]
    _reopen(case_id)
    _run(client, case_id=case_id)

    entries = client.get(f"/cases/{case_id}").json()["ledger"]
    idem = [
        e
        for e in entries
        if e.get("gate_name") == "idempotency" and e.get("gate_result") == "block"
    ]
    assert idem, "expected a blocked idempotency gate_check row in the trail"

    # Exactly one action actually executed.
    actions = [e for e in entries if e.get("kind") == "action"]
    assert len(actions) == 1


def test_different_action_on_same_case_still_executes(client: TestClient):
    """Idempotency must block replays, not legitimate follow-up actions."""
    first = _run(client)
    case_id = first["case_id"]
    _reopen(case_id)

    # Different day_offset => different fingerprint => must not be blocked.
    other = _run(client, case_id=case_id, day_offset=2, max_attempts=5)
    assert other["blocked_by"] != "idempotency"
    assert other["executed"] is True


def test_fingerprints_rebuilt_from_ledger(client: TestClient):
    """The set must come from the DB, not from request-local state."""
    first = _run(client)
    case_id = first["case_id"]

    session = SessionLocal()
    try:
        fps = reader.executed_fingerprints(session, case_id)
    finally:
        session.close()

    # Composition is case_id:verb:day_offset:channel:reason_code — the live gate
    # and the ledger replay must agree byte for byte or dedup silently fails.
    assert fps == {f"{case_id}:schedule_retry:0:none:EXECUTE_DEMO"}


def test_empty_case_has_no_fingerprints():
    session = SessionLocal()
    try:
        assert reader.executed_fingerprints(session, "case_does_not_exist") == set()
    finally:
        session.close()
