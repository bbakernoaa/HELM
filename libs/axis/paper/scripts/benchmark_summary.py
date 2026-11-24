# SPDX-License-Identifier: Apache-2.0
"""Summarize immutable paper runs, using allocations as independent samples."""

import csv
import hashlib
import json
import math
import random
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from benchmark_evidence import PLACEMENT, SCHEMA_VERSION, SEMANTICS

_CASE_FIELDS = (
    *SEMANTICS,
    "workload_id",
    "scaling",
    "direction",
    "extrapolation",
    "missing_policy",
    "tolerance_profile_id",
    "chunking",
    "fixture_representation",
    "field_dtype",
)
_LAYOUT_FIELDS = (
    *PLACEMENT,
    "site",
    "cluster",
    "processes",
    "ranks_per_node",
    "threads_per_rank",
    "workers_per_node",
    "cpus_per_task",
    "jobs",
    "memory_bytes",
    "worker_memory_bytes",
    "cpu_binding",
)
_REFERENCE = {"mpi": "esmf", "python": "xesmf"}


def _finite(value):
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _quantile(values, p):
    ordered = sorted(values)
    index = p * (len(ordered) - 1)
    lower = math.floor(index)
    return ordered[lower] + (ordered[math.ceil(index)] - ordered[lower]) * (index - lower)


def _metadata(path, *, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if default is None:
            raise
        return default


def _freeze(value):
    """Use canonical JSON for hashable configuration values, including lists."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class Run:
    directory: Path
    metadata: dict
    observations: tuple
    quality: dict
    outcome: dict

    @property
    def resources(self):
        return self.metadata.get("resources", {})

    @property
    def eligible(self):
        return (
            self.outcome.get("status") == "complete"
            and self.quality.get("passed") is True
            and self.quality.get("comparison_eligible") is not False
            and all(self.metadata.get(key) is not None for key in SEMANTICS)
            and (_finite(self.resources.get("cores")) or 0) > 0
            and (_finite(self.resources.get("nodes")) or 0) > 0
        )


def load_runs(root):
    """Read result directories recursively without modifying them."""
    root = Path(root)
    if not root.is_dir():
        raise FileNotFoundError(root)
    runs = []
    for metadata_path in sorted(root.rglob("run.json")):
        directory = metadata_path.parent
        metadata = _metadata(metadata_path)
        if "pathway" not in metadata and "mode" in metadata and "backend" in metadata:
            # The existing single-rank paper runner uses a different run.json format.
            continue
        if metadata.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"{metadata_path}: expected result schema version {SCHEMA_VERSION}")
        quality = _metadata(directory / "quality.json", default={})
        outcome = _metadata(
            directory / "outcome.json",
            default={"status": "interrupted", "reason": "No final outcome was recorded"},
        )
        observations_path = directory / "observations.csv"
        if observations_path.is_file():
            with observations_path.open(newline="", encoding="utf-8") as handle:
                observations = tuple(csv.DictReader(handle))
        else:
            observations = ()
        runs.append(Run(directory, metadata, observations, quality, outcome))
    return runs


def _case(run):
    return {
        **{field: run.metadata.get(field) for field in _CASE_FIELDS},
        **{field: run.resources.get(field, run.metadata.get(field)) for field in _LAYOUT_FIELDS},
    }


def _samples(runs):
    """Extract usable non-warmup observations with their scientific comparison key."""
    for run in runs:
        if not run.eligible:
            continue
        case = _case(run)
        for row in run.observations:
            seconds = _finite(row.get("seconds"))
            if (
                seconds is None
                or seconds <= 0
                or not row.get("phase")
                or str(row.get("warmup")) != "0"
            ):
                continue
            key = {
                **case,
                "phase": row["phase"],
                "backend_scope": (
                    run.metadata.get("backend_scope")
                    if row["phase"] in {"fit", "setup_and_reuse"}
                    else None
                ),
                "scope": (
                    row.get("scope")
                    or run.metadata.get("phase_scopes", {}).get(row["phase"])
                    or case["timing_scope"]
                ),
                "fields": _finite(row.get("fields")),
                "cells": _finite(row.get("cells", run.metadata.get("cells"))),
            }
            yield run, row, seconds, key


@dataclass(frozen=True)
class AllocationTiming:
    engine: str
    allocation: str
    pair: str
    key: dict
    seconds: float


def _allocation_timings(runs):
    launches = defaultdict(list)
    keys = {}
    for run, row, seconds, key in _samples(runs):
        engine = run.metadata["engine"]
        allocation = run.metadata.get("allocation_id")
        if not allocation:
            continue
        pair = run.metadata.get("comparison_pair_id") or allocation
        group = (engine, allocation, pair, _freeze(key))
        keys[group] = key
        launches[(*group, run.metadata["run_id"], row.get("launch_id"))].append(seconds)

    allocations = defaultdict(list)
    for launch, trials in launches.items():
        allocations[launch[:-2]].append(statistics.median(trials))
    return [
        AllocationTiming(*group[:3], keys[group], statistics.median(values))
        for group, values in allocations.items()
    ]


def _resource_counters(runs):
    counters = defaultdict(lambda: defaultdict(list))
    for run, row, _, key in _samples(runs):
        group = counters[(run.metadata["engine"], _freeze(key))]
        for field in ("peak_memory_bytes", "spill_bytes", "tasks"):
            value = _finite(row.get(field))
            if value is not None and value >= 0:
                scope = (
                    (row.get("memory_scope") or run.metadata.get("memory_scope"))
                    if field == "peak_memory_bytes"
                    else None
                )
                group[(field, scope)].append(value)
    return counters


def phase_summaries(runs):
    """Pool repetitions within launches, then pool launches within allocations."""
    points = defaultdict(lambda: defaultdict(list))
    keys = {}
    for trial in _allocation_timings(runs):
        group = (trial.engine, _freeze(trial.key))
        points[group][trial.allocation].append(trial.seconds)
        keys[group] = trial.key
    counters = _resource_counters(runs)
    result = []
    for group, allocations in sorted(points.items()):
        case = keys[group]
        samples = [statistics.median(values) for values in allocations.values()]
        median = statistics.median(samples)
        resource_counters = counters[group]
        memory = [
            (scope, values)
            for (field, scope), values in resource_counters.items()
            if field == "peak_memory_bytes"
        ]
        memory_scope, memory_values = memory[0] if len(memory) == 1 else (None, [])
        result.append(
            {
                **case,
                "engine": group[0],
                "allocations": len(samples),
                "median_seconds": median,
                "q1_seconds": _quantile(samples, 0.25),
                "q3_seconds": _quantile(samples, 0.75),
                "iqr_seconds": _quantile(samples, 0.75) - _quantile(samples, 0.25),
                "median_core_hours": median * float(case["cores"]) / 3600,
                "peak_memory_bytes": max(memory_values, default=None),
                "memory_scope": memory_scope,
                "mixed_memory_scopes": len(memory) > 1,
                "max_spill_bytes": max(
                    resource_counters.get(("spill_bytes", None), []), default=None
                ),
                "max_task_count": max(resource_counters.get(("tasks", None), []), default=None),
            }
        )
    return result


def _paired_timings(runs):
    points = defaultdict(lambda: defaultdict(list))
    for trial in _allocation_timings(runs):
        points[(_freeze(trial.key), trial.pair)][trial.engine].append(trial)
    for by_engine in points.values():
        axis = by_engine.get("axis", [])
        if len(axis) != 1:
            continue
        baseline = _REFERENCE.get(axis[0].key["pathway"])
        reference = by_engine.get(baseline, [])
        if len(reference) == 1:
            yield axis[0], reference[0]


def _bootstrap_interval(samples):
    # Very small samples are shown as individual pairs and IQR only.
    if len(samples) < 5:
        return None, None
    rng = random.Random(0)
    medians = [statistics.median(rng.choices(samples, k=len(samples))) for _ in range(2_000)]
    return _quantile(medians, 0.025), _quantile(medians, 0.975)


def paired_speedups(runs):
    """Report the ratio of matched reference/AXIS times per independent pair."""
    points = defaultdict(list)
    for axis, reference in _paired_timings(runs):
        points[_freeze(axis.key)].append((axis, reference))
    result = []
    for pairs in points.values():
        ratios = [ref.seconds / axis.seconds for axis, ref in pairs]
        low, high = _bootstrap_interval(ratios)
        result.append(
            {
                **pairs[0][0].key,
                "reference_engine": pairs[0][1].engine,
                "paired_allocations": len(ratios),
                "median_speedup": statistics.median(ratios),
                "iqr_speedup": _quantile(ratios, 0.75) - _quantile(ratios, 0.25),
                "bootstrap_low": low,
                "bootstrap_high": high,
            }
        )
    return result


def scaling_series(runs):
    """Use the smallest successful point in each tested strong/weak series."""
    points = defaultdict(list)
    for row in phase_summaries(runs):
        if row["scaling"] not in {"strong", "weak"}:
            continue
        # Resource counts vary along a curve; architecture and local layout do not.
        ignored = {"nodes", "cores", "workers", "ranks", "jobs", "memory_limit_bytes"}
        if row["scaling"] == "weak":
            ignored |= {"fixture_id", "cells"}
        key = {
            k: row[k]
            for k in (
                *_CASE_FIELDS,
                *_LAYOUT_FIELDS,
                "fields",
                "cells",
                "engine",
                "scope",
                "phase",
                "backend_scope",
            )
            if k not in ignored
        }
        points[_freeze(key)].append(row)
    result = []
    for series_key, rows in points.items():
        series_id = hashlib.sha256(series_key.encode()).hexdigest()[:10]
        rows.sort(key=lambda row: float(row["cores"]))
        baseline = rows[0]
        base_cores = float(baseline["cores"])
        for row in rows:
            core_growth = float(row["cores"]) / base_cores
            speedup = baseline["median_seconds"] / row["median_seconds"]
            workload_growth = 1.0 if row["scaling"] == "strong" else None
            if row["scaling"] == "weak" and baseline["cells"] and row["cells"]:
                workload_growth = row["cells"] / baseline["cells"]
            result.append(
                {
                    **row,
                    "series_id": series_id,
                    "relative_to_cores": base_cores,
                    "relative_to_nodes": baseline["nodes"],
                    "workload_growth": workload_growth,
                    "speedup": speedup,
                    "efficiency": (
                        speedup * workload_growth / core_growth if workload_growth else None
                    ),
                }
            )
    return result


def reuse_break_even(runs):
    """Estimate setup plus N warmed applications for matched phase pairs."""
    setups = {}
    finalizations = {}
    applies = {}
    for axis, reference in _paired_timings(runs):
        key = {k: v for k, v in axis.key.items() if k not in {"phase", "fields", "scope"}}
        index = (axis.pair, _freeze(key))
        if axis.key["phase"] in {"setup", "fit"}:
            setups[index] = (axis, reference)
        if axis.key["phase"] == "operator_finalize":
            finalizations[index] = (axis, reference)
        if axis.key["phase"] == "apply":
            applies[(*index, axis.key["fields"])] = (axis, reference)

    result = []
    for (pair, key, _), (axis_apply, reference_apply) in applies.items():
        setup = setups.get((pair, key))
        if not setup:
            continue
        axis_setup, reference_setup = setup
        one_time_axis, one_time_ref = axis_setup.seconds, reference_setup.seconds
        finalize = finalizations.get((pair, key))
        if finalize:
            one_time_axis += finalize[0].seconds
            one_time_ref += finalize[1].seconds
        setup_difference = one_time_axis - one_time_ref
        apply_savings = reference_apply.seconds - axis_apply.seconds
        count = None
        if apply_savings > 0:
            count = max(1, math.ceil(setup_difference / apply_savings))
        elif setup_difference <= 0 and apply_savings == 0:
            count = 1
        result.append(
            {
                **axis_apply.key,
                "comparison_pair_id": pair,
                "reference_engine": reference_apply.engine,
                "included_operator_finalize": finalize is not None,
                "axis_setup_seconds": one_time_axis,
                "reference_setup_seconds": one_time_ref,
                "axis_apply_seconds": axis_apply.seconds,
                "reference_apply_seconds": reference_apply.seconds,
                "applications_to_break_even": count,
            }
        )
    return result


def audit_rows(runs):
    """Expose ineligible, unsupported, incomplete and unpaired observations."""
    paired = {
        (entry.engine, entry.allocation, entry.pair, _freeze(entry.key))
        for pair in _paired_timings(runs)
        for entry in pair
    }
    paired_phases = defaultdict(set)
    unmatched_phases = defaultdict(set)
    for run, _, _, key in _samples(runs):
        allocation = run.metadata.get("allocation_id")
        pair = run.metadata.get("comparison_pair_id") or allocation
        entry = (run.metadata["engine"], allocation, pair, _freeze(key))
        target = paired_phases if entry in paired else unmatched_phases
        target[run.directory].add(key["phase"])
    result = []
    for run in runs:
        status = run.outcome.get("status", "interrupted")
        if status != "complete":
            comparison = status
        elif run.quality.get("passed") is not True:
            comparison = "quality-failed" if run.quality else "quality-missing"
        elif not run.eligible:
            comparison = "ineligible"
        elif not paired_phases[run.directory]:
            comparison = "no-paired-results"
        elif unmatched_phases[run.directory]:
            comparison = "partially-paired"
        else:
            comparison = "has-paired-results"
        result.append(
            {
                "run_id": run.metadata.get("run_id"),
                "allocation_id": run.metadata.get("allocation_id"),
                "engine": run.metadata.get("engine"),
                **_case(run),
                "status": status,
                "reason": run.outcome.get("reason"),
                "comparison": comparison,
                "paired_phases": ", ".join(sorted(paired_phases[run.directory])),
                "unmatched_phases": ", ".join(sorted(unmatched_phases[run.directory])),
                **{f"metric_{key}": value for key, value in run.quality.get("metrics", {}).items()},
            }
        )
    return result
