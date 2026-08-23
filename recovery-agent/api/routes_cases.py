"""
api/routes_cases.py — GET /cases/{id} (case + ledger trail).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ledger.db import SessionLocal
from ledger.schemas import CaseStatus
from ledger.service import get_case_trail
from ledger import reader

router = APIRouter(prefix="/cases", tags=["cases"])


@router.get("/{case_id}")
def get_case(case_id: str) -> dict:
    session = SessionLocal()
    try:
        trail = get_case_trail(session, case_id)
        if trail["case"] is None:
            raise HTTPException(404, f"case not found: {case_id}")
        case = trail["case"]
        ledger = trail["ledger"]
        return {
            "case": case.model_dump(mode="json"),
            "ledger": [e.model_dump(mode="json") for e in ledger],
        }
    finally:
        session.close()


@router.get("/{case_id}/status")
def get_case_status(case_id: str) -> dict:
    """Lightweight poll target for live payment_link.paid → RECOVERED UI."""
    session = SessionLocal()
    try:
        case_row = reader.get_case(session, case_id)
        if case_row is None:
            raise HTTPException(404, f"case not found: {case_id}")
        case = reader.case_to_view(case_row)
        ledger = reader.list_ledger(session, case_id)
        plink = None
        for e in ledger:
            if e.kind.value == "outcome":
                ext = str((e.payload or {}).get("external_id") or "")
                if ext.startswith("plink_"):
                    plink = ext
        paid_payload = reader.latest_payment_link_paid_payload(session, case_id)
        return {
            "case_id": case_id,
            "status": case.status.value,
            "recovered": case.status == CaseStatus.recovered,
            "payment_link_id": plink,
            "payment_id": (paid_payload or {}).get("payment_id"),
            "webhook_paid": paid_payload,
        }
    finally:
        session.close()
