# SPDX-License-Identifier: Apache-2.0
import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from benchmark_summary import (  # noqa: E402
    audit_rows,
    load_runs,
    paired_speedups,
    phase_summaries,
    reuse_break_even,
    scaling_series,
)


def write_run(
    root,
    run_id,
    engine,
    allocation,
    *,
    cores=4,
    fixture="grid",
    scope="in-memory",
    scaling="strong",
    seconds=(2, 2),
    setup=8,
    cells=100,
    status="complete",
    passed=True,
):
    directory = root / run_id
    directory.mkdir()
    metadata = {
        "schema_version": 1,
        "run_id": run_id,
        "allocation_id": allocation,
        "pathway": "mpi",
        "engine": engine,
        "fixture_id": fixture,
        "method": "bilinear",
        "normalization": "none",
        "edge_model": "great_circle",
        "unmapped": "ignore",
        "precision": "float64",
        "timing_scope": scope,
        "workload_id": "grid-family",
        "scaling": scaling,
        "resources": {"nodes": cores // 4, "cores": cores, "ranks": cores},
    }
    for name, record in {
        "run": metadata,
        "quality": {"passed": passed, "metrics": {"rmse": 0.01}},
        "outcome": {"status": status, "reason": None if status == "complete" else "test failure"},
    }.items():
        (directory / f"{name}.json").write_text(json.dumps(record))
    rows = [(0, "setup", setup), (1, "apply", 10_000), *[(0, "apply", s) for s in seconds]]
    with (directory / "observations.csv").open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["phase", "seconds", "trial", "launch_id", "warmup", "fields", "cells"])
        for trial, (warmup, phase, duration) in enumerate(rows):
            writer.writerow([phase, duration, trial, "launch-1", warmup, 1, cells])
    return directory


def test_allocation_is_unit_of_replication_and_warmups_are_excluded(tmp_path):
    write_run(tmp_path, "long", "axis", "a", seconds=(1,) * 21)
    write_run(tmp_path, "extra-launch", "axis", "a", seconds=(3,))
    write_run(tmp_path, "short", "axis", "b", seconds=(6,))
    rows = phase_summaries(load_runs(tmp_path))
    apply = next(row for row in rows if row["phase"] == "apply")
    assert apply["median_seconds"] == 4
    assert apply["iqr_seconds"] == 2
    assert apply["allocations"] == 2
    assert apply["median_core_hours"] == pytest.approx(16 / 3600)


def test_speedup_is_paired_and_failures_stay_in_audit(tmp_path):
    write_run(tmp_path, "axis-a", "axis", "a")
    write_run(tmp_path, "ref-a", "esmf", "a", seconds=(4,))
    write_run(tmp_path, "ref-b", "esmf", "b", seconds=(100,))
    write_run(tmp_path, "ref-c", "esmf", "a", scope="includes-I/O", seconds=(100,))
    write_run(tmp_path, "failed", "axis", "c", status="oom")
    write_run(tmp_path, "bad-physics", "esmf", "a", passed=False)
    interrupted = write_run(tmp_path, "interrupted", "axis", "e")
    (interrupted / "outcome.json").unlink()
    runs = load_runs(tmp_path)
    pairs = [row for row in paired_speedups(runs) if row["phase"] == "apply"]
    assert len(pairs) == 1
    assert pairs[0]["median_speedup"] == 2
    assert pairs[0]["paired_allocations"] == 1
    audit = {row["run_id"]: row for row in audit_rows(runs)}
    assert audit["failed"]["status"] == "oom"
    assert audit["interrupted"]["status"] == "interrupted"
    assert audit["bad-physics"]["comparison"] == "quality-failed"
    assert audit["ref-b"]["comparison"] == "no-paired-results"
    assert audit["ref-c"]["comparison"] == "no-paired-results"


def test_scaling_uses_smallest_success_and_workload_growth(tmp_path):
    write_run(tmp_path, "failed", "axis", "a", status="oom")
    write_run(tmp_path, "eight", "axis", "b", cores=8, seconds=(5,))
    write_run(tmp_path, "sixteen", "axis", "c", cores=16, seconds=(2.5,))
    write_run(tmp_path, "weak-small", "axis", "d", scaling="weak", cells=100)
    write_run(
        tmp_path, "weak-large", "axis", "e", scaling="weak", cells=180, fixture="grid-big", cores=8
    )
    rows = scaling_series(load_runs(tmp_path))
    strong = next(row for row in rows if row["scaling"] == "strong" and row["cores"] == 16)
    assert strong["relative_to_cores"] == 8
    assert strong["efficiency"] == 1
    weak = next(row for row in rows if row["scaling"] == "weak" and row["cores"] == 8)
    assert weak["workload_growth"] == 1.8
    assert weak["efficiency"] == 0.9


def test_reuse_break_even_from_matched_allocation(tmp_path):
    write_run(tmp_path, "axis", "axis", "a", setup=8, seconds=(2,))
    write_run(tmp_path, "esmf", "esmf", "a", setup=2, seconds=(4,))
    (row,) = reuse_break_even(load_runs(tmp_path))
    assert row["applications_to_break_even"] == 3
    assert row["axis_setup_seconds"] == 8
    assert row["reference_apply_seconds"] == 4


def test_memory_reports_only_measured_values(tmp_path):
    present = write_run(tmp_path, "measured", "axis", "a")
    write_run(tmp_path, "absent", "axis", "b")
    csv_path = present / "observations.csv"
    with csv_path.open(newline="") as file:
        rows = list(csv.DictReader(file))
    with csv_path.open("w", newline="") as file:
        names = [*rows[0], "peak_memory_bytes", "memory_scope"]
        writer = csv.DictWriter(file, fieldnames=names)
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, "peak_memory_bytes": "1024", "memory_scope": "per rank"})
    row = next(
        record for record in phase_summaries(load_runs(tmp_path)) if record["phase"] == "apply"
    )
    assert row["peak_memory_bytes"] == 1024
    assert row["memory_scope"] == "per rank"


def test_phase_scopes_gate_only_the_affected_comparison(tmp_path):
    axis = write_run(tmp_path, "axis", "axis", "a")
    reference = write_run(tmp_path, "ref", "esmf", "a")
    for directory, scope in ((axis, "read-on-fit"), (reference, "in-memory-grid")):
        path = directory / "run.json"
        metadata = json.loads(path.read_text())
        metadata["phase_scopes"] = {"setup": scope}
        path.write_text(json.dumps(metadata))
    runs = load_runs(tmp_path)
    (row,) = paired_speedups(runs)
    assert row["phase"] == "apply"
    assert not reuse_break_even(runs)
    for item in audit_rows(runs):
        assert item["comparison"] == "partially-paired"
        assert item["paired_phases"] == "apply"
        assert item["unmatched_phases"] == "setup"


def test_legacy_paper_workers_do_not_appear_interrupted(tmp_path):
    write_run(tmp_path, "actual", "axis", "a")
    legacy = tmp_path / "legacy-paper-worker"
    legacy.mkdir()
    (legacy / "run.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "timing",
                "backend": "ESMF native single PET",
            }
        )
    )
    assert [run.metadata["run_id"] for run in load_runs(tmp_path)] == ["actual"]
