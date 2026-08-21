"""
api/routes_ui.py — Bottom-line proof home + Batch + Case screens.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from demo.live_flow import execute_link_for_case, run_ai_demo_case
from demo.replay import replay_fixture
from eval.run_store import get_store
from eval.service import run_eval
from eval.types import FailureReason
from ledger.db import SessionLocal
from ledger.models import LedgerEntryRow
from ledger.schemas import LedgerKind
from ledger.service import get_case_trail
from ai.client import LLMClient

# Demo picker labels (same keys as taxonomy / batch mix)
_FAILURE_OPTIONS = [
    (FailureReason.card_expired.value, "Card expired — usually Payment Link"),
    (FailureReason.insufficient_funds.value, "Insufficient funds — timed retry"),
    (FailureReason.issuer_transient.value, "Issuer transient — quick retry"),
    (FailureReason.gateway_timeout.value, "Gateway timeout — reconcile / retry"),
    (FailureReason.token_invalid.value, "Token invalid — update instrument"),
    (FailureReason.mandate_revoked.value, "Mandate revoked — re-auth / stop"),
    (FailureReason.do_not_honour.value, "Do not honour — careful contact"),
    (FailureReason.risk_fraud.value, "Risk / fraud — escalate / stop"),
]

_ROOT = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=str(_ROOT / "templates"))

router = APIRouter(tags=["ui"])


def _metrics_by_label(record) -> dict:
    return {m.label: m for m in record.metrics}


def _latest_live_plink(session) -> tuple[Optional[str], Optional[str]]:
    """Most recent ledger outcome with a real Razorpay plink_ id."""
    stmt = (
        select(LedgerEntryRow)
        .where(LedgerEntryRow.kind == LedgerKind.outcome.value)
        .order_by(LedgerEntryRow.seq.desc())
        .limit(40)
    )
    for row in session.scalars(stmt).all():
        try:
            payload = json.loads(row.payload_json or "{}")
        except json.JSONDecodeError:
            continue
        ext = str(payload.get("external_id") or "")
        if ext.startswith("plink_") and not ext.startswith("plink_test_"):
            return row.case_id, ext
    return None, None


@router.get("/", response_class=HTMLResponse)
@router.get("/ui", response_class=HTMLResponse)
def proof_home(request: Request) -> HTMLResponse:
    """Bottom-line demo page: measure · bound · real edge."""
    store = get_store()
    run = store.latest()
    session = SessionLocal()
    try:
        live_case_id, live_plink = _latest_live_plink(session)
    finally:
        session.close()
    ollama = LLMClient()
    return templates.TemplateResponse(
        request,
        "proof.html",
        {
            "run": run,
            "by_label": _metrics_by_label(run) if run else {},
            "live_case_id": live_case_id,
            "live_plink": live_plink,
            "ollama_up": ollama.available(),
            "ollama_model": ollama.model,
            "failure_options": _FAILURE_OPTIONS,
            "default_reason": FailureReason.card_expired.value,
        },
    )


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


@router.post("/ui/demo/ai-case")
def ui_ai_case(
    raw_error_reason: str = Form("card_expired"),
    amount_paise: int = Form(49900),
    force_fallback: str = Form("0"),
    refuse_at_gate: str = Form("0"),
    create_payment_link: str = Form("0"),
) -> RedirectResponse:
    """
    One-click video path: AI (or rules) → ledger → gates → optional Razorpay link.
    """
    try:
        result = run_ai_demo_case(
            raw_error_reason=raw_error_reason,
            amount_paise=int(amount_paise),
            force_fallback=force_fallback in {"1", "true", "on", "yes"},
            refuse_at_gate=refuse_at_gate in {"1", "true", "on", "yes"},
            create_payment_link=create_payment_link in {"1", "true", "on", "yes"},
        )
    except Exception as exc:
        # Don't dump a raw 500 in the demo — send back to proof with a hint.
        from urllib.parse import quote

        msg = quote(str(exc)[:180])
        return RedirectResponse(url=f"/ui?error={msg}", status_code=303)

    q = []
    if result.get("used_llm"):
        q.append("ai=1")
    else:
        q.append("ai=0")
    if result.get("blocked_by"):
        q.append(f"blocked={result['blocked_by']}")
    if result.get("external_id"):
        q.append(f"plink={result['external_id']}")
    qs = ("?" + "&".join(q)) if q else ""
    return RedirectResponse(
        url=f"/ui/cases/{result['case_id']}{qs}",
        status_code=303,
    )

@router.post("/ui/cases/{case_id}/create-link")
def ui_create_link(case_id: str) -> RedirectResponse:
    session = SessionLocal()
    try:
        result = execute_link_for_case(session, case_id)
        session.commit()
        qs = ""
        if result.get("external_id"):
            qs = f"?plink={result['external_id']}"
        elif result.get("blocked_by"):
            qs = f"?blocked={result['blocked_by']}"
        return RedirectResponse(url=f"/ui/cases/{case_id}{qs}", status_code=303)
    finally:
        session.close()


def _classify_case_source(ledger: list) -> dict:
    """
    Loud labels for judges: SIM batch fixture vs offline demo vs Razorpay live.
    """
    source = "unknown"
    plink = None
    plink_live = False
    has_llm = False
    has_gate_block = False
    event_source = None

    for e in ledger:
        kind = e.kind.value if hasattr(e.kind, "value") else str(e.kind)
        actor = e.actor.value if hasattr(e.actor, "value") else str(e.actor)
        payload = e.payload or {}
        gate_result = None
        if e.gate_result is not None:
            gate_result = (
                e.gate_result.value
                if hasattr(e.gate_result, "value")
                else str(e.gate_result)
            )

        if kind == "event":
            event_source = payload.get("source") or event_source
            eid = str(payload.get("event_id") or "")
            if eid.startswith("demo_replay"):
                source = "demo_fixture"
        if actor == "llm" or kind in {"classification", "decision"}:
            if actor == "llm":
                has_llm = True
        if gate_result == "block":
            has_gate_block = True
        if kind == "outcome":
            ext = str(payload.get("external_id") or "")
            note = str(payload.get("note") or "")
            if ext.startswith("plink_"):
                plink = ext
                if (
                    not ext.startswith("plink_test_")
                    and not ext.startswith("plink_demo_")
                    and "dry_run" not in note
                    and note == "razorpay_payment_link_created"
                ):
                    plink_live = True
                    source = "razorpay_live"
                elif source != "razorpay_live":
                    if ext.startswith("plink_demo_") or "fixture" in note:
                        source = "demo_fixture"

    if source == "unknown":
        if event_source == "razorpay_webhook":
            source = "razorpay_webhook"
        elif event_source == "simulator":
            source = "simulator"

    labels = {
        "demo_fixture": {
            "badge": "OFFLINE FIXTURE",
            "tone": "fixture",
            "blurb": "Pre-built trail for video backup — not a live Razorpay API call. Shows AI + gate refusal clearly.",
        },
        "ai_live": {
            "badge": "AI LIVE (OLLAMA)",
            "tone": "live",
            "blurb": "Diagnosis/proposal came from the local model. Check classification/decision rows with actor=llm.",
        },
        "ai_fallback": {
            "badge": "RULES FALLBACK",
            "tone": "sim",
            "blurb": "Ollama was down or forced off — taxonomy rules proposed the action. Still gated before execute.",
        },
        "simulator": {
            "badge": "SIM / LOCAL",
            "tone": "sim",
            "blurb": "Case opened from local/demo ingest. Execute may still create a real test-mode link if mode=razorpay.",
        },
        "razorpay_live": {
            "badge": "RAZORPAY TEST LIVE",
            "tone": "live",
            "blurb": "Real test-mode Payment Link created via Razorpay API. Match this plink_ id in the Razorpay dashboard.",
        },
        "razorpay_webhook": {
            "badge": "RAZORPAY WEBHOOK",
            "tone": "live",
            "blurb": "Ingested from a signed Razorpay webhook event (test mode).",
        },
        "unknown": {
            "badge": "CASE",
            "tone": "sim",
            "blurb": "Inspect the ledger rows below for source and outcome ids.",
        },
    }
    # Prefer razorpay_live if we have a real plink; else surface AI provenance
    if source != "razorpay_live" and source != "demo_fixture":
        if has_llm:
            source = "ai_live"
        elif any(
            (e.actor.value if hasattr(e.actor, "value") else str(e.actor)) == "policy"
            and (e.kind.value if hasattr(e.kind, "value") else str(e.kind))
            in {"classification", "decision"}
            for e in ledger
        ):
            source = "ai_fallback"

    meta = labels.get(source, labels["unknown"])
    # If we also have live plink, keep razorpay as primary badge but note AI
    if plink_live:
        source = "razorpay_live"
        meta = labels["razorpay_live"]
        if has_llm:
            meta = {
                **meta,
                "blurb": meta["blurb"]
                + " This case also has live AI (actor=llm) diagnosis above the link.",
            }
    return {
        "source_key": source,
        "badge": meta["badge"],
        "tone": meta["tone"],
        "blurb": meta["blurb"],
        "plink": plink,
        "plink_live": plink_live,
        "has_llm": has_llm,
        "has_gate_block": has_gate_block,
        "event_source": event_source,
    }


def _case_story(ledger: list, case) -> dict:
    """Plain-English progress for the case page header."""
    failure = None
    proposed = None
    by_ai = False
    by_rules = False
    gates = "none"
    blocked_by = None
    plink = None
    saw_gate = False

    for e in ledger:
        kind = e.kind.value if hasattr(e.kind, "value") else str(e.kind)
        actor = e.actor.value if hasattr(e.actor, "value") else str(e.actor)
        payload = e.payload or {}
        gate_result = None
        if e.gate_result is not None:
            gate_result = (
                e.gate_result.value
                if hasattr(e.gate_result, "value")
                else str(e.gate_result)
            )

        if kind == "event" and not failure:
            failure = payload.get("raw_error_reason") or payload.get("reason")
        if kind == "classification":
            failure = payload.get("likely_class") or failure
        if kind == "decision":
            action = payload.get("action") or payload
            if isinstance(action, dict):
                proposed = action.get("verb") or proposed
            if actor == "llm":
                by_ai = True
            elif actor == "policy":
                by_rules = True
        if kind == "gate_check":
            saw_gate = True
            if gate_result == "block":
                gates = "blocked"
                blocked_by = e.gate_name or payload.get("gate") or blocked_by
            elif gates != "blocked":
                gates = "passed"
        if kind == "outcome":
            ext = str(payload.get("external_id") or "")
            if ext.startswith("plink_"):
                plink = ext

    if case is not None and not failure:
        failure = getattr(case, "failure_class", None)

    if not saw_gate:
        gates = "none"

    if plink:
        next_hint = "Done for the live edge — open this plink_ in the Razorpay test dashboard."
    elif gates == "blocked":
        next_hint = "Gates refused contact. That is the compliance beat — try Step 2 again without “gate block”, or Step 3."
    elif gates == "passed":
        next_hint = "Gates allowed the action. Use the button below for Step 3 (Razorpay), or go home for Measure."
    elif proposed:
        next_hint = "Proposal is on the ledger. Gates should appear above — refresh if missing."
    else:
        next_hint = "Run Step 2 from the demo home to fill this trail."

    return {
        "failure": failure,
        "proposed": proposed,
        "by_ai": by_ai,
        "by_rules": by_rules,
        "gates": gates,
        "blocked_by": blocked_by,
        "plink": plink,
        "next_hint": next_hint,
    }


@router.get("/ui/cases/{case_id}", response_class=HTMLResponse)
def case_page(request: Request, case_id: str) -> HTMLResponse:
    session = SessionLocal()
    try:
        trail = get_case_trail(session, case_id)
        case = trail["case"]
        ledger = trail["ledger"] or []
        missing = case is None
        provenance = _classify_case_source(ledger) if not missing else None
        story = _case_story(ledger, case) if not missing else None
        return templates.TemplateResponse(
            request,
            "case.html",
            {
                "case": case,
                "ledger": ledger,
                "missing": missing,
                "case_id": case_id,
                "provenance": provenance,
                "story": story,
            },
        )
    finally:
        session.close()
