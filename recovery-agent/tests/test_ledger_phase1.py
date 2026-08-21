"""
tests/test_ledger_phase1.py — Phase 1 exit checks.

Senior teaching:
- These three asserts ARE the Phase 1 definition of done from BUILD_TECH:
  1) Insert a fake RiskEvent
  2) Read it back as ledger rows
  3) Duplicate event_id does not create two cases

Run from recovery-agent/:
  py -3 -m pytest -q
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ledger.db import Base
from ledger.schemas import EventSource, LedgerKind, PayerContext, Rail, RiskEvent
from ledger.service import get_case_trail, ingest_risk_event


@pytest.fixture()
def session() -> Session:
    """
    Fresh in-memory SQLite DB for every test.

    Why memory?
    - Fast
    - Isolated (no leftover recovery.db pollution)
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    # Create tables for this temporary engine.
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


def make_event(event_id: str = "evt_test_001") -> RiskEvent:
    """Helper: one valid RiskEvent for tests (card expired example)."""
    return RiskEvent(
        event_id=event_id,
        source=EventSource.simulator,
        occurred_at=datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc),
        merchant_id="merch_demo",
        payer_ref="payer_9c2",
        subscription_id="sub_abc",
        mandate_id="mandate_abc",
        payment_ref=None,
        amount_paise=49900,  # INR 499.00
        currency="INR",
        rail=Rail.card,
        raw_error_code="BAD_REQUEST_ERROR",
        raw_error_reason="card_expired",
        attempt_number=1,
        payer_context=PayerContext(tenure_days=120, prior_failures=0),
    )


def test_ingest_writes_case_and_ledger(session: Session) -> None:
    """Exit check 1+2: insert RiskEvent, read ledger trail back."""
    event = make_event("evt_unique_1")
    result = ingest_risk_event(session, event)
    session.commit()

    assert result.duplicate is False
    assert result.case_id.startswith("case_")
    assert result.ledger_seq is not None

    trail = get_case_trail(session, result.case_id)
    assert trail["case"] is not None
    assert trail["case"].payer_ref == "payer_9c2"
    assert trail["case"].amount_paise == 49900

    ledger = trail["ledger"]
    assert len(ledger) == 1
    assert ledger[0].kind == LedgerKind.event
    assert ledger[0].reason_code == "card_expired"
    # Payload should still carry the observed RiskEvent fields.
    assert ledger[0].payload["event_id"] == "evt_unique_1"
    assert ledger[0].payload["raw_error_reason"] == "card_expired"


def test_duplicate_event_id_is_idempotent(session: Session) -> None:
    """Exit check 3: same event_id must NOT open a second case."""
    event = make_event("evt_dup_1")

    first = ingest_risk_event(session, event)
    session.commit()

    second = ingest_risk_event(session, event)
    session.commit()

    assert first.duplicate is False
    assert second.duplicate is True
    assert second.case_id == first.case_id

    trail = get_case_trail(session, first.case_id)
    # Still only ONE ledger event row — we did not append again.
    assert len(trail["ledger"]) == 1


def test_risk_event_rejects_negative_amount() -> None:
    """Pydantic should protect us from nonsense money values."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RiskEvent(
            event_id="evt_bad_money",
            source=EventSource.simulator,
            occurred_at=datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc),
            merchant_id="merch_demo",
            payer_ref="payer_9c2",
            amount_paise=-1,  # invalid
            rail=Rail.card,
            raw_error_reason="card_expired",
        )
