from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from benchmark_evidence import comparable, read_run, write_run
from benchmark_fixtures import load_dask_fixture, load_manifest, prepare_tiny_fixture


def test_fixture_ids_masks_and_checksum(tmp_path):
    manifest = prepare_tiny_fixture(tmp_path / "fixture", ranks=2, masked=True)
    data = load_manifest(manifest)
    repartitioned = load_manifest(
        prepare_tiny_fixture(tmp_path / "repartitioned", ranks=1, masked=True)
    )
    assert data["fixture_id"] == repartitioned["fixture_id"]
    assert data["manifest_sha256"] != repartitioned["manifest_sha256"]
    fixture = load_dask_fixture(manifest)
    assert len(fixture.source_tiles) == len(fixture.destination_tiles) == 2
    np.testing.assert_array_equal(fixture.destination_ids, np.arange(len(fixture.expected)))
    assert np.any(fixture.expected == 0)
    assert np.any(fixture.expected == 1)
    first, second = (tile.load() for tile in fixture.source_tiles)
    assert set(first[4]) & set(second[4])
    with (manifest.parent / data["shards"][0]["file"]).open("ab") as output:
        output.write(b"corrupt")
    with pytest.raises(ValueError, match="checksum"):
        load_manifest(manifest)


def metadata(engine):
    return {
        "run_id": engine,
        "allocation_id": "pair-1",
        "pathway": "python",
        "engine": engine,
        "fixture_id": "same",
        "method": "bilinear",
        "normalization": "none",
        "edge_model": "great_circle",
        "unmapped": "zero",
        "precision": "float64",
        "timing_scope": "in_memory",
        "workload_id": "small",
        "scaling": "smoke",
        "resources": {"nodes": 1, "cores": 2, "workers": 2},
    }


def test_evidence_round_trip_and_comparison(tmp_path):
    observations = [
        {
            "phase": "apply",
            "seconds": 0.1,
            "trial": 0,
            "launch_id": "a",
            "warmup": False,
            "fields": 1,
            "peak_memory_bytes": 0,
        }
    ]
    quality = {"passed": True, "metrics": {"max_abs_error": 0.0}}
    write_run(tmp_path / "axis", metadata("axis"), observations, quality, "complete")
    write_run(tmp_path / "xesmf", metadata("xesmf"), observations, quality, "complete")
    axis, esmf = (read_run(tmp_path / name) for name in ("axis", "xesmf"))
    assert axis["observations"][0]["peak_memory_bytes"] == 0
    assert comparable(axis, esmf, "apply")
    esmf["run"]["timing_scope"] = "includes_write"
    assert not comparable(axis, esmf, "apply")
    esmf["run"]["timing_scope"] = "in_memory"
    esmf["run"]["unmapped"] = "nan"
    assert not comparable(axis, esmf, "apply")
    write_run(tmp_path / "failed", metadata("bad"), observations, None, "timeout", "job timed out")
    failed = read_run(tmp_path / "failed")
    assert failed["outcome"] == {"status": "timeout", "reason": "job timed out"}
    assert len(failed["observations"]) == 1
    assert not comparable(axis, failed, "apply")
