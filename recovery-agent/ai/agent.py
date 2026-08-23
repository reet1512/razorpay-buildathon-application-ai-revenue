"""
ai/agent.py — Phase 5 orchestrator.

Senior teaching:
1) Build a CaseContext with NO PII
2) LLM diagnoses (JSON)
3) LLM proposes Action (JSON)
4) PolicyEngine.validate_proposal bounds it
5) Optional message draft if contact verb
6) If Ollama is down / JSON fails twice -> rules_fallback

Ledger-shaped dicts are returned so API/UI can append actor=llm rows.
"""

from __future__ import annotations

from typing import Any, Optional

from ai import prompts
from ai.client import LLMClient, LLMError
from ai.schemas import (
    AgentRunResult,
    CaseContext,
    Diagnosis,
    MessageDraft,
    ProposalPayload,
)
from diagnose.scoring import recoverability_score
from policy.engine import PolicyEngine, get_engine
from policy.schemas import Action, ActionVerb, Channel, ProposedBy


def amount_bucket_inr(amount_paise: int) -> str:
    inr = amount_paise / 100.0
    if inr < 200:
        return "0-199"
    if inr < 500:
        return "200-499"
    if inr < 1000:
        return "500-999"
    if inr < 2000:
        return "1000-1999"
    return "2000+"


def build_context(
    *,
    raw_error_reason: str,
    amount_paise: int,
    raw_error_code: str = "",
    rail: str = "card",
    attempt_number: int = 1,
    failure_dom: int = 15,
    observed_credit_day: Optional[int] = None,
    contacts_used: int = 0,
    tenure_days: int = 0,
    event_id: str = "unknown",
    case_id: Optional[str] = None,
    engine: Optional[PolicyEngine] = None,
) -> CaseContext:
    eng = engine or get_engine()
    classes = sorted((eng.taxonomy.get("classes") or {}).keys())
    verbs = [v.value for v in ActionVerb]
    return CaseContext(
        event_id=event_id,
        case_id=case_id,
        raw_error_reason=raw_error_reason,
        raw_error_code=raw_error_code,
        rail=rail,
        amount_bucket_inr=amount_bucket_inr(amount_paise),
        amount_paise=amount_paise,
        attempt_number=attempt_number,
        failure_dom=failure_dom,
        observed_credit_day=observed_credit_day,
        contacts_used=contacts_used,
        tenure_days=tenure_days,
        allowed_classes=classes,
        allowed_verbs=verbs,
    )


class RecoveryAgent:
    """
    Significant AI role for the hackathon, bounded by taxonomy/policy.
    """

    def __init__(
        self,
        client: Optional[LLMClient] = None,
        engine: Optional[PolicyEngine] = None,
    ) -> None:
        self.client = client or LLMClient()
        self.engine = engine or get_engine()

    def run(self, ctx: CaseContext) -> AgentRunResult:
        # Always compute rules decision as safety net + ablation baseline.
        rules = self.engine.decide(
            raw_reason=ctx.raw_error_reason,
            raw_code=ctx.raw_error_code,
            amount_paise=ctx.amount_paise,
            contacts_used=ctx.contacts_used,
            tenure_days=ctx.tenure_days,
            failure_dom=ctx.failure_dom,
            observed_credit_day=ctx.observed_credit_day,
        )

        if not self.client.available():
            return self._fallback(
                ctx,
                rules,
                reason="ollama_unavailable",
                diagnosis=Diagnosis(
                    summary=f"Rules fallback: classified as {rules.failure_class}",
                    likely_class=rules.failure_class,
                    confidence=1.0 if rules.classification_matched_on != "ambiguous" else 0.2,
                    rationale="LLM unavailable; used taxonomy rules.",
                ),
            )

        # --- 1) Diagnose ---
        try:
            diag_raw = self._json_with_repair(
                system=prompts.DIAGNOSE_SYSTEM,
                user=prompts.diagnose_user(ctx),
                schema_hint="summary,likely_class,confidence,rationale",
            )
            diagnosis = Diagnosis.model_validate(diag_raw)
            # Clamp class to taxonomy
            if diagnosis.likely_class not in (self.engine.taxonomy.get("classes") or {}):
                diagnosis.likely_class = rules.failure_class
        except Exception as exc:
            return self._fallback(
                ctx,
                rules,
                reason=f"diagnose_failed:{exc}",
                diagnosis=Diagnosis(
                    summary=f"Rules fallback after diagnose failure ({rules.failure_class})",
                    likely_class=rules.failure_class,
                    confidence=0.3,
                    rationale=str(exc),
                ),
            )

        # Prefer AI class when known; else rules class
        failure_class = diagnosis.likely_class or rules.failure_class
        cfg = self.engine.class_config(failure_class)
        category = str(cfg.get("category", "ambiguous"))
        score = recoverability_score(
            category=category,
            amount_paise=ctx.amount_paise,
            contacts_used=ctx.contacts_used,
            tenure_days=ctx.tenure_days,
            scoring_cfg=self.engine.taxonomy.get("scoring") or {},
        )

        # --- 2) Propose action ---
        try:
            prop_raw = self._json_with_repair(
                system=prompts.PROPOSE_SYSTEM,
                user=prompts.propose_user(ctx, diagnosis.model_dump()),
                schema_hint="verb,day_offset,channel,reason_code,note",
            )
            proposal = ProposalPayload.model_validate(prop_raw)
        except Exception as exc:
            return self._fallback(
                ctx,
                rules,
                reason=f"propose_failed:{exc}",
                diagnosis=diagnosis,
            )

        draft_action = Action(
            verb=proposal.verb,
            day_offset=proposal.day_offset,
            channel=proposal.channel,
            amount_paise=ctx.amount_paise,
            reason_code=proposal.reason_code,
            note=proposal.note,
            proposed_by=ProposedBy.llm,
            failure_class=failure_class,
            score=score,
            policy_version=self.engine.policy_version,
        )
        validated = self.engine.validate_proposal(
            draft_action,
            failure_class=failure_class,
            amount_paise=ctx.amount_paise,
            score=score,
        )

        # --- 3) Message (only if contact-like verb) ---
        message: Optional[MessageDraft] = None
        if validated.verb in {
            ActionVerb.send_payment_link,
            ActionVerb.request_mandate_update,
        }:
            try:
                msg_raw = self._json_with_repair(
                    system=prompts.MESSAGE_SYSTEM,
                    user=prompts.message_user(
                        ctx, diagnosis.model_dump(), validated.verb.value
                    ),
                    schema_hint="channel,subject,body",
                )
                message = MessageDraft.model_validate(msg_raw)
            except Exception:
                message = MessageDraft(
                    channel=Channel.link,
                    subject="Action needed for your subscription",
                    body=(
                        "Your recent subscription payment did not go through. "
                        "Please update your payment method using the secure link we sent."
                    ),
                )

        ledger_events = self._ledger_events(
            diagnosis=diagnosis,
            proposal=proposal,
            validated=validated,
            message=message,
            used_llm=True,
            ctx=ctx,
        )
        return AgentRunResult(
            context=ctx,
            diagnosis=diagnosis,
            proposal_raw=proposal,
            action_validated=validated,
            message=message,
            used_llm=True,
            fallback_reason=None,
            decision_rules=rules,
            ledger_events=ledger_events,
        )

    def _json_with_repair(self, *, system: str, user: str, schema_hint: str) -> dict[str, Any]:
        """Call model; on parse/validation caller errors, one repair retry."""
        try:
            return self.client.chat_json(system, user)
        except LLMError as first:
            repair = prompts.repair_user(str(first), str(first), schema_hint)
            return self.client.chat_json(system, repair)

    def _fallback(
        self,
        ctx: CaseContext,
        rules,
        *,
        reason: str,
        diagnosis: Diagnosis,
    ) -> AgentRunResult:
        action = rules.actions[0] if rules.actions else Action(
            verb=ActionVerb.escalate_human,
            proposed_by=ProposedBy.rules_fallback,
            failure_class=rules.failure_class,
            policy_version=rules.policy_version,
            reason_code="FALLBACK",
        )
        # Stamp fallback provenance
        action = action.model_copy(
            update={"proposed_by": ProposedBy.rules_fallback, "note": f"fallback:{reason}"}
        )
        message = None
        if action.verb in {
            ActionVerb.send_payment_link,
            ActionVerb.request_mandate_update,
        }:
            message = MessageDraft(
                channel=Channel.link,
                subject="Action needed for your subscription",
                body=(
                    "Your recent subscription payment did not go through. "
                    "Please update your payment method using the secure link."
                ),
            )
        ledger_events = self._ledger_events(
            diagnosis=diagnosis,
            proposal=None,
            validated=action,
            message=message,
            used_llm=False,
            extra_note=reason,
            ctx=ctx,
        )
        return AgentRunResult(
            context=ctx,
            diagnosis=diagnosis,
            proposal_raw=None,
            action_validated=action,
            message=message,
            used_llm=False,
            fallback_reason=reason,
            decision_rules=rules,
            ledger_events=ledger_events,
        )

    def _ledger_events(
        self,
        *,
        diagnosis: Diagnosis,
        proposal: Optional[ProposalPayload],
        validated: Action,
        message: Optional[MessageDraft],
        used_llm: bool,
        extra_note: str = "",
        ctx: Optional[CaseContext] = None,
    ) -> list[dict[str, Any]]:
        """
        Shape rows for ledger.append later.

        kind/actor match Phase 1 ledger enums.
        """
        model_name = self.client.model if used_llm else "rules_fallback"
        prompt_hash = None
        if used_llm and ctx is not None and proposal is not None:
            prompt_hash = prompts.propose_prompt_hash(ctx, diagnosis.model_dump())

        events: list[dict[str, Any]] = [
            {
                "kind": "classification",
                "actor": "llm" if used_llm else "policy",
                "reason_code": diagnosis.likely_class,
                "payload": {
                    **diagnosis.model_dump(),
                    "audit": {"model": model_name, "prompt_hash": prompts.diagnose_prompt_hash(ctx) if ctx and used_llm else None},
                },
            },
            {
                "kind": "decision",
                "actor": "llm" if used_llm and proposal else "policy",
                "reason_code": validated.reason_code,
                "payload": {
                    "proposal_raw": proposal.model_dump() if proposal else None,
                    "validated": validated.model_dump(mode="json"),
                    "extra_note": extra_note,
                    "audit": {"model": model_name, "prompt_hash": prompt_hash},
                },
            },
        ]
        if message is not None:
            events.append(
                {
                    "kind": "action",
                    "actor": "llm" if used_llm else "system",
                    "reason_code": "message_draft",
                    "payload": message.model_dump(),
                }
            )
        return events


def run_agent_for_reason(
    raw_error_reason: str,
    amount_paise: int,
    **kwargs: Any,
) -> AgentRunResult:
    """Convenience for demos/tests."""
    agent = RecoveryAgent()
    ctx = build_context(
        raw_error_reason=raw_error_reason,
        amount_paise=amount_paise,
        **kwargs,
    )
    return agent.run(ctx)
