"""
api/routes_agent.py — Phase 5 HTTP surface for demos.

POST /agent/run
  body: { raw_error_reason, amount_paise, ... }
  -> AgentRunResult JSON (diagnosis, validated action, message, ledger_events)
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ai.agent import RecoveryAgent, build_context
from ai.client import LLMClient

router = APIRouter(prefix="/agent", tags=["agent"])


class AgentRunRequest(BaseModel):
    raw_error_reason: str
    amount_paise: int = Field(ge=0)
    raw_error_code: str = ""
    rail: str = "card"
    attempt_number: int = 1
    failure_dom: int = 15
    observed_credit_day: Optional[int] = None
    event_id: str = "demo_event"
    case_id: Optional[str] = None
    force_fallback: bool = Field(
        default=False,
        description="If true, pretend Ollama is down (for demos/tests)",
    )


@router.get("/health")
def agent_health() -> dict:
    """Is Ollama reachable with configured model endpoint?"""
    client = LLMClient()
    return {
        "ollama_up": client.available(),
        "provider": client.provider,
        "model": client.model,
        "base_url": client.base_url,
    }


@router.post("/run")
def agent_run(req: AgentRunRequest) -> dict:
    """
    Run the significant AI path once.

    Always returns a bounded action (LLM or rules_fallback).
    """
    client = LLMClient()
    if req.force_fallback:
        client.available = lambda: False  # type: ignore[method-assign]

    agent = RecoveryAgent(client=client)
    ctx = build_context(
        raw_error_reason=req.raw_error_reason,
        amount_paise=req.amount_paise,
        raw_error_code=req.raw_error_code,
        rail=req.rail,
        attempt_number=req.attempt_number,
        failure_dom=req.failure_dom,
        observed_credit_day=req.observed_credit_day,
        event_id=req.event_id,
        case_id=req.case_id,
    )
    result = agent.run(ctx)
    return result.model_dump(mode="json")
