"""
execute/base.py — shared Outcome + Executor protocol.

Teaching:
- Guard decides WHETHER to execute.
- Executor decides HOW (sim vs Razorpay).
- Never call an executor before gates pass.
"""

from __future__ import annotations

from typing import Any, Optional, Protocol

from pydantic import BaseModel, Field

from ledger.models import CaseRow
from policy.schemas import Action


class Outcome(BaseModel):
    """Result of attempting an Action against a backend."""

    ok: bool
    external_id: Optional[str] = None  # plink_xxx / pay_xxx / sim_xxx
    recovered: bool = False
    status: str = "ok"  # ok | failed | skipped | created_link | escalated | reconciled_skip
    raw: dict[str, Any] = Field(default_factory=dict)
    note: str = ""


class ExecuteMeta(BaseModel):
    """Extra context adapters need (not always on CaseRow)."""

    failure_reason: str = "unknown"
    failure_dom: int = 15
    observed_credit_day: Optional[int] = None
    payment_ref: Optional[str] = None  # existing pay_ for reconcile
    dry_run: bool = False
    seed: str = "exec"


class Executor(Protocol):
    name: str

    def run(self, action: Action, case: CaseRow, meta: ExecuteMeta) -> Outcome: ...
