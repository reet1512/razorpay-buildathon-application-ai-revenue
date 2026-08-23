"""
tests/test_costs.py — Task 1 cost model contracts.

(a) config.costs is the only module that reads costs.json
(b) No module outside config/ defines module-level cost parameter names
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from config.costs import (
    clear_cost_overrides,
    get_cost,
    get_cost_value,
    load_costs,
    set_cost_overrides,
)

_ROOT = Path(__file__).resolve().parents[1]

# Module-level assignment targets only (not functions, not class fields).
_NAME_COST = re.compile(r".*_cost$", re.IGNORECASE)
_NAME_MDR = re.compile(r"^mdr", re.IGNORECASE)
_NAME_INR = re.compile(r".*_inr$", re.IGNORECASE)

_SCAN_DIRS = ("api", "ai", "demo", "diagnose", "eval", "execute", "guard", "ingest", "ledger", "policy", "scripts", "tests")
_SKIP_FILES = frozenset({"test_costs.py"})


def _iter_project_py() -> list[Path]:
    paths: list[Path] = []
    for part in _SCAN_DIRS:
        base = _ROOT / part
        if not base.is_dir():
            continue
        paths.extend(sorted(base.rglob("*.py")))
    return paths


def _module_level_assigned_names(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.append(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.append(node.target.id)
    return names


def _is_forbidden_cost_name(name: str) -> bool:
    return bool(_NAME_COST.match(name) or _NAME_MDR.match(name) or _NAME_INR.match(name))


def test_load_costs_has_expected_leaves():
    params = load_costs()
    assert "attempt.sms_dlt" in params
    assert "success.mdr_pct" in params
    assert "risk.chargeback_fee" in params
    assert "customer.ltv" in params
    assert "scheme_limits.max_attempts_per_transaction_30d" in params


def test_get_cost_returns_typed_param():
    p = get_cost("attempt.whatsapp_utility")
    assert p.value == pytest.approx(0.12)
    assert p.source == "ASSUMPTION"
    assert p.note is not None


def test_get_cost_missing_key_raises():
    with pytest.raises(KeyError, match="costs.json missing required key: 'nope'"):
        get_cost("nope")


def test_get_cost_value():
    assert get_cost_value("success.mdr_pct") == pytest.approx(0.02)


def test_overrides_apply_to_value_only():
    clear_cost_overrides()
    try:
        set_cost_overrides({"attempt.email": 0.99})
        assert get_cost_value("attempt.email") == pytest.approx(0.99)
        assert get_cost("attempt.email").source == "ASSUMPTION"
    finally:
        clear_cost_overrides()


def test_only_config_costs_reads_costs_json():
    """(a) costs.json path must only be opened from config/costs.py."""
    offenders: list[str] = []
    costs_py = (_ROOT / "config" / "costs.py").resolve()
    needle = 'parent / "costs.json"'

    for path in _iter_project_py():
        if path.name in _SKIP_FILES:
            continue
        if path.resolve() == costs_py:
            continue
        text = path.read_text(encoding="utf-8")
        if needle in text or '_COSTS_PATH' in text:
            offenders.append(str(path.relative_to(_ROOT)))

    assert offenders == [], (
        "Only config/costs.py may open costs.json; found: " + ", ".join(offenders)
    )


def test_no_cost_parameter_names_outside_config():
    """(b) No module-level *_cost, mdr*, or *_inr names outside config/."""
    violations: list[str] = []
    config_dir = (_ROOT / "config").resolve()

    for path in _iter_project_py():
        if path.name in _SKIP_FILES:
            continue
        if config_dir in path.resolve().parents:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = path.relative_to(_ROOT)
        for name in _module_level_assigned_names(tree):
            if _is_forbidden_cost_name(name):
                violations.append(f"{rel}:{name}")

    assert violations == [], (
        "Module-level cost-like names outside config/: " + ", ".join(violations)
    )


def test_config_costs_is_only_json_loader_module():
    """(a) json.load of costs path should live only in config/costs.py."""
    offenders: list[str] = []
    costs_py = (_ROOT / "config" / "costs.py").resolve()

    for path in _iter_project_py():
        if path.name in _SKIP_FILES:
            continue
        if path.resolve() == costs_py:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "load":
                if isinstance(func.value, ast.Name) and func.value.id == "json":
                    offenders.append(str(path.relative_to(_ROOT)))
                    break

    # json.load appears in many places; narrow to files that also mention costs.json
    costs_json_loaders = [
        o for o in offenders
        if "costs.json" in (_ROOT / o).read_text(encoding="utf-8")
    ]
    assert costs_json_loaders == [], (
        "json.load on costs.json outside config/costs.py: "
        + ", ".join(costs_json_loaders)
    )
