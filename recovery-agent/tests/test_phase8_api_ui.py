"""
tests/test_phase8_api_ui.py — Phase 8 routes + demo trail.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("APP_ENV", "dev")
os.environ["RAZORPAY_WEBHOOK_SECRET"] = "whsec_test_phase8"

from eval.run_store import EvalRunStore  # noqa: E402
from eval.service import run_eval  # noqa: E402
from main import app  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_runs(tmp_path, monkeypatch):
    d = tmp_path / "eval_runs"
    d.mkdir()
    monkeypatch.setenv("EVAL_RUN_DIR", str(d))
    import eval.run_store as rs

    rs._STORE = EvalRunStore(directory=d)
    yield


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_eval_run_and_get(client: TestClient):
    r = client.post("/eval/run", json={"seed": 42, "n": 40, "labels": ["b2", "ours"]})
    assert r.status_code == 200
    body = r.json()
    assert body["run_id"]
    assert len(body["metrics"]) == 2
    assert "ours" in body["gate_blocks"]
    assert body["gate_blocks"]["b2"] >= 0

    g = client.get(f"/eval/runs/{body['run_id']}")
    assert g.status_code == 200
    assert g.json()["n"] == 40


def test_demo_replay_and_case_trail(client: TestClient):
    # Unique event so replay is not stuck on a prior duplicate from recovery.db
    from demo import replay as replay_mod

    fixture = replay_mod.load_fixture()
    fixture = {**fixture, "event_id": f"demo_replay_{uuid4().hex[:10]}"}

    from ledger.db import SessionLocal

    session = SessionLocal()
    try:
        result = replay_mod.replay_fixture(session, fixture=fixture)
        session.commit()
        case_id = result["case_id"]
    finally:
        session.close()

    c = client.get(f"/cases/{case_id}")
    assert c.status_code == 200
    trail = c.json()
    kinds = [e["kind"] for e in trail["ledger"]]
    assert "classification" in kinds
    assert "decision" in kinds
    assert "gate_check" in kinds
    assert "outcome" in kinds

    actors = [e["actor"] for e in trail["ledger"]]
    assert "llm" in actors

    blocked = [
        e
        for e in trail["ledger"]
        if e.get("gate_result") == "block" and e.get("gate_name") == "contact_window"
    ]
    assert blocked, "demo must show a gate refusal row"

    ui = client.get(f"/ui/cases/{case_id}")
    assert ui.status_code == 200
    assert b"AI diagnosis" in ui.content
    assert b"contact_window" in ui.content
    assert b"block" in ui.content


def test_batch_ui_renders_after_run(client: TestClient):
    client.post("/eval/run", json={"seed": 7, "n": 30})
    page = client.get("/ui/batch")
    assert page.status_code == 200
    assert b"Recovery Agent" in page.content
    assert b"Gate blocks" in page.content


def test_webhook_ingest_with_signature(client: TestClient):
    pay_id = f"pay_phase8_{uuid4().hex[:8]}"
    payload = {
        "event": "payment.failed",
        "event_id": f"evt_phase8_{uuid4().hex[:8]}",
        "payload": {
            "payment": {
                "entity": {
                    "id": pay_id,
                    "amount": 19900,
                    "currency": "INR",
                    "method": "card",
                    "customer_id": "cust_x",
                    "error": {"code": "BAD_REQUEST_ERROR", "reason": "card_expired"},
                    "created_at": 1720000000,
                }
            }
        },
    }
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(b"whsec_test_phase8", raw, hashlib.sha256).hexdigest()
    r = client.post(
        "/webhooks/razorpay",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Signature": sig,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["duplicate"] is False
    assert body["case_id"]

    r2 = client.post(
        "/webhooks/razorpay",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Signature": sig,
        },
    )
    assert r2.json()["duplicate"] is True


def test_demo_replay_endpoint(client: TestClient):
    r = client.post("/demo/replay")
    assert r.status_code == 200
    assert r.json()["case_id"]


def test_run_eval_service_delta():
    rec = run_eval(seed=42, n=50, labels=["b2", "ours"])
    assert rec.delta_ours_vs_b2_inr is not None
    assert set(rec.gate_blocks) == {"b2", "ours"}
