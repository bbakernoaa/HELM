"""Expand the pilot matrix into reviewable points without submitting jobs."""

import argparse
import json
from pathlib import Path

from artifacts import load

ENGINE_PAIRS = {"mpi": ["axis", "esmf"], "python": ["axis", "xesmf"]}
DEFAULT_MATRIX = Path(__file__).resolve().parents[1] / "config" / "benchmark_matrix_candidate.json"


def _positive_counts(values, name):
    if (
        not isinstance(values, list)
        or not values
        or any(type(n) is not int or n < 1 for n in values)
        or len(set(values)) != len(values)
    ):
        raise ValueError(f"{name} must contain distinct positive integers")
    return values


def expand_matrix(matrix, *, stage):
    """Return candidate point IDs and proposed resources. Fixture inputs may be unresolved."""
    if matrix.get("schema_version") != 1 or matrix.get("status") != "pending_pilot":
        raise ValueError("Expected a pending schema-version 1 pilot matrix")
    pilot_nodes = _positive_counts(matrix["pilot_nodes"], "pilot nodes")
    anchor_nodes = _positive_counts(matrix["anchor_nodes"], "anchor nodes")
    if not set(anchor_nodes) <= set(pilot_nodes):
        raise ValueError("Anchor nodes must be a subset of the pilot nodes")
    if stage == "pilot":
        nodes = pilot_nodes
    elif stage == "anchors":
        nodes = anchor_nodes
    else:
        raise ValueError("Use the pilot or anchors stage")
    cores_per_node = matrix["cores_per_node"]
    allocations = matrix["headline_allocations"]
    launches = matrix["fresh_launches"]
    if any(type(n) is not int or n < 1 for n in (cores_per_node, allocations, launches)):
        raise ValueError("Allocation, launch, and core counts must be positive integers")

    points = []
    seen = set()
    for scenario in matrix["scenarios"]:
        scenario_id = scenario["id"]
        if not scenario_id or scenario_id in seen:
            raise ValueError(f"Invalid or duplicate scenario ID: {scenario_id!r}")
        seen.add(scenario_id)
        engines = scenario["engines"]
        pathway = scenario["pathway"]
        if pathway not in ENGINE_PAIRS or engines != ENGINE_PAIRS[pathway]:
            raise ValueError(f"Unexpected engine pair for {scenario_id}: {engines}")
        if scenario["scaling"] not in {"strong", "weak", "stress"}:
            raise ValueError(f"Unexpected scaling strategy for {scenario_id}")
        methods = scenario["methods"]
        if not methods or not set(methods) <= {"bilinear", "conservative"}:
            raise ValueError(f"Unexpected method for {scenario_id}")
        if len(methods) != len(set(methods)):
            raise ValueError(f"Duplicate methods for {scenario_id}")
        if stage == "anchors" and not scenario.get("anchor", True):
            continue
        for n in nodes:
            for method in methods:
                points.append(
                    {
                        "id": f"{scenario_id}/{method}/{n}n",
                        "pathway": pathway,
                        "scaling": scenario["scaling"],
                        "engines": engines,
                        "method": method,
                        "nodes": n,
                        "cores": n * cores_per_node,
                        "fixture": scenario["fixture"],
                        "tolerance": scenario["tolerance"],
                        "fixture_policy": scenario.get("fixture_policy"),
                    }
                )
    return {
        "schema_version": 1,
        "status": matrix["status"],
        "stage": stage,
        "planned_allocations_per_headline_point": allocations,
        "planned_setup_launches_per_allocation": launches,
        "points": points,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--stage", choices=("pilot", "anchors"), default="pilot")
    args = parser.parse_args()
    try:
        result = expand_matrix(load(args.matrix), stage=args.stage)
    except (ValueError, KeyError, OSError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
