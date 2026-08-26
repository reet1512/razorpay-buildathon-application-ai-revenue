"""
engine.py — load taxonomy, classify, score, emit Actions (rules fallback).

Also validates AI proposals (Phase 5): illegal verbs get repaired/rejected.

Senior flow:
  raw_reason -> Classifier -> taxonomy row -> timing -> Action(s)
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml

from diagnose.classifier import Classification, Classifier
from diagnose.scoring import effort_band, recoverability_score
from policy.schemas import (
    Action,
    ActionVerb,
    Channel,
    DecisionBundle,
    ProposedBy,
)
from policy import timing as timing_mod

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TAXONOMY = Path(__file__).resolve().parent / "taxonomy.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=4)
def load_taxonomy(path_str: str | None = None) -> dict[str, Any]:
    path = Path(path_str) if path_str else DEFAULT_TAXONOMY
    data = _load_yaml(path)
    if "version" not in data or "classes" not in data:
        raise ValueError(f"taxonomy missing version/classes: {path}")
    return data


class PolicyEngine:
    """
    Rules fallback + proposal validator.

    Call `decide(...)` for deterministic product/sim decisions.
    Call `validate_proposal(...)` when Phase 5 AI suggests an Action.
    """

    def __init__(
        self,
        taxonomy_path: Path | None = None,
        classifier: Classifier | None = None,
    ) -> None:
        self.taxonomy_path = taxonomy_path or DEFAULT_TAXONOMY
        self.taxonomy = load_taxonomy(str(self.taxonomy_path))
        self.classifier = classifier or Classifier()
        self.policy_version = str(self.taxonomy.get("version", "unset"))

    def class_config(self, failure_class: str) -> dict[str, Any]:
        classes = self.taxonomy.get("classes") or {}
        if failure_class not in classes:
            return classes["ambiguous"]
        return classes[failure_class]

    def decide(
        self,
        *,
        raw_reason: str,
        raw_code: str = "",
        amount_paise: int,
        contacts_used: int = 0,
        tenure_days: int = 0,
        failure_dom: int = 15,
        observed_credit_day: Optional[int] = None,
    ) -> DecisionBundle:
        """Rules-only decision path (Phase 4 exit)."""
        clf: Classification = self.classifier.classify(raw_reason, raw_code)
        cfg = self.class_config(clf.failure_class)
        category = str(cfg.get("category", "ambiguous"))

        score = recoverability_score(
            category=category,
            amount_paise=amount_paise,
            contacts_used=contacts_used,
            tenure_days=tenure_days,
            scoring_cfg=self.taxonomy.get("scoring") or {},
        )
        band = effort_band(score, self.taxonomy.get("effort_bands") or {})

        actions = self._actions_from_class_cfg(
            failure_class=clf.failure_class,
            cfg=cfg,
            amount_paise=amount_paise,
            score=score,
            failure_dom=failure_dom,
            observed_credit_day=observed_credit_day,
            proposed_by=ProposedBy.rules_fallback,
        )

        return DecisionBundle(
            failure_class=clf.failure_class,
            category=category,
            score=score,
            effort_band=band,
            actions=actions,
            classification_matched_on=clf.matched_on,
            policy_version=self.policy_version,
        )

    def _actions_from_class_cfg(
        self,
        *,
        failure_class: str,
        cfg: dict[str, Any],
        amount_paise: int,
        score: float,
        failure_dom: int,
        observed_credit_day: Optional[int],
        proposed_by: ProposedBy,
    ) -> list[Action]:
        verb_raw = str(cfg.get("default_verb", "escalate_human"))
        verb = ActionVerb(verb_raw)
        allow_contact = bool(cfg.get("allow_contact", False))
        max_retries = int(cfg.get("max_retries", 0))
        timing_name = str(cfg.get("timing", "none"))
        reason_code = str(cfg.get("reason_code", failure_class.upper()))

        if verb == ActionVerb.escalate_human or timing_name == "none":
            return [
                Action(
                    verb=ActionVerb.escalate_human,
                    channel=Channel.none,
                    amount_paise=None,
                    reason_code=reason_code,
                    policy_version=self.policy_version,
                    proposed_by=proposed_by,
                    failure_class=failure_class,
                    score=score,
                    day_offset=0,
                    note="escalate_or_no_auto",
                )
            ]

        # Dead / contact verbs: primary fix path + one delayed follow-up link.
        if verb in {ActionVerb.send_payment_link, ActionVerb.request_mandate_update}:
            channel = Channel.link if allow_contact else Channel.none
            actions = [
                Action(
                    verb=verb,
                    channel=channel,
                    amount_paise=amount_paise,
                    reason_code=reason_code,
                    policy_version=self.policy_version,
                    proposed_by=proposed_by,
                    failure_class=failure_class,
                    score=score,
                    day_offset=0,
                    note="dead_instrument_fix_path",
                )
            ]
            if allow_contact:
                actions.append(
                    Action(
                        verb=ActionVerb.send_payment_link,
                        channel=Channel.link,
                        amount_paise=amount_paise,
                        reason_code=reason_code,
                        policy_version=self.policy_version,
                        proposed_by=proposed_by,
                        failure_class=failure_class,
                        score=score,
                        day_offset=3,
                        note="dead_instrument_followup_link",
                    )
                )
            return actions

        # Retries (+ optional later link for ambiguous spaced_then_link).
        offsets = timing_mod.offsets_for_timing(
            timing_name,
            failure_dom=failure_dom,
            observed_credit_day=observed_credit_day,
            max_retries=max_retries,
        )
        actions: list[Action] = []
        for off in offsets:
            if timing_name == "spaced_then_link" and off >= 4 and allow_contact:
                actions.append(
                    Action(
                        verb=ActionVerb.send_payment_link,
                        channel=Channel.link,
                        amount_paise=amount_paise,
                        reason_code=reason_code,
                        policy_version=self.policy_version,
                        proposed_by=proposed_by,
                        failure_class=failure_class,
                        score=score,
                        day_offset=off,
                        note="spaced_link",
                    )
                )
            else:
                actions.append(
                    Action(
                        verb=ActionVerb.schedule_retry,
                        channel=Channel.none,
                        amount_paise=amount_paise,
                        reason_code=reason_code,
                        policy_version=self.policy_version,
                        proposed_by=proposed_by,
                        failure_class=failure_class,
                        score=score,
                        day_offset=off,
                        note=f"retry_offset_{off}",
                    )
                )
        return actions

    def validate_proposal(
        self,
        proposal: Action,
        *,
        failure_class: str,
        amount_paise: int,
        score: float,
    ) -> Action:
        """
        Phase 5 hook: AI proposes, we bound.

        - Verb must be in ActionVerb enum (Pydantic already enforces).
        - If class forbids contact, rewrite contact verbs to escalate/retry.
        - If class is dead, force max_retries semantics (no schedule_retry).
        - Stamp policy_version.
        """
        cfg = self.class_config(failure_class)
        allow_contact = bool(cfg.get("allow_contact", False))
        max_retries = int(cfg.get("max_retries", 0))
        category = str(cfg.get("category", "ambiguous"))

        verb = proposal.verb
        repaired = proposal.model_copy(deep=True)
        repaired.policy_version = self.policy_version
        repaired.failure_class = failure_class
        repaired.score = score
        repaired.proposed_by = ProposedBy.llm

        if category == "stop":
            repaired.verb = ActionVerb.escalate_human
            repaired.channel = Channel.none
            repaired.reason_code = "RISK_ESCALATE"
            repaired.note = "validator_forced_escalate"
            return repaired

        if category == "dead" and verb == ActionVerb.schedule_retry:
            # AI tried a useless retry — repair to taxonomy default.
            default = ActionVerb(str(cfg.get("default_verb", "send_payment_link")))
            repaired.verb = default
            repaired.channel = Channel.link if allow_contact else Channel.none
            repaired.day_offset = 0
            repaired.note = "validator_blocked_retry_on_dead"
            return repaired

        if not allow_contact and verb in {
            ActionVerb.send_payment_link,
            ActionVerb.request_mandate_update,
        }:
            repaired.verb = ActionVerb.schedule_retry if max_retries > 0 else ActionVerb.escalate_human
            repaired.channel = Channel.none
            repaired.note = "validator_blocked_contact"
            return repaired

        if repaired.amount_paise is None and repaired.verb != ActionVerb.escalate_human:
            repaired.amount_paise = amount_paise
        return repaired


# ---- Eval bridge ---------------------------------------------------------

def decision_to_planned_actions(bundle: DecisionBundle):
    """
    Convert DecisionBundle -> eval PlannedAction list.

    escalate_human with no money movement => empty plan (like B0 automation),
    EXCEPT we still want natural recovery only — empty list is correct.
    """
    from eval.types import PlannedAction, SimVerb

    planned: list[PlannedAction] = []
    for a in bundle.actions:
        if a.verb == ActionVerb.escalate_human:
            # No automated money/contact actions.
            continue
        if a.verb == ActionVerb.schedule_retry:
            planned.append(
                PlannedAction(
                    verb=SimVerb.schedule_retry,
                    day_offset=int(a.day_offset or 0),
                    note=a.note or a.reason_code,
                )
            )
        elif a.verb in {ActionVerb.send_payment_link, ActionVerb.request_mandate_update}:
            planned.append(
                PlannedAction(
                    verb=SimVerb.send_payment_link,
                    day_offset=int(a.day_offset or 0),
                    note=a.note or a.reason_code,
                )
            )
    return planned


_engine: PolicyEngine | None = None


def get_engine() -> PolicyEngine:
    global _engine
    if _engine is None:
        _engine = PolicyEngine()
    return _engine


def reset_engine() -> None:
    """Clear cached engine (tests / after taxonomy hot-reload)."""
    global _engine
    _engine = None


def policy_ours_from_taxonomy(case) -> list:
    """
    Drop-in PolicyFn for eval harness (`ours`).

    Uses VisibleCase.failure_reason as raw_reason (sim world).
    """
    engine = get_engine()
    v = case.visible
    bundle = engine.decide(
        raw_reason=v.failure_reason.value,
        raw_code="",
        amount_paise=v.amount_paise,
        contacts_used=0,
        tenure_days=0,
        failure_dom=case.failure_dom,
        observed_credit_day=v.observed_credit_day,
    )
    return decision_to_planned_actions(bundle)
