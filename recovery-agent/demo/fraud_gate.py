"""
demo/fraud_gate.py — scripted risk/fraud demo: model proposes contact, gate blocks.

The prohibited_recovery gate is the product — not a crash.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from ai import prompts
from ai.schemas import Diagnosis
from guard.context import GuardContext
from guard.gates import fingerprint_action
from guard.pipeline import guard_and_maybe_execute
from ledger.db import SessionLocal
from ledger.models import CaseRow
from ledger.schemas import (
    CaseStatus,
    EventSource,
    LedgerActor,
    LedgerKind,
    PayerContext,
    Rail,
    RiskEvent,
)
from ledger import writer
from ledger.service import ingest_risk_event
from policy.schemas import Action, ActionVerb, Channel, ProposedBy

_DAYTIME = datetime(2026, 8, 21, 6, 0, tzinfo=timezone.utc)
_DEMO_MODEL = "scripted-demo-qwen3:8b"


def run_fraud_gate_demo(*, amount_paise: int = 49900) -> dict[str, Any]:
    """
    Model (scripted) proposes send_payment_link on risk_fraud; gate must block.
    """
    event_id = f"ui_fraud_gate_{uuid4().hex[:10]}"
    event = RiskEvent(
        event_id=event_id,
        source=EventSource.simulator,
        occurred_at=datetime.now(timezone.utc),
        merchant_id="merch_demo",
        payer_ref="payer_fraud_demo",
        amount_paise=amount_paise,
        rail=Rail.card,
        raw_error_reason="risk_fraud",
        raw_error_code="FRAUD_SUSPECTED",
        payer_context=PayerContext(),
    )

    session = SessionLocal()
    try:
        ingested = ingest_risk_event(session, event)
        case_id = ingested.case_id
        case = session.get(CaseRow, case_id)
        assert case is not None

        diagnosis = Diagnosis(
            summary="Suspected fraud — do not automate recovery contact.",
            likely_class="risk_fraud",
            confidence=0.93,
            rationale=(
                "Scripted demo: the model wrongly proposes a payment link. "
                "The prohibited_recovery gate must block before any execute."
            ),
        )
        prompt_hash = prompts.bundle_hash(
            "fraud_gate_demo",
            "risk_fraud",
            "send_payment_link",
        )

        writer.append_ledger(
            session,
            case_id=case.id,
            kind=LedgerKind.classification,
            actor=LedgerActor.llm,
            payload={
                **diagnosis.model_dump(),
                "audit": {"model": _DEMO_MODEL, "prompt_hash": prompt_hash},
            },
            reason_code=diagnosis.likely_class,
            policy_version="fraud-gate-demo",
        )

        bad_action = Action(
            verb=ActionVerb.send_payment_link,
            channel=Channel.link,
            amount_paise=amount_paise,
            day_offset=0,
            reason_code="AI_BAD_CONTACT_DEMO",
            note="scripted_model_proposes_contact_on_fraud",
            proposed_by=ProposedBy.llm,
            failure_class="risk_fraud",
            policy_version="fraud-gate-demo",
        )

        writer.append_ledger(
            session,
            case_id=case.id,
            kind=LedgerKind.decision,
            actor=LedgerActor.llm,
            payload={
                "proposal_raw": bad_action.model_dump(mode="json"),
                "validated": bad_action.model_dump(mode="json"),
                "scripted_demo": True,
                "audit": {"model": _DEMO_MODEL, "prompt_hash": prompt_hash},
            },
            reason_code=bad_action.reason_code,
            policy_version="fraud-gate-demo",
        )

        case.failure_class = "risk_fraud"
        session.add(case)

        guard_ctx = GuardContext(
            case_id=case.id,
            case_status=CaseStatus(case.status),
            action=bad_action,
            now=_DAYTIME,
            failure_class="risk_fraud",
            contacts_used=int(case.contacts_used or 0),
            attempts_used=int(case.attempts_used or 0),
        )
        guard_ctx.action_fingerprint = fingerprint_action(guard_ctx)

        pipe = guard_and_maybe_execute(
            session,
            case,
            guard_ctx,
            execute_fn=None,
            policy_version="fraud-gate-demo",
            audit={"model": _DEMO_MODEL, "prompt_hash": prompt_hash},
        )

        session.commit()
        return {
            "case_id": case.id,
            "event_id": event_id,
            "failure_class": "risk_fraud",
            "verb": bad_action.verb.value,
            "allowed": pipe.allowed,
            "blocked_by": pipe.blocked_by,
            "gate_success": pipe.blocked_by == "prohibited_recovery",
            "model": _DEMO_MODEL,
            "prompt_hash": prompt_hash,
            "scripted_demo": True,
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
