"""
writer.py — append facts; never rewrite history.

Teaching:
- All "something happened" writes go through helpers here.
- Callers should not invent ad-hoc SQL inserts for ledger rows.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from ledger.models import CaseRow, LedgerEntryRow, ProcessedEventRow, utcnow
from ledger.schemas import (
    CaseStatus,
    GateResult,
    LedgerActor,
    LedgerKind,
    RiskEvent,
)


def new_case_id() -> str:
    """Human-readable-ish id for demos and logs."""
    return f"case_{uuid4().hex[:12]}"


def append_ledger(
    session: Session,
    *,
    case_id: str,
    kind: LedgerKind,
    actor: LedgerActor,
    payload: dict[str, Any],
    reason_code: str = "",
    policy_version: str = "unset",
    gate_name: Optional[str] = None,
    gate_result: Optional[GateResult] = None,
    at: Optional[datetime] = None,
) -> LedgerEntryRow:
    """
    Append one immutable fact.

    payload is stored as JSON text so SQLite stays simple.
    """
    row = LedgerEntryRow(
        case_id=case_id,
        at=at or utcnow(),
        kind=kind.value,
        actor=actor.value,
        policy_version=policy_version,
        payload_json=json.dumps(payload, default=str),
        reason_code=reason_code,
        gate_name=gate_name,
        gate_result=gate_result.value if gate_result else None,
    )
    session.add(row)
    session.flush()  # assign seq without committing yet
    return row


def get_or_create_case_for_event(session: Session, event: RiskEvent) -> CaseRow:
    """
    Open a Case for this failure.

    Phase-1 policy (simple + teachable):
    - One new Case per first-seen event_id path.
    - Later phases may attach retries to an existing open case by mandate/sub id.
      For now, idempotency is handled by processed_events, not by merging cases.
    """
    case = CaseRow(
        id=new_case_id(),
        status=CaseStatus.open.value,
        payer_ref=event.payer_ref,
        amount_paise=event.amount_paise,
        rail=event.rail.value,
        subscription_id=event.subscription_id,
        mandate_id=event.mandate_id,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(case)
    session.flush()
    return case


def mark_event_processed(session: Session, event_id: str, case_id: str) -> ProcessedEventRow:
    """Record that this event_id has been handled."""
    row = ProcessedEventRow(
        event_id=event_id,
        case_id=case_id,
        received_at=utcnow(),
    )
    session.add(row)
    session.flush()
    return row


def find_processed(session: Session, event_id: str) -> Optional[ProcessedEventRow]:
    """Return existing processed row, or None."""
    return session.get(ProcessedEventRow, event_id)


def risk_event_payload(event: RiskEvent) -> dict[str, Any]:
    """
    Serialize RiskEvent into JSON-friendly dict for ledger payload.

    mode='json' ensures datetime -> ISO string, enums -> values.
    """
    return event.model_dump(mode="json")
