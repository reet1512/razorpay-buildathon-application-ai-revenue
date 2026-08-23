"""Tests for PaymentEpisode factory conversion."""

from __future__ import annotations

from eval.batch import generate_batch
from eval.baselines import POLICIES
from eval.recovery_class import RecoveryClass
from eval.simulate import run_batch
from eval.types import FailureReason
from memory.constants import SIMULATION_VERSION
from memory.episode_factory import (
    generate_episodes_for_seed,
    payment_episode_from_case,
)
from memory.episode_text import build_episode_text
from memory.identity import logical_episode_id
from memory.schemas import DataSource, EpisodeOutcome


def test_logical_identity_deterministic():
    a = logical_episode_id(seed=42, case_id="sim_42_0017", simulation_version=SIMULATION_VERSION)
    b = logical_episode_id(seed=42, case_id="sim_42_0017", simulation_version=SIMULATION_VERSION)
    assert a == b
    assert a.startswith("recovery_v1_")


def test_generate_episodes_for_seed_count():
    eps = generate_episodes_for_seed(42, 5)
    assert len(eps) == 5
    assert all(ep.data_source == DataSource.synthetic_simulation for ep in eps)
    assert all(ep.seed == 42 for ep in eps)


def test_episode_preserves_outcome_and_net():
    cases = generate_batch(seed=42, n=10)
    outcomes = run_batch(seed=42, cases=cases, plan_fn=POLICIES["ours"])
    for case, outcome in zip(cases, outcomes, strict=True):
        ep = payment_episode_from_case(case=case, outcome=outcome, seed=42)
        if outcome.recovered:
            assert ep.outcome == EpisodeOutcome.success
            assert ep.recovered_paise == outcome.recovered_paise
        else:
            assert ep.outcome == EpisodeOutcome.failed
        assert ep.net_recovered_paise is not None
        assert ep.net_recovered_paise <= ep.recovered_paise


def test_all_recovery_classes_represented():
    eps = generate_episodes_for_seed(42, 200)
    classes = {ep.recovery_class_value() for ep in eps}
    assert RecoveryClass.RETRY_FIXABLE.value in classes
    assert RecoveryClass.CUSTOMER_ACTION.value in classes
    assert RecoveryClass.AMBIGUOUS.value in classes
    assert RecoveryClass.PROHIBITED.value in classes


def test_failure_reasons_preserved():
    eps = generate_episodes_for_seed(42, 100)
    reasons = {ep.failure_reason_value() for ep in eps}
    for fr in FailureReason:
        assert fr.value in reasons


def test_semantic_text_includes_recovery_context():
    ep = generate_episodes_for_seed(42, 1)[0]
    text = build_episode_text(ep)
    assert ep.failure_reason_value().replace("_", " ") in text
    assert ep.recovery_class_value().replace("_", " ") in text
    assert "synthetic simulation" in text
    assert "metadata" in text.lower()
    assert "payer_" not in text


def test_metadata_fields():
    ep = generate_episodes_for_seed(42, 1)[0]
    meta = ep.metadata_for_ingest()
    assert meta["seed"] == 42
    assert meta["data_source"] == "synthetic_simulation"
    assert meta["recovery_class"]
    assert meta["failure_reason"]
    assert meta["action"]
    assert meta["outcome"]
