"""
api/routes_guard.py — demo a gate refusal (highest-value Phase 6 beat).

POST /guard/check
  -> runs gates, returns which gate blocked (if any) + ledger rows written
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from guard.context import GuardContext
from guard.pipeline import guard_and_maybe_execute
from ledger.db import SessionLocal
from ledger.models import CaseRow
from ledger.schemas import CaseStatus, MandateState
from ledger.service import ingest_risk_event
from ledger.schemas import EventSource, PayerContext, Rail, RiskEvent
from policy.schemas import Action, ActionVerb, Channel, ProposedBy

router = APIRouter(prefix="/guard", tags=["guard"])


class GuardCheckRequest(BaseModel):
    raw_error_reason: str = "card_expired"
    amount_paise: int = 49900
    verb: ActionVerb = ActionVerb.send_payment_link
    channel: Channel = Channel.link
    # Freeze time for demos: "2026-08-21T18:30:00+00:00" is late night IST (~midnight)
    now_iso: Optional[str] = None
    contacts_used: int = 0
    attempts_used: int = 0
    max_contacts: int = 2
    max_attempts: int = 3
    mandate_state: MandateState = MandateState.active
    opt_out: bool = False
    force_execute: bool = Field(
        default=False,
        description="If true and gates pass, run a stub executor",
    )


@router.post("/check")
def guard_check(req: GuardCheckRequest) -> dict:
    """
    Create a throwaway case, propose an action, run gates.

    Perfect for the demo beat: agent wanted to message; window gate refused.
    """
    session: Session = SessionLocal()
    try:
        event = RiskEvent(
            event_id=f"guard_demo_{datetime.utcnow().timestamp()}",
            source=EventSource.simulator,
            occurred_at=datetime.utcnow(),
            merchant_id="merch_demo",
            payer_ref="payer_demo",
            amount_paise=req.amount_paise,
            rail=Rail.card,
            raw_error_reason=req.raw_error_reason,
            payer_context=PayerContext(),
        )
        ingested = ingest_risk_event(session, event)
        case = session.get(CaseRow, ingested.case_id)
        if case is None:
            raise HTTPException(500, "case missing after ingest")

        now = datetime.fromisoformat(req.now_iso) if req.now_iso else datetime.utcnow()
        action = Action(
            verb=req.verb,
            channel=req.channel,
            amount_paise=req.amount_paise,
            reason_code="DEMO_PROPOSAL",
            proposed_by=ProposedBy.llm,
            day_offset=0,
        )
        ctx = GuardContext(
            case_id=case.id,
            case_status=CaseStatus(case.status),
            action=action,
            now=now,
            contacts_used=req.contacts_used,
            attempts_used=req.attempts_used,
            max_contacts=req.max_contacts,
            max_attempts=req.max_attempts,
            mandate_state=req.mandate_state,
            opt_out=req.opt_out,
        )

        execute_calls: list[dict] = []

        def stub_execute(a: Action, c: CaseRow) -> dict:
            execute_calls.append({"verb": a.verb.value, "case_id": c.id})
            return {"ok": True, "external_id": "stub_1"}

        result = guard_and_maybe_execute(
            session,
            case,
            ctx,
            execute_fn=stub_execute if req.force_execute else None,
        )
        session.commit()

        return {
            "case_id": case.id,
            "allowed": result.allowed,
            "blocked_by": result.blocked_by,
            "skipped_because_stopped": result.skipped_because_stopped,
            "executed": result.executed,
            "execute_calls": execute_calls,
            "checks": [
                {
                    "name": c.name,
                    "passed": c.passed,
                    "reason_code": c.reason_code,
                }
                for c in result.checks
            ],
            "case_status": case.status,
        }
    finally:
        session.close()
