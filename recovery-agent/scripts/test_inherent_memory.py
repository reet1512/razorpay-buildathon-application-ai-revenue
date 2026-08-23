#!/usr/bin/env python3
"""
End-to-end smoke test for Inherent payment recovery memory.

Run from recovery-agent/:
  python scripts/test_inherent_memory.py

Requires INHERENT_ENABLED=true and a valid INHERENT_API_KEY.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from eval.recovery_class import RecoveryClass
from eval.types import FailureReason
from ledger.schemas import Rail
from memory.episode_factory import payment_episode_from_case
from memory.episode_text import build_episode_text
from memory.inherent_client import InherentClient, InherentConfig, is_completed_status
from memory.schemas import DataSource, EpisodeOutcome, PaymentEpisode
from policy.schemas import ActionVerb


def _synthetic_episode() -> PaymentEpisode:
    from eval.payer_model import sample_hidden_truth
    from eval.types import CaseOutcome, HiddenPayerTruth, SimCase, VisibleCase

    hidden = HiddenPayerTruth(
        instrument_valid=True,
        true_credit_day=15,
        natural_recovery_prob=0.05,
        base_contact_response_prob=0.3,
    )
    case = SimCase(
        visible=VisibleCase(
            case_key="sim_smoke_0001",
            payer_ref="payer_smoke_0001",
            amount_paise=499900,
            rail="upi_autopay",
            failure_reason=FailureReason.issuer_transient,
            attempt_number=1,
        ),
        hidden=hidden,
        failure_dom=12,
    )
    outcome = CaseOutcome(
        case_key=case.visible.case_key,
        recovered=True,
        recovered_paise=499900,
        contacts=0,
        retries=1,
        notes=["retry@1:ok"],
    )
    return payment_episode_from_case(case=case, outcome=outcome, seed=42)


async def _run() -> int:
    cfg = InherentConfig.from_env()
    host = cfg.base_url.replace("http://", "").replace("https://", "")

    print("=== INHERENT MEMORY SMOKE TEST ===\n")
    print(f"Inherent:\n{host}\n")

    if not cfg.enabled:
        print("SKIP: INHERENT_ENABLED is false")
        return 1

    ep = _synthetic_episode()
    text = build_episode_text(ep)
    filename = f"recovery-smoke-{ep.episode_id}.txt"

    print("Upload:")
    try:
        async with InherentClient(cfg) as client:
            upload = await client.upload_document(
                filename=filename,
                content=text.encode("utf-8"),
            )
            print("PASS\n")
            print(f"Document ID:\n{upload.document_id}\n")

            final = await client.wait_for_document(upload.document_id)
            print(f"Processing:\n{final.status}\n")

            if not is_completed_status(final.status):
                print(f"FAIL: unexpected status {final.status}")
                return 1

            query = "UPI issuer transient retry fixable"
            rows, meta = await client.search(query, limit=5, search_mode="semantic")
            print("Search:")
            print("PASS\n")
            print(f"Query:\n{query}\n")
            print(f"Results:\n{len(rows)}\n")
            if rows:
                top = rows[0]
                print(f"Top result:\n{top.get('document_name') or top.get('document_id')}\n")
                print(f"Score:\n{top.get('score')}\n")
            else:
                print("Top result:\n(none yet — indexing may need more time)\n")
                print("Score:\nunavailable\n")

            if meta and meta.processing_time_ms is not None:
                print(f"Processing time:\n{meta.processing_time_ms} ms\n")
            else:
                print("Processing time:\nunavailable\n")

            print("ROUND TRIP:")
            print("PASS" if rows else "PARTIAL (upload ok, search empty)")
            return 0 if rows else 1
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 1


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
