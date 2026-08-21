"""
ai/service.py — persist an AgentRunResult onto a case ledger.

Teaching:
- Agent returns ledger_events as dicts.
- This module writes them with actor=llm|policy using Phase 1 writer helpers.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ai.schemas import AgentRunResult
from ledger import writer
from ledger.schemas import LedgerActor, LedgerKind


def persist_agent_run(session: Session, case_id: str, result: AgentRunResult) -> list[int]:
    """
    Append classification/decision/(message) rows for a case.
    Returns list of ledger seq numbers.
    """
    seqs: list[int] = []
    for ev in result.ledger_events:
        kind = LedgerKind(ev["kind"])
        actor = LedgerActor(ev.get("actor", "llm"))
        row = writer.append_ledger(
            session,
            case_id=case_id,
            kind=kind,
            actor=actor,
            payload=ev.get("payload") or {},
            reason_code=str(ev.get("reason_code") or ""),
            policy_version=result.action_validated.policy_version,
        )
        seqs.append(row.seq)
    session.flush()
    return seqs
