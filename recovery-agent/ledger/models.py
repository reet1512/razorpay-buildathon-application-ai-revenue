"""
models.py — SQLAlchemy tables (what survives process restart).

Teaching contrast with schemas.py:
- schemas.RiskEvent  = validate + pass around in memory
- models.CaseRow     = row in the `cases` table on disk

We intentionally do NOT store RiskEvent as its own forever table.
Instead:
  1) upsert / open a Case
  2) append a ledger row (kind=event) with the RiskEvent JSON as payload
  3) mark event_id in processed_events for idempotency

That matches BUILD_TECH Phase 1.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ledger.db import Base


def utcnow() -> datetime:
    """Always store timezone-aware UTC. Avoid naive datetimes."""
    return datetime.now(timezone.utc)


class CaseRow(Base):
    """
    Mutable case status (solo shortcut).

    We update this row as the case progresses, BUT every meaningful change
    should ALSO be appended to ledger_entries so the trail never lies.
    """

    __tablename__ = "cases"

    # We use a string id (e.g. case_...) so it is easy to show in demos/logs.
    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    failure_class: Mapped[str | None] = mapped_column(String(64), nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)

    attempts_used: Mapped[int] = mapped_column(Integer, default=0)
    contacts_used: Mapped[int] = mapped_column(Integer, default=0)
    stop_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_action: Mapped[str | None] = mapped_column(String(64), nullable=True)

    payer_ref: Mapped[str] = mapped_column(String(64), index=True)
    amount_paise: Mapped[int] = mapped_column(Integer)
    rail: Mapped[str] = mapped_column(String(32))

    # Optional links back to recurring objects (filled when known).
    subscription_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mandate_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class LedgerEntryRow(Base):
    """
    Append-only audit log.

    Senior rule: NEVER update or delete these rows in product code.
    If you made a mistake, append a correcting fact — do not rewrite history.
    """

    __tablename__ = "ledger_entries"

    # Autoincrement seq gives us a total order for "what happened next".
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    case_id: Mapped[str] = mapped_column(String(64), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    kind: Mapped[str] = mapped_column(String(32), index=True)
    actor: Mapped[str] = mapped_column(String(32), default="system")

    # Which taxonomy/policy build produced this decision (matters for audits).
    policy_version: Mapped[str] = mapped_column(String(64), default="unset")

    # Free-form but structured JSON blob (RiskEvent, Action, gate detail, ...).
    payload_json: Mapped[str] = mapped_column(Text, default="{}")

    reason_code: Mapped[str] = mapped_column(String(128), default="")
    gate_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    gate_result: Mapped[str | None] = mapped_column(String(16), nullable=True)


class ProcessedEventRow(Base):
    """
    Idempotency table.

    Payments systems get duplicate webhooks. If event_id is already here,
    we must NO-OP instead of opening a second case / double-acting.
    """

    __tablename__ = "processed_events"
    __table_args__ = (UniqueConstraint("event_id", name="uq_processed_event_id"),)

    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(64), index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
