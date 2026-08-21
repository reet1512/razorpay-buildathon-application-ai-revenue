"""
service.py — Phase 1 use-case: ingest a RiskEvent idempotently.

This is the function later phases will call after normalise():
  webhook/sim JSON -> RiskEvent -> ingest_risk_event()

Flow (from BUILD_TECH):
  JSON -> Pydantic RiskEvent
       -> if event_id seen: return duplicate (no second case)
       -> else create Case + ledger(event) + processed_events
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ledger import reader, writer
from ledger.schemas import IngestResult, LedgerActor, LedgerKind, RiskEvent


def ingest_risk_event(session: Session, event: RiskEvent) -> IngestResult:
    """
    Persist one RiskEvent exactly once.

    Returns:
      IngestResult.duplicate = True  -> already processed; safe no-op
      IngestResult.duplicate = False -> new case + first ledger row created

    Caller is responsible for session.commit() (or rollback on error).
    Why? So API handlers can group multiple writes in one transaction later.
    """
    # 1) IDEMPOTENCY GATE (payments golden rule)
    existing = writer.find_processed(session, event.event_id)
    if existing is not None:
        return IngestResult(
            case_id=existing.case_id,
            event_id=event.event_id,
            duplicate=True,
            ledger_seq=None,
        )

    # 2) Open a case for this first-seen failure
    case = writer.get_or_create_case_for_event(session, event)

    # 3) Append observed truth to the audit diary
    entry = writer.append_ledger(
        session,
        case_id=case.id,
        kind=LedgerKind.event,
        actor=LedgerActor.system,
        payload=writer.risk_event_payload(event),
        reason_code=event.raw_error_reason,
        policy_version="phase1",
        at=event.occurred_at,
    )

    # 4) Remember we handled this event_id
    writer.mark_event_processed(session, event.event_id, case.id)

    return IngestResult(
        case_id=case.id,
        event_id=event.event_id,
        duplicate=False,
        ledger_seq=entry.seq,
    )


def get_case_trail(session: Session, case_id: str) -> dict:
    """
    Convenience for tests / future API:
    case snapshot + ordered ledger rows.
    """
    row = reader.get_case(session, case_id)
    if row is None:
        return {"case": None, "ledger": []}
    return {
        "case": reader.case_to_view(row),
        "ledger": reader.list_ledger(session, case_id),
    }
