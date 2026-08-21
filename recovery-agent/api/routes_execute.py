"""
api/routes_execute.py — Phase 7: guard then sim/Razorpay adapter.

POST /execute/run
  body: failure reason, verb, mode=sim|razorpay, …
  -> gates -> adapter (only if allowed) -> ledger outcome
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from execute.base import ExecuteMeta
from execute.service import execute_with_guards
from guard.context import GuardContext
from ledger.db import SessionLocal
from ledger.models import CaseRow
from ledger.schemas import (
    CaseStatus,
    EventSource,
    MandateState,
    PayerContext,
    Rail,
    RiskEvent,
)
from ledger.service import ingest_risk_event
from policy.schemas import Action, ActionVerb, Channel, ProposedBy

router = APIRouter(prefix="/execute", tags=["execute"])


class ExecuteRunRequest(BaseModel):
    raw_error_reason: str = "insufficient_funds"
    amount_paise: int = 49900
    verb: ActionVerb = ActionVerb.schedule_retry
    channel: Channel = Channel.none
    day_offset: int = 0
    mode: str = Field(default="sim", description="sim | razorpay")
    failure_dom: int = 15
    observed_credit_day: Optional[int] = 1
    payment_ref: Optional[str] = None
    dry_run: bool = False
    now_iso: Optional[str] = None
    contacts_used: int = 0
    attempts_used: int = 0
    max_contacts: int = 2
    max_attempts: int = 3
    mandate_state: MandateState = MandateState.active
    opt_out: bool = False
    case_id: Optional[str] = None  # reuse existing case if set


@router.post("/run")
def execute_run(req: ExecuteRunRequest) -> dict[str, Any]:
    """
    Demo path: ingest (or load case) → propose Action → guard → execute.
    """
    session: Session = SessionLocal()
    try:
        if req.case_id:
            case = session.get(CaseRow, req.case_id)
            if case is None:
                raise HTTPException(404, f"case not found: {req.case_id}")
        else:
            event = RiskEvent(
                event_id=f"exec_{uuid4().hex[:12]}",
                source=EventSource.simulator,
                occurred_at=datetime.now(timezone.utc),
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

        now = (
            datetime.fromisoformat(req.now_iso)
            if req.now_iso
            else datetime.now(timezone.utc)
        )
        # Contact verbs need a daytime IST clock by default for demos.
        if req.verb in {
            ActionVerb.send_payment_link,
            ActionVerb.request_mandate_update,
        } and req.now_iso is None:
            # 06:00 UTC ≈ 11:30 IST — inside 09–21 window
            now = datetime(2026, 8, 21, 6, 0, tzinfo=timezone.utc)

        channel = req.channel
        if req.verb == ActionVerb.send_payment_link and channel == Channel.none:
            channel = Channel.link

        action = Action(
            verb=req.verb,
            channel=channel,
            amount_paise=req.amount_paise,
            day_offset=req.day_offset,
            reason_code="EXECUTE_DEMO",
            proposed_by=ProposedBy.rules_fallback,
        )
        ctx = GuardContext(
            case_id=case.id,
            case_status=CaseStatus(case.status),
            action=action,
            now=now,
            contacts_used=req.contacts_used
            if req.case_id
            else int(case.contacts_used or 0),
            attempts_used=req.attempts_used
            if req.case_id
            else int(case.attempts_used or 0),
            max_contacts=req.max_contacts,
            max_attempts=req.max_attempts,
            mandate_state=req.mandate_state,
            opt_out=req.opt_out,
        )
        meta = ExecuteMeta(
            failure_reason=req.raw_error_reason,
            failure_dom=req.failure_dom,
            observed_credit_day=req.observed_credit_day,
            payment_ref=req.payment_ref,
            dry_run=req.dry_run,
            seed=case.id,
        )

        result, outcome = execute_with_guards(
            session,
            case,
            ctx,
            meta=meta,
            mode=req.mode,
        )
        session.commit()

        return {
            "case_id": case.id,
            "mode": req.mode,
            "allowed": result.allowed,
            "blocked_by": result.blocked_by,
            "executed": result.executed,
            "outcome": outcome.model_dump() if outcome else None,
            "case_status": case.status,
            "checks": [
                {
                    "name": c.name,
                    "passed": c.passed,
                    "reason_code": c.reason_code,
                }
                for c in result.checks
            ],
        }
    finally:
        session.close()
