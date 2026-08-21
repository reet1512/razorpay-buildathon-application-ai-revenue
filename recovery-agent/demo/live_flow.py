"""
demo/live_flow.py — one-click demo: ingest → AI (or rules) → ledger → gates.

Important: do NOT hold a SQLite write lock while Ollama is thinking.
We commit ingest first, run the model, then open a fresh session for writes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from ai.agent import RecoveryAgent, build_context
from ai.client import LLMClient
from ai.schemas import AgentRunResult
from ai.service import persist_agent_run
from execute.base import ExecuteMeta
from execute.service import execute_with_guards
from guard.context import GuardContext
from guard.gates import fingerprint_action
from guard.pipeline import guard_and_maybe_execute
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
from policy.schemas import Action, ActionVerb, Channel

_DAYTIME = datetime(2026, 8, 21, 6, 0, tzinfo=timezone.utc)
_NIGHTTIME = datetime(2026, 8, 21, 18, 30, tzinfo=timezone.utc)


def run_ai_demo_case(
    *,
    raw_error_reason: str = "card_expired",
    amount_paise: int = 49900,
    force_fallback: bool = False,
    refuse_at_gate: bool = False,
    create_payment_link: bool = False,
) -> dict[str, Any]:
    """
    Full product beat for the UI (manages its own DB sessions).
    """
    event_id = f"ui_ai_{uuid4().hex[:12]}"
    event = RiskEvent(
        event_id=event_id,
        source=EventSource.simulator,
        occurred_at=datetime.now(timezone.utc),
        merchant_id="merch_demo",
        payer_ref="payer_demo",
        amount_paise=amount_paise,
        rail=Rail.card,
        raw_error_reason=raw_error_reason,
        raw_error_code="",
        payer_context=PayerContext(),
    )

    # --- short write: open case ---
    session = SessionLocal()
    try:
        ingested = ingest_risk_event(session, event)
        case_id = ingested.case_id
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    # --- no DB lock: call Ollama / rules ---
    client = LLMClient()
    if force_fallback:
        client.available = lambda: False  # type: ignore[method-assign]

    agent = RecoveryAgent(client=client)
    ctx = build_context(
        raw_error_reason=raw_error_reason,
        amount_paise=amount_paise,
        event_id=event_id,
        case_id=case_id,
    )
    agent_result: AgentRunResult = agent.run(ctx)

    # --- short write: ledger + gates (+ optional link) ---
    session = SessionLocal()
    try:
        case = session.get(CaseRow, case_id)
        assert case is not None

        persist_agent_run(session, case.id, agent_result)
        case.failure_class = agent_result.diagnosis.likely_class
        try:
            case.score = float(agent_result.diagnosis.confidence)
        except (TypeError, ValueError):
            case.score = None
        session.add(case)

        action = agent_result.action_validated
        if action.verb in {
            ActionVerb.send_payment_link,
            ActionVerb.request_mandate_update,
        } and action.channel == Channel.none:
            action = action.model_copy(update={"channel": Channel.link})

        # Step 3 Prove: always create a Payment Link after gates, even if AI
        # proposed escalate/retry — AI proposal still stays on the ledger.
        if create_payment_link and not refuse_at_gate:
            action = Action(
                verb=ActionVerb.send_payment_link,
                channel=Channel.link,
                amount_paise=case.amount_paise,
                day_offset=0,
                reason_code="UI_PROVE_LINK",
            )

        now = _NIGHTTIME if refuse_at_gate else _DAYTIME
        guard_ctx = GuardContext(
            case_id=case.id,
            case_status=CaseStatus(case.status),
            action=action,
            now=now,
            contacts_used=int(case.contacts_used or 0),
            attempts_used=int(case.attempts_used or 0),
            mandate_state=MandateState.active,
        )
        guard_ctx.action_fingerprint = fingerprint_action(guard_ctx)

        executed = False
        outcome = None
        if create_payment_link and not refuse_at_gate:
            meta = ExecuteMeta(
                failure_reason=raw_error_reason,
                seed=case.id,
                dry_run=False,
            )
            pipe, outcome = execute_with_guards(
                session,
                case,
                guard_ctx,
                meta=meta,
                mode="razorpay",
                policy_version="ui-demo",
            )
            executed = pipe.executed
            blocked_by = pipe.blocked_by
            allowed = pipe.allowed
        else:
            pipe = guard_and_maybe_execute(
                session,
                case,
                guard_ctx,
                execute_fn=None,
                policy_version="ui-demo",
            )
            allowed = pipe.allowed
            blocked_by = pipe.blocked_by

        session.commit()
        return {
            "case_id": case.id,
            "event_id": event_id,
            "used_llm": agent_result.used_llm,
            "fallback_reason": agent_result.fallback_reason,
            "failure_class": agent_result.diagnosis.likely_class,
            "verb": action.verb.value,
            "allowed": allowed,
            "blocked_by": blocked_by,
            "executed": executed,
            "external_id": outcome.external_id if outcome else None,
            "refuse_at_gate": refuse_at_gate,
            "force_fallback": force_fallback,
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def execute_link_for_case(
    session: Session,
    case_id: str,
    *,
    raw_error_reason: str = "card_expired",
) -> dict[str, Any]:
    """Case-page button: create a real test-mode Payment Link behind gates."""
    case = session.get(CaseRow, case_id)
    if case is None:
        return {"ok": False, "error": "case_not_found"}

    action = Action(
        verb=ActionVerb.send_payment_link,
        channel=Channel.link,
        amount_paise=case.amount_paise,
        day_offset=0,
        reason_code="UI_CREATE_LINK",
    )
    guard_ctx = GuardContext(
        case_id=case.id,
        case_status=CaseStatus(case.status),
        action=action,
        now=_DAYTIME,
        contacts_used=int(case.contacts_used or 0),
        attempts_used=int(case.attempts_used or 0),
        mandate_state=MandateState.active,
    )
    meta = ExecuteMeta(
        failure_reason=raw_error_reason or case.failure_class or "unknown",
        seed=case.id,
    )
    pipe, outcome = execute_with_guards(
        session,
        case,
        guard_ctx,
        meta=meta,
        mode="razorpay",
        policy_version="ui-demo",
    )
    session.flush()
    return {
        "ok": pipe.allowed and pipe.executed,
        "case_id": case.id,
        "allowed": pipe.allowed,
        "blocked_by": pipe.blocked_by,
        "external_id": outcome.external_id if outcome else None,
        "status": outcome.status if outcome else None,
    }
