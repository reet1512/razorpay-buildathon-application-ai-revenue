"""
tests/test_policy_phase4.py — Phase 4 exit checks.

- Rules fallback runs a batch (ours via taxonomy)
- Expired card => 0 retries + link
- NSF => delayed retry (not day-0 spam)
- Validator repairs illegal AI retry on dead instrument
"""

from __future__ import annotations

from diagnose.classifier import classify
from eval.baselines import POLICIES
from eval.batch import generate_batch
from eval.metrics import compute_metrics
from eval.simulate import run_batch
from eval.types import FailureReason, SimVerb
from policy.engine import PolicyEngine
from policy.schemas import Action, ActionVerb, Channel, ProposedBy


def test_classifier_maps_card_expired():
    c = classify("card_expired", "BAD_REQUEST_ERROR")
    assert c.failure_class == "card_expired"
    assert c.matched_on == "reason"


def test_classifier_unknown_is_ambiguous():
    c = classify("some_weird_bank_string_xyz", "")
    assert c.failure_class == "ambiguous"


def test_expired_card_zero_retries_one_link():
    engine = PolicyEngine()
    bundle = engine.decide(
        raw_reason="card_expired",
        amount_paise=49900,
        failure_dom=10,
    )
    assert bundle.failure_class == "card_expired"
    assert all(a.verb != ActionVerb.schedule_retry for a in bundle.actions)
    assert any(a.verb == ActionVerb.send_payment_link for a in bundle.actions)
    assert bundle.actions[0].policy_version.startswith("2026")


def test_nsf_delayed_retry_not_immediate_when_credit_known():
    engine = PolicyEngine()
    bundle = engine.decide(
        raw_reason="insufficient_funds",
        amount_paise=99900,
        failure_dom=20,
        observed_credit_day=3,  # next month-ish wrap
    )
    retry_offsets = [
        a.day_offset for a in bundle.actions if a.verb == ActionVerb.schedule_retry
    ]
    assert retry_offsets, "NSF should schedule retries"
    assert 0 not in retry_offsets, "should not retry same empty day blindly"
    assert all(a.verb != ActionVerb.send_payment_link for a in bundle.actions)


def test_validator_blocks_retry_on_dead():
    engine = PolicyEngine()
    bad = Action(
        verb=ActionVerb.schedule_retry,
        day_offset=0,
        channel=Channel.none,
        proposed_by=ProposedBy.llm,
        reason_code="AI_HALUCINATION",
    )
    fixed = engine.validate_proposal(
        bad, failure_class="card_expired", amount_paise=49900, score=0.5
    )
    assert fixed.verb == ActionVerb.send_payment_link
    assert "validator_blocked_retry_on_dead" in fixed.note


def test_ours_taxonomy_runs_batch():
    seed, n = 42, 80
    cases = generate_batch(seed=seed, n=n)
    outcomes = run_batch(seed=seed, cases=cases, plan_fn=POLICIES["ours"])
    metrics = compute_metrics(label="ours", seed=seed, cases=cases, outcomes=outcomes)
    assert metrics.n == n
    assert metrics.at_risk_inr > 0


def test_ours_expired_plan_matches_yaml_contract():
    cases = generate_batch(seed=7, n=200)
    expired = next(
        c for c in cases if c.visible.failure_reason == FailureReason.card_expired
    )
    plan = POLICIES["ours"](expired)
    assert not any(a.verb == SimVerb.schedule_retry for a in plan)
    assert any(a.verb == SimVerb.send_payment_link for a in plan)
