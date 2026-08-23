"""
ui_mock.py — Phase 1 UI mock data (presentation only).

Real backend integration comes in a later phase.
"""

from __future__ import annotations

from typing import Any


def overview_context() -> dict[str, Any]:
    return {
        "kpis": [
            {"label": "Net recovered", "value": "₹60.6K", "delta": "+12.4% vs last period"},
            {"label": "Recovery rate", "value": "48.7%", "delta": "+2.1 pts"},
            {"label": "Payments analyzed", "value": "1,240", "delta": "Last 30 days"},
            {"label": "Recovery success", "value": "72.3%", "delta": "AI-assisted cases"},
        ],
        "performance_chart": {
            "labels": ["Week 1", "Week 2", "Week 3", "Week 4"],
            "ai": [42, 48, 51, 55],
            "baseline": [38, 41, 43, 44],
        },
        "outcomes": [
            {"label": "Recovered", "count": 604, "pct": 48.7, "tone": "success"},
            {"label": "Retry pending", "count": 312, "pct": 25.2, "tone": "info"},
            {"label": "Failed", "count": 218, "pct": 17.6, "tone": "danger"},
            {"label": "Blocked by policy", "count": 106, "pct": 8.5, "tone": "warning"},
        ],
        "failure_reasons": [
            {"reason": "Insufficient funds", "count": 412, "pct": 33.2},
            {"reason": "Issuer transient", "count": 286, "pct": 23.1},
            {"reason": "Card expired", "count": 198, "pct": 16.0},
            {"reason": "Authentication failure", "count": 156, "pct": 12.6},
            {"reason": "Gateway timeout", "count": 98, "pct": 7.9},
            {"reason": "Other", "count": 90, "pct": 7.2},
        ],
        "recent_cases": [
            {
                "case_id": "CASE-10482",
                "payment": "₹499.00",
                "failure": "Insufficient funds",
                "strategy": "Retry after 24h",
                "outcome": "Recovered",
                "recovered_inr": "₹499",
                "time": "2.1h",
                "status": "recovered",
            },
            {
                "case_id": "CASE-10479",
                "payment": "₹1,299.00",
                "failure": "Issuer transient",
                "strategy": "Immediate retry",
                "outcome": "Recovered",
                "recovered_inr": "₹1,299",
                "time": "0.4h",
                "status": "recovered",
            },
            {
                "case_id": "CASE-10475",
                "payment": "₹499.00",
                "failure": "Insufficient funds",
                "strategy": "Retry after 48h",
                "outcome": "Pending",
                "recovered_inr": "—",
                "time": "—",
                "status": "pending",
            },
            {
                "case_id": "CASE-10471",
                "payment": "₹799.00",
                "failure": "Card expired",
                "strategy": "Payment link",
                "outcome": "Failed",
                "recovered_inr": "—",
                "time": "—",
                "status": "failed",
            },
            {
                "case_id": "CASE-10468",
                "payment": "₹499.00",
                "failure": "Risk / fraud",
                "strategy": "—",
                "outcome": "Blocked",
                "recovered_inr": "—",
                "time": "—",
                "status": "blocked",
            },
        ],
    }


def recover_workspace_context() -> dict[str, Any]:
    return {
        "payment": {
            "amount_inr": "₹499.00",
            "method": "Card",
            "failure": "Insufficient funds",
            "class": "Retry fixable",
            "payment_id": "pay_mock_8f2a91",
            "created": "23 Aug 2026, 09:41 IST",
            "customer": "cust_••••4821",
        },
        "pipeline": [
            {
                "num": "01",
                "key": "classification",
                "title": "Classification",
                "status": "done",
                "time": "09:41:03",
                "duration_ms": 12,
                "summary": "Insufficient funds",
                "detail": "Retry fixable · RETRY_FIXABLE",
            },
            {
                "num": "02",
                "key": "memory",
                "title": "Historical memory",
                "status": "done",
                "time": "09:41:03",
                "duration_ms": 187,
                "summary": "20 episodes retrieved",
                "detail": "15 comparable cases · Inherent",
            },
            {
                "num": "03",
                "key": "evidence",
                "title": "Evidence",
                "status": "done",
                "time": "09:41:04",
                "duration_ms": 45,
                "summary": "15 comparable cases",
                "detail": "Historical recovery rate 68.2%",
            },
            {
                "num": "04",
                "key": "strategies",
                "title": "Strategy analysis",
                "status": "done",
                "time": "09:41:04",
                "duration_ms": 28,
                "summary": "4 viable strategies",
                "detail": "Delayed retry · 24h strongest",
            },
            {
                "num": "05",
                "key": "economics",
                "title": "Economics",
                "status": "done",
                "time": "09:41:04",
                "duration_ms": 18,
                "summary": "Expected net ₹261",
                "detail": "Cost model · config/costs.json",
            },
            {
                "num": "06",
                "key": "ai",
                "title": "AI recommendation",
                "status": "done",
                "time": "09:41:05",
                "duration_ms": 1240,
                "summary": "Retry after 24 hours",
                "detail": "Confidence 95%",
            },
            {
                "num": "07",
                "key": "safety",
                "title": "Safety",
                "status": "done",
                "time": "09:41:05",
                "duration_ms": 8,
                "summary": "6 / 6 checks passed",
                "detail": "Recovery permitted",
            },
            {
                "num": "08",
                "key": "action",
                "title": "Action",
                "status": "waiting",
                "time": "—",
                "duration_ms": None,
                "summary": "Pending approval",
                "detail": "Awaiting operator action",
            },
        ],
        "decision": {
            "strategy": "Retry after 24 hours",
            "confidence_pct": 95,
            "comparable_cases": 15,
            "expected_net_inr": 261,
        },
        "safety_checks": [
            {"label": "Fraud policy", "status": "passed"},
            {"label": "Attempt cap", "status": "passed"},
            {"label": "Contact window", "status": "passed"},
            {"label": "Amount threshold", "status": "passed"},
            {"label": "Mandate validity", "status": "passed"},
            {"label": "Velocity limit", "status": "passed"},
        ],
        "strategies_preview": [
            {
                "label": "Immediate retry",
                "attempts": 8,
                "recovered": 2,
                "success_rate": 25.0,
                "avg_time_h": 2.1,
                "expected_net": 89,
                "selected": False,
            },
            {
                "label": "Delayed retry · 24h",
                "attempts": 11,
                "recovered": 8,
                "success_rate": 72.7,
                "avg_time_h": 21.4,
                "expected_net": 261,
                "selected": True,
            },
            {
                "label": "Delayed retry · 48h",
                "attempts": 5,
                "recovered": 3,
                "success_rate": 60.0,
                "avg_time_h": 44.0,
                "expected_net": 198,
                "selected": False,
            },
            {
                "label": "Manual review",
                "attempts": 3,
                "recovered": 1,
                "success_rate": 33.3,
                "avg_time_h": 31.0,
                "expected_net": 112,
                "selected": False,
            },
        ],
    }


def cases_list_context() -> dict[str, Any]:
    ctx = overview_context()
    return {
        "cases": ctx["recent_cases"]
        + [
            {
                "case_id": "CASE-10465",
                "payment": "₹2,499.00",
                "failure": "Gateway timeout",
                "strategy": "Reconcile",
                "outcome": "Recovered",
                "recovered_inr": "₹2,499",
                "time": "6.2h",
                "status": "recovered",
            },
            {
                "case_id": "CASE-10461",
                "payment": "₹499.00",
                "failure": "Token invalid",
                "strategy": "Update instrument",
                "outcome": "Pending",
                "recovered_inr": "—",
                "time": "—",
                "status": "pending",
            },
        ],
        "filters": ["All", "Failed", "Recoverable", "Recovered", "Blocked"],
    }


def case_detail_mock(case_id: str = "CASE-10482") -> dict[str, Any]:
    ws = recover_workspace_context()
    return {
        "case_id": case_id,
        "status": "recovered",
        "payment": ws["payment"],
        "pipeline": ws["pipeline"],
        "decision": ws["decision"],
        "safety_checks": ws["safety_checks"],
        "strategies": ws["strategies_preview"],
        "timeline_events": [
            {"time": "09:41:02", "title": "Payment failed", "detail": "Insufficient funds", "tone": "danger"},
            {"time": "09:41:03", "title": "Classified", "detail": "Retry fixable", "tone": "info"},
            {"time": "09:41:03", "title": "Historical memory", "detail": "20 episodes retrieved", "tone": "info"},
            {"time": "09:41:04", "title": "Evidence analyzed", "detail": "15 comparable cases", "tone": "info"},
            {"time": "09:41:04", "title": "Strategies compared", "detail": "4 viable recovery strategies", "tone": "info"},
            {"time": "09:41:04", "title": "AI recommendation", "detail": "Retry after 24 hours", "tone": "primary"},
            {"time": "09:41:04", "title": "Safety", "detail": "6/6 checks passed", "tone": "success"},
            {"time": "09:42:18", "title": "Recovery action", "detail": "Retry scheduled", "tone": "success"},
            {"time": "11:48:02", "title": "Recovered", "detail": "₹499.00 collected", "tone": "success"},
        ],
    }


def strategies_page_context() -> dict[str, Any]:
    ws = recover_workspace_context()
    return {
        "strategies": ws["strategies_preview"]
        + [
            {
                "label": "Payment link",
                "attempts": 14,
                "recovered": 9,
                "success_rate": 64.3,
                "avg_time_h": 18.5,
                "expected_net": 220,
                "cost_inr": 42,
                "selected": False,
            },
            {
                "label": "Do not retry",
                "attempts": 22,
                "recovered": 1,
                "success_rate": 4.5,
                "avg_time_h": 0,
                "expected_net": 12,
                "cost_inr": 8,
                "selected": False,
            },
        ],
        "filters": {
            "failure_types": ["All", "Insufficient funds", "Issuer transient", "Card expired"],
            "methods": ["All", "Card", "UPI", "Netbanking"],
            "periods": ["7d", "30d", "90d"],
        },
    }


def historical_page_context() -> dict[str, Any]:
    return {
        "stats": {
            "episodes": 200,
            "comparable": 15,
            "avg_similarity": 0.84,
            "latency_ms": 187,
        },
        "results": [
            {
                "case": "sim_42_0017",
                "similarity": 0.91,
                "failure": "Insufficient funds",
                "strategy": "Delayed retry · 24h",
                "outcome": "Recovered",
                "recovered_inr": "₹499",
                "date": "12 Aug 2026",
            },
            {
                "case": "sim_42_0033",
                "similarity": 0.88,
                "failure": "Insufficient funds",
                "strategy": "Delayed retry · 24h",
                "outcome": "Recovered",
                "recovered_inr": "₹499",
                "date": "08 Aug 2026",
            },
            {
                "case": "sim_42_0088",
                "similarity": 0.86,
                "failure": "Insufficient funds",
                "strategy": "Immediate retry",
                "outcome": "Failed",
                "recovered_inr": "—",
                "date": "02 Aug 2026",
            },
            {
                "case": "sim_42_0041",
                "similarity": 0.82,
                "failure": "Issuer transient",
                "strategy": "Immediate retry",
                "outcome": "Recovered",
                "recovered_inr": "₹499",
                "date": "28 Jul 2026",
            },
        ],
    }


def evaluate_ui_context(run=None, by_label=None) -> dict[str, Any]:
    mock = {
        "ours_inr": 60607,
        "baseline_inr": 59492,
        "advantage_inr": 1115,
        "recovery_rate_ours": 48.7,
        "recovery_rate_baseline": 46.2,
        "cost_per_rupee_ours": 0.082,
        "cost_per_rupee_baseline": 0.091,
        "wasted_ours": 124,
        "wasted_baseline": 186,
        "gate_blocks_ours": 18,
        "gate_blocks_baseline": 22,
        "run_history": [
            {"run_id": "run_a1b2c3", "seed": 42, "n": 200, "advantage": "+₹1,115", "date": "23 Aug 2026"},
            {"run_id": "run_d4e5f6", "seed": 43, "n": 200, "advantage": "+₹892", "date": "22 Aug 2026"},
        ],
    }
    if run and by_label and by_label.get("ours") and by_label.get("b2"):
        ours = by_label["ours"]
        b2 = by_label["b2"]
        mock["ours_inr"] = int(ours.net_recovered_inr)
        mock["baseline_inr"] = int(b2.net_recovered_inr)
        mock["advantage_inr"] = int(run.delta_net_ours_vs_b2_inr or 0)
        mock["recovery_rate_ours"] = round(ours.recovery_rate * 100, 1) if ours.recovery_rate else mock["recovery_rate_ours"]
        mock["recovery_rate_baseline"] = round(b2.recovery_rate * 100, 1) if b2.recovery_rate else mock["recovery_rate_baseline"]
        mock["has_run"] = True
        mock["run"] = run
        mock["by_label"] = by_label
    else:
        mock["has_run"] = False
    return mock


def api_docs_context() -> dict[str, Any]:
    return {
        "endpoints": [
            {
                "method": "POST",
                "path": "/agent/run",
                "title": "Run recovery agent",
                "description": "Classify failure and propose a recovery action.",
            },
            {
                "method": "GET",
                "path": "/cases/{case_id}",
                "title": "Get case",
                "description": "Retrieve case trail and ledger entries.",
            },
            {
                "method": "POST",
                "path": "/eval/run",
                "title": "Run evaluation",
                "description": "Batch compare AI recovery vs baseline.",
            },
            {
                "method": "POST",
                "path": "/webhooks/razorpay",
                "title": "Razorpay webhook",
                "description": "Ingest payment.failed and payment_link.paid events.",
            },
        ]
    }
