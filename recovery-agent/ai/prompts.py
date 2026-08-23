"""
ai/prompts.py — prompt builders (no PII).
"""

from __future__ import annotations

import hashlib

from ai.schemas import CaseContext


DIAGNOSE_SYSTEM = """You are a payments recovery analyst for Indian subscription rails.
Return ONLY valid JSON (no markdown, no prose) with keys:
  summary (string),
  likely_class (string — must be one of the allowed classes),
  confidence (number 0..1),
  rationale (string).
Never invent customer PII. Never suggest illegal or unbounded actions.
"""


PROPOSE_SYSTEM = """You are a recovery agent that proposes ONE next action.
Return ONLY valid JSON with keys:
  verb (one of allowed verbs),
  day_offset (integer >= 0),
  channel (none|sms|email|link),
  reason_code (string),
  note (short string).
Rules:
- Dead instruments (card_expired, token_invalid, mandate_revoked): NEVER schedule_retry.
- Risk/fraud: escalate_human only.
- NSF/time-shiftable: prefer schedule_retry with day_offset away from day 0 when possible.
- Do not invent new verbs.
"""


MESSAGE_SYSTEM = """You write one short payer message for a failed subscription payment in India.
Return ONLY valid JSON with keys:
  channel (sms|email|link),
  subject (string),
  body (string, clear, polite, under 500 chars).
No threats. No dark patterns. One clear next step (update method / pay link).
"""


def bundle_hash(*parts: str) -> str:
    """Stable short hash for prompt versioning in the audit log."""
    joined = "\n---\n".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def diagnose_prompt_hash(ctx: CaseContext) -> str:
    return bundle_hash(DIAGNOSE_SYSTEM, diagnose_user(ctx))


def propose_prompt_hash(ctx: CaseContext, diagnosis_json: dict) -> str:
    return bundle_hash(PROPOSE_SYSTEM, propose_user(ctx, diagnosis_json))


def diagnose_user(ctx: CaseContext) -> str:
    return (
        f"allowed_classes: {ctx.allowed_classes}\n"
        f"raw_error_reason: {ctx.raw_error_reason}\n"
        f"raw_error_code: {ctx.raw_error_code}\n"
        f"rail: {ctx.rail}\n"
        f"amount_bucket_inr: {ctx.amount_bucket_inr}\n"
        f"attempt_number: {ctx.attempt_number}\n"
        f"failure_dom: {ctx.failure_dom}\n"
        f"observed_credit_day: {ctx.observed_credit_day}\n"
        "Respond with JSON only."
    )


def propose_user(ctx: CaseContext, diagnosis_json: dict) -> str:
    return (
        f"allowed_verbs: {ctx.allowed_verbs}\n"
        f"allowed_classes: {ctx.allowed_classes}\n"
        f"diagnosis: {diagnosis_json}\n"
        f"raw_error_reason: {ctx.raw_error_reason}\n"
        f"rail: {ctx.rail}\n"
        f"amount_bucket_inr: {ctx.amount_bucket_inr}\n"
        f"attempt_number: {ctx.attempt_number}\n"
        f"failure_dom: {ctx.failure_dom}\n"
        f"observed_credit_day: {ctx.observed_credit_day}\n"
        "Propose the single best next Action as JSON only."
    )


def message_user(ctx: CaseContext, diagnosis_json: dict, verb: str) -> str:
    return (
        f"failure_reason: {ctx.raw_error_reason}\n"
        f"diagnosis_summary: {diagnosis_json.get('summary')}\n"
        f"planned_verb: {verb}\n"
        f"amount_bucket_inr: {ctx.amount_bucket_inr}\n"
        "Write the payer-facing message JSON only."
    )


def repair_user(previous_output: str, error: str, schema_hint: str) -> str:
    return (
        "Your previous output was invalid.\n"
        f"error: {error}\n"
        f"required_schema_hint: {schema_hint}\n"
        f"previous_output: {previous_output[:1200]}\n"
        "Return corrected JSON only."
    )
