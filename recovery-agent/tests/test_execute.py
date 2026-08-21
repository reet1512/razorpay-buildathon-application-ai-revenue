"""
tests/test_execute.py — Phase 7 sim + Razorpay + reconcile + gate wiring.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from execute.base import ExecuteMeta
from execute.razorpay_adapter import RazorpayExecutor
from execute.reconcile import already_succeeded
from execute.service import execute_with_guards
from execute.sim_adapter import SimExecutor
from guard.context import GuardContext
from ledger.db import Base
from ledger.models import CaseRow
from ledger.schemas import CaseStatus, EventSource, PayerContext, Rail, RiskEvent
from ledger.service import ingest_risk_event
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


def _case(session: Session, reason: str = "insufficient_funds") -> CaseRow:
    ev = RiskEvent(
        event_id=f"evt_exec_{reason}",
        source=EventSource.simulator,
        occurred_at=datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc),
        merchant_id="m",
        payer_ref="p",
        amount_paise=49900,
        rail=Rail.card,
        raw_error_reason=reason,
        payer_context=PayerContext(),
    )
    r = ingest_risk_event(session, ev)
    session.commit()
    case = session.get(CaseRow, r.case_id)
    assert case is not None
    return case


def test_sim_nsf_retry_near_salary_often_recovers():
    """Sim path recovers some NSF cases when day_offset hits credit window."""
    ex = SimExecutor()
    case = CaseRow(
        id="case_sim_nsf",
        payer_ref="p",
        amount_paise=49900,
        rail="card",
        status="open",
    )
    action = Action(
        verb=ActionVerb.schedule_retry,
        day_offset=0,
        reason_code="RETRY",
    )
    # failure_dom=1, credit_day=1 → funded on offset 0
    meta = ExecuteMeta(
        failure_reason="insufficient_funds",
        failure_dom=1,
        observed_credit_day=1,
        seed="nsf_ok",
    )
    wins = sum(
        1
        for i in range(40)
        for out in [
            ex.run(
                action,
                case,
                meta.model_copy(update={"seed": f"nsf_ok_{i}"}),
            )
        ]
        if out.recovered
    )
    assert wins >= 20  # ~85% expected


def test_sim_dead_instrument_retry_fails_link_can_work():
    ex = SimExecutor()
    case = CaseRow(
        id="case_dead",
        payer_ref="p",
        amount_paise=100,
        rail="card",
        status="open",
    )
    meta = ExecuteMeta(failure_reason="card_expired", seed="dead")
    retry = ex.run(
        Action(verb=ActionVerb.schedule_retry, day_offset=1),
        case,
        meta,
    )
    assert retry.recovered is False
    assert retry.ok is False

    link_wins = sum(
        1
        for i in range(50)
        if ex.run(
            Action(verb=ActionVerb.send_payment_link, channel=Channel.link),
            case,
            ExecuteMeta(failure_reason="card_expired", seed=f"link_{i}"),
        ).recovered
    )
    assert link_wins >= 5  # ~40% expected over 50


def test_razorpay_dry_run_creates_plink_id():
    ex = RazorpayExecutor(key_id="rzp_test_xxx", key_secret="xxx")
    case = CaseRow(
        id="case_rzp",
        payer_ref="p",
        amount_paise=49900,
        rail="card",
        status="open",
    )
    out = ex.run(
        Action(
            verb=ActionVerb.send_payment_link,
            channel=Channel.link,
            amount_paise=49900,
        ),
        case,
        ExecuteMeta(failure_reason="card_expired", dry_run=True),
    )
    assert out.ok is True
    assert out.external_id and out.external_id.startswith("plink_test_")
    assert out.status == "created_link"


def test_razorpay_http_creates_real_shaped_plink():
    mock = MagicMock()
    mock.post.return_value.status_code = 200
    mock.post.return_value.json.return_value = {
        "id": "plink_abc123",
        "short_url": "https://rzp.io/i/abc",
        "status": "created",
    }
    ex = RazorpayExecutor(
        key_id="rzp_test_real",
        key_secret="secret",
        client=mock,
    )
    # Force non-dry-run path
    ex.dry_run = False
    case = CaseRow(
        id="case_http",
        payer_ref="p",
        amount_paise=10000,
        rail="card",
        status="open",
    )
    out = ex.run(
        Action(verb=ActionVerb.send_payment_link, channel=Channel.link),
        case,
        ExecuteMeta(failure_reason="card_expired"),
    )
    assert out.ok is True
    assert out.external_id == "plink_abc123"
    mock.post.assert_called_once()
    args, kwargs = mock.post.call_args
    assert args[0].endswith("/payment_links")
    assert kwargs["auth"] == ("rzp_test_real", "secret")


def test_reconcile_skips_retry_when_already_captured():
    mock = MagicMock()
    mock.get.return_value.status_code = 200
    mock.get.return_value.json.return_value = {
        "id": "pay_already",
        "status": "captured",
    }
    mock.get.return_value.raise_for_status = MagicMock()
    ex = RazorpayExecutor(
        key_id="rzp_test_real",
        key_secret="secret",
        client=mock,
    )
    ex.dry_run = False
    case = CaseRow(
        id="case_recon",
        payer_ref="p",
        amount_paise=100,
        rail="card",
        status="open",
    )
    out = ex.run(
        Action(verb=ActionVerb.schedule_retry, day_offset=1),
        case,
        ExecuteMeta(
            failure_reason="gateway_timeout",
            payment_ref="pay_already",
        ),
    )
    assert out.status == "reconciled_skip"
    assert out.recovered is True
    mock.get.assert_called_once()
    mock.post.assert_not_called()


def test_already_succeeded_helper():
    assert already_succeeded({"status": "captured"})
    assert already_succeeded({"status": "authorized"})
    assert not already_succeeded({"status": "failed"})


def test_gate_block_never_calls_adapter(session: Session):
    case = _case(session)
    # Outside IST contact window
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
    result, outcome = execute_with_guards(
        session,
        case,
        ctx,
        meta=ExecuteMeta(failure_reason="card_expired"),
        mode="sim",
    )
    session.commit()
    assert result.allowed is False
    assert result.executed is False
    assert outcome is None
    assert result.blocked_by == "contact_window"


def test_allowed_execute_writes_outcome_and_can_recover(session: Session):
    case = _case(session, "insufficient_funds")
    # Non-contact verb — window gate does not apply
    action = Action(
        verb=ActionVerb.schedule_retry,
        day_offset=0,
        reason_code="RETRY_NSF",
    )
    ctx = GuardContext(
        case_id=case.id,
        action=action,
        now=datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc),
        case_status=CaseStatus.open,
    )
    result, outcome = execute_with_guards(
        session,
        case,
        ctx,
        meta=ExecuteMeta(
            failure_reason="insufficient_funds",
            failure_dom=1,
            observed_credit_day=1,
            seed="recover_me",
        ),
        mode="sim",
    )
    session.commit()
    assert result.allowed is True
    assert result.executed is True
    assert outcome is not None
    assert outcome.external_id
    session.refresh(case)
    if outcome.recovered:
        assert case.status == CaseStatus.recovered.value
    else:
        assert case.attempts_used == 1
