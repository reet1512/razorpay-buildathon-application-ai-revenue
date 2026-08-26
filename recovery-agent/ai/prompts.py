"""
ai/prompts.py — prompt builders (no PII).
"""

from __future__ import annotations

import hashlib
from typing import Any

from ai.schemas import CaseContext


DIAGNOSE_SYSTEM = """You are a payments recovery analyst for Indian subscription rails.
Return ONLY valid JSON (no markdown, no prose) with keys:
  summary (string),
  likely_class (string — must be one of the allowed classes),
  confidence (number 0..1),
  rationale (string).
Never invent customer PII. Never suggest illegal or unbounded actions.
When historical_similar_episodes are provided, use them as reference evidence
(what worked or failed for similar failures) but still pick likely_class from allowed_classes.
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
- When historical_similar_episodes are present, prefer verbs/outcomes that succeeded on
  similar failures unless policy rules above forbid them. Mention that evidence briefly in note.
  Prefer citing the top episode action when it matches an allowed verb.
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


def format_rag_evidence(episodes: list[dict[str, Any]], *, limit: int = 8) -> str:
    """Compact de-identified Inherent hits for the model (no PII fields)."""
    if not episodes:
        return ""
    lines: list[str] = ["historical_similar_episodes:"]
    for i, ep in enumerate(episodes[:limit], start=1):
        score = ep.get("score")
        score_s = f"{float(score):.3f}" if isinstance(score, (int, float)) else "n/a"
        parts = [
            f"#{i}",
            f"score={score_s}",
            f"failure={ep.get('failure_reason') or 'unknown'}",
            f"class={ep.get('recovery_class') or 'unknown'}",
            f"action={ep.get('action') or 'unknown'}",
            f"outcome={ep.get('outcome') or 'unknown'}",
        ]
        name = ep.get("document_name")
        if name:
            parts.append(f"doc={name}")
        lines.append("- " + " | ".join(parts))
    return "\n".join(lines)


def diagnose_user(ctx: CaseContext) -> str:
    parts = [
        f"allowed_classes: {ctx.allowed_classes}",
        f"raw_error_reason: {ctx.raw_error_reason}",
        f"raw_error_code: {ctx.raw_error_code}",
        f"rail: {ctx.rail}",
        f"amount_bucket_inr: {ctx.amount_bucket_inr}",
        f"attempt_number: {ctx.attempt_number}",
        f"failure_dom: {ctx.failure_dom}",
        f"observed_credit_day: {ctx.observed_credit_day}",
    ]
    if ctx.rag_query:
        parts.append(f"retrieval_query: {ctx.rag_query}")
    evidence = format_rag_evidence(ctx.rag_episodes)
    if evidence:
        parts.append(evidence)
    parts.append("Respond with JSON only.")
    return "\n".join(parts)


def propose_user(ctx: CaseContext, diagnosis_json: dict) -> str:
    parts = [
        f"allowed_verbs: {ctx.allowed_verbs}",
        f"allowed_classes: {ctx.allowed_classes}",
        f"diagnosis: {diagnosis_json}",
        f"raw_error_reason: {ctx.raw_error_reason}",
        f"rail: {ctx.rail}",
        f"amount_bucket_inr: {ctx.amount_bucket_inr}",
        f"attempt_number: {ctx.attempt_number}",
        f"failure_dom: {ctx.failure_dom}",
        f"observed_credit_day: {ctx.observed_credit_day}",
    ]
    evidence = format_rag_evidence(ctx.rag_episodes)
    if evidence:
        parts.append(evidence)
    parts.append("Propose the single best next Action as JSON only.")
    return "\n".join(parts)


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
