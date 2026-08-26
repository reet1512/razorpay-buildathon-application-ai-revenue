"""
timing.py — when to act (salary window, short backoff, etc.).

Teaching:
- Taxonomy says *which* timing mode.
- This module turns that mode into concrete day_offsets for the sim,
  or datetimes for the product path later.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional


def salary_window_offsets(
    failure_dom: int,
    observed_credit_day: Optional[int],
) -> list[int]:
    """
    NSF / time-shiftable: prefer days near salary credit.

    If we have observed_credit_day, aim there (and nearby days).
    Else cover the common Indian salary cluster (days 1–7) with
    several offsets from failure_dom so we still hit a funded day.
    """
    if observed_credit_day is None:
        # No hint — fan out across likely payday cluster relative to failure.
        candidates = []
        for target in (1, 2, 3, 5, 7):
            delta = (target - failure_dom) % 28
            if delta == 0:
                delta = 1
            if delta not in candidates:
                candidates.append(delta)
        return sorted(candidates)[:4]

    delta = (observed_credit_day - failure_dom) % 28
    if delta == 0:
        # Failed on credit day already — don't retry the same empty moment.
        delta = 1
    # Cover credit day and the two following funded days in the payer model.
    offs = [delta, delta + 1, delta + 2]
    # Small early probe if the wait is long (funds sometimes clear early).
    if delta >= 4:
        offs.insert(0, max(1, delta // 2))
    # Dedupe preserve order
    seen: set[int] = set()
    out: list[int] = []
    for o in offs:
        if o not in seen and o >= 0:
            seen.add(o)
            out.append(o)
    return out


def short_backoff_offsets() -> list[int]:
    """Transient: retry same day and next day (sim granularity is days)."""
    return [0, 1]


def immediate_contact_offsets() -> list[int]:
    return [0]


def spaced_then_link_offsets() -> list[int]:
    """Ambiguous DNH-style: retry day 2, link day 4."""
    return [2, 4]


def offsets_for_timing(
    timing: str,
    *,
    failure_dom: int = 15,
    observed_credit_day: Optional[int] = None,
    max_retries: int = 2,
) -> list[int]:
    if timing == "salary_window":
        offs = salary_window_offsets(failure_dom, observed_credit_day)
        return offs[: max(0, max_retries)]
    if timing == "short_backoff":
        return short_backoff_offsets()[: max(0, max_retries)]
    if timing == "immediate_contact":
        return immediate_contact_offsets()
    if timing == "spaced_then_link":
        return spaced_then_link_offsets()
    if timing == "none":
        return []
    # Safe default
    return [1][: max(0, max_retries)]


def when_from_offset(base: datetime, day_offset: int) -> datetime:
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    return base + timedelta(days=day_offset)
