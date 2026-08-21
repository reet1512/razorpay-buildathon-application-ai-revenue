"""
eval/service.py — run compare/single batch for API + UI (metrics from metrics.py only).
"""

from __future__ import annotations

from typing import Optional

from eval.baselines import POLICIES
from eval.batch import generate_batch, summarize_mix
from eval.gate_estimate import count_gate_blocks
from eval.metrics import BatchMetrics, compute_metrics
from eval.run_store import EvalRunRecord, EvalRunStore, get_store, new_run_id, utc_now_iso
from eval.simulate import run_batch


def run_eval(
    *,
    seed: int = 42,
    n: int = 200,
    labels: Optional[list[str]] = None,
    store: Optional[EvalRunStore] = None,
) -> EvalRunRecord:
    """
    Generate one batch, score each label, estimate gate blocks, persist.
    Default labels: b2 + ours (Batch UI headline pair).
    """
    labels = labels or ["b2", "ours"]
    for lab in labels:
        if lab not in POLICIES:
            raise ValueError(f"unknown label {lab}; choose from {sorted(POLICIES)}")

    cases = generate_batch(seed=seed, n=n)
    mix = summarize_mix(cases)
    metrics: list[BatchMetrics] = []
    gate_blocks: dict[str, int] = {}

    for lab in labels:
        plan_fn = POLICIES[lab]
        outcomes = run_batch(seed=seed, cases=cases, plan_fn=plan_fn)
        m = compute_metrics(label=lab, seed=seed, cases=cases, outcomes=outcomes)
        metrics.append(m)
        gate_blocks[lab] = count_gate_blocks(cases, plan_fn)

    delta = None
    by_label = {m.label: m for m in metrics}
    if "ours" in by_label and "b2" in by_label:
        delta = round(by_label["ours"].net_vs(by_label["b2"]), 2)

    record = EvalRunRecord(
        run_id=new_run_id(),
        created_at=utc_now_iso(),
        seed=seed,
        n=n,
        labels=labels,
        metrics=metrics,
        gate_blocks=gate_blocks,
        decline_mix=mix,
        delta_ours_vs_b2_inr=delta,
    )
    return (store or get_store()).save(record)
