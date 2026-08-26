"""
demo/live_flow.py — one-click demo: ingest → AI (or rules) → ledger → gates.

Important: do NOT hold a SQLite write lock while Ollama is thinking.
We commit ingest first, run the model, then open a fresh session for writes.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from memory.rag import RagMetrics, persist_memory_retrieval, retrieve_for_payment
from ai.agent import RecoveryAgent, build_context
from ai.client import LLMClient
from ai.schemas import AgentRunResult
from ai.service import persist_agent_run
from execute.base import ExecuteMeta, Outcome
from execute.razorpay_adapter import RazorpayExecutor
from execute.service import execute_with_guards
from guard.context import GuardContext
from guard.gates import fingerprint_action
from guard.pipeline import guard_and_maybe_execute
from ledger import writer
from ledger.db import SessionLocal
from ledger.models import CaseRow
from ledger.schemas import (
    CaseStatus,
    EventSource,
    LedgerActor,
    LedgerKind,
    MandateState,
    PayerContext,
    Rail,
    RiskEvent,
)
from ledger.service import ingest_risk_event
from logging_util import slog
from policy.schemas import Action, ActionVerb, Channel, ProposedBy

_DAYTIME = datetime(2026, 8, 21, 6, 0, tzinfo=timezone.utc)
_NIGHTTIME = datetime(2026, 8, 21, 18, 30, tzinfo=timezone.utc)

_GATE_LABELS: dict[str, str] = {
    "prohibited_recovery": "Fraud policy",
    "contact_window": "Contact window",
    "frequency_cap": "Frequency cap",
    "mandate_validity": "Mandate validity",
    "attempt_cap": "Attempt cap",
    "idempotency": "Idempotency",
}


def _step(key: str, title: str, status: str, detail: str = "", thinking: str = "") -> dict[str, Any]:
    return {
        "event": "step",
        "key": key,
        "title": title,
        "status": status,
        "detail": detail,
        "thinking": thinking,
    }


def _gate_payload(check, *, proposed_verb: str, source: str) -> dict[str, Any]:
    return {
        "event": "gate",
        "gate": check.name,
        "label": _GATE_LABELS.get(check.name, check.name.replace("_", " ")),
        "passed": bool(check.passed),
        "reason_code": check.reason_code,
        "status": "passed" if check.passed else "blocked",
        "proposed_verb": proposed_verb,
        "source": source,
    }


def _create_demo_payment_link(
    session: Session,
    case: CaseRow,
    *,
    raw_error_reason: str,
    gated_verb: str,
) -> Outcome:
    """
    UI-only Razorpay Payment Link for Live demos.

    Not the gated recovery action — created only after gates have already
    validated agent_result.action_validated. Ledger note makes this explicit.
    """
    demo_action = Action(
        verb=ActionVerb.send_payment_link,
        channel=Channel.link,
        amount_paise=case.amount_paise,
        day_offset=0,
        reason_code="UI_DEMO_LINK_NOT_GATED",
        note=f"demo_affordance_after_gate;gated_verb={gated_verb}",
        proposed_by=ProposedBy.rules_fallback,
    )
    meta = ExecuteMeta(
        failure_reason=raw_error_reason,
        seed=case.id,
        dry_run=False,
    )
    outcome = RazorpayExecutor().run(demo_action, case, meta)
    writer.append_ledger(
        session,
        case_id=case.id,
        kind=LedgerKind.action,
        actor=LedgerActor.system,
        payload={
            "demo_payment_link": True,
            "not_the_gated_action": True,
            "gated_verb": gated_verb,
            "action": demo_action.model_dump(mode="json"),
            "execute_result": outcome.model_dump(),
        },
        reason_code="UI_DEMO_LINK_NOT_GATED",
        policy_version="ui-demo",
    )
    slog(
        "demo_payment_link",
        case_id=case.id,
        verb=gated_verb,
        status="created" if outcome.external_id else "failed",
        note="not_the_gated_action",
        external_id=outcome.external_id,
    )
    return outcome


def iter_ai_demo_case(
    *,
    raw_error_reason: str = "card_expired",
    amount_paise: int = 49900,
    force_fallback: bool = False,
    refuse_at_gate: bool = False,
    create_payment_link: bool = False,
):
    """Yield pipeline steps so the UI can show thinking, then a final result."""
    event_id = f"ui_ai_{uuid4().hex[:12]}"
    live = bool(create_payment_link) and not refuse_at_gate
    yield _step(
        "ingest",
        "Ingest failed payment",
        "running",
        "Opening case from Razorpay test decline" if live else "Opening case from simulated decline",
    )
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

    yield _step("ingest", "Ingest failed payment", "done", f"Case {case_id}")

    # --- no DB lock: RAG then Ollama / rules ---
    client = LLMClient()
    if force_fallback:
        client.available = lambda: False  # type: ignore[method-assign]

    yield _step(
        "memory",
        "Historical memory (RAG)",
        "running",
        "Searching Inherent for similar recoveries",
    )

    rag_metrics: RagMetrics = retrieve_for_payment(
        failure_reason=raw_error_reason,
        rail=Rail.card.value,
        limit=20,
    )
    rag_detail = (
        f"{rag_metrics.similar_cases} similar episodes"
        if rag_metrics.enabled and rag_metrics.available
        else (rag_metrics.status_label if hasattr(rag_metrics, "status_label") else "RAG unavailable")
    )
    if rag_metrics.retrieval_latency_ms is not None:
        rag_detail += f" · {int(rag_metrics.retrieval_latency_ms)} ms"
    yield _step("memory", "Historical memory (RAG)", "done", rag_detail)

    chunks = list(rag_metrics.episodes or [])
    yield {
        "event": "rag_meta",
        "similar_cases": rag_metrics.similar_cases,
        "latency_ms": rag_metrics.retrieval_latency_ms,
        "status_label": rag_metrics.status_label,
        "top_similarity": rag_metrics.top_similarity_score,
        "query": rag_metrics.query,
        "chunk_count": len(chunks),
    }
    for i, ep in enumerate(chunks):
        yield {
            "event": "rag_chunk",
            "index": i,
            "total": len(chunks),
            "document_name": ep.get("document_name") or ep.get("document_id") or f"episode_{i+1}",
            "score": ep.get("score"),
            "failure_reason": ep.get("failure_reason"),
            "action": ep.get("action"),
            "outcome": ep.get("outcome"),
            "recovery_class": ep.get("recovery_class"),
        }
        time.sleep(0.04)

    yield _step(
        "agent",
        "Agentic reasoning",
        "running",
        "Diagnosing failure and proposing a bounded action",
    )

    agent = RecoveryAgent(client=client)
    ctx = build_context(
        raw_error_reason=raw_error_reason,
        amount_paise=amount_paise,
        event_id=event_id,
        case_id=case_id,
        rag_episodes=chunks,
        rag_query=rag_metrics.query,
    )

    agent_result: AgentRunResult = agent.run(ctx)
    diag = agent_result.diagnosis
    think = diag.rationale or diag.summary or ""
    source = agent_result.source
    source_label = "LLM" if source == "llm" else "rules_fallback"
    yield {
        "event": "reasoning",
        "used_llm": agent_result.used_llm,
        "source": source,
        "fallback_reason": agent_result.fallback_reason,
        "summary": diag.summary,
        "rationale": think,
        "likely_class": diag.likely_class,
        "confidence": diag.confidence,
        "verb": agent_result.action_validated.verb.value,
        "day_offset": getattr(agent_result.action_validated, "day_offset", 0) or 0,
        "proposed_by": agent_result.action_validated.proposed_by.value,
    }
    yield _step(
        "agent",
        "Agentic reasoning",
        "done",
        f"{source_label} · {diag.likely_class} · {agent_result.action_validated.verb.value}",
        thinking=think,
    )

    yield _step("safety", "Safety gates", "running", "Policy checks before any money moves")

    # --- short write: ledger + gates (+ optional link) ---
    session = SessionLocal()
    try:
        case = session.get(CaseRow, case_id)
        assert case is not None

        persist_agent_run(session, case.id, agent_result)
        if rag_metrics.enabled:
            persist_memory_retrieval(session, case.id, rag_metrics)
        case.failure_class = agent_result.diagnosis.likely_class
        try:
            case.score = float(agent_result.diagnosis.confidence)
        except (TypeError, ValueError):
            case.score = None
        session.add(case)

        # BUG fix: gates must validate the agent's action only — never a UI override.
        action = agent_result.action_validated
        now = _NIGHTTIME if refuse_at_gate else _DAYTIME
        guard_ctx = GuardContext(
            case_id=case.id,
            case_status=CaseStatus(case.status),
            action=action,
            now=now,
            failure_class=agent_result.diagnosis.likely_class or raw_error_reason,
            contacts_used=int(case.contacts_used or 0),
            attempts_used=int(case.attempts_used or 0),
            mandate_state=MandateState.active,
        )
        assert (
            guard_ctx.action.model_dump(mode="json")
            == agent_result.action_validated.model_dump(mode="json")
        ), "guard_ctx.action must equal agent_result.action_validated (no UI override)"
        guard_ctx.action_fingerprint = fingerprint_action(guard_ctx)

        executed = False
        outcome = None
        demo_outcome: Outcome | None = None
        if create_payment_link and not refuse_at_gate:
            yield _step(
                "action",
                "Razorpay execute",
                "running",
                f"Executing gated action: {action.verb.value}",
            )
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
            # Demo-only Payment Link when the gated verb did not create one.
            if (
                allowed
                and not (outcome and outcome.external_id)
                and action.verb != ActionVerb.send_payment_link
            ):
                demo_outcome = _create_demo_payment_link(
                    session,
                    case,
                    raw_error_reason=raw_error_reason,
                    gated_verb=action.verb.value,
                )
        else:
            yield _step(
                "action",
                "Simulated execute",
                "running",
                f"Applying gated action in simulation: {action.verb.value}",
            )
            pipe = guard_and_maybe_execute(
                session,
                case,
                guard_ctx,
                execute_fn=None,
                policy_version="ui-demo",
            )
            allowed = pipe.allowed
            blocked_by = pipe.blocked_by

        for check in getattr(pipe, "checks", None) or []:
            yield _gate_payload(check, proposed_verb=action.verb.value, source=source)
            time.sleep(0.03)

        session.commit()
        display_plink = None
        demo_link_not_gated = False
        if outcome and outcome.external_id:
            display_plink = outcome.external_id
        elif demo_outcome and demo_outcome.external_id:
            display_plink = demo_outcome.external_id
            demo_link_not_gated = True

        action_detail = (
            f"Demo Payment Link {display_plink} (not the gated action)"
            if demo_link_not_gated and display_plink
            else (
                f"Razorpay Payment Link {display_plink}"
                if display_plink and live
                else (
                    f"Blocked by {blocked_by}"
                    if blocked_by
                    else f"Gated {action.verb.value}"
                )
            )
        )
        yield _step(
            "safety",
            "Safety gates",
            "blocked" if blocked_by else "done",
            f"Blocked by {blocked_by}" if blocked_by else f"Validated {action.verb.value}",
        )
        yield _step(
            "action",
            "Razorpay execute" if live else "Simulated execute",
            "blocked" if blocked_by else "done",
            action_detail,
        )
        amount_inr = round(case.amount_paise / 100.0, 2)
        conf = agent_result.diagnosis.confidence
        try:
            confidence_pct = round(float(conf) * 100)
        except (TypeError, ValueError):
            confidence_pct = None
        day_offset = getattr(action, "day_offset", 0) or 0
        safety_checks = [
            {
                "gate": c.name,
                "label": _GATE_LABELS.get(c.name, c.name.replace("_", " ")),
                "status": "passed" if c.passed else "blocked",
                "passed": bool(c.passed),
                "reason_code": c.reason_code,
                "proposed_verb": action.verb.value,
                "source": source,
            }
            for c in (getattr(pipe, "checks", None) or [])
        ]
        if blocked_by:
            recovery_status = "blocked"
            recovered_inr = 0.0
            recovery_label = "₹0 — policy refused"
        elif live and display_plink and not demo_link_not_gated:
            recovery_status = "link_created"
            recovered_inr = 0.0
            recovery_label = f"₹{amount_inr:,.2f} at risk — Payment Link live"
        elif live and demo_link_not_gated:
            recovery_status = "gated_with_demo_link"
            recovered_inr = 0.0
            recovery_label = (
                f"₹{amount_inr:,.2f} — gated {action.verb.value}; demo link only"
            )
        elif executed:
            recovery_status = "scheduled"
            recovered_inr = 0.0
            recovery_label = f"₹{amount_inr:,.2f} — action scheduled"
        else:
            recovery_status = "proposed"
            recovered_inr = 0.0
            recovery_label = f"₹{amount_inr:,.2f} — recommendation ready"

        result = {
            "case_id": case.id,
            "event_id": event_id,
            "amount_paise": case.amount_paise,
            "amount_inr": amount_inr,
            "failure_reason": raw_error_reason,
            "failure_class": agent_result.diagnosis.likely_class,
            "source": source,
            "used_llm": agent_result.used_llm,
            "fallback_reason": agent_result.fallback_reason,
            "proposed_by": action.proposed_by.value,
            "rationale": agent_result.diagnosis.rationale,
            "summary": agent_result.diagnosis.summary,
            "confidence": conf,
            "confidence_pct": confidence_pct,
            "verb": action.verb.value,
            "day_offset": day_offset,
            "allowed": allowed,
            "blocked_by": blocked_by,
            "executed": executed,
            "external_id": display_plink,
            "demo_link_not_gated": demo_link_not_gated,
            "refuse_at_gate": refuse_at_gate,
            "force_fallback": force_fallback,
            "rag": rag_metrics.to_public_dict(),
            "chunks": chunks,
            "safety_checks": safety_checks,
            "live": live,
            "recovery_status": recovery_status,
            "recovered_inr": recovered_inr,
            "recovery_label": recovery_label,
            "at_risk_inr": amount_inr,
        }
        yield {"event": "done", "result": result}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def run_ai_demo_case(
    *,
    raw_error_reason: str = "card_expired",
    amount_paise: int = 49900,
    force_fallback: bool = False,
    refuse_at_gate: bool = False,
    create_payment_link: bool = False,
) -> dict[str, Any]:
    """Full product beat for the UI (manages its own DB sessions)."""
    result: dict[str, Any] = {}
    for ev in iter_ai_demo_case(
        raw_error_reason=raw_error_reason,
        amount_paise=amount_paise,
        force_fallback=force_fallback,
        refuse_at_gate=refuse_at_gate,
        create_payment_link=create_payment_link,
    ):
        if ev.get("event") == "done":
            result = ev["result"]
    if not result:
        raise RuntimeError("recovery pipeline did not complete")
    return result


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
        failure_class=raw_error_reason or case.failure_class,
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
