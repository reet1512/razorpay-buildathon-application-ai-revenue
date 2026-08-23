"""
config/costs.py — single reader for config/costs.json.

Every monetary assumption lives in costs.json. Other modules must call
get_cost() / get_cost_value() here — never hardcode fee tables.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel

_VALID_SOURCES = frozenset({"dashboard", "invoice", "published", "ASSUMPTION"})

_COSTS_PATH = Path(__file__).resolve().parent / "costs.json"

# Live UI overrides (Task 6); merged on top of file defaults.
_overrides: dict[str, float] = {}


class CostParam(BaseModel):
    value: float
    source: str
    note: Optional[str] = None


def _validate_source(source: str, key: str) -> None:
    if source not in _VALID_SOURCES:
        raise ValueError(
            f"costs.json[{key!r}].source must be one of "
            f"{sorted(_VALID_SOURCES)}, got {source!r}"
        )


def _parse_leaf(key: str, raw: Any) -> CostParam:
    if not isinstance(raw, dict):
        raise ValueError(f"costs.json[{key!r}] must be an object with value/source")
    if "value" not in raw:
        raise KeyError(f"costs.json missing required key: {key}.value")
    if "source" not in raw:
        raise KeyError(f"costs.json missing required key: {key}.source")
    param = CostParam(
        value=float(raw["value"]),
        source=str(raw["source"]),
        note=str(raw["note"]) if raw.get("note") is not None else None,
    )
    _validate_source(param.source, key)
    return param


def _walk_leaves(
    node: Any,
    prefix: str,
    out: dict[str, CostParam],
) -> None:
    if not isinstance(node, dict):
        return
    for name, child in node.items():
        if name.startswith("_"):
            continue
        key = f"{prefix}.{name}" if prefix else name
        if isinstance(child, dict) and "value" in child and "source" in child:
            out[key] = _parse_leaf(key, child)
        elif isinstance(child, dict):
            _walk_leaves(child, key, out)
        else:
            raise ValueError(f"costs.json[{key!r}] is not a recognised cost leaf")


def _load_raw() -> dict[str, Any]:
    if not _COSTS_PATH.is_file():
        raise FileNotFoundError(f"costs file not found: {_COSTS_PATH}")
    with _COSTS_PATH.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("costs.json root must be an object")
    return data


@lru_cache(maxsize=1)
def load_costs() -> dict[str, CostParam]:
    """Load and validate every cost leaf from costs.json."""
    raw = _load_raw()
    params: dict[str, CostParam] = {}
    _walk_leaves(raw, "", params)
    if not params:
        raise ValueError("costs.json contains no cost parameters")
    return params


def get_cost(key: str) -> CostParam:
    """
    Return one cost parameter by dotted key (e.g. 'attempt.sms_dlt').

    Raises KeyError with an explicit message if the key is absent.
    Applies in-memory overrides from set_cost_overrides() to .value only.
    """
    params = load_costs()
    if key not in params:
        known = ", ".join(sorted(params))
        raise KeyError(f"costs.json missing required key: {key!r}. Known: {known}")
    base = params[key]
    if key in _overrides:
        return base.model_copy(update={"value": _overrides[key]})
    return base


def get_cost_value(key: str) -> float:
    """Convenience: numeric value only."""
    return get_cost(key).value


def all_costs() -> dict[str, CostParam]:
    """All parameters, including live overrides on values."""
    return {k: get_cost(k) for k in load_costs()}


def set_cost_overrides(overrides: dict[str, float]) -> None:
    """Replace live overrides (Task 6 assumptions panel)."""
    global _overrides
    _overrides = dict(overrides)


def clear_cost_overrides() -> None:
    _overrides.clear()


def costs_json_path() -> Path:
    """Absolute path to costs.json (for enforcement tests)."""
    return _COSTS_PATH


def reload_costs() -> None:
    """Clear caches after tests mutate the file on disk."""
    load_costs.cache_clear()
