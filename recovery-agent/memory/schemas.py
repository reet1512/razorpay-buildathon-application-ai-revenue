"""
memory/schemas.py — payment recovery episode shapes for Inherent memory.

Thin models that reuse existing domain vocabulary (FailureReason, RecoveryClass,
Rail, ActionVerb) without duplicating ledger or eval domain objects.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from eval.recovery_class import RecoveryClass
from eval.types import FailureReason
from ledger.schemas import Rail
from policy.schemas import ActionVerb


class DataSource(str, Enum):
    """Provenance tag — never mislabel synthetic data as production."""

    synthetic_simulation = "synthetic_simulation"
    razorpay_test = "razorpay_test"
    demo = "demo"


class EpisodeOutcome(str, Enum):
    success = "success"
    failed = "failed"
    pending = "pending"


class PaymentEpisode(BaseModel):
    """
    One historical recovery episode for semantic memory.

    Identifiers must be synthetic/anonymized. No payer PII, no secrets.
    """

    episode_id: str = Field(description="Synthetic id, e.g. recovery_v1_seed42_sim_42_0017")
    case_id: Optional[str] = Field(default=None, description="Simulator case_key")
    seed: Optional[int] = Field(default=None, description="Batch seed that generated case")
    simulation_version: str = Field(default="v1")
    amount_paise: int = Field(ge=0)
    currency: str = "INR"
    rail: Rail | str = Rail.card
    failure_reason: FailureReason | str
    recovery_class: RecoveryClass | str
    attempt_number: int = Field(default=1, ge=1)
    action: ActionVerb | str
    outcome: EpisodeOutcome
    recovered_paise: int = Field(default=0, ge=0)
    net_recovered_paise: Optional[int] = Field(default=None, ge=0)
    data_source: DataSource
    delay_seconds: Optional[int] = Field(default=None, ge=0)
    prohibited: bool = Field(default=False, description="Recovery class PROHIBITED")
    customer_type: Optional[str] = Field(
        default=None,
        description="Coarse label only, e.g. returning — no PII",
    )

    def rail_value(self) -> str:
        return self.rail.value if isinstance(self.rail, Rail) else str(self.rail)

    def failure_reason_value(self) -> str:
        if isinstance(self.failure_reason, FailureReason):
            return self.failure_reason.value
        return str(self.failure_reason)

    def recovery_class_value(self) -> str:
        if isinstance(self.recovery_class, RecoveryClass):
            return self.recovery_class.value
        return str(self.recovery_class)

    def action_value(self) -> str:
        if isinstance(self.action, ActionVerb):
            return self.action.value
        return str(self.action)

    def amount_bucket(self) -> str:
        from ai.agent import amount_bucket_inr

        return amount_bucket_inr(self.amount_paise)

    def metadata_for_ingest(self) -> dict[str, Any]:
        """Structured metadata embedded in episode text (no secrets)."""
        meta: dict[str, Any] = {
            "episode_id": self.episode_id,
            "case_id": self.case_id,
            "seed": self.seed,
            "simulation_version": self.simulation_version,
            "amount_paise": self.amount_paise,
            "amount_bucket": self.amount_bucket(),
            "currency": self.currency,
            "rail": self.rail_value(),
            "failure_reason": self.failure_reason_value(),
            "recovery_class": self.recovery_class_value(),
            "attempt_number": self.attempt_number,
            "action": self.action_value(),
            "outcome": self.outcome.value,
            "recovered_paise": self.recovered_paise,
            "net_recovered_paise": self.net_recovered_paise,
            "data_source": self.data_source.value,
            "prohibited": self.prohibited,
        }
        if self.delay_seconds is not None:
            meta["delay_seconds"] = self.delay_seconds
        if self.customer_type:
            meta["customer_type"] = self.customer_type
        return meta


class RetrievalResult(BaseModel):
    """
    One retrieved episode from Inherent.

    Fields populated only from actual API response parsing — may be sparse
    if the upstream schema differs from expectations.
    """

    episode_id: Optional[str] = None
    document_id: Optional[str] = None
    document_name: Optional[str] = None
    content: Optional[str] = None
    score: Optional[float] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
