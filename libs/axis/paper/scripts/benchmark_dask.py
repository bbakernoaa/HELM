"""Measure synchronized AXIS and xESMF Dask phases using shared fixtures."""

import importlib.metadata
import math
import os
import resource
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import numpy as np

from benchmark_evidence import write_run
from benchmark_fixtures import load_dask_fixture, load_manifest


class UnsupportedCase(ValueError):
    """The selected engine cannot provide the requested comparison semantics."""


def _worker_peak_rss():
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(usage * (1 if sys.platform == "darwin" else 1024))


def _telemetry(client):
    workers = client.scheduler_info(n_workers=-1)["workers"]
    peak = client.run(_worker_peak_rss)
    spills = [
        worker.get("metrics", {}).get("spilled_bytes", {}).get("disk")
        for worker in workers.values()
    ]
    return {
        "peak_memory_bytes": max(peak.values(), default=None),
        "spill_bytes": sum(spills)
        if spills and all(value is not None for value in spills)
        else None,
    }


def _persist(client, data):
    from distributed import futures_of, wait

    result = client.persist(data)
    completed, _ = wait(futures_of(result))
    for future in completed:
        if future.status != "finished":
            future.result()
    return result


def _layout(client):
    workers = client.scheduler_info(n_workers=-1)["workers"]
    hostnames = client.run(socket.gethostname)
    threads = [worker["nthreads"] for worker in workers.values()]
    memory = [worker.get("memory_limit", 0) for worker in workers.values()]
    nodes = len(set(hostnames.values()))
    return {
        "nodes": nodes,
        "hosts": sorted(set(hostnames.values())),
        "cores": sum(threads),
        "workers": len(workers),
        "threads_per_worker": threads[0] if len(set(threads)) == 1 else None,
        "memory_limit_bytes": sum(memory),
        "worker_memory_bytes": memory[0] if len(set(memory)) == 1 else None,
        "workers_per_node": len(workers) // nodes if nodes and len(workers) % nodes == 0 else None,
        "worker_layout": [
            {
                "worker": address,
                "hostname": hostnames[address],
                "threads": worker["nthreads"],
                "memory_limit_bytes": worker.get("memory_limit"),
            }
            for address, worker in sorted(workers.items())
        ],
    }


def _axis_fit(client, fixture, method, memory_budget):
    from axis import DistributedRegridder

    options = {} if memory_budget is None else {"memory_budget": memory_budget}
    fitted = DistributedRegridder(
        client, method=method, norm=fixture.manifest["normalization"], **options
    ).fit(fixture.source_tiles, fixture.destination_tiles)
    return lambda field: fitted.apply(field, dim="cell")


def _xesmf_fit(fixture, method, backend, fit_cores):
    import dask
    import xarray as xr

    try:
        import xesmf as xe
    except ImportError as error:
        raise UnsupportedCase(f"xESMF or ESMPy is unavailable: {error}") from error

    structured = fixture.manifest["structured"]

    def grid(group, mask):
        geometry = structured[group]
        xb = np.asarray(geometry["longitude_bounds"])
        yb = np.asarray(geometry["latitude_bounds"])
        nx, ny = len(xb) - 1, len(yb) - 1
        sizes = [shard[f"{group}_cells"] for shard in fixture.manifest["shards"]]
        rows = [size // nx for size in sizes]
        if not all(rows) or sum(rows) != ny or any(size % nx for size in sizes):
            raise UnsupportedCase("xESMF requires whole latitude rows per shared fixture chunk")
        dataset = xr.Dataset(
            {
                "lon": ("lon", geometry["longitude_centers"], {"units": "degrees_east"}),
                "lat": ("lat", geometry["latitude_centers"], {"units": "degrees_north"}),
                "lon_b": ("lon_b", xb),
                "lat_b": ("lat_b", yb),
                "mask": (("lat", "lon"), mask.reshape(ny, nx)),
            }
        )
        return dataset.chunk({"lat": tuple(rows), "lon": nx}), (ny, nx), max(rows)

    source, input_shape, _ = grid("source", fixture.source_mask)
    source = source.set_coords("mask")
    target, output_shape, output_rows = grid("destination", fixture.destination_mask)
    xesmf_method = (
        "conservative_normed"
        if method == "conservative" and fixture.manifest["normalization"] == "fracarea"
        else method
    )
    # xESMF's parallel fitter currently uses a local multiprocessing scheduler.
    # Bound its own processes explicitly and report that scope in result metadata.
    with dask.config.set(num_workers=fit_cores):
        fitted = xe.Regridder(
            source,
            target,
            xesmf_method,
            parallel=backend == "local_parallel",
            unmapped_to_nan=False,
        )

    def apply(field):
        shape = (*field.shape[:-1], *input_shape)
        reshaped = xr.DataArray(field.data.reshape(shape), dims=(*field.dims[:-1], "lat", "lon"))
        result = fitted(reshaped, output_chunks=(output_rows, output_shape[1]))
        result = result.where(target["mask"] != 0, 0.0)
        shape = (*field.shape[:-1], math.prod(output_shape))
        return xr.DataArray(result.data.reshape(shape), dims=field.dims)

    return apply


def _quality(fixture, computed, method):
    import dask

    values = computed.data
    expected = fixture.expected
    area = fixture.destination_area
    covered = fixture.destination_fraction
    eligible = (
        (fixture.destination_mask != 0) & (covered > 0)
        if covered is not None
        else fixture.destination_mask != 0
    )
    error = values - expected
    active_area = np.where(eligible, area, 0)
    rmse = (
        ((error**2 * active_area).sum() / active_area.sum()) ** 0.5 if active_area.any() else None
    )
    checks = {
        "max_abs_error": abs(error).max(),
        "area_weighted_rmse": rmse,
        "minimum": values.min(),
        "maximum": values.max(),
        "unmapped_area": float(area[~eligible].sum()),
    }
    if method == "conservative" and covered is not None and fixture.source_fraction is not None:
        target_measure = area * covered if fixture.manifest["normalization"] == "fracarea" else area
        src_measure = fixture.source_area * fixture.source_fraction
        checks["mass_residual"] = (values * target_measure).sum() - (
            fixture.field.data * src_measure
        ).sum()
    (resolved,) = dask.compute(checks)
    metrics = {
        key: float(value) if value is not None and math.isfinite(float(value)) else None
        for key, value in resolved.items()
    }
    tolerance = fixture.manifest["abs_tolerance"]
    passed = metrics["max_abs_error"] is not None and metrics["max_abs_error"] <= tolerance
    if "mass_residual" in metrics:
        mass_tolerance = tolerance * float(area.sum())
        metrics["mass_tolerance"] = mass_tolerance
        passed = (
            passed
            and metrics["mass_residual"] is not None
            and abs(metrics["mass_residual"]) <= mass_tolerance
        )
    return {
        "passed": passed,
        "metrics": metrics,
        "tolerance": tolerance,
        "oracle": fixture.manifest["oracle"],
    }


def execute_dask(
    case,
    manifest_path,
    output,
    client,
    *,
    cluster_metadata=None,
    finalize=True,
    verified_manifest=None,
):
    """Run one Python engine in an already provisioned cluster."""
    output = Path(output).resolve()
    if (output / "outcome.json").exists():
        raise FileExistsError(f"Run is already finalized in {output}")
    manifest = verified_manifest or load_manifest(manifest_path)
    engine, method = case["engine"], case["method"]
    run_id = uuid.uuid4().hex
    resources = _layout(client) if client is not None else {}
    setup_backend = case.get("fit_backend", "distributed" if engine == "axis" else "serial")
    allowed = {"distributed"} if engine == "axis" else {"serial", "local_parallel"}
    if setup_backend not in allowed:
        raise ValueError(f"Choose fit_backend from {', '.join(sorted(allowed))} for {engine}")
    fit_cores = case.get("fit_cores", 1)
    available_cores = (
        len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 1)
    )
    if type(fit_cores) is not int or not 1 <= fit_cores <= available_cores:
        raise ValueError("fit_cores must be a positive integer within controller CPU affinity")
    metadata = {
        **{key: value for key, value in case.items() if key != "fixture"},
        "pathway": "python",
        "run_id": run_id,
        "allocation_id": case.get("allocation_id", run_id),
        "fixture_id": manifest["fixture_id"],
        "manifest_sha256": manifest["manifest_sha256"],
        "cells": sum(shard["destination_cells"] for shard in manifest["shards"]),
        "workload_id": case.get("workload_id", manifest["case_id"]),
        "fixture_representation": "shared_netcdf",
        "edge_model": manifest["edge_model"],
        "normalization": manifest["normalization"],
        "unmapped": manifest["unmapped"],
        "precision": "float64",
        "scaling": case.get("scaling", "smoke"),
        "timing_scope": "persisted_input_and_output",
        "setup_scope": "tile_geometry_and_weights"
        if engine == "axis"
        else "structured_grid_and_weights",
        "backend_scope": setup_backend,
        "controller_fit_cores": fit_cores if engine == "xesmf" else None,
        "phase_scopes": {
            "fit": "tile_geometry_io" if engine == "axis" else "structured_metadata",
            "setup_and_reuse": "tile_geometry_io" if engine == "axis" else "structured_metadata",
        },
        "resources": resources,
        "cluster_metadata": cluster_metadata,
        "memory_scope": "maximum_worker_process_lifetime_peak_rss",
        "spill_scope": "sum_worker_disk_spill_at_phase_end",
    }
    observations = []
    quality = None
    status = "complete"
    reason = None
    try:
        if engine not in {"axis", "xesmf"}:
            raise UnsupportedCase(f"Unknown Python engine {engine}")
        if engine == "xesmf" and (
            method not in {"bilinear", "conservative"} or not manifest.get("structured")
        ):
            raise UnsupportedCase(
                "xESMF requires a validated structured fixture and bilinear or conservative semantics"
            )
        if client is None or not resources.get("workers"):
            raise ValueError("Python benchmark needs a live Dask client")
        if cluster_metadata and (
            resources["nodes"] != cluster_metadata["requested_jobs"]
            or resources["workers"] != cluster_metadata["requested_workers"]
        ):
            raise RuntimeError("Worker layout no longer matches the requested allocation")
        if engine == "xesmf" and resources["threads_per_worker"] != 1:
            raise UnsupportedCase("Use one thread per worker for ESMPy weight generation")
        repetitions, warmups = case.get("repetitions", 15), case.get("warmups", 2)
        reuse = case.get("reuse", [1, 10, 100])
        if repetitions < 1 or warmups < 0 or any(count < 1 for count in reuse):
            raise ValueError(
                "Repetitions and reuse counts must be positive, and warmups nonnegative"
            )
        from distributed import get_task_stream
        import xarray as xr

        versions = {}
        for package in (
            "axis-regrid",
            "numpy",
            "xarray",
            "netCDF4",
            "dask",
            "distributed",
            "dask-jobqueue",
            "xesmf",
            "esmpy",
        ):
            try:
                versions[package] = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                versions[package] = None
        metadata["versions"] = versions
        for name, arguments in (
            ("source_revision", ["rev-parse", "HEAD"]),
            ("source_changes", ["status", "--porcelain"]),
        ):
            try:
                completed = subprocess.run(
                    ["git", "-C", str(Path(__file__).parent), *arguments],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=10,
                )
                metadata[name] = completed.stdout.strip()
            except (OSError, subprocess.SubprocessError):
                metadata[name] = None
        metadata["container_image"] = os.environ.get("AXIS_BENCHMARK_IMAGE")

        def observe(phase, operation, *, trial=0, warmup=False, fields=1):
            with get_task_stream(client) as stream:
                started = time.perf_counter()
                result = operation()
                elapsed = time.perf_counter() - started
            observations.append(
                {
                    "phase": phase,
                    "seconds": elapsed,
                    "trial": trial,
                    "warmup": warmup,
                    "fields": fields,
                    "launch_id": case.get("launch_id", run_id),
                    "tasks": len(stream.data),
                    **_telemetry(client),
                }
            )
            return result

        if (
            cluster_metadata
            and cluster_metadata.get("provisioning_seconds") is not None
            and case.get("launch_id", "1") == "1"
        ):
            observations.append(
                {
                    "phase": "provision",
                    "seconds": cluster_metadata["provisioning_seconds"],
                    "trial": 0,
                    "warmup": False,
                    "fields": 1,
                    "launch_id": case.get("launch_id", run_id),
                }
            )
        with client.as_current():
            fixture = observe(
                "fixture_open",
                lambda: load_dask_fixture(
                    manifest_path, verified_manifest=manifest, include_mesh_tiles=engine == "axis"
                ),
            )
            field = observe("read", lambda: _persist(client, fixture.field))

            def fit():
                if engine == "axis":
                    return _axis_fit(client, fixture, method, case.get("memory_budget"))
                return _xesmf_fit(fixture, method, setup_backend, fit_cores)

            fitted = observe("fit", fit)
            for trial in range(warmups + repetitions):
                # Vary the xarray graph so a previous persisted result cannot satisfy this trial.
                trial_field = field * float(trial + 1)
                result = observe(
                    "apply",
                    lambda: _persist(client, fitted(trial_field)),
                    trial=trial,
                    warmup=trial < warmups,
                )
                if trial == 0:
                    quality = _quality(fixture, result, method)
                    if not quality["passed"]:
                        status, reason = (
                            "numerical_failure",
                            "Output failed the fixture reference checks",
                        )
                        break
                del result
            if status == "complete":
                for count in reuse:
                    batch = xr.concat(
                        [field * float(index + 1) for index in range(count)], dim="field"
                    )
                    batch = _persist(client, batch)
                    observe(
                        "repeated_workload", lambda: _persist(client, fitted(batch)), fields=count
                    )
                    observe("setup_and_reuse", lambda: _persist(client, fit()(batch)), fields=count)
        if status == "complete" and _layout(client) != resources:
            status, reason = "launch_error", "Worker layout changed during measurement"
    except UnsupportedCase as error:
        status, reason = "unsupported", str(error)
    except MemoryError as error:
        status, reason = "oom", str(error) or "Out of memory"
    except TimeoutError as error:
        status, reason = "timeout", str(error) or "Dask operation timed out"
    except KeyboardInterrupt:
        status, reason = "interrupted", "Interrupted by the user"
    except Exception as error:
        status, reason = "launch_error", f"{type(error).__name__}: {error}"
        import traceback

        (output / "logs").mkdir(parents=True, exist_ok=True)
        (output / "logs" / "error.txt").write_text(traceback.format_exc())
    if finalize:
        write_run(output, metadata, observations, quality, status, reason)
        return {"status": status, "reason": reason, "output": str(output)}
    return metadata, observations, quality, status, reason
