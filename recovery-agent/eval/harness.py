"""
harness.py — CLI scoreboard entrypoint.

Examples (from recovery-agent/):
  python -m eval.harness --baseline b2 --seed 42 --n 500
  python -m eval.harness --policy ours --seed 42 --n 500
  python -m eval.harness --compare --seed 42 --n 500

Teaching:
- This file should stay thin: parse args -> generate batch -> simulate -> metrics -> print.
- If you feel like putting payer math here, you are in the wrong module.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Embeddable/local Python may not put the project root on sys.path.
# This keeps `python eval/harness.py` and `-m` style launches working.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from eval.baselines import POLICIES
from eval.batch import generate_batch, summarize_mix
from eval.metrics import compute_metrics, format_metrics
from eval.simulate import run_batch


def run_label(label: str, seed: int, n: int):
    if label not in POLICIES:
        raise SystemExit(f"Unknown policy/baseline '{label}'. Choose from: {sorted(POLICIES)}")
    cases = generate_batch(seed=seed, n=n)
    outcomes = run_batch(seed=seed, cases=cases, plan_fn=POLICIES[label])
    metrics = compute_metrics(label=label, seed=seed, cases=cases, outcomes=outcomes)
    return cases, outcomes, metrics


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Recovery Agent Phase 2 eval harness — measured INR on a seeded batch"
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument(
        "--baseline",
        choices=["b0", "b1", "b2", "b3"],
        help="Run a cause-blind baseline",
    )
    g.add_argument(
        "--policy",
        choices=["ours"],
        help="Run our early cause-aware policy stub",
    )
    g.add_argument(
        "--compare",
        action="store_true",
        help="Run b0,b1,b2,ours side by side on the same seed",
    )
    p.add_argument("--seed", type=int, default=42, help="RNG seed (default 42)")
    p.add_argument("--n", type=int, default=500, help="Batch size (default 500)")
    p.add_argument(
        "--json",
        action="store_true",
        help="Print metrics as JSON instead of text table",
    )
    p.add_argument(
        "--show-mix",
        action="store_true",
        help="Also print failure-reason mix counts",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    seed, n = args.seed, args.n

    if args.compare:
        labels = ["b0", "b1", "b2", "ours"]
        rows = []
        # Generate batch ONCE so every label sees identical cases.
        cases = generate_batch(seed=seed, n=n)
        if args.show_mix:
            print("decline_mix:", summarize_mix(cases))
        for label in labels:
            outcomes = run_batch(seed=seed, cases=cases, plan_fn=POLICIES[label])
            m = compute_metrics(label=label, seed=seed, cases=cases, outcomes=outcomes)
            rows.append(m)
        if args.json:
            print(json.dumps([r.model_dump() for r in rows], indent=2))
        else:
            for m in rows:
                print("-" * 40)
                print(format_metrics(m))
            # Helpful delta vs B2 for the pitch.
            ours = next(r for r in rows if r.label == "ours")
            b2 = next(r for r in rows if r.label == "b2")
            print("-" * 40)
            print(f"ours net_vs b2 (INR): {ours.net_vs(b2):,.2f}")
            print(
                f"ours contacts/recovery vs b2: "
                f"{ours.contacts_per_recovery} vs {b2.contacts_per_recovery}"
            )
        return 0

    label = args.baseline or args.policy
    cases, _outcomes, metrics = run_label(label, seed=seed, n=n)
    if args.show_mix:
        print("decline_mix:", summarize_mix(cases))
    if args.json:
        print(json.dumps(metrics.model_dump(), indent=2))
    else:
        print(format_metrics(metrics))
    return 0


if __name__ == "__main__":
    sys.exit(main())
