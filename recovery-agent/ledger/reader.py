"""
reader.py — read case snapshots and ledger trails.

Teaching:
- UI / demos should READ from here.
- Never recompute history in the frontend. The ledger is the story.
"""

from __future__ import annotations

import json
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ledger.models import CaseRow, LedgerEntryRow
from ledger.schemas import (
    CaseStatus,
    CaseView,
    GateResult,
    LedgerActor,
    LedgerEntryView,
    LedgerKind,
    Rail,
)


def get_case(session: Session, case_id: str) -> Optional[CaseRow]:
    return session.get(CaseRow, case_id)


def case_to_view(row: CaseRow) -> CaseView:
    """Convert DB row -> Pydantic view for APIs/tests."""
    return CaseView(
        case_id=row.id,
        status=CaseStatus(row.status),
        failure_class=row.failure_class,
        score=row.score,
        attempts_used=row.attempts_used,
        contacts_used=row.contacts_used,
        stop_reason=row.stop_reason,
        last_action=row.last_action,
        payer_ref=row.payer_ref,
        amount_paise=row.amount_paise,
        rail=Rail(row.rail),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def list_ledger(session: Session, case_id: str) -> list[LedgerEntryView]:
    """
    Return the full ordered trail for a case.

    ORDER BY seq ASC = chronological story.
    """
    stmt = (
        select(LedgerEntryRow)
        .where(LedgerEntryRow.case_id == case_id)
        .order_by(LedgerEntryRow.seq.asc())
    )
    rows = session.scalars(stmt).all()
    views: list[LedgerEntryView] = []
    for row in rows:
        payload = json.loads(row.payload_json or "{}")
        views.append(
            LedgerEntryView(
                seq=row.seq,
                case_id=row.case_id,
                at=row.at,
                kind=LedgerKind(row.kind),
                actor=LedgerActor(row.actor),
                policy_version=row.policy_version,
                payload=payload,
                reason_code=row.reason_code,
                gate_name=row.gate_name,
                gate_result=GateResult(row.gate_result) if row.gate_result else None,
            )
        )
    return views
