#!/usr/bin/env python3
"""Prepare fixtures and explicitly run or plan a paper benchmark."""

import argparse
import json
import os
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path

from benchmark_evidence import write_run
from benchmark_fixtures import load_manifest, prepare_paper_fixture, prepare_tiny_fixture
from benchmark_mpi import launch_mpi
from slurm_cluster import managed_cluster, read_profile, render_cluster


def _parse():
    parser = argparse.ArgumentParser(description=__doc__)
    paths = parser.add_subparsers(dest="pathway", required=True)
    fixture = paths.add_parser("fixture", help="Prepare immutable shared fixtures")
    variants = fixture.add_subparsers(dest="variant", required=True)
    tiny = variants.add_parser("tiny", help="Spherical identity for smoke tests")
    tiny.add_argument("--masked", action="store_true")
    tiny.add_argument("--field", choices=("constant", "smooth"), default="constant")
    tiny.add_argument("--nx", type=int, default=8)
    tiny.add_argument("--ny", type=int, default=8)
    tiny.add_argument("--norm", choices=("dstarea", "fracarea"), default="dstarea")
    paper = variants.add_parser("paper", help="Partition an existing spherical paper fixture")
    paper.add_argument("--case", type=Path, required=True)
    paper.add_argument("--reference", type=Path, required=True)
    paper.add_argument("--abs-tolerance", type=float, required=True)
    for variant in (tiny, paper):
        variant.add_argument("--output", type=Path, required=True)
        variant.add_argument("--ranks", type=int, required=True)
    mpi = paths.add_parser("mpi", help="Run or plan one MPI engine")
    mpi.add_argument("--build-dir", type=Path, required=True)
    mpi.add_argument("--nodes", type=int, required=True)
    mpi.add_argument("--ranks", type=int, required=True)
    mpi.add_argument("--threads", type=int, default=1)
    mpi.add_argument("--launcher", choices=("srun", "mpiexec"), default="srun")
    mpi.add_argument("--mpi-plugin", default=os.environ.get("AXIS_SLURM_MPI"))
    dask = paths.add_parser("dask", help="Run or plan a Dask workflow")
    dask_layout = dask.add_mutually_exclusive_group(required=True)
    dask_layout.add_argument("--jobs", type=int, help="One exclusive Slurm worker job per host")
    dask_layout.add_argument("--local-workers", type=int, help="One process per local worker")
    dask.add_argument("--launches", type=int, default=1, help="Fresh fits in the same allocation")
    for launch in (mpi, dask):
        launch.add_argument("--site", type=Path, help="Reviewed Slurm site profile")
        launch.add_argument("--case", type=Path, required=True, help="JSON benchmark case")
        launch.add_argument("--output", type=Path, required=True)
        launch.add_argument(
            "--live", action="store_true", help="Execute instead of printing the plan"
        )
    return parser.parse_args()


def _launch_config(args):
    case_file = args.case.resolve()
    case = json.loads(case_file.read_text())
    allowed = {"axis", "esmf"} if args.pathway == "mpi" else {"axis", "xesmf"}
    if case.get("engine") not in allowed:
        raise ValueError(f"Choose engine from {', '.join(sorted(allowed))}")
    fixture_path = (case_file.parent / case["fixture"]).resolve()
    if fixture_path.is_dir():
        fixture_path /= "manifest.json"
    manifest = load_manifest(fixture_path, verify=args.live)
    case.update(
        fixture=str(fixture_path.parent),
        fixture_id=manifest["fixture_id"],
        manifest_sha256=manifest["manifest_sha256"],
        normalization=manifest["normalization"],
        unmapped=manifest["unmapped"],
        edge_model=manifest["edge_model"],
        precision="float64",
        workload_id=case.get("workload_id", manifest["case_id"]),
        scaling=case.get("scaling", "smoke"),
        oracle_id=manifest["oracle"],
        cells=sum(shard["destination_cells"] for shard in manifest["shards"]),
    )
    return case, fixture_path, manifest


def _check_live_profile(profile):
    for key in ("account", "interface", "scheduler_interface", "local_directory"):
        value = profile.get(key, "")
        if "REPLACE" in value or value == "YOUR_PROJECT":
            raise ValueError(f"Set real site value for {key} before using --live")


def _mpi(args, case, manifest):
    if args.ranks != manifest["ranks"]:
        raise ValueError("MPI ranks must equal the number of manifest shards")
    site = None
    case.setdefault("site", "local")
    if args.launcher == "srun":
        if args.site is None:
            raise ValueError("srun needs --site")
        profile = read_profile(args.site)
        case["site"] = profile.get("cluster", profile["queue"])
        render_cluster(profile, args.nodes)
        if args.live and profile["account"] == "YOUR_PROJECT":
            raise ValueError("Set a valid allocation account in the site profile")
        resources = [
            "sbatch",
            f"--account={profile['account']}",
            f"--partition={profile['queue']}",
            f"--time={profile['walltime']}",
            f"--nodes={args.nodes}",
            f"--ntasks={args.ranks}",
            f"--cpus-per-task={args.threads}",
        ]
        for key, flag in (("cluster", "clusters"), ("qos", "qos")):
            if key in profile:
                resources.append(f"--{flag}={profile[key]}")
        site = resources
    case["timing_scope"] = "native_max_rank"
    result = launch_mpi(
        case,
        build_dir=args.build_dir,
        output_dir=args.output,
        nodes=args.nodes,
        ranks=args.ranks,
        threads=args.threads,
        launcher=args.launcher,
        mpi_plugin=args.mpi_plugin,
        live=args.live,
    )
    if not args.live and site:
        result["allocation_command"] = site
    return result


@contextmanager
def _dask_client(args, profile):
    if args.local_workers is not None:
        from distributed import Client

        with Client(
            n_workers=args.local_workers,
            threads_per_worker=1,
            processes=True,
            dashboard_address=None,
        ) as client:
            yield client, None
    else:
        with managed_cluster(
            profile, args.jobs, minimum_hosts=args.jobs, log_dir=args.output / "logs"
        ) as (client, cluster):
            client.upload_file(str(Path(__file__).with_name("benchmark_fixtures.py")), load=False)
            yield client, cluster


def _dask(args, case, path, manifest):
    if args.launches < 1:
        raise ValueError("--launches must be positive")
    profile = None
    case.setdefault("site", "local")
    if args.jobs is not None:
        if args.site is None:
            raise ValueError("--jobs requires --site")
        profile = read_profile(args.site)
        case["site"] = profile.get("cluster", profile["queue"])
        plan = render_cluster(profile, args.jobs)
        if args.live:
            _check_live_profile(profile)
    else:
        if args.site or args.local_workers < 1:
            raise ValueError("Local runs require positive --local-workers and no site profile")
        plan = {"local_workers": args.local_workers}
    if not args.live:
        return {"case": case, "launches": args.launches, **plan}

    from benchmark_dask import execute_dask

    args.output.mkdir(parents=True, exist_ok=False)
    allocation_id = case.get("allocation_id", uuid.uuid4().hex)
    cluster_failure = None
    records = []
    try:
        with _dask_client(args, profile) as (client, cluster):
            for index in range(1, args.launches + 1):
                output = args.output if args.launches == 1 else args.output / f"launch-{index:03}"
                launch_case = {**case, "allocation_id": allocation_id, "launch_id": str(index)}
                result = execute_dask(
                    launch_case,
                    path,
                    output,
                    client,
                    cluster_metadata=cluster,
                    finalize=False,
                    verified_manifest=manifest,
                )
                records.append((output, result))
    except (Exception, KeyboardInterrupt) as error:
        status = (
            "interrupted"
            if isinstance(error, KeyboardInterrupt)
            else "timeout"
            if isinstance(error, TimeoutError)
            else "launch_error"
        )
        reason = f"{type(error).__name__}: {error}"
        cluster_failure = (status, reason)
        if not records:
            metadata = {
                **case,
                "run_id": uuid.uuid4().hex,
                "allocation_id": allocation_id,
                "pathway": "python",
                "resources": {"nodes": args.jobs or 1},
            }
            records.append((args.output, (metadata, [], None, status, reason)))
    failures = [cluster_failure] if cluster_failure else []
    for output, (metadata, observations, quality, status, reason) in records:
        if cluster_failure and status == "complete":
            status, reason = cluster_failure
        write_run(output, metadata, observations, quality, status, reason)
        if status != "complete" and (status, reason) not in failures:
            failures.append((status, reason))
    status, reason = failures[0] if failures else ("complete", None)
    return {"status": status, "reason": reason, "output": str(args.output.resolve())}


def main():
    args = _parse()
    try:
        if args.pathway == "fixture":
            if args.variant == "tiny":
                print(
                    prepare_tiny_fixture(
                        args.output,
                        args.ranks,
                        args.masked,
                        nx=args.nx,
                        ny=args.ny,
                        norm=args.norm,
                        field_kind=args.field,
                    )
                )
            else:
                print(
                    prepare_paper_fixture(
                        args.output,
                        args.case,
                        args.reference,
                        args.ranks,
                        abs_tolerance=args.abs_tolerance,
                    )
                )
            return 0
        case, path, manifest = _launch_config(args)
        result = (
            _mpi(args, case, manifest)
            if args.pathway == "mpi"
            else _dask(args, case, path, manifest)
        )
        print(json.dumps(result, indent=2, default=str))
        return 0 if result.get("status", "complete") == "complete" else 1
    except (ValueError, KeyError, OSError) as error:
        print(f"AXIS paper benchmark: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
