"""
api/ui_helpers.py — presentation-only context for judge-facing UI.

Does not change business logic, scoring, gates, or agent behavior.
"""

from __future__ import annotations

from typing import Any, Optional

from eval.recovery_class import RecoveryClass, recovery_class_for
from eval.types import FailureReason
from memory.rag import (
    RagMetrics,
    extract_case_rag,
    is_rag_configured,
    probe_inherent_health,
    probe_platform_rag,
)

# Gate display names (matches guard/gates.py order)
GATE_LABELS: dict[str, str] = {
    "prohibited_recovery": "Fraud policy",
    "contact_window": "Contact window",
    "frequency_cap": "Frequency cap",
    "mandate_validity": "Mandate validity",
    "attempt_cap": "Attempt cap",
    "idempotency": "Idempotency",
}

GATE_ORDER: tuple[str, ...] = tuple(GATE_LABELS.keys())

_ACTION_LABELS: dict[str, str] = {
    "schedule_retry": "Schedule retry",
    "send_payment_link": "Send payment link",
    "request_mandate_update": "Request mandate update",
    "escalate_human": "Escalate to human",
}

_RAIL_LABELS: dict[str, str] = {
    "card": "Card",
    "upi_autopay": "UPI",
    "enach": "eNACH",
}

_FAILURE_LABELS: dict[str, str] = {
    "insufficient_funds": "Insufficient funds",
    "issuer_transient": "Temporary issuer failure",
    "gateway_timeout": "Gateway timeout",
    "card_expired": "Card expired",
    "token_invalid": "Invalid payment token",
    "mandate_revoked": "Mandate revoked",
    "do_not_honour": "Do not honour",
    "risk_fraud": "Risk / fraud",
}


def inherent_enabled() -> bool:
    """Configured for RAG (env flag + API key)."""
    return is_rag_configured()


def corpus_counts() -> dict[str, int]:
    """Local seeder manifest counts (corpus size), not search top-k."""
    try:
        from memory.manifest import MemoryManifest

        m = MemoryManifest()
        d = m.data
        return {
            "corpus_expected": int(d.get("expected_episodes") or 0),
            "corpus_uploaded": int(d.get("uploaded") or 0),
            "corpus_completed": int(d.get("completed") or 0),
        }
    except Exception:
        return {
            "corpus_expected": 0,
            "corpus_uploaded": 0,
            "corpus_completed": 0,
        }


def _format_latency_ms(ms: Optional[float]) -> Optional[str]:
    if ms is None:
        return None
    if ms == int(ms):
        return f"{int(ms)} ms"
    return f"{ms:.0f} ms"


def _platform_rag_metrics() -> RagMetrics:
    try:
        return probe_platform_rag()
    except Exception:
        return RagMetrics(
            enabled=is_rag_configured(),
            available=False,
            error="probe_failed",
        )


def rag_status_payload(*, force: bool = True) -> dict[str, Any]:
    """
    Live RAG snapshot for Stats polling.

    Online when configured and either Public API /health is OK or search probe works.
    Episodes / latency only from a successful search probe (no fabricated metrics).
    """
    configured = is_rag_configured()
    healthy = False
    try:
        healthy = probe_inherent_health() if configured else False
    except Exception:
        healthy = False

    if force:
        try:
            rag = probe_platform_rag(force=True)
        except Exception:
            rag = RagMetrics(
                enabled=configured,
                available=False,
                error="probe_failed",
            )
    else:
        rag = _platform_rag_metrics()

    active = bool(rag.enabled and rag.available)
    online = bool(configured and (active or healthy))
    if active:
        label = rag.status_label  # RAG ACTIVE
    elif online:
        label = "RAG ONLINE"
    elif configured:
        label = rag.status_label  # RAG UNAVAILABLE
    else:
        label = "RAG DISABLED"

    corpus = corpus_counts()
    return {
        "rag_configured": configured,
        "rag_healthy": healthy,
        "rag_available": rag.available,
        "rag_enabled": active,
        "rag_online": online,
        "rag_provider": rag.provider,
        "rag_label": label,
        "rag_error": rag.error,
        "similar_cases": rag.similar_cases if active else 0,
        "retrieval_latency_ms": rag.retrieval_latency_ms if active else None,
        "retrieval_latency_label": _format_latency_ms(rag.retrieval_latency_ms)
        if active
        else None,
        **corpus,
    }


def platform_metrics(run, by_label: dict) -> dict[str, Any]:
    """Landing-page metrics row — real probe data when Inherent is available."""
    ours = by_label.get("ours") if by_label else None
    live = rag_status_payload(force=False)
    return {
        "net_recovered_inr": ours.net_recovered_inr if ours else None,
        "recovery_rate_pct": round(ours.recovery_rate * 100, 1) if ours else None,
        "similar_cases": live["similar_cases"],
        "retrieval_latency_ms": live["retrieval_latency_ms"],
        "retrieval_latency_label": live["retrieval_latency_label"],
        "rag_enabled": live["rag_enabled"],
        "rag_online": live["rag_online"],
        "rag_configured": live["rag_configured"],
        "rag_available": live["rag_available"],
        "rag_healthy": live["rag_healthy"],
        "rag_provider": live["rag_provider"],
        "rag_label": live["rag_label"],
        "rag_error": live["rag_error"],
        "corpus_expected": live.get("corpus_expected", 0),
        "corpus_uploaded": live.get("corpus_uploaded", 0),
        "corpus_completed": live.get("corpus_completed", 0),
        "has_eval_run": ours is not None,
    }


def _recovery_class_for(failure: Optional[str]) -> Optional[str]:
    if not failure:
        return None
    try:
        return recovery_class_for(FailureReason(failure)).value
    except (ValueError, KeyError):
        return None


def _human_failure(reason: Optional[str]) -> str:
    if not reason:
        return "Unknown failure"
    return _FAILURE_LABELS.get(reason, reason.replace("_", " "))


def _human_action(verb: Optional[str], payload: Optional[dict] = None) -> str:
    if not verb:
        return "Pending"
    base = _ACTION_LABELS.get(verb, verb.replace("_", " "))
    if verb == "schedule_retry" and payload:
        offset = payload.get("day_offset")
        if offset is not None and int(offset) > 0:
            return f"Retry after {int(offset)} day(s)"
        if offset == 0:
            return "Retry shortly"
    return base


def _ledger_classification(ledger: list) -> dict[str, Any]:
    for e in ledger:
        kind = e.kind.value if hasattr(e.kind, "value") else str(e.kind)
        if kind != "classification":
            continue
        p = e.payload or {}
        return {
            "summary": p.get("summary"),
            "likely_class": p.get("likely_class"),
            "confidence": p.get("confidence"),
            "rationale": p.get("rationale"),
            "model": (p.get("audit") or {}).get("model"),
        }
    return {}


def _ledger_decision(ledger: list) -> dict[str, Any]:
    for e in ledger:
        kind = e.kind.value if hasattr(e.kind, "value") else str(e.kind)
        if kind != "decision":
            continue
        p = e.payload or {}
        validated = p.get("validated") or p.get("action") or {}
        if not isinstance(validated, dict):
            validated = {}
        audit = p.get("audit") or {}
        return {
            "verb": validated.get("verb"),
            "validated": validated,
            "note": validated.get("note") or p.get("extra_note"),
            "score": validated.get("score"),
            "model": audit.get("model"),
            "prompt_hash": audit.get("prompt_hash"),
            "proposed_by": validated.get("proposed_by"),
        }
    return {}


def build_safety_checks(audit_log: list) -> list[dict[str, Any]]:
    """Map gate audit rows to judge-friendly checklist."""
    by_gate: dict[str, str] = {}
    for row in audit_log:
        if row.gate_name:
            by_gate[row.gate_name] = row.verdict or "unknown"

    checks: list[dict[str, Any]] = []
    for gate in GATE_ORDER:
        verdict = by_gate.get(gate)
        if verdict == "pass":
            status = "passed"
        elif verdict == "block":
            status = "blocked"
        elif verdict is None:
            status = "pending"
        else:
            status = "unknown"
        checks.append(
            {
                "gate": gate,
                "label": GATE_LABELS[gate],
                "verdict": verdict,
                "status": status,
            }
        )
    return checks


def build_case_view(
    *,
    case,
    ledger: list,
    story: dict,
    audit_log: list,
    provenance: Optional[dict] = None,
    rag: Optional[RagMetrics] = None,
) -> dict[str, Any]:
    """Judge-facing case presentation model — RAG stats from ledger when present."""
    classification = _ledger_classification(ledger)
    decision = _ledger_decision(ledger)
    failure = story.get("failure") or classification.get("likely_class")
    recovery_class = _recovery_class_for(failure) or classification.get("likely_class")
    rag_metrics = rag or extract_case_rag(ledger)
    rag_on = bool(rag_metrics and rag_metrics.enabled and rag_metrics.available)
    rag_configured = is_rag_configured()

    checks = build_safety_checks(audit_log)
    passed = sum(1 for c in checks if c["status"] == "passed")
    blocked = sum(1 for c in checks if c["status"] == "blocked")
    ran = sum(1 for c in checks if c["verdict"] is not None)

    gates_state = story.get("gates", "none")
    if gates_state == "blocked":
        safety_headline = "Recovery blocked"
        safety_tone = "blocked"
    elif gates_state == "passed":
        safety_headline = "Recovery permitted"
        safety_tone = "passed"
    elif ran:
        safety_headline = "Safety checks recorded"
        safety_tone = "neutral"
    else:
        safety_headline = "Safety checks pending"
        safety_tone = "pending"

    llm_used = bool(provenance and provenance.get("has_llm")) or story.get("by_ai")
    rules_only = story.get("by_rules") and not llm_used

    verb = decision.get("verb") or story.get("proposed")
    action_label = _human_action(verb, decision.get("validated"))

    confidence = classification.get("confidence")
    if confidence is not None:
        try:
            confidence_pct = round(float(confidence) * 100)
        except (TypeError, ValueError):
            confidence_pct = None
    else:
        confidence_pct = None

    # Timeline step states
    def step(done: bool, blocked: bool = False, waiting: bool = False) -> str:
        if blocked:
            return "blocked"
        if done:
            return "done"
        if waiting:
            return "waiting"
        return "pending"

    timeline = [
        {
            "key": "classified",
            "title": "Classified",
            "status": step(bool(failure)),
            "line1": _human_failure(failure),
            "line2": recovery_class.replace("_", " ") if recovery_class else None,
        },
        {
            "key": "memory",
            "title": "Historical payment memory",
            "status": "done" if rag_on else ("disabled" if not rag_configured else "waiting"),
            "line1": (
                f"Retrieved {rag_metrics.similar_cases} similar episodes"
                if rag_on and rag_metrics
                else (
                    "Historical memory unavailable"
                    if not rag_configured
                    else "Retrieval unavailable"
                )
            ),
            "line2": "Powered by Inherent" if rag_configured else "RAG disabled",
        },
        {
            "key": "evidence",
            "title": "Historical evidence",
            "status": "done" if rag_on else ("disabled" if not rag_configured else "waiting"),
            "line1": (
                f"Top similarity {_format_top_score(rag_metrics.top_similarity_score)}"
                if rag_on and rag_metrics and rag_metrics.top_similarity_score is not None
                else (
                    "No similar cases retrieved"
                    if not rag_configured
                    else "No evidence retrieved"
                )
            ),
            "line2": (
                _format_latency_ms(rag_metrics.retrieval_latency_ms)
                if rag_on and rag_metrics
                else None
            ),
        },
        {
            "key": "economics",
            "title": "Economic decision",
            "status": "disabled" if not rag_configured else ("done" if rag_on else "waiting"),
            "line1": "Uses config/costs.json",
            "line2": "Historical economics in Phase 4" if rag_on else None,
        },
        {
            "key": "ai",
            "title": "AI recommendation",
            "status": step(bool(verb), waiting=not verb),
            "line1": action_label if verb else "Pending",
            "line2": "Reasoning model not required"
            if rules_only
            else ("Qwen3:8b" if llm_used else "Rules fallback"),
        },
        {
            "key": "safety",
            "title": "Safety check",
            "status": step(
                gates_state in {"passed", "blocked"},
                blocked=gates_state == "blocked",
            ),
            "line1": f"{passed} / {len(GATE_ORDER)} checks passed"
            if ran
            else "Not run yet",
            "line2": safety_headline,
        },
        {
            "key": "action",
            "title": "Recovery action",
            "status": step(
                bool(story.get("plink") or story.get("recovered")),
                blocked=gates_state == "blocked" and not story.get("plink"),
            ),
            "line1": "Executed" if story.get("plink") or story.get("recovered") else (
                "Blocked by policy" if gates_state == "blocked" else "Pending"
            ),
            "line2": story.get("plink"),
        },
    ]

    rail = "card"
    for e in ledger:
        kind = e.kind.value if hasattr(e.kind, "value") else str(e.kind)
        if kind == "event":
            rail = (e.payload or {}).get("rail") or rail
            break

    return {
        "payment": {
            "amount_inr": case.amount_paise / 100 if case else 0,
            "rail_label": _RAIL_LABELS.get(str(rail), str(rail)),
            "failure_label": _human_failure(failure),
            "recovery_class": recovery_class.replace("_", " ") if recovery_class else None,
            "failure_code": failure,
        },
        "timeline": timeline,
        "recommendation": {
            "action": action_label,
            "confidence_pct": confidence_pct,
            "reason": classification.get("rationale") or classification.get("summary"),
            "llm_used": llm_used,
            "rules_only": rules_only,
            "model": decision.get("model") or classification.get("model"),
        },
        "why": {
            "rag_enabled": rag_on,
            "rag_configured": rag_configured,
            "historical_episodes": rag_metrics.similar_cases if rag_on and rag_metrics else 0,
            "retrieval_latency_ms": rag_metrics.retrieval_latency_ms if rag_metrics else None,
            "retrieval_latency_label": _format_latency_ms(
                rag_metrics.retrieval_latency_ms if rag_metrics else None
            ),
            "top_similarity_score": rag_metrics.top_similarity_score if rag_metrics else None,
            "action_stats": [],
            "expected_net_inr": None,
            "message": _rag_why_message(rag_metrics, rag_configured=rag_configured),
        },
        "memory": {
            "enabled": rag_on,
            "configured": rag_configured,
            "retrieved_count": rag_metrics.similar_cases if rag_on and rag_metrics else 0,
            "episodes": rag_metrics.episodes if rag_metrics else [],
            "label": "Historical payment memory",
            "subtitle": (
                f"Inherent · {rag_metrics.similar_cases} episodes · "
                f"{_format_latency_ms(rag_metrics.retrieval_latency_ms)}"
                if rag_on and rag_metrics
                else ("Powered by Inherent" if rag_configured else "RAG disabled")
            ),
            "provider": "inherent",
        },
        "safety": {
            "checks": checks,
            "passed": passed,
            "blocked": blocked,
            "total": len(GATE_ORDER),
            "ran": ran,
            "headline": safety_headline,
            "tone": safety_tone,
            "blocked_by": story.get("blocked_by"),
        },
        "classification": classification,
        "decision": decision,
    }


def _format_top_score(score: Optional[float]) -> str:
    if score is None:
        return "n/a"
    return f"{score:.2f}"


def _rag_why_message(
    rag: Optional[RagMetrics],
    *,
    rag_configured: bool,
) -> str:
    if not rag_configured:
        return (
            "Historical memory unavailable — set INHERENT_ENABLED and INHERENT_API_KEY "
            "to retrieve similar recovery episodes."
        )
    if rag is None:
        return "No Inherent retrieval recorded for this case yet."
    if not rag.available:
        detail = f" ({rag.error})" if rag.error else ""
        return f"Inherent retrieval failed{detail}."
    if rag.similar_cases == 0:
        return "Inherent search returned no similar episodes for this failure profile."
    return (
        f"Retrieved {rag.similar_cases} similar episodes from Inherent "
        f"in {_format_latency_ms(rag.retrieval_latency_ms) or '—'}."
    )


def recover_demo_context() -> dict[str, Any]:
    rag = _platform_rag_metrics()
    active = rag.enabled and rag.available
    return {
        "rag_enabled": active,
        "rag_configured": rag.enabled,
        "rag_available": rag.available,
        "rag_label": rag.status_label,
        "rag_provider": rag.provider,
        "similar_cases": rag.similar_cases if active else 0,
        "retrieval_latency_label": _format_latency_ms(rag.retrieval_latency_ms)
        if active
        else None,
    }
