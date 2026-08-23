"""
CLI seeder — ingest synthetic evaluation episodes into Inherent memory.

Usage:
  python -m memory.seed --seeds 42-51 --n 200
  python -m memory.seed --seed 42 --n 5 --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from collections import Counter
from typing import Any, Optional, Sequence

from eval.benchmark import parse_seeds_arg

from memory.episode_factory import generate_episodes_for_seeds
from memory.episode_text import build_episode_text
from memory.identity import document_filename
from memory.inherent_client import (
    InherentClient,
    InherentClientError,
    InherentConfig,
    is_completed_status,
)
from memory.manifest import MemoryManifest
from memory.schemas import PaymentEpisode


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Seed Inherent payment recovery memory")
    p.add_argument("--seeds", type=str, default="42-51", help="Seeds: 42-51 or 42,43")
    p.add_argument("--seed", type=int, default=None, help="Single seed (overrides --seeds)")
    p.add_argument("--n", type=int, default=200, help="Cases per seed")
    p.add_argument("--limit", type=int, default=None, help="Max episodes total")
    p.add_argument("--dry-run", action="store_true", help="Generate only; no Inherent calls")
    p.add_argument("--resume", action="store_true", help="Skip already-completed manifest entries")
    p.add_argument("--force", action="store_true", help="Reset manifest before run")
    p.add_argument("--validate", action="store_true", help="Run retrieval sanity checks after seeding")
    p.add_argument("--manifest", type=str, default=None, help="Manifest JSON path")
    return p.parse_args(argv)


def _resolve_seeds(args: argparse.Namespace) -> list[int]:
    if args.seed is not None:
        return [args.seed]
    return parse_seeds_arg(args.seeds)


def _safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", errors="replace").decode("ascii"))


def _print_dry_run(episodes: list[PaymentEpisode]) -> None:
    print(f"Expected episodes: {len(episodes)}")
    if not episodes:
        return
    ep = episodes[0]
    print("\nExample episode:")
    print(ep.model_dump_json(indent=2))
    print("\nSemantic text:")
    _safe_print(build_episode_text(ep))
    print("\nMetadata:")
    for k, v in ep.metadata_for_ingest().items():
        print(f"  {k}: {v}")
    print(f"\nLogical identity: {ep.episode_id}")
    fname = document_filename(seed=ep.seed or 0, case_id=ep.case_id or "")
    print(f"Document name: {fname}")


async def _upload_episode(
    client: InherentClient,
    episode: PaymentEpisode,
    *,
    poll: bool,
) -> dict[str, Any]:
    seed = episode.seed if episode.seed is not None else 0
    case_id = episode.case_id or episode.episode_id
    filename = document_filename(
        seed=seed,
        case_id=case_id,
        simulation_version=episode.simulation_version,
    )
    text = build_episode_text(episode)
    t0 = time.perf_counter()
    upload = await client.upload_document(
        filename=filename,
        content=text.encode("utf-8"),
    )
    upload_ms = (time.perf_counter() - t0) * 1000
    status = upload.status
    if poll:
        final = await client.wait_for_document(upload.document_id)
        status = final.status
    return {
        "document_id": upload.document_id,
        "document_name": upload.name or filename,
        "status": status,
        "upload_ms": upload_ms,
        "rate_limit_remaining": upload.rate_limit_remaining,
    }


async def _seed_async(args: argparse.Namespace) -> int:
    seeds = _resolve_seeds(args)
    manifest = MemoryManifest(
        path=__import__("pathlib").Path(args.manifest)
        if args.manifest
        else None
    )
    manifest.init_run(seeds=seeds, cases_per_seed=args.n, force=args.force)

    episodes = generate_episodes_for_seeds(
        seeds, args.n, limit=args.limit
    )
    print(f"Generated {len(episodes)} episodes from seeds {seeds} × n={args.n}")

    if args.dry_run:
        _print_dry_run(episodes)
        return 0

    cfg = InherentConfig.from_env()
    if not cfg.enabled:
        print("ERROR: INHERENT_ENABLED must be true for seeding", file=sys.stderr)
        return 1
    if not cfg.api_key:
        print("WARNING: INHERENT_API_KEY is empty — upload may fail with 401", file=sys.stderr)

    concurrency = max(1, cfg.seed_concurrency)
    sem = asyncio.Semaphore(concurrency)
    upload_latencies: list[float] = []
    processing_latencies: list[float] = []
    counts: Counter[str] = Counter()
    t_start = time.perf_counter()

    async with InherentClient(cfg) as client:

        async def _one(ep: PaymentEpisode) -> None:
            logical_id = ep.episode_id
            if manifest.should_skip(logical_id, resume=args.resume):
                manifest.record_episode(
                    logical_id,
                    seed=ep.seed or 0,
                    case_id=ep.case_id or "",
                    status="skipped",
                )
                counts["skipped"] += 1
                return

            async with sem:
                try:
                    t0 = time.perf_counter()
                    result = await _upload_episode(client, ep, poll=True)
                    elapsed = (time.perf_counter() - t0) * 1000
                    upload_latencies.append(result["upload_ms"])
                    processing_latencies.append(elapsed)
                    st = (
                        "completed"
                        if is_completed_status(result["status"])
                        else result["status"]
                    )
                    manifest.record_episode(
                        logical_id,
                        seed=ep.seed or 0,
                        case_id=ep.case_id or "",
                        document_id=result["document_id"],
                        document_name=result["document_name"],
                        status=st,
                    )
                    counts[st] += 1
                except InherentClientError as exc:
                    err = str(exc)
                    st = "retry_exhausted" if "exhausted" in err else "failed"
                    manifest.record_episode(
                        logical_id,
                        seed=ep.seed or 0,
                        case_id=ep.case_id or "",
                        status=st,
                        error=err,
                    )
                    counts[st] += 1

        await asyncio.gather(*[_one(ep) for ep in episodes])
    total_s = time.perf_counter() - t_start
    manifest.set_metrics(
        {
            "total_ingestion_seconds": round(total_s, 2),
            "episodes_attempted": len(episodes),
            "upload_latency_ms_p50": _pct(upload_latencies, 50),
            "upload_latency_ms_p95": _pct(upload_latencies, 95),
            "round_trip_ms_p50": _pct(processing_latencies, 50),
            "round_trip_ms_p95": _pct(processing_latencies, 95),
            "upload_throughput_eps": round(len(episodes) / total_s, 4) if total_s else 0,
        }
    )
    manifest.save()

    print("\n=== SEED SUMMARY ===")
    print(f"Seeds: {seeds}")
    print(f"Cases per seed: {args.n}")
    print(f"Expected: {manifest.data['expected_episodes']}")
    print(f"Uploaded: {manifest.data['uploaded']}")
    print(f"Completed: {manifest.data['completed']}")
    print(f"Failed: {manifest.data['failed']}")
    print(f"Skipped: {manifest.data['skipped']}")
    print(f"Retry exhausted: {manifest.data['retry_exhausted']}")
    print(f"Total time: {total_s:.1f}s")
    for k, v in sorted(counts.items()):
        print(f"  {k}: {v}")

    if args.validate:
        await _run_validation(cfg)

    return 0 if manifest.data["failed"] == 0 and manifest.data["retry_exhausted"] == 0 else 1


def _pct(values: list[float], pct: float) -> Optional[float]:
    if not values:
        return None
    if len(values) == 1:
        return round(values[0], 2)
    quantiles = statistics.quantiles(values, n=100, method="inclusive")
    idx = max(0, min(len(quantiles) - 1, int(pct) - 1))
    return round(quantiles[idx], 2)


VALIDATION_QUERIES = [
    "UPI temporary bank failure retry fixable",
    "card expired customer action",
    "mandate revoked customer action",
    "do not honour ambiguous payment",
    "fraud risk prohibited recovery",
    "gateway timeout retry",
]


async def _run_validation(cfg: InherentConfig) -> None:
    print("\n=== RETRIEVAL VALIDATION ===")
    async with InherentClient(cfg) as client:
        for query in VALIDATION_QUERIES:
            for mode in ("semantic", "hybrid"):
                rows, meta = await client.search(query, limit=20, search_mode=mode)
                rc_dist: Counter[str] = Counter()
                fr_dist: Counter[str] = Counter()
                scores: list[float] = []
                for row in rows:
                    md = row.get("metadata") or {}
                    rc = md.get("recovery_class") or _extract_meta_from_content(
                        row.get("content"), "recovery_class"
                    )
                    fr = md.get("failure_reason") or _extract_meta_from_content(
                        row.get("content"), "failure_reason"
                    )
                    if rc:
                        rc_dist[str(rc)] += 1
                    if fr:
                        fr_dist[str(fr)] += 1
                    if row.get("score") is not None:
                        scores.append(float(row["score"]))
                top = rows[0] if rows else {}
                top_md = top.get("metadata") or {}
                print(f"\nQuery: {query}")
                print(f"Search mode: {mode}")
                print(f"Result count: {len(rows)}")
                if meta and meta.processing_time_ms is not None:
                    print(f"Processing time: {meta.processing_time_ms} ms")
                print(f"Top document: {top.get('document_name') or top.get('document_id')}")
                print(f"Top score: {top.get('score')}")
                print(
                    f"Top recovery_class: {top_md.get('recovery_class') or _extract_meta_from_content(top.get('content'), 'recovery_class')}"
                )
                print(
                    f"Top failure_reason: {top_md.get('failure_reason') or _extract_meta_from_content(top.get('content'), 'failure_reason')}"
                )
                print(f"Top action: {top_md.get('action') or _extract_meta_from_content(top.get('content'), 'action')}")
                print(f"Top outcome: {top_md.get('outcome') or _extract_meta_from_content(top.get('content'), 'outcome')}")
                print(f"Top seed: {top_md.get('seed') or _extract_meta_from_content(top.get('content'), 'seed')}")
                print(f"RETRY_FIXABLE: {rc_dist.get('RETRY_FIXABLE', 0)}")
                print(f"CUSTOMER_ACTION: {rc_dist.get('CUSTOMER_ACTION', 0)}")
                print(f"AMBIGUOUS: {rc_dist.get('AMBIGUOUS', 0)}")
                print(f"PROHIBITED: {rc_dist.get('PROHIBITED', 0)}")
                if scores:
                    print(f"Avg score: {statistics.fmean(scores):.4f}")


def _extract_meta_from_content(content: Optional[str], key: str) -> Optional[str]:
    if not content:
        return None
    prefix = f"{key}: "
    for line in content.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return None


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    return asyncio.run(_seed_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
