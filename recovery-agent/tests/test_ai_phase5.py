"""
tests/test_ai_phase5.py — Phase 5 exit checks (no live Ollama required).

We mock LLMClient so CI/laptops without the model still pass.
"""

from __future__ import annotations

from ai.agent import RecoveryAgent, build_context
from ai.client import LLMClient, parse_json_content
from ai.service import persist_agent_run
from ledger.db import Base
from ledger.schemas import LedgerActor, LedgerKind
from ledger.service import get_case_trail, ingest_risk_event
from ledger.schemas import EventSource, PayerContext, Rail, RiskEvent
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from policy.schemas import ActionVerb


class FakeLLM(LLMClient):
    """Deterministic stand-in for Ollama."""

    def __init__(self, responses: list[dict]):
        # Skip real env init side effects lightly
        self.provider = "fake"
        self.base_url = "http://fake/v1"
        self.api_key = "x"
        self.model = "fake"
        self.timeout = 5
        self._responses = list(responses)
        self._i = 0

    def available(self) -> bool:
        return True

    def chat_json(self, system: str, user: str, *, temperature: float = 0.1) -> dict:
        if self._i >= len(self._responses):
            raise RuntimeError("no more fake responses")
        out = self._responses[self._i]
        self._i += 1
        return out


def test_parse_json_strips_think_and_fences():
    raw = """<think>hmm</think>
```json
{"summary": "ok", "likely_class": "card_expired", "confidence": 0.9, "rationale": "expired"}
```"""
    data = parse_json_content(raw)
    assert data["likely_class"] == "card_expired"


def test_fallback_when_ollama_down():
    client = LLMClient()
    client.available = lambda: False  # type: ignore[method-assign]
    agent = RecoveryAgent(client=client)
    ctx = build_context(raw_error_reason="card_expired", amount_paise=49900)
    result = agent.run(ctx)
    assert result.used_llm is False
    assert result.source == "rules_fallback"
    assert result.fallback_reason == "ollama_unavailable:Ollama health check failed (GET /api/tags)" or result.fallback_reason.startswith(
        "ollama_unavailable"
    )
    assert result.action_validated.proposed_by.value == "rules_fallback"
    assert result.action_validated.verb == ActionVerb.send_payment_link
    assert any(e["actor"] in ("policy", "system", "llm") for e in result.ledger_events)
    assert result.ledger_events[1]["payload"]["source"] == "rules_fallback"


def test_agent_happy_path_mocked_llm_and_validator():
    # Diagnose + propose retry on expired card -> validator should repair to link
    fake = FakeLLM(
        [
            {
                "summary": "Card looks expired",
                "likely_class": "card_expired",
                "confidence": 0.91,
                "rationale": "reason says card_expired",
            },
            {
                "verb": "schedule_retry",
                "day_offset": 0,
                "channel": "none",
                "reason_code": "AI_BAD_RETRY",
                "note": "model wrongly retries",
            },
            {
                "channel": "link",
                "subject": "Update card",
                "body": "Please update your card to continue.",
            },
        ]
    )
    agent = RecoveryAgent(client=fake)
    ctx = build_context(raw_error_reason="card_expired", amount_paise=49900)
    result = agent.run(ctx)
    assert result.used_llm is True
    assert result.source == "llm"
    assert result.action_validated.proposed_by.value == "llm"
    assert result.action_validated.verb == ActionVerb.send_payment_link
    assert result.message is not None
    assert result.ledger_events[0]["actor"] == "llm"
    assert result.ledger_events[0]["kind"] == "classification"
    assert result.ledger_events[1]["payload"]["source"] == "llm"


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_persist_llm_rows_on_ledger(session: Session):
    event = RiskEvent(
        event_id="evt_ai_1",
        source=EventSource.simulator,
        occurred_at=datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc),
        merchant_id="m",
        payer_ref="payer_x",
        amount_paise=49900,
        rail=Rail.card,
        raw_error_reason="card_expired",
        payer_context=PayerContext(),
    )
    ingested = ingest_risk_event(session, event)
    session.commit()

    client = LLMClient()
    client.available = lambda: False  # type: ignore[method-assign]
    agent = RecoveryAgent(client=client)
    ctx = build_context(
        raw_error_reason="card_expired",
        amount_paise=49900,
        event_id="evt_ai_1",
        case_id=ingested.case_id,
    )
    result = agent.run(ctx)
    persist_agent_run(session, ingested.case_id, result)
    session.commit()

    trail = get_case_trail(session, ingested.case_id)
    kinds = [e.kind for e in trail["ledger"]]
    assert LedgerKind.event in kinds
    assert LedgerKind.classification in kinds
    assert LedgerKind.decision in kinds
    # message draft may appear as action
    actors = {e.actor for e in trail["ledger"]}
    assert LedgerActor.policy in actors or LedgerActor.llm in actors


def test_prompts_include_rag_evidence():
    from ai.prompts import diagnose_user, propose_user, format_rag_evidence

    evidence = format_rag_evidence(
        [
            {
                "score": 0.88,
                "failure_reason": "card_expired",
                "recovery_class": "CUSTOMER_ACTION",
                "action": "send_payment_link",
                "outcome": "success",
                "document_name": "recovery-sim-v1-seed42-case3.txt",
            }
        ]
    )
    assert "historical_similar_episodes" in evidence
    assert "send_payment_link" in evidence

    ctx = build_context(
        raw_error_reason="card_expired",
        amount_paise=49900,
        rag_episodes=[
            {
                "score": 0.88,
                "failure_reason": "card_expired",
                "recovery_class": "CUSTOMER_ACTION",
                "action": "send_payment_link",
                "outcome": "success",
            }
        ],
        rag_query="card expired payment recovery",
    )
    diag = diagnose_user(ctx)
    assert "historical_similar_episodes" in diag
    assert "retrieval_query: card expired payment recovery" in diag
    prop = propose_user(ctx, {"likely_class": "card_expired", "summary": "x"})
    assert "send_payment_link" in prop


def test_agent_passes_rag_into_llm_user_prompt():
    seen_users: list[str] = []

    class CaptureLLM(FakeLLM):
        def chat_json(self, system: str, user: str, *, temperature: float = 0.1) -> dict:
            seen_users.append(user)
            return super().chat_json(system, user, temperature=temperature)

    fake = CaptureLLM(
        [
            {
                "summary": "Expired card; similar cases used payment link",
                "likely_class": "card_expired",
                "confidence": 0.9,
                "rationale": "RAG shows link success",
            },
            {
                "verb": "send_payment_link",
                "day_offset": 0,
                "channel": "link",
                "reason_code": "RAG_EVIDENCE",
                "note": "similar episodes recovered via link",
            },
            {
                "channel": "link",
                "subject": "Update card",
                "body": "Please update your payment method.",
            },
        ]
    )
    agent = RecoveryAgent(client=fake)
    ctx = build_context(
        raw_error_reason="card_expired",
        amount_paise=49900,
        rag_episodes=[
            {
                "score": 0.91,
                "failure_reason": "card_expired",
                "action": "send_payment_link",
                "outcome": "success",
            }
        ],
        rag_query="card card_expired",
    )
    result = agent.run(ctx)
    assert result.used_llm is True
    assert any("historical_similar_episodes" in u for u in seen_users)
    assert ctx.rag_episodes[0]["action"] == "send_payment_link"
