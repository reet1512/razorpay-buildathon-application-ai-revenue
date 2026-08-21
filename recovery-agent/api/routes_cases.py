"""
api/routes_cases.py — GET /cases/{id} (case + ledger trail).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ledger.db import SessionLocal
from ledger.service import get_case_trail

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
