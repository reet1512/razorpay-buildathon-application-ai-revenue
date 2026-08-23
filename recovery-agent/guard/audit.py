"""
guard/audit.py — replayable gate audit log from ledger rows.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

from pydantic import BaseModel, Field

from ledger.schemas import LedgerEntryView, LedgerKind


class AuditLogRow(BaseModel):
    seq: int
    at: str
    proposed_verb: Optional[str] = None
    proposed_channel: Optional[str] = None
    failure_class: Optional[str] = None
    gate_name: Optional[str] = None
    verdict: Optional[str] = None
    rule: Optional[str] = None
    model: Optional[str] = None
    prompt_hash: Optional[str] = None
    actor: Optional[str] = None


def _decision_audit(ledger: Sequence[LedgerEntryView]) -> dict[str, Any]:
    for e in reversed(ledger):
        if e.kind != LedgerKind.decision:
            continue
        payload = e.payload or {}
        audit = payload.get("audit") or {}
        validated = payload.get("validated") or payload.get("action") or {}
        if isinstance(validated, dict):
            verb = validated.get("verb")
            channel = validated.get("channel")
            failure_class = validated.get("failure_class")
        else:
            verb = channel = failure_class = None
        return {
            "proposed_verb": verb,
            "proposed_channel": channel,
            "failure_class": failure_class,
            "model": audit.get("model"),
            "prompt_hash": audit.get("prompt_hash"),
            "actor": e.actor.value if hasattr(e.actor, "value") else str(e.actor),
        }
    return {}


def build_audit_log(ledger: Sequence[LedgerEntryView]) -> list[AuditLogRow]:
    """One row per gate_check, enriched with the latest decision audit metadata."""
    base = _decision_audit(ledger)
    rows: list[AuditLogRow] = []
    for e in ledger:
        if e.kind != LedgerKind.gate_check:
            continue
        payload = e.payload or {}
        verdict = payload.get("verdict")
        if verdict is None and e.gate_result is not None:
            verdict = (
                e.gate_result.value
                if hasattr(e.gate_result, "value")
                else str(e.gate_result)
            )
        rows.append(
            AuditLogRow(
                seq=e.seq,
                at=e.at.isoformat(),
                proposed_verb=payload.get("proposed_verb") or base.get("proposed_verb"),
                proposed_channel=payload.get("proposed_channel") or base.get("proposed_channel"),
                failure_class=payload.get("failure_class") or base.get("failure_class"),
                gate_name=e.gate_name or payload.get("gate"),
                verdict=verdict,
                rule=payload.get("reason_code") or e.reason_code,
                model=payload.get("model") or base.get("model"),
                prompt_hash=payload.get("prompt_hash") or base.get("prompt_hash"),
                actor=base.get("actor"),
            )
        )
    return rows


def headline_gate_block(audit_log: Sequence[AuditLogRow]) -> Optional[AuditLogRow]:
    for row in reversed(audit_log):
        if row.verdict == "block":
            return row
    return None
