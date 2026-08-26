"""
api/routes_ui.py — Bottom-line proof home + Batch + Case screens.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from config.costs import all_costs
from demo.fraud_gate import run_fraud_gate_demo
from demo.live_flow import execute_link_for_case, iter_ai_demo_case, run_ai_demo_case
from demo.replay import replay_fixture
from eval.break_even import solve_break_even
from eval.benchmark import DEFAULT_MULTI_SEEDS, parse_seeds_arg
from eval.run_store import get_store
from eval.service import run_eval, run_multi_seed_report
from eval.types import FailureReason
from ledger.db import SessionLocal
from ledger.models import LedgerEntryRow
from ledger.schemas import LedgerKind
from guard.audit import build_audit_log, headline_gate_block
from ledger import reader
from ledger.service import get_case_trail
from ai.client import LLMClient
from api.ui_helpers import (
    build_case_view,
    platform_metrics,
    rag_status_payload,
    recover_demo_context,
)
from api.ui_mock import (
    api_docs_context,
    case_detail_mock,
    cases_list_context,
    evaluate_ui_context,
    historical_page_context,
    intelligence_hub_context,
    overview_context,
    recover_page_context,
    recover_workspace_context,
    strategies_page_context,
)

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

# Subset of costs.json editable in the assumptions panel (Task 6).
_EDITABLE_COST_KEYS = (
    "attempt.sms_dlt",
    "attempt.whatsapp_utility",
    "attempt.email",
    "success.mdr_pct",
    "customer.churn_prob_per_inappropriate_contact",
    "customer.ltv",
    "risk.support_ticket",
    "risk.chargeback_fee",
)


def _parse_cost_overrides(form) -> dict[str, float]:
    overrides: dict[str, float] = {}
    for key in _EDITABLE_COST_KEYS:
        field = key.replace(".", "__")
        raw = form.get(f"cost_{field}")
        if raw is None or str(raw).strip() == "":
            continue
        try:
            overrides[key] = float(raw)
        except ValueError:
            continue
    return overrides


def _batch_context(run, *, break_even=None, multi_report=None) -> dict:
    ctx = {
        "run": run,
        "by_label": _metrics_by_label(run) if run else {},
        "recent": get_store().list_runs(8),
        "cost_params": all_costs(),
        "editable_cost_keys": _EDITABLE_COST_KEYS,
        "break_even": break_even,
        "multi_report": multi_report,
    }
    return ctx


def _metrics_by_label(record) -> dict:
    return {m.label: m for m in record.metrics}


def _latest_live_plink(session) -> tuple[Optional[str], Optional[str], Optional[float]]:
    """Most recent ledger outcome with a real Razorpay plink_ id + amount INR."""
    from ledger.models import CaseRow

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
            amount_inr = None
            case = session.get(CaseRow, row.case_id)
            if case is not None:
                amount_inr = round(case.amount_paise / 100.0, 2)
            return row.case_id, ext, amount_inr
    return None, None, None


def _demo_context(
    *,
    run=None,
    live_case_id=None,
    live_plink=None,
    live_amount_inr=None,
) -> dict:
    ollama = LLMClient()
    by_label = _metrics_by_label(run) if run else {}
    return {
        "run": run,
        "by_label": by_label,
        "live_case_id": live_case_id,
        "live_plink": live_plink,
        "live_amount_inr": live_amount_inr,
        "ollama_up": ollama.available(),
        "ollama_model": ollama.model,
        "failure_options": _FAILURE_OPTIONS,
        "default_reason": FailureReason.insufficient_funds.value,
        "demo_amount_inr": 499.0,
        "platform": platform_metrics(run, by_label),
        **recover_demo_context(),
    }


@router.get("/", response_class=HTMLResponse)
def landing_page() -> RedirectResponse:
    return RedirectResponse(url="/ui", status_code=303)


@router.get("/sign-in", response_class=HTMLResponse)
def sign_in_page() -> RedirectResponse:
    return RedirectResponse(url="/ui", status_code=303)


@router.post("/sign-in")
def sign_in_submit() -> RedirectResponse:
    return RedirectResponse(url="/ui", status_code=303)


@router.get("/sign-out")
def sign_out() -> RedirectResponse:
    return RedirectResponse(url="/ui", status_code=303)


@router.get("/ui", response_class=HTMLResponse)
def app_overview(request: Request) -> HTMLResponse:
    """Ours vs B2 recovery stats, RAG, and agentic recovery."""
    store = get_store()
    run_id = request.query_params.get("run")
    run = store.get(run_id) if run_id else store.latest()
    if run is None and run_id:
        run = store.latest()
    by_label = _metrics_by_label(run) if run else {}
    platform = platform_metrics(run, by_label)
    eval_ui = evaluate_ui_context(run, by_label)
    ollama = LLMClient()
    return templates.TemplateResponse(
        request,
        "product/overview.html",
        {
            "nav_active": "overview",
            "eval_ui": eval_ui,
            "platform": platform,
            "run": run,
            "ollama_up": ollama.available(),
            "ollama_model": ollama.model,
            "error": request.query_params.get("error"),
        },
    )


@router.get("/ui/rag-status")
def ui_rag_status(request: Request) -> JSONResponse:
    """Live Inherent / RAG status for Stats page polling (Public API :18000)."""
    force = request.query_params.get("force", "1") not in ("0", "false", "no")
    return JSONResponse(rag_status_payload(force=force))


@router.get("/ui/evaluate", response_class=HTMLResponse)
def evaluate_page(request: Request) -> RedirectResponse:
    run_id = request.query_params.get("run")
    url = f"/ui?run={run_id}" if run_id else "/ui"
    return RedirectResponse(url=url, status_code=303)


@router.get("/ui/recover", response_class=HTMLResponse)
def recover_page(request: Request) -> HTMLResponse:
    """Simulated recovery pipeline with live thinking."""
    ctx = _demo_context()
    ctx["nav_active"] = "recover"
    ctx["think_live"] = 0
    return templates.TemplateResponse(request, "product/recover.html", ctx)


@router.get("/ui/intelligence", response_class=HTMLResponse)
def intelligence_hub_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "product/intelligence.html",
        {
            "nav_active": "intelligence",
            "sidebar": True,
            "intel_active": "overview",
            "mock": intelligence_hub_context(),
        },
    )


@router.get("/ui/cases", response_class=HTMLResponse)
def cases_list_page(request: Request) -> HTMLResponse:
    """All recovery cases — mock list for Phase 1 UI."""
    return templates.TemplateResponse(
        request,
        "product/cases.html",
        {"nav_active": "cases", "sidebar": True, "mock": cases_list_context()},
    )


@router.get("/ui/intelligence/strategies", response_class=HTMLResponse)
def intelligence_strategies_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "product/strategies.html",
        {
            "nav_active": "intelligence",
            "sidebar": True,
            "intel_active": "strategies",
            "mock": strategies_page_context(),
        },
    )


@router.get("/ui/intelligence/historical", response_class=HTMLResponse)
def intelligence_historical_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "product/historical.html",
        {
            "nav_active": "intelligence",
            "sidebar": True,
            "intel_active": "historical",
            "mock": historical_page_context(),
        },
    )


@router.get("/ui/api", response_class=HTMLResponse)
def api_docs_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "product/api.html",
        {"nav_active": "api", "mock": api_docs_context()},
    )


@router.get("/ui/live-test", response_class=HTMLResponse)
def live_test_page(request: Request) -> HTMLResponse:
    """Live Razorpay test payment loop."""
    session = SessionLocal()
    try:
        live_case_id, live_plink, live_amount_inr = _latest_live_plink(session)
    finally:
        session.close()
    ctx = _demo_context(
        live_case_id=live_case_id,
        live_plink=live_plink,
        live_amount_inr=live_amount_inr,
    )
    ctx["nav_active"] = "live_test"
    ctx["think_live"] = 1
    return templates.TemplateResponse(request, "product/live_test.html", ctx)


@router.get("/ui/batch", response_class=HTMLResponse)
def batch_page(request: Request) -> HTMLResponse:
    """Legacy alias — redirects to Evaluate."""
    run_id = request.query_params.get("run")
    url = f"/ui?run={run_id}" if run_id else "/ui"
    return RedirectResponse(url=url, status_code=303)


@router.post("/ui/batch/run")
async def batch_run(request: Request) -> RedirectResponse:
    form = await request.form()
    seed = int(form.get("seed", 42))
    n = max(10, min(int(form.get("n", 200)), 1000))
    overrides = _parse_cost_overrides(form)
    record = run_eval(
        seed=seed,
        n=n,
        labels=["b2", "ours"],
        cost_overrides=overrides or None,
    )
    return RedirectResponse(url=f"/ui?run={record.run_id}", status_code=303)


@router.get("/ui/batch/distribution", response_class=HTMLResponse)
def batch_distribution_page(request: Request) -> HTMLResponse:
    n = int(request.query_params.get("n", 200))
    seeds_raw = request.query_params.get("seeds", "42-51")
    try:
        seeds = parse_seeds_arg(seeds_raw)
    except ValueError:
        seeds = list(DEFAULT_MULTI_SEEDS)
    report = run_multi_seed_report(seeds=seeds, n=max(10, min(n, 1000)))
    return templates.TemplateResponse(
        request,
        "distribution.html",
        {
            "report": report,
            "seeds_arg": seeds_raw,
            "n": n,
        },
    )


@router.post("/ui/batch/distribution/run")
def batch_distribution_run(
    n: int = Form(200),
    seeds: str = Form("42-51"),
) -> RedirectResponse:
    n = max(10, min(int(n), 1000))
    try:
        parse_seeds_arg(seeds)
    except ValueError:
        seeds = "42-51"
    from urllib.parse import quote

    return RedirectResponse(
        url=f"/ui/batch/distribution?n={n}&seeds={quote(seeds)}",
        status_code=303,
    )


@router.get("/ui/batch/{run_id}", response_class=HTMLResponse)
def batch_run_view(request: Request, run_id: str) -> HTMLResponse:
    store = get_store()
    run = store.get(run_id)
    if run is None:
        return RedirectResponse(url="/ui/batch", status_code=303)
    break_even = solve_break_even(seed=run.seed, n=run.n)
    return templates.TemplateResponse(
        request,
        "batch.html",
        _batch_context(run, break_even=break_even),
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


@router.post("/ui/demo/fraud-gate")
def ui_fraud_gate_demo() -> RedirectResponse:
    """Scripted beat: model proposes contact on risk/fraud; gate blocks (success)."""
    try:
        result = run_fraud_gate_demo()
    except Exception as exc:
        from urllib.parse import quote

        msg = quote(str(exc)[:180])
        return RedirectResponse(url=f"/ui?error={msg}", status_code=303)

    qs = "?gate=prohibited&demo=fraud"
    if result.get("blocked_by"):
        qs += f"&blocked={result['blocked_by']}"
    return RedirectResponse(url=f"/ui/cases/{result['case_id']}{qs}", status_code=303)


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


def _sse_pack(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.get("/ui/demo/think")
def think_stream(
    raw_error_reason: str = "insufficient_funds",
    amount_paise: int = 49900,
    live: int = 0,
):
    """Server-sent pipeline steps for Simulate and Live thinking views."""

    def gen():
        try:
            for ev in iter_ai_demo_case(
                raw_error_reason=raw_error_reason,
                amount_paise=int(amount_paise),
                create_payment_link=bool(int(live)),
            ):
                yield _sse_pack(ev.get("event") or "step", ev)
        except Exception as exc:
            yield _sse_pack("fail", {"message": str(exc)[:240]})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
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
            action = payload.get("validated") or payload.get("action") or payload
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
        if case is not None:
            status_val = (
                case.status.value
                if hasattr(case.status, "value")
                else str(case.status)
            )
            if status_val == "recovered":
                next_hint = "Recovered — payment_link.paid received. Match webhook payload below against Razorpay dashboard."
            else:
                next_hint = (
                    "Payment Link created. Pay in Razorpay test mode (or POST payment_link.paid webhook). "
                    "This page refreshes when status flips to RECOVERED."
                )
        else:
            next_hint = "Done for the live edge — open this plink_ in the Razorpay test dashboard."
    elif gates == "blocked":
        next_hint = (
            "Gate blocked this action — that is the product working. "
            "Compliance refused before any money moved."
        )
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
        "recovered": (
            case is not None
            and (
                case.status.value if hasattr(case.status, "value") else str(case.status)
            )
            == "recovered"
        ),
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
        webhook_paid = reader.latest_payment_link_paid_payload(session, case_id) if not missing else None
        audit_log = build_audit_log(ledger) if not missing else []
        gate_block = headline_gate_block(audit_log) if audit_log else None
        case_view = (
            build_case_view(
                case=case,
                ledger=ledger,
                story=story,
                audit_log=audit_log,
                provenance=provenance,
            )
            if not missing and story
            else None
        )
        mock = case_detail_mock(case_id)
        st = case.status.value if case and hasattr(case.status, "value") else (str(case.status) if case else "pending")
        if missing:
            return templates.TemplateResponse(
                request,
                "product/case_detail.html",
                {
                    "nav_active": "cases",
                    "case_id": case_id,
                    "display_id": case_id,
                    "display_status": "pending",
                    "display_payment": mock["payment"],
                    "mock": mock,
                    "case_view": None,
                    "ledger": [],
                    "missing": True,
                },
            )
        display_payment = (
            {
                "amount_inr": case_view["payment"]["amount_inr"],
                "failure": case_view["payment"]["failure_label"],
                "failure_label": case_view["payment"]["failure_label"],
            }
            if case_view
            else mock["payment"]
        )
        return templates.TemplateResponse(
            request,
            "product/case_detail.html",
            {
                "nav_active": "cases",
                "case": case,
                "ledger": ledger,
                "missing": missing,
                "case_id": case_id,
                "display_id": case_id,
                "display_status": st,
                "display_payment": display_payment,
                "provenance": provenance,
                "story": story,
                "webhook_paid": webhook_paid,
                "audit_log": audit_log,
                "gate_block": gate_block,
                "case_view": case_view,
                "mock": mock,
            },
        )
    finally:
        session.close()
