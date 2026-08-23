"""
tests/test_webhooks_paid.py — Task 8 payment_link.paid live loop.
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
os.environ["RAZORPAY_WEBHOOK_SECRET"] = "whsec_test_paid"

from ledger.db import SessionLocal  # noqa: E402
from ledger.models import CaseRow  # noqa: E402
from ledger.schemas import CaseStatus, LedgerActor, LedgerKind  # noqa: E402
from ledger import writer  # noqa: E402
from main import app  # noqa: E402


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _sign(raw: bytes) -> str:
    return hmac.new(b"whsec_test_paid", raw, hashlib.sha256).hexdigest()


def _seed_case_with_plink(plink_id: str) -> str:
    session = SessionLocal()
    try:
        case = CaseRow(
            id=f"case_{uuid4().hex[:12]}",
            status=CaseStatus.open.value,
            payer_ref="payer_webhook_test",
            amount_paise=49900,
            rail="card",
        )
        session.add(case)
        session.flush()
        writer.append_ledger(
            session,
            case_id=case.id,
            kind=LedgerKind.outcome,
            actor=LedgerActor.system,
            payload={
                "ok": True,
                "external_id": plink_id,
                "status": "created_link",
                "note": "razorpay_payment_link_created",
            },
            reason_code="created_link",
            policy_version="test",
        )
        session.commit()
        return case.id
    finally:
        session.close()


def test_payment_link_paid_recovers_case(client: TestClient):
    plink = f"plink_test_{uuid4().hex[:10]}"
    case_id = _seed_case_with_plink(plink)
    event_id = f"evt_plpaid_{uuid4().hex[:8]}"
    payload = {
        "event": "payment_link.paid",
        "event_id": event_id,
        "payload": {
            "payment_link": {
                "entity": {
                    "id": plink,
                    "amount_paid": 49900,
                    "currency": "INR",
                    "notes": {"case_id": case_id},
                }
            },
            "payment": {"entity": {"id": f"pay_{uuid4().hex[:8]}", "amount": 49900}},
        },
    }
    raw = json.dumps(payload).encode("utf-8")
    r = client.post(
        "/webhooks/razorpay",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Signature": _sign(raw),
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["event"] == "payment_link.paid"
    assert body["case_id"] == case_id
    assert body["recovered"] is True
    assert body["payment_link_id"] == plink
    assert body["duplicate"] is False

    status = client.get(f"/cases/{case_id}/status")
    assert status.status_code == 200
    st = status.json()
    assert st["recovered"] is True
    assert st["status"] == "recovered"
    assert st["payment_link_id"] == plink
    assert st["webhook_paid"]["payment_link_id"] == plink


def test_payment_link_paid_idempotent(client: TestClient):
    plink = f"plink_test_{uuid4().hex[:10]}"
    case_id = _seed_case_with_plink(plink)
    event_id = f"evt_plpaid_{uuid4().hex[:8]}"
    payload = {
        "event": "payment_link.paid",
        "event_id": event_id,
        "payload": {
            "payment_link": {
                "entity": {
                    "id": plink,
                    "amount_paid": 49900,
                    "notes": {"case_id": case_id},
                }
            }
        },
    }
    raw = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-Razorpay-Signature": _sign(raw),
    }
    assert client.post("/webhooks/razorpay", content=raw, headers=headers).json()["duplicate"] is False
    assert client.post("/webhooks/razorpay", content=raw, headers=headers).json()["duplicate"] is True


def test_payment_link_paid_resolves_case_by_plink_lookup(client: TestClient):
    plink = f"plink_test_{uuid4().hex[:10]}"
    case_id = _seed_case_with_plink(plink)
    payload = {
        "event": "payment_link.paid",
        "event_id": f"evt_plpaid_{uuid4().hex[:8]}",
        "payload": {"payment_link": {"entity": {"id": plink, "amount_paid": 49900}}},
    }
    raw = json.dumps(payload).encode("utf-8")
    r = client.post(
        "/webhooks/razorpay",
        content=raw,
        headers={"Content-Type": "application/json", "X-Razorpay-Signature": _sign(raw)},
    )
    assert r.status_code == 200
    assert r.json()["case_id"] == case_id
