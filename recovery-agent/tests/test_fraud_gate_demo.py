"""Fraud gate demo + audit log."""

from __future__ import annotations

from guard.audit import build_audit_log, headline_gate_block
from ledger.db import SessionLocal
from ledger.service import get_case_trail

from demo.fraud_gate import run_fraud_gate_demo


def test_fraud_gate_demo_blocks_before_execute():
    result = run_fraud_gate_demo(amount_paise=10000)
    assert result["gate_success"] is True
    assert result["blocked_by"] == "prohibited_recovery"
    assert result["allowed"] is False
    assert result["failure_class"] == "risk_fraud"
    assert result["verb"] == "send_payment_link"


def test_audit_log_from_fraud_demo_trail():
    result = run_fraud_gate_demo(amount_paise=10000)
    session = SessionLocal()
    try:
        trail = get_case_trail(session, result["case_id"])
        audit = build_audit_log(trail["ledger"])
        assert audit
        block = headline_gate_block(audit)
        assert block is not None
        assert block.gate_name == "prohibited_recovery"
        assert block.verdict == "block"
        assert block.failure_class == "risk_fraud"
        assert block.proposed_verb == "send_payment_link"
        assert block.model == "scripted-demo-qwen3:8b"
        assert block.prompt_hash
    finally:
        session.close()
