"""Tests for RAG status and UI metrics wiring."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from memory.rag import RagMetrics, build_retrieval_query, probe_platform_rag
from memory.schemas import RetrievalResult
from api.ui_helpers import platform_metrics, build_case_view, recover_demo_context


def test_build_retrieval_query_includes_failure_and_class():
    q = build_retrieval_query(failure_reason="issuer_transient", rail="upi_autopay")
    assert "UPI" in q
    assert "issuer transient" in q
    assert "RETRY FIXABLE" in q


def test_platform_metrics_disabled_when_not_configured(monkeypatch):
    monkeypatch.setenv("INHERENT_ENABLED", "false")
    monkeypatch.delenv("INHERENT_API_KEY", raising=False)
    m = platform_metrics(None, {})
    assert m["rag_enabled"] is False
    assert m["rag_label"] == "RAG DISABLED"
    assert m["similar_cases"] == 0


def test_platform_metrics_active_from_probe(monkeypatch):
    monkeypatch.setenv("INHERENT_ENABLED", "true")
    monkeypatch.setenv("INHERENT_API_KEY", "ink_test")
    fake = RagMetrics(
        enabled=True,
        available=True,
        similar_cases=12,
        retrieval_latency_ms=184.2,
        top_similarity_score=0.76,
    )
    with patch("api.ui_helpers.probe_platform_rag", return_value=fake):
        m = platform_metrics(None, {})
    assert m["rag_enabled"] is True
    assert m["rag_label"] == "RAG ACTIVE"
    assert m["similar_cases"] == 12
    assert m["retrieval_latency_ms"] == 184.2
    assert m["retrieval_latency_label"] == "184 ms"


def test_platform_metrics_unavailable(monkeypatch):
    monkeypatch.setenv("INHERENT_ENABLED", "true")
    monkeypatch.setenv("INHERENT_API_KEY", "ink_test")
    fake = RagMetrics(
        enabled=True,
        available=False,
        error="inherent_search_timeout",
    )
    with patch("api.ui_helpers.probe_platform_rag", return_value=fake):
        m = platform_metrics(None, {})
    assert m["rag_enabled"] is False
    assert m["rag_configured"] is True
    assert m["rag_available"] is False
    assert m["rag_label"] == "RAG UNAVAILABLE"


def test_build_case_view_with_rag_ledger():
    from datetime import datetime, timezone

    from ledger.schemas import LedgerEntryView, LedgerKind, LedgerActor

    rag = RagMetrics(
        enabled=True,
        available=True,
        similar_cases=5,
        retrieval_latency_ms=142.0,
        top_similarity_score=0.7618,
        episodes=[{"document_name": "recovery-sim.txt", "score": 0.76}],
    )
    ledger = [
        LedgerEntryView(
            seq=1,
            case_id="c1",
            at=datetime.now(timezone.utc),
            kind=LedgerKind.memory_retrieval,
            actor=LedgerActor.system,
            policy_version="test",
            payload=rag.model_dump(),
            reason_code="inherent_retrieval",
        )
    ]

    class _Case:
        amount_paise = 49900
        status = "open"

    view = build_case_view(
        case=_Case(),
        ledger=ledger,
        story={"failure": "issuer_transient", "gates": "passed"},
        audit_log=[],
    )
    assert view["why"]["rag_enabled"] is True
    assert view["why"]["historical_episodes"] == 5
    assert view["memory"]["retrieved_count"] == 5
    assert view["timeline"][1]["status"] == "done"


def test_retrieve_async_measures_latency(monkeypatch):
    import asyncio

    from memory.rag import _retrieve_async

    monkeypatch.setenv("INHERENT_ENABLED", "true")
    monkeypatch.setenv("INHERENT_API_KEY", "ink_test")

    results = [
        RetrievalResult(document_id="d1", score=0.9, content="x"),
    ]

    async def fake_search(*args, **kwargs):
        return results, 50.0

    with patch("memory.rag.InherentMemoryService") as mock_svc:
        inst = mock_svc.return_value
        inst.search_with_meta = AsyncMock(side_effect=fake_search)
        metrics = asyncio.run(_retrieve_async("UPI issuer transient", limit=5))

    assert metrics.available is True
    assert metrics.similar_cases == 1
    assert metrics.retrieval_latency_ms == 50.0
    assert metrics.top_similarity_score == 0.9
