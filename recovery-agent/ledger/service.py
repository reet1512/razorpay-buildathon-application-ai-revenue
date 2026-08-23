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

from guard.stops import StopReason, apply_stop
from ledger import reader, writer
from ledger.schemas import (
    IngestResult,
    LedgerActor,
    LedgerKind,
    PaymentLinkPaidEvent,
    PaymentLinkPaidResult,
    RiskEvent,
)


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


def handle_payment_link_paid(
    session: Session,
    paid: PaymentLinkPaidEvent,
) -> PaymentLinkPaidResult:
    """
    Close the live Razorpay loop: payment_link.paid -> RECOVERED + audit row.

    Idempotent on event_id. Resolves case via notes.case_id or plink lookup.
    """
    existing = writer.find_processed(session, paid.event_id)
    if existing is not None:
        case = reader.get_case(session, existing.case_id)
        return PaymentLinkPaidResult(
            case_id=existing.case_id,
            event_id=paid.event_id,
            duplicate=True,
            recovered=case is not None and case.status == "recovered",
            payment_link_id=paid.payment_link_id,
            payment_id=paid.payment_id,
            ledger_seq=None,
        )

    case_id = paid.case_id or reader.find_case_id_by_plink(session, paid.payment_link_id)
    if case_id is None:
        raise ValueError(
            f"no case found for payment link {paid.payment_link_id!r}; "
            "create a link from this app first so notes.case_id is set"
        )

    case = reader.get_case(session, case_id)
    if case is None:
        raise ValueError(f"case not found: {case_id}")

    event_payload = {
        "source": "razorpay_webhook",
        "razorpay_event": paid.event_name,
        "event_id": paid.event_id,
        "payment_link_id": paid.payment_link_id,
        "payment_id": paid.payment_id,
        "amount_paise": paid.amount_paise,
        "currency": paid.currency,
        "webhook": paid.raw,
    }
    event_row = writer.append_ledger(
        session,
        case_id=case.id,
        kind=LedgerKind.event,
        actor=LedgerActor.system,
        payload=event_payload,
        reason_code="payment_link.paid",
        policy_version="webhook-paid",
        at=paid.occurred_at,
    )

    already_recovered = case.status == "recovered"
    if not already_recovered:
        outcome_payload = {
            "ok": True,
            "external_id": paid.payment_link_id,
            "payment_id": paid.payment_id,
            "recovered": True,
            "status": "paid",
            "note": "razorpay_payment_link_paid_webhook",
            "amount_paise": paid.amount_paise or case.amount_paise,
            "webhook_event_id": paid.event_id,
        }
        writer.append_ledger(
            session,
            case_id=case.id,
            kind=LedgerKind.outcome,
            actor=LedgerActor.system,
            payload=outcome_payload,
            reason_code="payment_link.paid",
            policy_version="webhook-paid",
            at=paid.occurred_at,
        )
        apply_stop(session, case, StopReason.recovered, policy_version="webhook-paid")

    writer.mark_event_processed(session, paid.event_id, case.id)

    return PaymentLinkPaidResult(
        case_id=case.id,
        event_id=paid.event_id,
        duplicate=False,
        recovered=True,
        payment_link_id=paid.payment_link_id,
        payment_id=paid.payment_id,
        ledger_seq=event_row.seq,
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
