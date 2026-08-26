"""Sprint 4 Inherent retrieval sanity checks."""
from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from memory.inherent_client import InherentClient, InherentConfig  # noqa: E402

QUERIES = [
    ("UPI temporary bank failure retry fixable", "RETRY_FIXABLE"),
    ("card expired customer action send payment link", "CUSTOMER_ACTION"),
    ("mandate revoked customer action", "CUSTOMER_ACTION"),
    ("do not honour ambiguous payment", "AMBIGUOUS"),
    ("fraud risk prohibited recovery escalate", "PROHIBITED"),
    ("gateway timeout retry fixable", "RETRY_FIXABLE"),
]


async def main() -> int:
    cfg = InherentConfig.from_env()
    if not cfg.enabled or not cfg.api_key:
        print("SKIP: Inherent not configured", flush=True)
        return 0
    out = []
    matched = 0
    async with InherentClient(cfg) as client:
        for q, expect in QUERIES:
            rows, _meta = await client.search(q, limit=8, search_mode="hybrid")
            classes = Counter()
            for r in rows:
                md = r.get("metadata") or {}
                classes[str(md.get("recovery_class") or "unknown")] += 1
            top = (rows[0].get("metadata") or {}) if rows else {}
            top_class = str(top.get("recovery_class") or "unknown")
            ok = top_class == expect or classes.get(expect, 0) >= 3
            if ok:
                matched += 1
            row = {
                "query": q,
                "expect": expect,
                "hits": len(rows),
                "class_dist": dict(classes),
                "top_class": top_class,
                "top_failure": top.get("failure_reason"),
                "top_action": top.get("action"),
                "ok": ok,
            }
            out.append(row)
            print(json.dumps(row), flush=True)
    path = ROOT / "artifacts" / "rag_validate_s4.json"
    path.write_text(
        json.dumps({"matched": matched, "total": len(QUERIES), "rows": out}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    print(f"MATCHED {matched}/{len(QUERIES)} WROTE {path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
