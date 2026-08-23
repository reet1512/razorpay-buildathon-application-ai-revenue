"""
Deterministic logical identity for synthetic simulation episodes.

Same seed + case_id + simulation_version => same logical record (idempotency).
"""

from __future__ import annotations

import re

from memory.constants import SIMULATION_VERSION

_CASE_INDEX_RE = re.compile(r"_(\d+)$")


def logical_episode_id(
    *,
    seed: int,
    case_id: str,
    simulation_version: str = SIMULATION_VERSION,
) -> str:
    """Stable id used as episode_id and manifest key."""
    safe_case = case_id.replace("/", "_")
    return f"recovery_{simulation_version}_seed{seed}_{safe_case}"


def document_filename(
    *,
    seed: int,
    case_id: str,
    simulation_version: str = SIMULATION_VERSION,
) -> str:
    """Human-readable upload filename for Inherent."""
    idx = _case_index_from_key(case_id)
    return f"recovery-sim-{simulation_version}-seed{seed}-case{idx}.txt"


def _case_index_from_key(case_id: str) -> str:
    match = _CASE_INDEX_RE.search(case_id)
    if match:
        return str(int(match.group(1)))
    tail = case_id.rsplit("_", 1)[-1]
    return tail if tail.isdigit() else "0"
