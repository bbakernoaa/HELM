"""The candidate matrix cannot be mistaken for a production run manifest."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from benchmark_matrix import expand_matrix


def _matrix():
    return {
        "schema_version": 1,
        "status": "pending_pilot",
        "pilot_nodes": [1, 2, 4],
        "anchor_nodes": [2],
        "headline_allocations": 3,
        "fresh_launches": 3,
        "cores_per_node": 32,
        "scenarios": [
            {
                "id": "spherical",
                "pathway": "mpi",
                "scaling": "strong",
                "engines": ["axis", "esmf"],
                "methods": ["conservative"],
                "fixture": None,
                "tolerance": None,
            },
            {
                "id": "tiles",
                "pathway": "python",
                "scaling": "weak",
                "engines": ["axis", "xesmf"],
                "methods": ["bilinear"],
                "fixture": None,
                "tolerance": None,
            },
        ],
    }


def test_pilot_expands_matched_pairs_but_keeps_unmeasured_inputs_unresolved():
    plan = expand_matrix(_matrix(), stage="pilot")
    assert plan["status"] == "pending_pilot"
    assert len(plan["points"]) == 6
    assert plan["points"][0]["engines"] == ["axis", "esmf"]
    assert plan["points"][-1]["cores"] == 128
    assert all(p["fixture"] is None and p["tolerance"] is None for p in plan["points"])


def test_anchor_points_use_requested_subset_only():
    plan = expand_matrix(_matrix(), stage="anchors")
    assert [p["nodes"] for p in plan["points"]] == [2, 2]
    assert len({point["id"] for point in plan["points"]}) == 2


def test_rejects_cross_pathway_baselines():
    matrix = _matrix()
    matrix["scenarios"][0]["engines"] = ["axis", "xesmf"]
    with pytest.raises(ValueError, match="engine"):
        expand_matrix(matrix, stage="pilot")
