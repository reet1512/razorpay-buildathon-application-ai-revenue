"""
Gates must validate agent_result.action_validated — never a UI_PROVE_LINK override.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ai.agent import RecoveryAgent, build_context
from ai.client import LLMClient
from demo import live_flow
from policy.schemas import ActionVerb, ProposedBy


@pytest.fixture()
def force_rules_agent(monkeypatch):
    client = LLMClient()
    client.available = lambda: False  # type: ignore[method-assign]
    monkeypatch.setattr(live_flow, "LLMClient", lambda: client)
    return client


def test_guard_receives_agent_action_not_ui_prove_link(monkeypatch, force_rules_agent):
    captured: dict = {}

    def fake_guard(session, case, ctx, *, execute_fn=None, policy_version="phase6", audit=None):
        captured["action"] = ctx.action.model_dump(mode="json")
        pipe = MagicMock()
        pipe.allowed = True
        pipe.blocked_by = None
        pipe.executed = False
        pipe.checks = []
        return pipe

    monkeypatch.setattr(live_flow, "guard_and_maybe_execute", fake_guard)
    monkeypatch.setattr(
        live_flow,
        "retrieve_for_payment",
        lambda **kwargs: MagicMock(
            enabled=False,
            available=False,
            similar_cases=0,
            retrieval_latency_ms=None,
            status_label="RAG off",
            top_similarity_score=None,
            query="",
            episodes=[],
            to_public_dict=lambda: {},
        ),
    )

    # Capture what agent would produce for the same inputs
    agent = RecoveryAgent(client=force_rules_agent)
    expected = agent.run(
        build_context(raw_error_reason="insufficient_funds", amount_paise=49900)
    ).action_validated.model_dump(mode="json")

    result = live_flow.run_ai_demo_case(
        raw_error_reason="insufficient_funds",
        amount_paise=49900,
        force_fallback=True,
        create_payment_link=False,
    )

    assert captured["action"] == expected
    assert captured["action"]["reason_code"] != "UI_PROVE_LINK"
    assert result["source"] == "rules_fallback"
    assert result["verb"] == expected["verb"]
    assert result["used_llm"] is False


def test_live_path_gates_agent_action_not_prove_link(monkeypatch, force_rules_agent):
    captured: dict = {}

    def fake_execute(session, case, ctx, *, meta=None, mode=None, policy_version="phase7"):
        captured["action"] = ctx.action.model_dump(mode="json")
        pipe = MagicMock()
        pipe.allowed = True
        pipe.blocked_by = None
        pipe.executed = True
        pipe.checks = []
        outcome = MagicMock()
        # No plink from gated schedule_retry / escalate — triggers demo affordance path
        outcome.external_id = None
        return pipe, outcome

    demo_calls: list = []

    def fake_demo(session, case, *, raw_error_reason, gated_verb):
        demo_calls.append({"gated_verb": gated_verb, "reason": raw_error_reason})
        out = MagicMock()
        out.external_id = "plink_demo_only"
        return out

    monkeypatch.setattr(live_flow, "execute_with_guards", fake_execute)
    monkeypatch.setattr(live_flow, "_create_demo_payment_link", fake_demo)
    monkeypatch.setattr(
        live_flow,
        "retrieve_for_payment",
        lambda **kwargs: MagicMock(
            enabled=False,
            available=False,
            similar_cases=0,
            retrieval_latency_ms=None,
            status_label="RAG off",
            top_similarity_score=None,
            query="",
            episodes=[],
            to_public_dict=lambda: {},
        ),
    )

    agent = RecoveryAgent(client=force_rules_agent)
    expected = agent.run(
        build_context(raw_error_reason="insufficient_funds", amount_paise=49900)
    ).action_validated

    result = live_flow.run_ai_demo_case(
        raw_error_reason="insufficient_funds",
        amount_paise=49900,
        force_fallback=True,
        create_payment_link=True,
    )

    assert captured["action"]["verb"] == expected.verb.value
    assert captured["action"]["reason_code"] != "UI_PROVE_LINK"
    assert captured["action"]["proposed_by"] == ProposedBy.rules_fallback.value
    assert result["source"] == "rules_fallback"
    assert result["verb"] == expected.verb.value
    # Demo link is separate when gated verb did not produce a plink
    if expected.verb != ActionVerb.send_payment_link:
        assert demo_calls and demo_calls[0]["gated_verb"] == expected.verb.value
        assert result["demo_link_not_gated"] is True
        assert result["external_id"] == "plink_demo_only"
    else:
        assert result.get("demo_link_not_gated") is False
