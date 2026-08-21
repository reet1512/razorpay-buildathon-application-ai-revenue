"""
api/routes_ui.py — Batch + Case screens (Jinja templates).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from demo.replay import replay_fixture
from eval.run_store import get_store
from eval.service import run_eval
from ledger.db import SessionLocal
from ledger.service import get_case_trail

_ROOT = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=str(_ROOT / "templates"))

router = APIRouter(tags=["ui"])


def _metrics_by_label(record) -> dict:
    return {m.label: m for m in record.metrics}


@router.get("/", response_class=HTMLResponse)
@router.get("/ui", response_class=HTMLResponse)
@router.get("/ui/batch", response_class=HTMLResponse)
def batch_page(request: Request) -> HTMLResponse:
    store = get_store()
    run = store.latest()
    return templates.TemplateResponse(
        request,
        "batch.html",
        {
            "run": run,
            "by_label": _metrics_by_label(run) if run else {},
            "recent": store.list_runs(8),
        },
    )


@router.post("/ui/batch/run")
def batch_run(
    seed: int = Form(42),
    n: int = Form(200),
) -> RedirectResponse:
    n = max(10, min(int(n), 1000))
    record = run_eval(seed=int(seed), n=n, labels=["b2", "ours"])
    return RedirectResponse(url=f"/ui/batch?run={record.run_id}", status_code=303)


@router.get("/ui/batch/{run_id}", response_class=HTMLResponse)
def batch_run_view(request: Request, run_id: str) -> HTMLResponse:
    store = get_store()
    run = store.get(run_id)
    if run is None:
        return RedirectResponse(url="/ui/batch", status_code=303)
    return templates.TemplateResponse(
        request,
        "batch.html",
        {
            "run": run,
            "by_label": _metrics_by_label(run),
            "recent": store.list_runs(8),
        },
    )


@router.post("/ui/demo/replay")
def ui_demo_replay() -> RedirectResponse:
    session = SessionLocal()
    try:
        result = replay_fixture(session)
        session.commit()
        return RedirectResponse(
            url=f"/ui/cases/{result['case_id']}",
            status_code=303,
        )
    finally:
        session.close()


@router.get("/ui/cases/{case_id}", response_class=HTMLResponse)
def case_page(request: Request, case_id: str) -> HTMLResponse:
    session = SessionLocal()
    try:
        trail = get_case_trail(session, case_id)
        case = trail["case"]
        ledger = trail["ledger"]
        missing = case is None
        return templates.TemplateResponse(
            request,
            "case.html",
            {
                "case": case,
                "ledger": ledger or [],
                "missing": missing,
                "case_id": case_id,
            },
        )
    finally:
        session.close()
