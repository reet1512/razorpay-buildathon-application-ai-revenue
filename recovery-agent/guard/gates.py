"""
guard/gates.py — five hard gates that can veto an Action.

Each gate returns GateCheck (name, passed, reason_code).
Pipeline records EVERY check to the ledger (pass and block).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta, timezone

from guard.context import GuardContext
from policy.schemas import ActionVerb, Channel

PROHIBITED_FAILURE_CLASSES = frozenset({"risk_fraud"})


@dataclass(frozen=True)
class GateCheck:
    name: str
    passed: bool
    reason_code: str

    @property
    def gate_result(self) -> str:
        return "pass" if self.passed else "block"


def _is_contact_action(ctx: GuardContext) -> bool:
    a = ctx.action
    if a.verb in {ActionVerb.send_payment_link, ActionVerb.request_mandate_update}:
        return True
    if a.channel in {Channel.sms, Channel.email, Channel.link}:
        return True
    return False


def _is_money_action(ctx: GuardContext) -> bool:
    return ctx.action.verb in {
        ActionVerb.schedule_retry,
        ActionVerb.send_payment_link,
        ActionVerb.request_mandate_update,
    }


def gate_prohibited_recovery(ctx: GuardContext) -> GateCheck:
    """
    Block automated money movement / contact on PROHIBITED (risk/fraud).

    escalate_human is always allowed. Compliance blocks here — not the payer model.
    """
    name = "prohibited_recovery"
    fc = (ctx.failure_class or "").strip()
    if fc not in PROHIBITED_FAILURE_CLASSES:
        return GateCheck(name, True, "GATE_PROHIBITED_N_A")

    if ctx.action.verb == ActionVerb.escalate_human:
        return GateCheck(name, True, "GATE_PROHIBITED_ESCALATE_OK")

    if _is_money_action(ctx) or _is_contact_action(ctx):
        return GateCheck(name, False, "GATE_PROHIBITED")

    return GateCheck(name, True, "GATE_PROHIBITED_N_A")


def gate_contact_window(ctx: GuardContext) -> GateCheck:
    """
    Block outbound contact outside permitted hours (IST 09:00-21:00 by default).

    Silent retries are allowed at night — only customer-facing contact is gated.
    """
    name = "contact_window"
    if not _is_contact_action(ctx):
        return GateCheck(name, True, "GATE_WINDOW_N_A")

    now = ctx.now
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    # Convert to IST = UTC+5:30
    ist = now.astimezone(timezone(timedelta(hours=5, minutes=30)))
    hour = ist.hour
    start = ctx.contact_window_start_hour_ist
    end = ctx.contact_window_end_hour_ist
    ok = start <= hour < end
    return GateCheck(
        name,
        ok,
        "GATE_WINDOW_OK" if ok else "GATE_WINDOW",
    )


def gate_frequency_cap(ctx: GuardContext) -> GateCheck:
    """Block another contact if contacts_used already at cap."""
    name = "frequency_cap"
    if not _is_contact_action(ctx):
        return GateCheck(name, True, "GATE_FREQ_N_A")
    ok = ctx.contacts_used < ctx.max_contacts
    return GateCheck(name, ok, "GATE_FREQ_OK" if ok else "GATE_FREQ")


def gate_mandate_validity(ctx: GuardContext) -> GateCheck:
    """
    Block money movement if mandate is revoked/expired.

    escalate_human always allowed.
    """
    name = "mandate_validity"
    if ctx.action.verb.value == "escalate_human":
        return GateCheck(name, True, "GATE_MANDATE_N_A")
    if not _is_money_action(ctx):
        return GateCheck(name, True, "GATE_MANDATE_N_A")

    state = ctx.mandate_state
    if state is None:
        return GateCheck(name, True, "GATE_MANDATE_UNKNOWN_ALLOW")
    bad = state.value in {"revoked", "expired"}
    return GateCheck(
        name,
        not bad,
        "GATE_MANDATE_OK" if not bad else "GATE_MANDATE",
    )


def gate_attempt_cap(ctx: GuardContext) -> GateCheck:
    """Block further retries/contacts if attempts_used hit the ceiling."""
    name = "attempt_cap"
    if ctx.action.verb.value == "escalate_human":
        return GateCheck(name, True, "GATE_ATTEMPTS_N_A")
    ok = ctx.attempts_used < ctx.max_attempts
    return GateCheck(name, ok, "GATE_ATTEMPTS_OK" if ok else "GATE_ATTEMPTS")


def gate_idempotency(ctx: GuardContext) -> GateCheck:
    """
    Block if this exact action fingerprint was already executed.

    Prevents double-charge / double-message on webhook retries. The set of
    already-executed fingerprints is rebuilt from the ledger by the pipeline
    (see guard/pipeline.py), so this survives process restarts and separate
    HTTP requests — not just one in-memory context.
    """
    name = "idempotency"
    fp = ctx.action_fingerprint or fingerprint_action(ctx)
    ok = fp not in ctx.executed_fingerprints
    return GateCheck(name, ok, "GATE_IDEM_OK" if ok else "GATE_IDEM")


def compose_fingerprint(
    *,
    case_id: str,
    verb: str,
    day_offset: object,
    channel: str,
    reason_code: str,
) -> str:
    """
    Single source of truth for fingerprint composition.

    Both the live context (fingerprint_action) and the ledger replay
    (ledger.reader.executed_fingerprints) must produce byte-identical strings,
    so the format lives here and nowhere else.
    """
    return f"{case_id}:{verb}:{day_offset}:{channel}:{reason_code}"


def fingerprint_action(ctx: GuardContext) -> str:
    a = ctx.action
    return compose_fingerprint(
        case_id=ctx.case_id,
        verb=a.verb.value,
        day_offset=a.day_offset,
        channel=a.channel.value,
        reason_code=a.reason_code,
    )


DEFAULT_GATES = (
    gate_prohibited_recovery,
    gate_contact_window,
    gate_frequency_cap,
    gate_mandate_validity,
    gate_attempt_cap,
    gate_idempotency,
)


def run_gates(ctx: GuardContext, gates=DEFAULT_GATES) -> list[GateCheck]:
    """
    Run gates in order. We still evaluate all of them for the audit trail,
    even after a block (demo clarity). Execution uses all_passed().
    """
    if not ctx.action_fingerprint:
        ctx.action_fingerprint = fingerprint_action(ctx)
    return [g(ctx) for g in gates]


def all_passed(checks: list[GateCheck]) -> bool:
    return all(c.passed for c in checks)
