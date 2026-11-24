"""Read and write the common paper benchmark result format."""

import csv
import json
import math
from pathlib import Path

SCHEMA_VERSION = 1
SEMANTICS = (
    "pathway",
    "fixture_id",
    "method",
    "normalization",
    "edge_model",
    "unmapped",
    "precision",
    "timing_scope",
)
PLACEMENT = (
    "node_type",
    "nodes",
    "cores",
    "ranks",
    "threads",
    "workers",
    "threads_per_worker",
    "processes_per_job",
    "memory_limit_bytes",
)
OBSERVATION_COLUMNS = ("phase", "seconds", "trial", "launch_id", "warmup", "fields")
OUTCOMES = {
    "complete",
    "unsupported",
    "skipped",
    "timeout",
    "oom",
    "launch_error",
    "numerical_failure",
    "interrupted",
}
NUMERIC_COLUMNS = {
    "seconds",
    "trial",
    "fields",
    "warmup",
    "peak_memory_bytes",
    "spill_bytes",
    "tasks",
    "cells",
    "read_bytes",
    "write_bytes",
}


def _write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(path)


def write_run(directory, metadata, observations, quality, status, reason=None):
    """Finalize a run after retaining any raw logs in its result directory."""
    directory = Path(directory)
    if status not in OUTCOMES or (status != "complete" and not reason):
        raise ValueError("A supported non-complete status requires a reason")
    observations = list(observations)
    for row in observations:
        if (
            not row.get("phase")
            or not math.isfinite(float(row["seconds"]))
            or float(row["seconds"]) < 0
        ):
            raise ValueError("Each observation requires a phase and finite nonnegative seconds")
    directory.mkdir(parents=True, exist_ok=True)
    if (directory / "outcome.json").exists():
        raise FileExistsError(f"Run is already finalized in {directory}")
    columns = list(OBSERVATION_COLUMNS)
    columns += sorted(set().union(*(row.keys() for row in observations)) - set(columns))
    _write_json(directory / "run.json", {**metadata, "schema_version": SCHEMA_VERSION})
    temporary = directory / "observations.tmp"
    with temporary.open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        for row in observations:
            writer.writerow(
                {
                    key: int(value) if isinstance(value, bool) else value
                    for key, value in row.items()
                }
            )
    temporary.replace(directory / "observations.csv")
    _write_json(directory / "quality.json", quality or {"passed": None, "metrics": {}})
    _write_json(directory / "outcome.json", {"status": status, "reason": reason})


def read_run(directory):
    """Load finalized evidence. Unavailable counters remain None."""
    directory = Path(directory)
    data = {
        key: json.loads((directory / f"{key}.json").read_text())
        for key in ("run", "quality", "outcome")
    }
    if data["run"].get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Unsupported evidence schema in {directory}")
    with (directory / "observations.csv").open(newline="") as input_file:
        data["observations"] = [
            {
                key: (
                    None
                    if value == ""
                    else float(value)
                    if key == "seconds"
                    else int(value)
                    if key in NUMERIC_COLUMNS
                    else value
                )
                for key, value in row.items()
            }
            for row in csv.DictReader(input_file)
        ]
    return data


def comparable(left, right, phase):
    """Check that two successful runs measured equivalent work and placement."""
    for evidence in (left, right):
        if (
            evidence["outcome"]["status"] != "complete"
            or evidence["quality"].get("passed") is not True
        ):
            return False
        if not any(row["phase"] == phase and not row["warmup"] for row in evidence["observations"]):
            return False
    first, second = left["run"], right["run"]
    if not all(first.get(key) is not None and first[key] == second.get(key) for key in SEMANTICS):
        return False
    for key in ("fixture_representation", "field_dtype", "site"):
        if first.get(key) != second.get(key):
            return False
    if first.get("phase_scopes", {}).get(phase) != second.get("phase_scopes", {}).get(phase):
        return False
    if phase in {"fit", "setup_and_reuse"} and first.get("backend_scope") != second.get(
        "backend_scope"
    ):
        return False
    if not all(first["resources"].get(key) == second["resources"].get(key) for key in PLACEMENT):
        return False
    fields = [
        {
            row["fields"]
            for row in run["observations"]
            if row["phase"] == phase and not row["warmup"]
        }
        for run in (left, right)
    ]
    return fields[0] == fields[1]
