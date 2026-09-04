"""
tests/test_phase9_hardening.py — secrets check, log hygiene, webhook fail-closed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging

import pytest

from ingest.verify import unsigned_webhooks_allowed, verify_razorpay_signature
from logging_util import configure_logging, slog
from scripts.check_no_secrets import main as secrets_main

REAL_SECRET = "whsec_unit_test_secret"
BODY = b'{"event":"payment.failed"}'


def _sig(secret: str = REAL_SECRET, body: bytes = BODY) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_secrets_scan_clean():
    assert secrets_main() == 0


# --- webhook signature: fail-closed contract ------------------------------


def test_valid_signature_accepted():
    assert verify_razorpay_signature(BODY, _sig(), secret=REAL_SECRET) is True


def test_wrong_signature_rejected():
    assert verify_razorpay_signature(BODY, "deadbeef", secret=REAL_SECRET) is False


def test_missing_signature_rejected_even_with_real_secret():
    assert verify_razorpay_signature(BODY, None, secret=REAL_SECRET) is False


def test_tampered_body_rejected():
    assert verify_razorpay_signature(b'{"event":"tampered"}', _sig(), secret=REAL_SECRET) is False


def test_placeholder_secret_rejects_when_bypass_disabled(monkeypatch):
    """A fresh clone must NOT accept unsigned webhooks."""
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.delenv("ALLOW_UNSIGNED_WEBHOOKS", raising=False)
    assert verify_razorpay_signature(BODY, None, secret="xxx") is False
    assert verify_razorpay_signature(BODY, _sig(), secret="") is False


def test_placeholder_secret_allows_only_with_explicit_optin(monkeypatch):
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("ALLOW_UNSIGNED_WEBHOOKS", "1")
    assert unsigned_webhooks_allowed() is True
    assert verify_razorpay_signature(BODY, None, secret="xxx") is True


def test_bypass_never_allowed_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ALLOW_UNSIGNED_WEBHOOKS", "1")
    assert unsigned_webhooks_allowed() is False
    assert verify_razorpay_signature(BODY, None, secret="xxx") is False


@pytest.mark.parametrize("flag", ["0", "false", "no", "", "maybe"])
def test_bypass_requires_truthy_flag(monkeypatch, flag):
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("ALLOW_UNSIGNED_WEBHOOKS", flag)
    assert unsigned_webhooks_allowed() is False


def test_bypass_is_logged(caplog, monkeypatch):
    """A silent bypass would be worse than no bypass."""
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("ALLOW_UNSIGNED_WEBHOOKS", "1")
    configure_logging(logging.INFO)
    with caplog.at_level(logging.INFO, logger="recovery_agent"):
        assert verify_razorpay_signature(BODY, None, secret="xxx") is True
    events = [json.loads(r.message)["event"] for r in caplog.records]
    assert "webhook_signature_bypass" in events


def test_slog_emits_json_without_raw_body(caplog):
    configure_logging(logging.INFO)
    with caplog.at_level(logging.INFO, logger="recovery_agent"):
        slog(
            "unit_test",
            case_id="case_x",
            event_id="evt_y",
            verb="send_payment_link",
            gate="contact_window",
            status="blocked",
            raw="SHOULD_NOT_APPEAR",
            phone="9999999999",
        )
    assert caplog.records
    payload = json.loads(caplog.records[-1].message)
    assert payload["event"] == "unit_test"
    assert payload["case_id"] == "case_x"
    assert payload["gate"] == "contact_window"
    assert "raw" not in payload
    assert "phone" not in payload
