"""
tests/test_inherent_memory.py — Inherent adapter + Phase 2 memory tests.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from eval.recovery_class import RecoveryClass
from eval.types import FailureReason
from ledger.schemas import Rail
from memory.episode_text import build_episode_text
from memory.inherent_client import (
    InherentClient,
    InherentClientError,
    InherentConfig,
    is_completed_status,
    is_failed_status,
    parse_document_status,
    parse_document_upload,
    parse_search_response,
)
from memory.schemas import DataSource, EpisodeOutcome, PaymentEpisode
from memory.service import InherentMemoryService
from policy.schemas import ActionVerb


def _run(coro):
    return asyncio.run(coro)


def _enabled_config(**overrides: Any) -> InherentConfig:
    base = {
        "enabled": True,
        "base_url": "http://inherent.test:18000",
        "search_path": "/v1/search",
        "documents_path": "/v1/documents",
        "api_key": "test-secret-key",
        "workspace_id": "ws_recovery",
        "timeout_seconds": 2.0,
        "poll_interval_seconds": 0.01,
        "poll_timeout_seconds": 1.0,
        "max_retries": 2,
        "seed_concurrency": 2,
        "seed_batch_size": 5,
    }
    base.update(overrides)
    return InherentConfig(**base)


def _sample_episode() -> PaymentEpisode:
    return PaymentEpisode(
        episode_id="recovery_v1_seed42_sim_42_0001",
        case_id="sim_42_0001",
        seed=42,
        amount_paise=499900,
        rail=Rail.upi_autopay,
        failure_reason=FailureReason.insufficient_funds,
        recovery_class=RecoveryClass.RETRY_FIXABLE,
        attempt_number=1,
        action=ActionVerb.schedule_retry,
        outcome=EpisodeOutcome.success,
        recovered_paise=499900,
        net_recovered_paise=493000,
        data_source=DataSource.synthetic_simulation,
        delay_seconds=900,
    )


# --- episode text ---


def test_build_episode_text_deterministic():
    ep = _sample_episode()
    a = build_episode_text(ep)
    b = build_episode_text(ep)
    assert a == b
    assert "Payment recovery episode." in a
    assert "UPI autopay" in a
    assert "insufficient funds" in a
    assert "RETRY FIXABLE" in a
    assert "₹4,999" in a
    assert "delayed retry" in a
    assert "15 minutes" in a
    assert "Outcome: successful" in a
    assert "synthetic simulation" in a
    assert "Seed: 42" in a
    assert "recovery_v1_seed42_sim_42_0001" in a  # in metadata block
    assert "test-secret-key" not in a


def test_parse_search_response_inherent_schema():
    payload = {
        "results": [
            {
                "chunk_id": "chunk-1",
                "document_id": "doc-1",
                "document_name": "recovery-sim-v1-seed42-case1.txt",
                "content": "Payment recovery episode.",
                "score": 0.91,
                "metadata": {"action": "schedule_retry", "recovery_class": "RETRY_FIXABLE"},
            }
        ],
        "query": "UPI failure",
        "total_results": 1,
        "processing_time_ms": 12.5,
        "search_mode": "semantic",
    }
    rows, meta = parse_search_response(payload)
    assert len(rows) == 1
    assert rows[0]["episode_id"] == "doc-1"
    assert rows[0]["document_name"] == "recovery-sim-v1-seed42-case1.txt"
    assert rows[0]["score"] == 0.91
    assert meta is not None
    assert meta.processing_time_ms == 12.5


def test_parse_document_upload_and_status():
    up = parse_document_upload(
        {
            "document_id": "abc",
            "name": "file.txt",
            "status": "pending",
            "workspace_id": "ws1",
            "mime_type": "text/plain",
            "size_bytes": 100,
        }
    )
    assert up.document_id == "abc"
    assert up.status == "pending"

    st = parse_document_status(
        {"id": "abc", "name": "file.txt", "status": "processed", "chunk_count": 2},
        document_id="abc",
    )
    assert st.status == "processed"
    assert is_completed_status("processed")
    assert is_failed_status("failed") is True


# --- disabled mode ---


def test_disabled_search_returns_empty(monkeypatch):
    monkeypatch.setenv("INHERENT_ENABLED", "false")
    svc = InherentMemoryService(config=InherentConfig.from_env())
    assert svc.enabled is False
    result = _run(svc.search_payment_cases("UPI insufficient funds", top_k=5))
    assert result == []


def test_disabled_store_no_network(monkeypatch):
    monkeypatch.setenv("INHERENT_ENABLED", "false")
    svc = InherentMemoryService(config=InherentConfig.from_env())

    with patch("memory.inherent_client.httpx.AsyncClient") as mock_client_cls:
        _run(svc.store_payment_episode(_sample_episode()))
        mock_client_cls.assert_not_called()


# --- successful retrieval ---


def test_search_success_converts_to_retrieval_result():
    cfg = _enabled_config()
    mock_http = AsyncMock()
    mock_http.request = AsyncMock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "document_id": "sim_43_abc",
                        "document_name": "recovery.txt",
                        "content": "Payment recovery episode.",
                        "score": 0.88,
                        "metadata": {"action": "schedule_retry"},
                    }
                ],
                "query": "insufficient funds UPI",
                "total_results": 1,
                "processing_time_ms": 5.0,
                "search_mode": "semantic",
            },
        ),
    )
    client = InherentClient(cfg, client=mock_http)
    svc = InherentMemoryService(config=cfg, client=client)

    results = _run(svc.search_payment_cases("insufficient funds UPI", top_k=10))
    assert len(results) == 1
    assert results[0].episode_id == "sim_43_abc"
    assert results[0].document_name == "recovery.txt"
    assert results[0].score == 0.88

    mock_http.request.assert_awaited()
    call_kwargs = mock_http.request.await_args.kwargs
    body = call_kwargs.get("json") or {}
    assert body["query"] == "insufficient funds UPI"
    assert body["limit"] == 10
    headers = call_kwargs["headers"]
    assert headers["X-API-Key"] == "test-secret-key"
    assert headers["X-Workspace-Id"] == "ws_recovery"
    assert "workspace_id" not in body


# --- successful ingestion ---


def test_store_success_multipart_upload():
    cfg = _enabled_config()
    mock_http = AsyncMock()
    mock_http.request = AsyncMock(
        return_value=httpx.Response(
            201,
            json={
                "document_id": "doc-new",
                "name": "recovery-sim-v1-seed42-case1.txt",
                "status": "pending",
                "workspace_id": "ws_recovery",
                "mime_type": "text/plain",
                "size_bytes": 512,
            },
        )
    )
    client = InherentClient(cfg, client=mock_http)
    svc = InherentMemoryService(config=cfg, client=client)
    ep = _sample_episode()

    doc_id = _run(svc.store_payment_episode(ep))
    assert doc_id == "doc-new"

    mock_http.request.assert_awaited()
    call_kwargs = mock_http.request.await_args.kwargs
    assert call_kwargs["headers"]["X-API-Key"] == "test-secret-key"
    assert call_kwargs["files"] is not None
    assert "test-secret-key" not in str(call_kwargs["files"])


# --- timeout / connection / invalid ---


def test_search_timeout_returns_empty():
    cfg = _enabled_config()
    mock_http = AsyncMock()
    mock_http.request = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
    client = InherentClient(cfg, client=mock_http)
    svc = InherentMemoryService(config=cfg, client=client)

    results = _run(svc.search_payment_cases("query", top_k=5))
    assert results == []


def test_search_connection_error_returns_empty():
    cfg = _enabled_config(max_retries=0)
    mock_http = AsyncMock()
    mock_http.request = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
    client = InherentClient(cfg, client=mock_http)
    svc = InherentMemoryService(config=cfg, client=client)

    results = _run(svc.search_payment_cases("query", top_k=5))
    assert results == []


def test_search_invalid_json_returns_empty():
    cfg = _enabled_config()
    mock_http = AsyncMock()
    mock_http.request = AsyncMock(
        return_value=httpx.Response(200, content=b"not-json", headers={"Content-Type": "text/plain"})
    )
    client = InherentClient(cfg, client=mock_http)
    svc = InherentMemoryService(config=cfg, client=client)

    results = _run(svc.search_payment_cases("query", top_k=5))
    assert results == []


def test_search_malformed_rows_skipped():
    cfg = _enabled_config()
    mock_http = AsyncMock()
    mock_http.request = AsyncMock(
        return_value=httpx.Response(
            200,
            json={
                "results": [{"document_id": "ok", "content": "x", "score": 0.5}, "bad-row"],
                "query": "q",
                "total_results": 1,
                "processing_time_ms": 1,
                "search_mode": "semantic",
            },
        )
    )
    client = InherentClient(cfg, client=mock_http)
    svc = InherentMemoryService(config=cfg, client=client)

    results = _run(svc.search_payment_cases("query", top_k=5))
    assert len(results) == 1
    assert results[0].episode_id == "ok"


# --- authentication ---


def test_auth_header_sent_never_logged():
    cfg = _enabled_config(api_key="super-secret-token")
    mock_http = AsyncMock()
    mock_http.request = AsyncMock(
        return_value=httpx.Response(
            200,
            json={
                "results": [],
                "query": "q",
                "total_results": 0,
                "processing_time_ms": 1,
                "search_mode": "semantic",
            },
        )
    )
    client = InherentClient(cfg, client=mock_http)
    svc = InherentMemoryService(config=cfg, client=client)

    with patch("memory.service.slog") as mock_slog:
        _run(svc.search_payment_cases("query"))

    headers = mock_http.request.await_args.kwargs["headers"]
    assert headers["X-API-Key"] == "super-secret-token"
    assert "Authorization" not in headers

    for call in mock_slog.call_args_list:
        assert "super-secret-token" not in str(call)


def test_client_search_raises_on_http_error():
    cfg = _enabled_config(max_retries=0)
    mock_http = AsyncMock()
    mock_http.request = AsyncMock(
        return_value=httpx.Response(401, json={"error": "unauthorized"})
    )
    client = InherentClient(cfg, client=mock_http)

    with pytest.raises(InherentClientError):
        _run(client.search("q", limit=1))


def test_429_is_retried():
    cfg = _enabled_config(max_retries=2)
    mock_http = AsyncMock()
    mock_http.request = AsyncMock(
        side_effect=[
            httpx.Response(429, json={"error": "rate limit"}),
            httpx.Response(
                200,
                json={
                    "results": [],
                    "query": "q",
                    "total_results": 0,
                    "processing_time_ms": 1,
                    "search_mode": "semantic",
                },
            ),
        ]
    )
    client = InherentClient(cfg, client=mock_http)
    rows, _ = _run(client.search("q", limit=1))
    assert rows == []
    assert mock_http.request.await_count == 2


def test_empty_query_returns_empty_without_call():
    cfg = _enabled_config()
    mock_http = AsyncMock()
    client = InherentClient(cfg, client=mock_http)
    svc = InherentMemoryService(config=cfg, client=client)

    assert _run(svc.search_payment_cases("   ", top_k=5)) == []
    mock_http.request.assert_not_awaited()


def test_all_requests_use_public_api_base_url():
    cfg = _enabled_config()
    mock_http = AsyncMock()
    mock_http.request = AsyncMock(
        return_value=httpx.Response(
            201,
            json={
                "document_id": "doc-1",
                "name": "f.txt",
                "status": "pending",
                "workspace_id": "ws",
                "mime_type": "text/plain",
                "size_bytes": 10,
            },
        )
    )
    client = InherentClient(cfg, client=mock_http)
    _run(client.upload_document(filename="f.txt", content=b"hello"))
    url = mock_http.request.await_args.args[1]
    assert url.startswith("http://inherent.test:18000/")
    assert ":18002" not in url


def test_wait_for_document_completed():
    cfg = _enabled_config(poll_interval_seconds=0.01, poll_timeout_seconds=1.0)
    mock_http = AsyncMock()
    mock_http.request = AsyncMock(
        side_effect=[
            httpx.Response(200, json={"id": "d1", "name": "f.txt", "status": "pending"}),
            httpx.Response(200, json={"id": "d1", "name": "f.txt", "status": "processed", "chunk_count": 1}),
        ]
    )
    client = InherentClient(cfg, client=mock_http)
    result = _run(client.wait_for_document("d1"))
    assert result.status == "processed"
