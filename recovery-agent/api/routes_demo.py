"""
api/routes_demo.py — POST /demo/replay
"""

from __future__ import annotations

from fastapi import APIRouter

from demo.replay import replay_fixture
from ledger.db import SessionLocal

router = APIRouter(prefix="/demo", tags=["demo"])


@router.post("/replay")
def demo_replay() -> dict:
    """Offline fixture → case with AI + gate block + outcome trail."""
    session = SessionLocal()
    try:
        result = replay_fixture(session)
        session.commit()
        return {"ok": True, **result, "case_url": f"/ui/cases/{result['case_id']}"}
    finally:
        session.close()
