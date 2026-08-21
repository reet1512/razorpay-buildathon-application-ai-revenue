"""
execute/sim_adapter.py — simulated execution for scale + offline demos.

Uses the same domain intuitions as eval/payer_model (instrument validity,
salary window, contact response) but for a single Action on one Case.
"""

from __future__ import annotations

import random
from typing import Optional

from execute.base import ExecuteMeta, Outcome
from ledger.models import CaseRow
from policy.schemas import Action, ActionVerb


class SimExecutor:
    """
    Offline executor.

    Does NOT talk to Razorpay. Safe for n=500 style loops and CI.
    """

    name = "sim"

    def run(self, action: Action, case: CaseRow, meta: ExecuteMeta) -> Outcome:
        rng = random.Random(f"{meta.seed}:{case.id}:{action.verb.value}:{action.day_offset}")

        if action.verb == ActionVerb.escalate_human:
            return Outcome(
                ok=True,
                external_id=f"sim_esc_{case.id[:8]}",
                recovered=False,
                status="escalated",
                note="handed_to_human",
            )

        reason = (meta.failure_reason or "").lower()
        dead = reason in {
            "card_expired",
            "token_invalid",
            "mandate_revoked",
        }

        if action.verb == ActionVerb.schedule_retry:
            if dead:
                return Outcome(
                    ok=False,
                    external_id=f"sim_retry_{rng.randint(1000,9999)}",
                    recovered=False,
                    status="failed",
                    note="dead_instrument_retry_impossible",
                    raw={"reason": reason},
                )
            # NSF succeeds more near salary window offsets
            funded = _funds_likely(meta, action.day_offset or 0)
            p = 0.85 if funded else 0.08
            if reason in {"issuer_transient", "gateway_timeout"}:
                p = 0.75
            recovered = rng.random() < p
            return Outcome(
                ok=recovered,
                external_id=f"sim_pay_{rng.randint(10000,99999)}",
                recovered=recovered,
                status="ok" if recovered else "failed",
                note="sim_retry",
                raw={"p": p, "funded": funded},
            )

        if action.verb in {
            ActionVerb.send_payment_link,
            ActionVerb.request_mandate_update,
        }:
            # Dead instruments recover via link more often than silent retry
            p = 0.40 if dead else 0.22
            recovered = rng.random() < p
            return Outcome(
                ok=True,  # link creation "succeeds" even if payer ignores
                external_id=f"sim_plink_{rng.randint(10000,99999)}",
                recovered=recovered,
                status="created_link",
                note="sim_link_sent",
                raw={"payer_acted": recovered, "p": p},
            )

        return Outcome(ok=False, status="failed", note="unknown_verb")


def _funds_likely(meta: ExecuteMeta, day_offset: int) -> bool:
    credit: Optional[int] = meta.observed_credit_day
    if credit is None:
        # Unknown credit day: mild chance
        return day_offset >= 3
    failure_dom = meta.failure_dom
    abs_dom = ((failure_dom - 1 + day_offset) % 28) + 1
    window = {credit, (credit % 28) + 1, ((credit + 1) % 28) + 1}
    return abs_dom in window
