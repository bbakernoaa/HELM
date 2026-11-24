"""Exercise allocation planning and native evidence intake without Slurm."""

import csv
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from benchmark_mpi import launch_mpi


@pytest.fixture
def mpi_case(tmp_path, monkeypatch):
    monkeypatch.setenv("SLURM_JOB_ID", "123")
    monkeypatch.setenv("SLURM_JOB_NUM_NODES", "2")
    monkeypatch.setenv("SLURM_NTASKS", "4")
    monkeypatch.setenv("SLURM_CPUS_PER_TASK", "2")
    fixture = tmp_path / "mesh-fixture"
    fixture.mkdir()
    return {
        "fixture": str(fixture),
        "fixture_id": "fixture-a",
        "workload_id": "small-spherical",
        "engine": "axis",
        "method": "conservative",
        "normalization": "dstarea",
        "edge_model": "great_circle",
        "unmapped": "zero",
        "precision": "float64",
        "timing_scope": "in_memory",
        "scaling": "strong",
        "cells": 64,
        "node_type": "mock64",
        "repetitions": 2,
        "warmups": 1,
        "reuse": [1, 10],
    }


@pytest.fixture
def fake_srun(tmp_path, monkeypatch):
    launcher = tmp_path / "srun"
    launcher.write_text(
        """#!/bin/sh
while [ "${1#--}" != "$1" ]; do shift; done
exec "$@"
"""
    )
    launcher.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    return launcher


def _run(case, work, **kwargs):
    return launch_mpi(
        case,
        build_dir=work / "build",
        output_dir=work / "out",
        nodes=2,
        ranks=4,
        threads=2,
        **kwargs,
    )


def _install_worker(work):
    worker = work / "build/paper/axis_paper_mpi_axis"
    worker.parent.mkdir(parents=True)
    worker.write_text(
        f"""#!{sys.executable}
import json
import os
import os
import sys
from pathlib import Path

out = Path(sys.argv[sys.argv.index("--output") + 1])
out.mkdir()
print("native stdout")
print("native stderr", file=sys.stderr)
(out / "observations.csv").write_text(
    "repetition,phase,applications,seconds,status\\n"
    "0,apply,1,0.5,complete\\n"
)
(out / "native_quality.json").write_text(json.dumps({{
    "passed": True,
    "ranks": 4,
    "hosts": os.environ.get("MOCK_HOSTS", "node1,node2").split(","),
    "threads_min": 2,
    "threads_max": 2,
}}))
if os.getenv("MOCK_BAD_REPORT"):
    (out / "native_quality.json").write_text("[]")
sys.exit(int(os.environ.get("MOCK_EXIT", "0")))
"""
    )
    worker.chmod(0o755)


def _json(path):
    return json.loads(path.read_text())


def test_dry_run_returns_command_without_creating_artifacts(mpi_case, tmp_path, fake_srun):
    plan = _run(mpi_case, tmp_path, mpi_plugin="pmix")
    assert plan["command"][:6] == [
        "srun",
        "--nodes=2",
        "--ntasks=4",
        "--cpus-per-task=2",
        "--distribution=block:block",
        "--cpu-bind=verbose,cores",
    ]
    assert "--mpi=pmix" in plan["command"]
    assert plan["command"][-2:] == ["--reuse", "1,10"]
    assert not (tmp_path / "out").exists()


def test_reads_native_output_and_verifies_layout(mpi_case, tmp_path, fake_srun, monkeypatch):
    monkeypatch.setenv("AXIS_MPI_LAUNCH_ID", "paired-2")
    mpi_case["launch_id"] = "different-id"
    _install_worker(tmp_path)
    _run(mpi_case, tmp_path, live=True)
    out = tmp_path / "out"
    assert _json(out / "outcome.json")["status"] == "complete"
    assert _json(out / "run.json")["resources"]["observed_hosts"] == ["node1", "node2"]
    assert "native stdout" in (out / "logs/stdout.txt").read_text()
    assert "native stderr" in (out / "logs/stderr.txt").read_text()
    with (out / "observations.csv").open(newline="") as records:
        assert {(row["launch_id"], row["cells"]) for row in csv.DictReader(records)} == {
            ("paired-2", "64")
        }
    assert _json(out / "run.json")["resources"]["node_type"] == "mock64"


def test_preserves_partial_evidence_and_logs_when_hosts_do_not_match(
    mpi_case, tmp_path, fake_srun, monkeypatch
):
    _install_worker(tmp_path)
    monkeypatch.setenv("MOCK_HOSTS", "node1")
    _run(mpi_case, tmp_path, live=True)
    out = tmp_path / "out"
    state = _json(out / "outcome.json")
    assert state["status"] == "launch_error"
    assert "expected 2" in state["reason"]
    assert "native stderr" in (out / "logs/stderr.txt").read_text()
    assert "0.5" in (out / "observations.csv").read_text()


def test_keeps_unsupported_optional_engine_record(mpi_case, tmp_path, fake_srun):
    _run({**mpi_case, "engine": "esmf"}, tmp_path, live=True)
    out = tmp_path / "out"
    state = _json(out / "outcome.json")
    assert state["status"] == "unsupported"
    assert "axis_paper_mpi_esmf" in state["reason"]


def test_rejects_live_srun_without_allocation(mpi_case, tmp_path, fake_srun, monkeypatch):
    monkeypatch.delenv("SLURM_JOB_ID")
    _run(mpi_case, tmp_path, live=True)
    out = tmp_path / "out"
    assert _json(out / "outcome.json")["status"] == "launch_error"
    assert not (out / "logs/stdout.txt").exists()


def test_preserves_timings_when_native_quality_is_malformed(
    mpi_case, tmp_path, fake_srun, monkeypatch
):
    _install_worker(tmp_path)
    monkeypatch.setenv("MOCK_BAD_REPORT", "yes")
    _run(mpi_case, tmp_path, live=True)
    out = tmp_path / "out"
    assert _json(out / "outcome.json")["status"] == "launch_error"
    assert "0.5" in (out / "observations.csv").read_text()
