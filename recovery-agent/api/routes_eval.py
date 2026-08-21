"""
api/routes_eval.py — POST /eval/run, GET /eval/runs/{id}
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from eval.run_store import get_store
from eval.service import run_eval
from logging_util import slog

router = APIRouter(prefix="/eval", tags=["eval"])


class EvalRunRequest(BaseModel):
    seed: int = 42
    n: int = Field(default=200, ge=10, le=2000)
    labels: Optional[list[str]] = Field(
        default=None,
        description="Default ['b2','ours']. Use ['b0','b1','b2','ours'] for full compare.",
    )


@router.post("/run")
def eval_run(req: EvalRunRequest) -> dict:
    try:
        record = run_eval(seed=req.seed, n=req.n, labels=req.labels)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    slog(
        "eval_run",
        run_id=record.run_id,
        status="ok",
        seed=req.seed,
        n=req.n,
    )
    return record.model_dump(mode="json")


@router.get("/runs/{run_id}")
def eval_get(run_id: str) -> dict:
    rec = get_store().get(run_id)
    if rec is None:
        raise HTTPException(404, f"run not found: {run_id}")
    return rec.model_dump(mode="json")


@router.get("/runs")
def eval_list(limit: int = 20) -> dict:
    rows = get_store().list_runs(limit=limit)
    return {"runs": [r.model_dump(mode="json") for r in rows]}
