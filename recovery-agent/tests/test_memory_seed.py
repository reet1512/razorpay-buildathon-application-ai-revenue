"""Tests for memory seeder CLI and manifest."""

from __future__ import annotations

import json
from pathlib import Path

from memory.manifest import MemoryManifest
from memory.seed import _parse_args, _resolve_seeds


def test_seed_parsing():
    args = _parse_args(["--seeds", "42-44", "--n", "10"])
    assert _resolve_seeds(args) == [42, 43, 44]

    args = _parse_args(["--seed", "42", "--n", "5"])
    assert _resolve_seeds(args) == [42]


def test_dry_run_no_manifest_write(tmp_path, capsys):
    manifest_path = tmp_path / "manifest.json"
    from memory.seed import main

    rc = main(["--seed", "42", "--n", "3", "--dry-run", "--manifest", str(manifest_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Expected episodes: 3" in out
    assert "Semantic text:" in out
    assert not manifest_path.exists()


def test_manifest_idempotency(tmp_path):
    path = tmp_path / "manifest.json"
    m = MemoryManifest(path)
    m.init_run(seeds=[42], cases_per_seed=5)
    m.record_episode(
        "recovery_v1_seed42_sim_42_0001",
        seed=42,
        case_id="sim_42_0001",
        document_id="doc-1",
        status="completed",
    )
    m.save()

    m2 = MemoryManifest(path)
    assert m2.should_skip("recovery_v1_seed42_sim_42_0001", resume=True)
    assert not m2.should_skip("recovery_v1_seed42_sim_42_0001", resume=False)

    data = json.loads(path.read_text())
    assert data["completed"] == 1
    assert data["data_source"] == "synthetic_simulation"
