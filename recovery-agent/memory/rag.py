"""
memory/rag.py — RAG status probing and case-scoped Inherent retrieval.

Measures real search latency and result counts. Does not alter agent decisions.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Optional

from pydantic import BaseModel, Field

from eval.recovery_class import recovery_class_for
from eval.types import FailureReason
from memory.inherent_client import InherentClientError, InherentConfig
from memory.schemas import RetrievalResult
from memory.service import InherentMemoryService

_RAIL_LABELS: dict[str, str] = {
    "card": "card",
    "upi_autopay": "UPI",
    "enach": "eNACH",
}

_PLATFORM_PROBE_QUERY = "payment recovery retry fixable"
_PROBE_CACHE_TTL_SECONDS = 45.0
_probe_cache: dict[str, Any] = {"at": 0.0, "metrics": None}


class RagMetrics(BaseModel):
    """Truthful RAG snapshot for API/UI — no fabricated values."""

    enabled: bool = False
    available: bool = False
    provider: str = "inherent"
    similar_cases: int = 0
    retrieval_latency_ms: Optional[float] = None
    top_similarity_score: Optional[float] = None
    query: Optional[str] = None
    error: Optional[str] = None
    used_in_recovery: bool = False
    episodes: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def status_label(self) -> str:
        if not self.enabled:
            return "RAG DISABLED"
        if not self.available:
            return "RAG UNAVAILABLE"
        return "RAG ACTIVE"

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "rag_enabled": self.enabled and self.available,
            "rag_configured": self.enabled,
            "rag_available": self.available,
            "rag_provider": self.provider,
            "similar_cases": self.similar_cases,
            "retrieval_latency_ms": self.retrieval_latency_ms,
            "top_similarity_score": self.top_similarity_score,
            "status_label": self.status_label,
            "query": self.query,
            "error": self.error,
            "used_in_recovery": self.used_in_recovery,
        }


def is_rag_configured() -> bool:
    cfg = InherentConfig.from_env()
    return bool(cfg.enabled and cfg.api_key)


def probe_inherent_health(*, timeout_seconds: float = 2.0) -> bool:
    """True when Inherent Public API /health responds OK (port 18000 by default)."""
    cfg = InherentConfig.from_env()
    url = f"{cfg.base_url.rstrip('/')}/health"
    try:
        import httpx

        with httpx.Client(timeout=timeout_seconds) as client:
            resp = client.get(url)
        if resp.status_code != 200:
            return False
        try:
            body = resp.json()
        except Exception:
            return True
        status = str(body.get("status", "")).lower()
        return status in ("", "healthy", "ok", "up")
    except Exception:
        return False


def build_retrieval_query(
    *,
    failure_reason: str,
    rail: str = "card",
) -> str:
    rail_label = _RAIL_LABELS.get(rail, rail.replace("_", " "))
    reason_label = failure_reason.replace("_", " ")
    try:
        rc = recovery_class_for(FailureReason(failure_reason))
        rc_label = rc.value.replace("_", " ")
    except (ValueError, KeyError):
        rc_label = ""
    # Verb hint improves Inherent hybrid retrieval for cause-aware episodes.
    verb_hint = {
        "insufficient_funds": "schedule retry salary window",
        "issuer_transient": "quick silent retry",
        "gateway_timeout": "quick silent retry",
        "card_expired": "send payment link update card",
        "token_invalid": "send payment link retokenize",
        "mandate_revoked": "request mandate update",
        "do_not_honour": "spaced retry then link",
        "risk_fraud": "escalate human prohibited",
    }.get(failure_reason, "")
    parts = [rail_label, reason_label, rc_label, verb_hint, "payment recovery"]
    return " ".join(p for p in parts if p)


def _top_score(results: list[RetrievalResult]) -> Optional[float]:
    scores = [r.score for r in results if r.score is not None]
    return max(scores) if scores else None


def _action_from_document_name(name: Optional[str]) -> Optional[str]:
    """Parse action suffix from sim filenames, e.g. ...-case48-delayed_retry.txt."""
    if not name:
        return None
    stem = name[:-4] if name.endswith(".txt") else name
    m = re.search(r"-case\d+-(.+)$", stem)
    if m:
        return m.group(1).replace("-", "_")
    return None


def _episode_summaries(results: list[RetrievalResult], *, limit: int = 8) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for r in results[:limit]:
        md = r.metadata or {}
        action = md.get("action") or _action_from_document_name(r.document_name)
        rows.append(
            {
                "document_id": r.document_id or r.episode_id,
                "document_name": r.document_name,
                "score": r.score,
                "recovery_class": md.get("recovery_class"),
                "failure_reason": md.get("failure_reason"),
                "action": action,
                "outcome": md.get("outcome"),
                "seed": md.get("seed"),
            }
        )
    return rows


async def _retrieve_async(
    query: str,
    *,
    limit: int = 20,
) -> RagMetrics:
    cfg = InherentConfig.from_env()
    if not cfg.enabled:
        return RagMetrics(enabled=False, available=False, query=query)
    if not cfg.api_key:
        return RagMetrics(
            enabled=True,
            available=False,
            query=query,
            error="INHERENT_API_KEY not configured",
        )

    svc = InherentMemoryService(config=cfg)
    t0 = time.perf_counter()
    try:
        results, server_ms = await svc.search_with_meta(query, top_k=limit)
    except InherentClientError as exc:
        elapsed = round((time.perf_counter() - t0) * 1000, 2)
        return RagMetrics(
            enabled=True,
            available=False,
            query=query,
            retrieval_latency_ms=elapsed,
            error=str(exc),
        )

    elapsed = round((time.perf_counter() - t0) * 1000, 2)
    latency = server_ms if server_ms is not None else elapsed
    return RagMetrics(
        enabled=True,
        available=True,
        query=query,
        similar_cases=len(results),
        retrieval_latency_ms=round(latency, 2),
        top_similarity_score=_top_score(results),
        episodes=_episode_summaries(results),
        used_in_recovery=True,
    )


def retrieve_for_payment(
    *,
    failure_reason: str,
    rail: str = "card",
    limit: int = 20,
) -> RagMetrics:
    """Sync retrieval for demo/recovery flows — measures wall-clock latency."""
    query = build_retrieval_query(failure_reason=failure_reason, rail=rail)
    if not is_rag_configured():
        return RagMetrics(enabled=False, available=False, query=query)
    return asyncio.run(_retrieve_async(query, limit=limit))


async def probe_platform_rag_async(*, force: bool = False) -> RagMetrics:
    """Lightweight probe for landing-page metrics (cached briefly)."""
    now = time.monotonic()
    if (
        not force
        and _probe_cache["metrics"] is not None
        and (now - float(_probe_cache["at"])) < _PROBE_CACHE_TTL_SECONDS
    ):
        return _probe_cache["metrics"]

    if not is_rag_configured():
        metrics = RagMetrics(enabled=False, available=False, query=_PLATFORM_PROBE_QUERY)
    else:
        metrics = await _retrieve_async(_PLATFORM_PROBE_QUERY, limit=20)
        metrics = metrics.model_copy(update={"used_in_recovery": False})

    _probe_cache["at"] = now
    _probe_cache["metrics"] = metrics
    return metrics


def probe_platform_rag(*, force: bool = False) -> RagMetrics:
    if not is_rag_configured():
        return RagMetrics(enabled=False, available=False, query=_PLATFORM_PROBE_QUERY)
    return asyncio.run(probe_platform_rag_async(force=force))


def rag_from_ledger_payload(payload: dict[str, Any]) -> RagMetrics:
    """Rehydrate RagMetrics stored on the case ledger."""
    try:
        return RagMetrics.model_validate(payload)
    except Exception:
        return RagMetrics(
            enabled=bool(payload.get("enabled")),
            available=bool(payload.get("available")),
            similar_cases=int(payload.get("similar_cases") or 0),
            retrieval_latency_ms=payload.get("retrieval_latency_ms"),
        )


def extract_case_rag(ledger: list) -> Optional[RagMetrics]:
    for entry in ledger:
        kind = entry.kind.value if hasattr(entry.kind, "value") else str(entry.kind)
        if kind != "memory_retrieval":
            continue
        payload = entry.payload or {}
        metrics = rag_from_ledger_payload(payload)
        return metrics.model_copy(update={"used_in_recovery": True})
    return None


def persist_memory_retrieval(session, case_id: str, rag: RagMetrics) -> None:
    """Append memory_retrieval row to case ledger."""
    from ledger import writer
    from ledger.schemas import LedgerActor, LedgerKind

    writer.append_ledger(
        session,
        case_id=case_id,
        kind=LedgerKind.memory_retrieval,
        actor=LedgerActor.system,
        payload=rag.model_dump(),
        reason_code="inherent_retrieval",
    )
