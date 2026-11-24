import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run-gaea-paper.sh"


def run(*args, env=None):
    return subprocess.run(
        ["bash", str(SCRIPT), *map(str, args)],
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
    )


def test_help_describes_one_command_and_dry_run():
    result = run("--help")
    assert result.returncode == 0
    assert "--account" in result.stdout
    assert "--dry-run" in result.stdout
    assert "ESMFMKFILE" in result.stdout


def test_missing_account_stops_before_creating_results(tmp_path):
    result = run("--output", tmp_path / "results")
    assert result.returncode != 0
    assert "account" in result.stderr.lower()
    assert not (tmp_path / "results").exists()


def test_invalid_node_counts_are_rejected_before_work(tmp_path):
    result = run("--account", "project", "--output", tmp_path / "results", "--nodes", "0,2")
    assert result.returncode != 0
    assert not (tmp_path / "results").exists()


def test_dry_run_creates_nothing(tmp_path):
    output = tmp_path / "pilot results"
    result = run("--account", "project", "--output", output, "--nodes", "1,2", "--dry-run")
    assert result.returncode == 0
    assert "MPI strong/weak" in result.stdout
    assert "Dask strong/weak" in result.stdout
    assert not output.exists()


def test_internal_test_uses_exported_checkout_when_slurm_copies_script(tmp_path):
    copy = tmp_path / "slurm_script"
    copy.write_text(SCRIPT.read_text())
    python = tmp_path / "python"
    python.write_text('#!/bin/sh\nprintf "%s\\n" "$AXIS_RUN_SLURM" "$AXIS_SLURM_PROFILE" "$AXIS_SLURM_SHARED_DIR" "$*"\n')
    python.chmod(0o755)
    root = SCRIPT.parents[4]
    result = subprocess.run(
        ["bash", str(copy), "--internal-test", "/shared/site", "/shared/results"],
        capture_output=True,
        text=True,
        env={**os.environ, "AXIS_REPO": str(root), "AXIS_PYTHON": str(python)},
    )
    assert result.returncode == 0
    assert "/shared/site" in result.stdout
    assert "test_axis_slurm_jobqueue.py" in result.stdout
