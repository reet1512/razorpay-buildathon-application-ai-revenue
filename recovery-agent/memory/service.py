"""
memory/service.py — application-facing Inherent memory API.

Not wired to RecoveryAgent yet (Phase 2). Safe to import; no side effects when disabled.
"""

from __future__ import annotations

from typing import Optional

from logging_util import slog

from memory.episode_text import build_episode_text
from memory.identity import document_filename
from memory.inherent_client import (
    InherentClient,
    InherentClientError,
    InherentConfig,
    SearchMode,
)
from memory.schemas import PaymentEpisode, RetrievalResult


class InherentMemoryService:
    """
    Semantic memory boundary for payment recovery episodes.

    When INHERENT_ENABLED=false:
      search_payment_cases → []
      store_payment_episode → no-op (no network)
    """

    def __init__(
        self,
        config: Optional[InherentConfig] = None,
        client: Optional[InherentClient] = None,
    ) -> None:
        self.config = config or InherentConfig.from_env()
        self._client = client

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def _client_instance(self) -> InherentClient:
        if self._client is not None:
            return self._client
        return InherentClient(self.config)

    async def search_with_meta(
        self,
        query: str,
        top_k: int = 20,
        *,
        search_mode: SearchMode = "semantic",
    ) -> tuple[list[RetrievalResult], Optional[float]]:
        """
        Search and return results plus server processing_time_ms when available.

        Raises InherentClientError on transport/API failure (callers handle).
        """
        if not self.config.enabled:
            return [], None

        query = (query or "").strip()
        if not query:
            return [], None

        limit = max(1, min(int(top_k), 100))
        client = self._client_instance()

        if self._client is None:
            async with client:
                raw_rows, meta = await client.search(
                    query, limit=limit, search_mode=search_mode
                )
        else:
            raw_rows, meta = await client.search(
                query, limit=limit, search_mode=search_mode
            )

        results: list[RetrievalResult] = []
        for row in raw_rows:
            try:
                results.append(RetrievalResult.model_validate(row))
            except Exception:
                continue

        server_ms = meta.processing_time_ms if meta else None
        slog(
            "inherent_search_ok",
            status="ok",
            retrieved_count=len(results),
        )
        return results, server_ms

    async def search_payment_cases(
        self,
        query: str,
        top_k: int = 20,
        *,
        search_mode: SearchMode = "semantic",
    ) -> list[RetrievalResult]:
        if not self.config.enabled:
            return []

        query = (query or "").strip()
        if not query:
            return []

        try:
            results, _ = await self.search_with_meta(
                query, top_k=top_k, search_mode=search_mode
            )
        except InherentClientError as exc:
            slog(
                "inherent_search_failed",
                status=str(exc),
                retrieved_count=0,
            )
            return []

        return results

    async def store_payment_episode(
        self,
        episode: PaymentEpisode,
        *,
        wait_for_processing: bool = False,
    ) -> Optional[str]:
        """
        Upload episode text to Inherent. Returns document_id when enabled.

        Does not poll unless wait_for_processing=True (seeder uses client directly).
        """
        if not self.config.enabled:
            return None

        text = build_episode_text(episode)
        seed = episode.seed if episode.seed is not None else 0
        case_id = episode.case_id or episode.episode_id
        filename = document_filename(
            seed=seed,
            case_id=case_id,
            simulation_version=episode.simulation_version,
        )
        client = self._client_instance()

        try:
            if self._client is None:
                async with client:
                    upload = await client.upload_document(
                        filename=filename,
                        content=text.encode("utf-8"),
                    )
                    if wait_for_processing:
                        await client.wait_for_document(upload.document_id)
            else:
                upload = await client.upload_document(
                    filename=filename,
                    content=text.encode("utf-8"),
                )
                if wait_for_processing:
                    await client.wait_for_document(upload.document_id)
        except InherentClientError as exc:
            slog(
                "inherent_ingest_failed",
                status=str(exc),
                event_id=episode.episode_id,
            )
            return None

        slog(
            "inherent_ingest_ok",
            status="ok",
            event_id=episode.episode_id,
        )
        return upload.document_id
