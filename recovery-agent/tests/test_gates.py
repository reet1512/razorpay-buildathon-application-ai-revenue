"""
tests/test_gates.py — adversarial gate tests (Phase 6).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from guard.context import GuardContext
from guard.gates import gate_contact_window, run_gates, all_passed
from guard.pipeline import guard_and_maybe_execute
from ledger.db import Base
from ledger.models import CaseRow
from ledger.schemas import CaseStatus, EventSource, LedgerKind, MandateState, PayerContext, Rail, RiskEvent
from ledger.service import get_case_trail, ingest_risk_event
from policy.schemas import Action, ActionVerb, Channel, ProposedBy


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield db
    finally:
        db.close()


def _case(session: Session) -> CaseRow:
    ev = RiskEvent(
        event_id="evt_gate_1",
        source=EventSource.simulator,
        occurred_at=datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc),
        merchant_id="m",
        payer_ref="p",
        amount_paise=49900,
        rail=Rail.card,
        raw_error_reason="card_expired",
        payer_context=PayerContext(),
    )
    r = ingest_risk_event(session, ev)
    session.commit()
    case = session.get(CaseRow, r.case_id)
    assert case is not None
    return case


def test_contact_outside_window_blocks_and_no_execute(session: Session):
    case = _case(session)
    # 18:30 UTC = 00:00 IST next day -> outside 09-21 IST
    now = datetime(2026, 8, 21, 18, 30, tzinfo=timezone.utc)
    action = Action(
        verb=ActionVerb.send_payment_link,
        channel=Channel.link,
        proposed_by=ProposedBy.llm,
        reason_code="AI_LINK",
    )
    ctx = GuardContext(
        case_id=case.id,
        action=action,
        now=now,
        case_status=CaseStatus.open,
    )

    calls: list[str] = []

    def execute_fn(a, c):
        calls.append(a.verb.value)
        return {"ok": True}

    result = guard_and_maybe_execute(session, case, ctx, execute_fn=execute_fn)
    session.commit()

    assert result.allowed is False
    assert result.blocked_by == "contact_window"
    assert result.executed is False
    assert calls == []

    trail = get_case_trail(session, case.id)
    gate_rows = [e for e in trail["ledger"] if e.kind == LedgerKind.gate_check]
    assert gate_rows, "gate checks must be written to ledger"
    assert any(e.gate_result and e.gate_result.value == "block" for e in gate_rows)


def test_window_gate_allows_silent_retry_at_night():
    now = datetime(2026, 8, 21, 18, 30, tzinfo=timezone.utc)
    ctx = GuardContext(
        case_id="c1",
        action=Action(verb=ActionVerb.schedule_retry, channel=Channel.none),
        now=now,
    )
    check = gate_contact_window(ctx)
    assert check.passed is True


def test_attempt_cap_blocks(session: Session):
    case = _case(session)
    ctx = GuardContext(
        case_id=case.id,
        action=Action(verb=ActionVerb.schedule_retry),
        attempts_used=3,
        max_attempts=3,
        now=datetime(2026, 8, 21, 5, 0, tzinfo=timezone.utc),  # within IST window if contact
    )
    result = guard_and_maybe_execute(session, case, ctx, execute_fn=lambda a, c: {"ok": True})
    assert result.allowed is False
    assert result.blocked_by == "attempt_cap"


def test_mandate_revoked_blocks_money(session: Session):
    case = _case(session)
    ctx = GuardContext(
        case_id=case.id,
        action=Action(verb=ActionVerb.schedule_retry),
        mandate_state=MandateState.revoked,
        now=datetime(2026, 8, 21, 5, 0, tzinfo=timezone.utc),
    )
    result = guard_and_maybe_execute(session, case, ctx, execute_fn=lambda a, c: {"ok": True})
    assert result.allowed is False
    assert result.blocked_by == "mandate_validity"


def test_idempotency_blocks_second_execute(session: Session):
    case = _case(session)
    action = Action(verb=ActionVerb.schedule_retry, reason_code="R1", day_offset=0)
    now = datetime(2026, 8, 21, 5, 0, tzinfo=timezone.utc)
    ctx1 = GuardContext(case_id=case.id, action=action, now=now)
    r1 = guard_and_maybe_execute(
        session, case, ctx1, execute_fn=lambda a, c: {"ok": True}
    )
    assert r1.allowed and r1.executed

    ctx2 = GuardContext(
        case_id=case.id,
        action=action,
        now=now,
        executed_fingerprints=set(ctx1.executed_fingerprints),
    )
    r2 = guard_and_maybe_execute(
        session, case, ctx2, execute_fn=lambda a, c: {"ok": True}
    )
    assert r2.allowed is False
    assert r2.blocked_by == "idempotency"
