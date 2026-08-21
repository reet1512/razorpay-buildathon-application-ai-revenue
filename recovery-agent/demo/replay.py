"""
demo/replay.py — offline fixture → full case trail (no network / no Ollama).

Creates ledger rows a judge can click: event → AI diagnosis → decision →
gate block or pass → action → outcome.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from ledger import writer
from ledger.models import CaseRow
from ledger.schemas import (
    CaseStatus,
    EventSource,
    GateResult,
    LedgerActor,
    LedgerKind,
    PayerContext,
    Rail,
    RiskEvent,
)
from ledger.service import ingest_risk_event

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "demo_replay.json"


def load_fixture(path: Optional[Path] = None) -> dict[str, Any]:
    p = path or _FIXTURE
    return json.loads(p.read_text(encoding="utf-8"))


def replay_fixture(
    session: Session,
    *,
    fixture: Optional[dict[str, Any]] = None,
    path: Optional[Path] = None,
) -> dict[str, Any]:
    """
    Build one showcase case from fixtures/demo_replay.json.
    Idempotent on fixture event_id (second call returns existing trail).
    """
    data = fixture or load_fixture(path)
    event_id = data.get("event_id") or f"demo_replay_{uuid4().hex[:8]}"
    amount = int(data.get("amount_paise", 49900))
    reason = data.get("raw_error_reason", "card_expired")

    event = RiskEvent(
        event_id=event_id,
        source=EventSource.simulator,
        occurred_at=datetime.now(timezone.utc),
        merchant_id=data.get("merchant_id", "merch_demo"),
        payer_ref=data.get("payer_ref", "payer_demo"),
        amount_paise=amount,
        rail=Rail(data.get("rail", "card")),
        raw_error_reason=reason,
        raw_error_code=data.get("raw_error_code", ""),
        payer_context=PayerContext(
            observed_credit_day=data.get("observed_credit_day"),
        ),
    )
    ingested = ingest_risk_event(session, event)
    case = session.get(CaseRow, ingested.case_id)
    assert case is not None

    if ingested.duplicate:
        return {
            "case_id": case.id,
            "event_id": event_id,
            "duplicate": True,
            "status": case.status,
        }

    case.failure_class = data.get("failure_class", "dead_instrument")
    case.score = float(data.get("score", 0.35))
    session.add(case)

    diagnosis = data.get("diagnosis") or {
        "summary": "Card looks expired; silent retry will not help.",
        "likely_class": "dead_instrument",
        "confidence": 0.91,
        "rationale": "Decline text maps to expired instrument.",
    }
    writer.append_ledger(
        session,
        case_id=case.id,
        kind=LedgerKind.classification,
        actor=LedgerActor.llm,
        payload=diagnosis,
        reason_code="AI_DIAGNOSIS",
        policy_version="phase8-demo",
    )

    proposal = data.get("proposal") or {
        "verb": "send_payment_link",
        "channel": "link",
        "day_offset": 0,
        "reason_code": "AI_LINK_DEAD",
        "note": "Ask payer to update card via payment link",
    }
    writer.append_ledger(
        session,
        case_id=case.id,
        kind=LedgerKind.decision,
        actor=LedgerActor.llm,
        payload={"action": proposal, "proposed_by": "llm"},
        reason_code=proposal.get("reason_code", "AI_PROPOSAL"),
        policy_version="phase8-demo",
    )

    if data.get("include_gate_block", True):
        writer.append_ledger(
            session,
            case_id=case.id,
            kind=LedgerKind.gate_check,
            actor=LedgerActor.system,
            payload={"gate": "contact_window", "hour_ist": 23},
            reason_code="GATE_WINDOW",
            policy_version="phase8-demo",
            gate_name="contact_window",
            gate_result=GateResult.blocked,
        )
        case.status = CaseStatus.blocked.value
        session.add(case)

    writer.append_ledger(
        session,
        case_id=case.id,
        kind=LedgerKind.gate_check,
        actor=LedgerActor.system,
        payload={"gate": "contact_window", "hour_ist": 11},
        reason_code="GATE_WINDOW_OK",
        policy_version="phase8-demo",
        gate_name="contact_window",
        gate_result=GateResult.passed,
    )
    for gname, code in (
        ("frequency_cap", "GATE_FREQ_OK"),
        ("mandate_validity", "GATE_MANDATE_OK"),
        ("attempt_cap", "GATE_ATTEMPT_OK"),
        ("idempotency", "GATE_IDEM_OK"),
    ):
        writer.append_ledger(
            session,
            case_id=case.id,
            kind=LedgerKind.gate_check,
            actor=LedgerActor.system,
            payload={"gate": gname},
            reason_code=code,
            policy_version="phase8-demo",
            gate_name=gname,
            gate_result=GateResult.passed,
        )

    case.status = CaseStatus.open.value
    case.last_action = proposal.get("verb", "send_payment_link")
    case.contacts_used = 1
    session.add(case)

    writer.append_ledger(
        session,
        case_id=case.id,
        kind=LedgerKind.action,
        actor=LedgerActor.system,
        payload={"action": proposal},
        reason_code=proposal.get("reason_code", "EXECUTE"),
        policy_version="phase8-demo",
    )

    outcome = data.get("outcome") or {
        "ok": True,
        "external_id": "plink_demo_abc123",
        "recovered": False,
        "status": "created_link",
        "note": "dry_run_or_fixture",
    }
    writer.append_ledger(
        session,
        case_id=case.id,
        kind=LedgerKind.outcome,
        actor=LedgerActor.system,
        payload=outcome,
        reason_code=outcome.get("status", "created_link"),
        policy_version="phase8-demo",
    )

    session.flush()
    return {
        "case_id": case.id,
        "event_id": event_id,
        "duplicate": False,
        "status": case.status,
        "failure_class": case.failure_class,
        "external_id": outcome.get("external_id"),
    }
