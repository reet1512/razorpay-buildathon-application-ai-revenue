"""
memory/inherent_client.py — HTTP client for Inherent Public API.

Verified against local OpenAPI at http://localhost:18000/openapi.json (v0.2.0):
  - Auth: X-API-Key header (+ optional X-Workspace-Id)
  - Upload: POST /v1/documents multipart/form-data (file field)
  - Status: GET /v1/documents/{document_id}
  - Search: POST /v1/search JSON { query, limit, search_mode, ... }

Document upload is asynchronous; poll status until completed/processed or failed.
"""

from __future__ import annotations

import asyncio
import os
import random
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

SearchMode = Literal["semantic", "hybrid", "keyword"]

# Status values observed from local API (upload returns "pending"; Document default "processed")
_COMPLETED_STATUSES = frozenset({"completed", "processed", "ready"})
_FAILED_STATUSES = frozenset({"failed", "error"})
_PROCESSING_STATUSES = frozenset({"pending", "processing", "queued", "indexing"})

_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class InherentClientError(Exception):
    """Client error — callers decide whether to degrade or abort."""


@dataclass(frozen=True)
class InherentConfig:
    enabled: bool
    base_url: str
    search_path: str
    documents_path: str
    api_key: str
    workspace_id: str
    timeout_seconds: float
    poll_interval_seconds: float
    poll_timeout_seconds: float
    max_retries: int
    seed_concurrency: int
    seed_batch_size: int

    @classmethod
    def from_env(cls) -> InherentConfig:
        def _bool(name: str, default: str = "false") -> bool:
            return os.getenv(name, default).strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }

        def _float(name: str, default: str) -> float:
            try:
                return float(os.getenv(name, default).strip())
            except ValueError:
                return float(default)

        def _int(name: str, default: str) -> int:
            try:
                return int(os.getenv(name, default).strip())
            except ValueError:
                return int(default)

        return cls(
            enabled=_bool("INHERENT_ENABLED", "false"),
            base_url=os.getenv("INHERENT_BASE_URL", "http://localhost:18000").rstrip(
                "/"
            ),
            search_path=os.getenv("INHERENT_SEARCH_PATH", "/v1/search"),
            documents_path=os.getenv("INHERENT_DOCUMENTS_PATH", "/v1/documents"),
            api_key=os.getenv("INHERENT_API_KEY", "").strip(),
            workspace_id=os.getenv("INHERENT_WORKSPACE_ID", "").strip(),
            timeout_seconds=_float("INHERENT_TIMEOUT_SECONDS", "30"),
            poll_interval_seconds=_float("INHERENT_POLL_INTERVAL_SECONDS", "2"),
            poll_timeout_seconds=_float("INHERENT_POLL_TIMEOUT_SECONDS", "120"),
            max_retries=_int("INHERENT_MAX_RETRIES", "4"),
            seed_concurrency=_int("INHERENT_SEED_CONCURRENCY", "4"),
            seed_batch_size=_int("INHERENT_SEED_BATCH_SIZE", "25"),
        )


@dataclass(frozen=True)
class DocumentUploadResult:
    document_id: str
    name: str
    status: str
    workspace_id: str = ""
    mime_type: str = "text/plain"
    size_bytes: int = 0
    rate_limit_remaining: Optional[int] = None


@dataclass(frozen=True)
class DocumentStatusResult:
    document_id: str
    name: str
    status: str
    chunk_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchResponseMeta:
    query: str
    total_results: int
    processing_time_ms: Optional[float]
    search_mode: str


def _auth_headers(api_key: str, workspace_id: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    if api_key:
        headers["X-API-Key"] = api_key
    if workspace_id:
        headers["X-Workspace-Id"] = workspace_id
    return headers


def _join_url(base: str, path: str) -> str:
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{base}{path}"


def _parse_rate_limit(headers: httpx.Headers) -> Optional[int]:
    raw = headers.get("X-RateLimit-Remaining")
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _normalize_status(status: str) -> str:
    return (status or "").strip().lower()


def is_terminal_status(status: str) -> bool:
    s = _normalize_status(status)
    return s in _COMPLETED_STATUSES or s in _FAILED_STATUSES


def is_completed_status(status: str) -> bool:
    return _normalize_status(status) in _COMPLETED_STATUSES


def is_failed_status(status: str) -> bool:
    return _normalize_status(status) in _FAILED_STATUSES


def _extract_result_list(payload: Any) -> list[Any]:
    if not isinstance(payload, dict):
        return []
    for key in ("results", "hits", "documents", "data", "items"):
        val = payload.get(key)
        if isinstance(val, list):
            return val
    return []


def parse_search_response(payload: Any) -> tuple[list[dict[str, Any]], SearchResponseMeta | None]:
    """
    Map Inherent search JSON to normalized rows + response metadata.

    Returns empty list on unparseable input — never raises.
    """
    if not isinstance(payload, dict):
        return [], None

    meta = SearchResponseMeta(
        query=str(payload.get("query", "")),
        total_results=int(payload.get("total_results") or 0),
        processing_time_ms=(
            float(payload["processing_time_ms"])
            if payload.get("processing_time_ms") is not None
            else None
        ),
        search_mode=str(payload.get("search_mode") or "semantic"),
    )

    rows: list[dict[str, Any]] = []
    for raw in _extract_result_list(payload):
        if not isinstance(raw, dict):
            continue
        episode_id = (
            raw.get("episode_id")
            or raw.get("document_id")
            or raw.get("id")
            or raw.get("chunk_id")
        )
        content = raw.get("content") or raw.get("text") or raw.get("body")
        score = raw.get("score")
        if score is None:
            score = raw.get("similarity") or raw.get("vector_similarity")
        metadata = raw.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {
                k: v
                for k, v in raw.items()
                if k
                not in {
                    "episode_id",
                    "document_id",
                    "chunk_id",
                    "id",
                    "content",
                    "text",
                    "body",
                    "score",
                    "similarity",
                    "vector_similarity",
                    "metadata",
                    "document_name",
                    "context_before",
                    "context_after",
                }
            }
        if raw.get("document_name"):
            metadata.setdefault("document_name", raw["document_name"])
        rows.append(
            {
                "episode_id": str(episode_id) if episode_id is not None else None,
                "document_id": raw.get("document_id"),
                "document_name": raw.get("document_name"),
                "content": str(content) if content is not None else None,
                "score": float(score) if score is not None else None,
                "metadata": metadata,
            }
        )
    return rows, meta


def parse_document_upload(payload: Any) -> DocumentUploadResult:
    if not isinstance(payload, dict):
        raise InherentClientError("inherent_upload_invalid_json")
    doc_id = payload.get("document_id") or payload.get("id")
    if not doc_id:
        raise InherentClientError("inherent_upload_missing_document_id")
    return DocumentUploadResult(
        document_id=str(doc_id),
        name=str(payload.get("name") or ""),
        status=str(payload.get("status") or "pending"),
        workspace_id=str(payload.get("workspace_id") or ""),
        mime_type=str(payload.get("mime_type") or "text/plain"),
        size_bytes=int(payload.get("size_bytes") or 0),
    )


def parse_document_status(payload: Any, *, document_id: str) -> DocumentStatusResult:
    if not isinstance(payload, dict):
        raise InherentClientError("inherent_status_invalid_json")
    status = str(payload.get("status") or "unknown")
    meta = payload.get("metadata")
    if not isinstance(meta, dict):
        meta = {}
    return DocumentStatusResult(
        document_id=str(payload.get("id") or payload.get("document_id") or document_id),
        name=str(payload.get("name") or ""),
        status=status,
        chunk_count=int(payload.get("chunk_count") or 0),
        metadata=meta,
    )


class InherentClient:
    """Async HTTP client — all Inherent API specifics stay here."""

    def __init__(
        self,
        config: Optional[InherentConfig] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.config = config or InherentConfig.from_env()
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> InherentClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.config.timeout_seconds)
            self._owns_client = True
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
        self._client = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.config.timeout_seconds)
            self._owns_client = True
        return self._client

    def _headers(self) -> dict[str, str]:
        return _auth_headers(self.config.api_key, self.config.workspace_id)

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        *,
        json: Any = None,
        files: Any = None,
        data: Any = None,
    ) -> httpx.Response:
        client = self._get_client()
        headers = self._headers()
        last_exc: Exception | None = None

        for attempt in range(self.config.max_retries + 1):
            try:
                resp = await client.request(
                    method,
                    url,
                    json=json,
                    files=files,
                    data=data,
                    headers=headers,
                )
                if resp.status_code in _RETRYABLE_STATUS_CODES and attempt < self.config.max_retries:
                    await asyncio.sleep(self._backoff_seconds(attempt))
                    continue
                return resp
            except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as exc:
                last_exc = exc
                if attempt >= self.config.max_retries:
                    break
                await asyncio.sleep(self._backoff_seconds(attempt))

        if last_exc is not None:
            raise InherentClientError(f"inherent_transport_error:{last_exc}") from last_exc
        raise InherentClientError("inherent_request_exhausted")

    @staticmethod
    def _backoff_seconds(attempt: int) -> float:
        base = min(2.0 ** attempt, 16.0)
        return base + random.uniform(0, 0.5)

    async def search(
        self,
        query: str,
        *,
        limit: int = 20,
        search_mode: SearchMode = "semantic",
        min_score: float = 0.0,
        include_context: bool = False,
    ) -> tuple[list[dict[str, Any]], SearchResponseMeta | None]:
        """POST /v1/search — raises InherentClientError on HTTP/transport failure."""
        if not self.config.enabled:
            return [], None

        url = _join_url(self.config.base_url, self.config.search_path)
        body: dict[str, Any] = {
            "query": query,
            "limit": max(1, min(int(limit), 100)),
            "min_score": min_score,
            "search_mode": search_mode,
            "include_context": include_context,
        }

        try:
            resp = await self._request_with_retry("POST", url, json=body)
            if resp.status_code >= 400:
                raise InherentClientError(
                    f"inherent_search_http_status:{resp.status_code}"
                )
        except InherentClientError:
            raise
        except httpx.HTTPError as exc:
            raise InherentClientError(f"inherent_search_http_error:{exc}") from exc

        try:
            data = resp.json()
        except ValueError as exc:
            raise InherentClientError("inherent_search_invalid_json") from exc

        return parse_search_response(data)

    async def upload_document(
        self,
        *,
        filename: str,
        content: bytes,
        mime_type: str = "text/plain",
    ) -> DocumentUploadResult:
        """POST /v1/documents multipart upload."""
        if not self.config.enabled:
            raise InherentClientError("inherent_disabled")

        url = _join_url(self.config.base_url, self.config.documents_path)
        files = {"file": (filename, content, mime_type)}

        try:
            resp = await self._request_with_retry("POST", url, files=files)
            if resp.status_code >= 400:
                raise InherentClientError(
                    f"inherent_upload_http_status:{resp.status_code}"
                )
        except InherentClientError:
            raise
        except httpx.HTTPError as exc:
            raise InherentClientError(f"inherent_upload_http_error:{exc}") from exc

        try:
            data = resp.json()
        except ValueError as exc:
            raise InherentClientError("inherent_upload_invalid_json") from exc

        result = parse_document_upload(data)
        remaining = _parse_rate_limit(resp.headers)
        if remaining is not None:
            return DocumentUploadResult(
                document_id=result.document_id,
                name=result.name,
                status=result.status,
                workspace_id=result.workspace_id,
                mime_type=result.mime_type,
                size_bytes=result.size_bytes,
                rate_limit_remaining=remaining,
            )
        return result

    async def get_document_status(self, document_id: str) -> DocumentStatusResult:
        """GET /v1/documents/{document_id}."""
        if not self.config.enabled:
            raise InherentClientError("inherent_disabled")

        path = f"{self.config.documents_path.rstrip('/')}/{document_id}"
        url = _join_url(self.config.base_url, path)

        try:
            resp = await self._request_with_retry("GET", url)
            if resp.status_code >= 400:
                raise InherentClientError(
                    f"inherent_status_http_status:{resp.status_code}"
                )
        except InherentClientError:
            raise
        except httpx.HTTPError as exc:
            raise InherentClientError(f"inherent_status_http_error:{exc}") from exc

        try:
            data = resp.json()
        except ValueError as exc:
            raise InherentClientError("inherent_status_invalid_json") from exc

        return parse_document_status(data, document_id=document_id)

    async def wait_for_document(
        self,
        document_id: str,
        *,
        poll_interval: Optional[float] = None,
        poll_timeout: Optional[float] = None,
    ) -> DocumentStatusResult:
        """Poll until document reaches a terminal status or timeout."""
        interval = poll_interval if poll_interval is not None else self.config.poll_interval_seconds
        timeout = poll_timeout if poll_timeout is not None else self.config.poll_timeout_seconds
        deadline = asyncio.get_event_loop().time() + timeout
        last: DocumentStatusResult | None = None

        while asyncio.get_event_loop().time() < deadline:
            last = await self.get_document_status(document_id)
            if is_completed_status(last.status):
                return last
            if is_failed_status(last.status):
                raise InherentClientError(f"inherent_processing_failed:{last.status}")
            await asyncio.sleep(interval)

        status = last.status if last else "unknown"
        raise InherentClientError(f"inherent_processing_timeout:{status}")

    # Back-compat aliases used by Phase 1 service layer
    async def ingest(
        self,
        document_id: str,
        text: str,
        metadata: dict[str, Any],
    ) -> DocumentUploadResult:
        """Upload semantic episode text; document_id used for filename hint only."""
        _ = metadata
        filename = document_id if document_id.endswith(".txt") else f"{document_id}.txt"
        return await self.upload_document(
            filename=filename,
            content=text.encode("utf-8"),
            mime_type="text/plain",
        )
