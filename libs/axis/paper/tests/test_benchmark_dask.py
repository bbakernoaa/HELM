from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from benchmark_dask import execute_dask
from benchmark_evidence import read_run
from benchmark_fixtures import prepare_tiny_fixture


@pytest.mark.parametrize("method", ["bilinear", "conservative"])
def test_axis_local_spherical_timing(tmp_path, method):
    from distributed import Client

    manifest = prepare_tiny_fixture(tmp_path / "fixture", masked=method == "conservative")
    output = tmp_path / "result"
    case = {"method": method, "engine": "axis", "warmups": 1, "repetitions": 2, "reuse": [2]}
    with Client(
        processes=False, n_workers=2, threads_per_worker=1, dashboard_address=None
    ) as client:
        assert execute_dask(case, manifest, output, client)["status"] == "complete"
    evidence = read_run(output)
    assert evidence["quality"]["passed"]
    assert evidence["run"]["resources"]["workers"] == 2
    assert sum(row["phase"] == "apply" for row in evidence["observations"]) == 3
    assert any(
        row["phase"] == "setup_and_reuse" and row["fields"] == 2 for row in evidence["observations"]
    )


def test_unsupported_method_does_not_emit_comparable_result(tmp_path):
    manifest = prepare_tiny_fixture(tmp_path / "fixture")
    output = tmp_path / "result"
    result = execute_dask({"method": "conservative2nd", "engine": "xesmf"}, manifest, output, None)
    assert result["status"] == "unsupported"
    assert read_run(output)["observations"] == []


def test_bilinear_smooth_identity(tmp_path):
    from distributed import Client

    manifest = prepare_tiny_fixture(tmp_path / "fixture", ranks=2, field_kind="smooth")
    with Client(processes=False, n_workers=2, threads_per_worker=1, dashboard_address=None) as client:
        result = execute_dask(
            {"method": "bilinear", "engine": "axis", "warmups": 1, "repetitions": 1, "reuse": [1]},
            manifest, tmp_path / "result", client,
        )
    assert result["status"] == "complete"
