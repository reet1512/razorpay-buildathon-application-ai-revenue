"""
logging_util.py — structured, PII-light logs for Phase 9.

Fields we allow: case_id, event_id, verb, gate, status, run_id.
Never pass raw webhook bodies, phone, email, or PAN into these helpers.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

_LOG = logging.getLogger("recovery_agent")


def configure_logging(level: int = logging.INFO) -> None:
    if _LOG.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    )
    _LOG.addHandler(handler)
    _LOG.setLevel(level)
    _LOG.propagate = False


def slog(
    event: str,
    *,
    case_id: Optional[str] = None,
    event_id: Optional[str] = None,
    verb: Optional[str] = None,
    gate: Optional[str] = None,
    status: Optional[str] = None,
    run_id: Optional[str] = None,
    **extra: Any,
) -> None:
    """Emit one JSON-ish structured line (easy to greppaste into a judge deck)."""
    configure_logging()
    payload = {"event": event}
    if case_id is not None:
        payload["case_id"] = case_id
    if event_id is not None:
        payload["event_id"] = event_id
    if verb is not None:
        payload["verb"] = verb
    if gate is not None:
        payload["gate"] = gate
    if status is not None:
        payload["status"] = status
    if run_id is not None:
        payload["run_id"] = run_id
    for k, v in extra.items():
        if v is not None and k not in payload:
            # Soft guard: skip obvious PII-ish keys
            if k.lower() in {"phone", "email", "pan", "card", "body", "raw"}:
                continue
            payload[k] = v
    _LOG.info("%s", json.dumps(payload, default=str))
