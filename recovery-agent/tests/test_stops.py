"""
tests/test_stops.py — adversarial stop tests (Phase 6).

After a stop, further guard/execute attempts must do nothing.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from guard.context import GuardContext
from guard.pipeline import guard_and_maybe_execute
from guard.stops import StopReason, apply_stop, evaluate_stop_signals, is_case_stopped
from ledger.db import Base
from ledger.models import CaseRow
from ledger.schemas import (
    CaseStatus,
    EventSource,
    LedgerKind,
    MandateState,
    PayerContext,
    Rail,
    RiskEvent,
)
from ledger.service import get_case_trail, ingest_risk_event
from policy.schemas import Action, ActionVerb, Channel


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield db
    finally:
        db.close()


def _case(session: Session, event_id: str = "evt_stop_1") -> CaseRow:
    ev = RiskEvent(
        event_id=event_id,
        source=EventSource.simulator,
        occurred_at=datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc),
        merchant_id="m",
        payer_ref="p",
        amount_paise=49900,
        rail=Rail.card,
        raw_error_reason="insufficient_funds",
        payer_context=PayerContext(),
    )
    r = ingest_risk_event(session, ev)
    session.commit()
    case = session.get(CaseRow, r.case_id)
    assert case is not None
    return case


def test_apply_stop_writes_ledger_and_status(session: Session):
    case = _case(session)
    apply_stop(session, case, StopReason.recovered)
    session.commit()
    assert case.status == CaseStatus.recovered.value
    assert is_case_stopped(case)
    trail = get_case_trail(session, case.id)
    assert any(e.kind == LedgerKind.stop for e in trail["ledger"])


def test_post_stop_event_does_not_execute(session: Session):
    case = _case(session)
    apply_stop(session, case, StopReason.attempt_cap)
    session.commit()

    calls: list[str] = []

    def execute_fn(a, c):
        calls.append("executed")
        return {"ok": True}

    ctx = GuardContext(
        case_id=case.id,
        action=Action(verb=ActionVerb.schedule_retry),
        now=datetime(2026, 8, 21, 5, 0, tzinfo=timezone.utc),
        case_status=CaseStatus.stopped,
    )
    result = guard_and_maybe_execute(session, case, ctx, execute_fn=execute_fn)
    session.commit()

    assert result.skipped_because_stopped is True
    assert result.executed is False
    assert calls == []


def test_evaluate_stop_signals_mandate_revoked():
    d = evaluate_stop_signals(mandate_state=MandateState.revoked)
    assert d.should_stop and d.reason == StopReason.mandate_revoked


def test_opt_out_stops_and_blocks_execute(session: Session):
    case = _case(session, event_id="evt_opt")
    calls: list[str] = []
    ctx = GuardContext(
        case_id=case.id,
        action=Action(verb=ActionVerb.send_payment_link, channel=Channel.link),
        opt_out=True,
        now=datetime(2026, 8, 21, 5, 0, tzinfo=timezone.utc),
    )
    result = guard_and_maybe_execute(
        session,
        case,
        ctx,
        execute_fn=lambda a, c: calls.append("x") or {"ok": True},
    )
    session.commit()
    assert result.skipped_because_stopped
    assert case.status == CaseStatus.stopped.value
    assert calls == []
