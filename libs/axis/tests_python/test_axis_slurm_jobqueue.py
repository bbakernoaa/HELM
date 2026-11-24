# SPDX-License-Identifier: Apache-2.0
"""Live two-host Dask test, enabled only by AXIS_RUN_SLURM=1."""

import json
import os
from dataclasses import replace
from pathlib import Path
from tempfile import mkdtemp

import pytest


@pytest.mark.skipif(
    os.environ.get("AXIS_RUN_SLURM") != "1",
    reason="requires explicit AXIS_RUN_SLURM=1 to submit worker jobs",
)
def test_tiled_regridding_on_two_slurm_hosts(monkeypatch):
    import numpy as np
    from axis import DistributedRegridder

    scripts = Path(__file__).resolve().parents[1] / "paper" / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    from benchmark_fixtures import load_dask_fixture, prepare_tiny_fixture, serial_axis_reference
    from slurm_cluster import managed_cluster, read_profile

    profile_path = os.environ.get("AXIS_SLURM_PROFILE")
    shared_path = os.environ.get("AXIS_SLURM_SHARED_DIR")
    if not profile_path or not shared_path:
        pytest.fail("Set AXIS_SLURM_PROFILE and AXIS_SLURM_SHARED_DIR for the live Slurm test")
    profile = read_profile(profile_path)
    run_path = Path(mkdtemp(prefix="axis-slurm-smoke-", dir=Path(shared_path).resolve(strict=True)))
    log_dir = run_path / "logs"
    print(f"AXIS Slurm smoke evidence: {run_path}")

    fixtures = {
        method: load_dask_fixture(prepare_tiny_fixture(run_path / method, ranks=2, masked=method == "conservative"))
        for method in ("bilinear", "conservative")
    }
    references = {}
    for method, fixture in fixtures.items():
        # A nonconstant field exposes ordering bugs that a constant cannot.
        factors = np.linspace(1.0, 2.0, fixture.field.sizes["cell"])
        changed = replace(fixture, field=fixture.field * factors)
        references[method] = (
            serial_axis_reference(fixture, method),
            serial_axis_reference(changed, method),
            factors,
        )

    with managed_cluster(profile, 2, minimum_hosts=2, log_dir=log_dir) as (client, metadata):
        assert len(metadata["hosts"]) == 2
        assert len(metadata["job_ids"]) == 2
        client.upload_file(str(scripts / "benchmark_fixtures.py"), load=False)

        for method, fixture in fixtures.items():
            operator = DistributedRegridder(client, method=method, norm="dstarea").fit(
                fixture.source_tiles, fixture.destination_tiles
            )
            source_field = client.persist(fixture.field)
            result = operator.apply(source_field, dim="cell").compute()
            assert result.dims == ("cell",)
            reference, reuse_reference, factors = references[method]
            np.testing.assert_allclose(result.values, fixture.expected, rtol=1e-8, atol=1e-10)
            np.testing.assert_allclose(result.values, reference, rtol=1e-8, atol=1e-10)

            reused = operator.apply(source_field * factors, dim="cell").compute()
            np.testing.assert_allclose(reused.values, reuse_reference, rtol=1e-8, atol=1e-10)

    saved = json.loads((log_dir / "dask-cluster.json").read_text())
    assert saved["cleanup_verified"] is True
    assert saved["job_ids"] == metadata["job_ids"]
