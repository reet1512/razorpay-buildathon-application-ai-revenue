"""One-off metrics helper for sprint execution."""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from policy.engine import reset_engine  # noqa: E402

reset_engine()

from eval.baselines import POLICIES  # noqa: E402
from eval.batch import generate_batch  # noqa: E402
from eval.benchmark import compare_seed  # noqa: E402
from eval.recovery_class import recovery_class_for  # noqa: E402
from eval.simulate import run_batch  # noqa: E402


def segment_rates(seed: int, n: int) -> dict:
    cases = generate_batch(seed, n)
    out: dict = {}
    for label in ("ours", "b2"):
        outs = run_batch(seed, cases, POLICIES[label])
        by: dict = defaultdict(lambda: {"n": 0, "rec": 0})
        for c, o in zip(cases, outs):
            rc = recovery_class_for(c.visible.failure_reason).value
            by[rc]["n"] += 1
            if o.recovered:
                by[rc]["rec"] += 1
        out[label] = {
            rc: {
                "n": s["n"],
                "rec_rate": round(s["rec"] / s["n"], 4) if s["n"] else 0.0,
            }
            for rc, s in sorted(by.items())
        }
    return out


def compare(seed: int, n: int) -> dict:
    r = compare_seed(seed, n)
    return {
        "seed": seed,
        "n": n,
        "ours_rr": round(r.ours.recovery_rate, 6),
        "b2_rr": round(r.b2.recovery_rate, 6),
        "ours_net": round(r.ours.net_recovered_inr, 2),
        "b2_net": round(r.b2.net_recovered_inr, 2),
        "delta_net": round(r.delta_net_recovered_inr, 2),
        "ours_gross": round(r.ours.gross_recovered_inr, 2),
        "b2_gross": round(r.b2.gross_recovered_inr, 2),
        "ours_wasted": int(getattr(r.ours, "wasted_attempts", 0) or 0),
        "b2_wasted": int(getattr(r.b2, "wasted_attempts", 0) or 0),
    }


def main() -> int:
    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)
    out_name = sys.argv[1] if len(sys.argv) > 1 else "metrics_run_seed42.json"
    payload: dict = {"compare": {}, "segments_n500": {}}
    for n in (200, 500, 1000):
        row = compare(42, n)
        payload["compare"][f"n{n}"] = row
        print(json.dumps(row), flush=True)
    segs = segment_rates(42, 500)
    payload["segments_n500"] = segs
    print("SEGMENTS " + json.dumps(segs), flush=True)
    path = artifacts / out_name
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"WROTE {path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
