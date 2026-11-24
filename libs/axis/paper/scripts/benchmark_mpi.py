"""Plan or launch the paired native benchmark on a Slurm allocation."""

import csv
import math
import os
import shutil
import socket
import subprocess
import time
import uuid
from pathlib import Path

from artifacts import ROOT, digest, load

_NATIVE_ENGINES = {
    "axis": "axis_paper_mpi_axis",
    "esmf": "axis_paper_mpi_esmf",
}


def mpi_command(
    case, *, build_dir, output_dir, nodes, ranks, threads, launcher="srun", mpi_plugin=None
):
    """Construct a command without invoking it or touching the result directory."""
    if any(type(n) is not int or n < 1 for n in (nodes, ranks, threads)):
        raise ValueError("MPI nodes, ranks and threads must be positive integers")
    if ranks < nodes:
        raise ValueError("MPI ranks must be at least the number of nodes")
    engine = case["engine"]
    if engine not in _NATIVE_ENGINES:
        raise ValueError(f"Unknown MPI engine: {engine}")
    if launcher == "srun":
        command = [
            "srun",
            f"--nodes={nodes}",
            f"--ntasks={ranks}",
            f"--cpus-per-task={threads}",
            "--distribution=block:block",
            "--cpu-bind=verbose,cores",
        ]
        if mpi_plugin:
            command.append(f"--mpi={mpi_plugin}")
    elif launcher == "mpiexec" and nodes == 1 and mpi_plugin is None:
        command = ["mpiexec", "-n", str(ranks)]
    else:
        raise ValueError("Use srun for Slurm, or mpiexec without a plugin for single-node checks")

    binary = Path(build_dir).resolve() / "paper" / _NATIVE_ENGINES[engine]
    return command + [
        str(binary),
        "--fixture",
        str(Path(case["fixture"]).resolve()),
        "--output",
        str(Path(output_dir).resolve() / "native"),
        "--method",
        case["method"],
        "--repetitions",
        str(case.get("repetitions", 15)),
        "--warmups",
        str(case.get("warmups", 2)),
        "--reuse",
        ",".join(map(str, case.get("reuse", [1, 10, 100]))),
    ]


def _allocation_issue(nodes, ranks, threads):
    if not os.environ.get("SLURM_JOB_ID"):
        return "srun requires an existing Slurm allocation (SLURM_JOB_ID is absent)"
    variables = {
        "SLURM_JOB_NUM_NODES": nodes,
        "SLURM_NTASKS": ranks,
        "SLURM_CPUS_PER_TASK": threads,
    }
    for name, expected in variables.items():
        actual = os.environ.get(name)
        if actual is None and name == "SLURM_CPUS_PER_TASK" and expected == 1:
            continue
        if actual != str(expected):
            return f"{name}={actual!r}; expected {expected} from run configuration"
    return None


def _capture(command, path):
    """Record command output if the provenance tool is available."""
    with path.open("w") as log:
        try:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=15, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            log.write(f"{error}\n")


def _native_timings(native, launch_id):
    records = []
    path = native / "observations.csv"
    if path.is_file():
        with path.open(newline="") as handle:
            for row in csv.DictReader(handle):
                if row["status"] != "complete":
                    continue
                seconds = float(row["seconds"])
                if not math.isfinite(seconds) or seconds < 0:
                    raise ValueError("Native timing contains an invalid duration")
                records.append(
                    {
                        "phase": row["phase"],
                        "seconds": seconds,
                        "trial": int(row["repetition"]),
                        "launch_id": launch_id,
                        "warmup": False,
                        "fields": int(row["applications"]),
                    }
                )
    return records


def _native_report(native):
    report_path = native / "native_quality.json"
    if not report_path.is_file():
        return {}
    report = load(report_path)
    if not isinstance(report, dict):
        raise TypeError("Native quality report must be an object")
    return report


def _placement_issue(report, nodes, ranks, threads):
    hosts = report.get("hosts")
    if not isinstance(hosts, list) or not all(isinstance(host, str) and host for host in hosts):
        return "Native MPI evidence does not identify the compute hosts"
    if len(set(hosts)) != nodes:
        return f"Native MPI evidence reports {len(set(hosts))} distinct hosts; expected {nodes}"
    if report.get("ranks") != ranks:
        return f"Native MPI evidence reports {report.get('ranks')} ranks; expected {ranks}"
    if report.get("threads_min") != threads or report.get("threads_max") != threads:
        return (
            f"Native MPI evidence reports {report.get('threads_min')}–"
            f"{report.get('threads_max')} threads per rank; expected {threads}"
        )
    return None


def launch_mpi(
    case,
    *,
    build_dir,
    output_dir,
    nodes,
    ranks,
    threads,
    launcher="srun",
    mpi_plugin=None,
    live=False,
):
    """Return a dry-run plan or execute one engine and normalize its evidence."""
    command = mpi_command(
        case,
        build_dir=build_dir,
        output_dir=output_dir,
        nodes=nodes,
        ranks=ranks,
        threads=threads,
        launcher=launcher,
        mpi_plugin=mpi_plugin,
    )
    resources = {"nodes": nodes, "ranks": ranks, "threads": threads, "cores": ranks * threads}
    if ranks % nodes == 0:
        resources["ranks_per_node"] = ranks // nodes
    if case.get("node_type"):
        resources["node_type"] = case["node_type"]
    if not live:
        return {"command": command, "resources": resources, "engine": case["engine"]}

    # Keep planning available without loading the artifact writer.
    from benchmark_evidence import write_run

    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=False)
    logs = output / "logs"
    logs.mkdir()
    native = output / "native"
    binary = Path(build_dir).resolve() / "paper" / _NATIVE_ENGINES[case["engine"]]
    env = dict(
        os.environ,
        OMP_NUM_THREADS=str(threads),
        KOKKOS_NUM_THREADS=str(threads),
        OMP_PLACES="cores",
        OMP_PROC_BIND="close",
    )
    job_id = os.environ.get("SLURM_JOB_ID")
    cluster = os.environ.get("SLURM_CLUSTER_NAME")
    run_id = uuid.uuid4().hex
    launch_id = os.environ.get("AXIS_MPI_LAUNCH_ID") or str(case.get("launch_id", run_id))
    metadata = {
        **case,
        "fixture": str(Path(case["fixture"]).resolve()),
        "schema_version": 1,
        "pathway": "mpi",
        "allocation_id": f"{cluster or 'slurm'}-{job_id}" if job_id else f"local-{run_id}",
        "run_id": run_id,
        "launch_id": launch_id,
        "resources": resources,
        "command": command,
        "slurm_job_id": job_id,
        "cluster": cluster,
        "controller_host": socket.gethostname(),
        "binary_sha256": digest(binary) if binary.is_file() else None,
        "thread_environment": {
            key: env[key]
            for key in ("OMP_NUM_THREADS", "KOKKOS_NUM_THREADS", "OMP_PLACES", "OMP_PROC_BIND")
        },
    }
    for suffix, args in (("revision", ["rev-parse", "HEAD"]), ("status", ["status", "--short"])):
        _capture(["git", "-C", str(ROOT), *args], logs / f"source-{suffix}.txt")
    cache = Path(build_dir) / "CMakeCache.txt"
    metadata["cmake_cache_sha256"] = None
    if cache.is_file():
        shutil.copyfile(cache, logs / "CMakeCache.txt")
        metadata["cmake_cache_sha256"] = digest(cache)

    observations = []
    report = {}
    issue = _allocation_issue(nodes, ranks, threads) if launcher == "srun" else None
    if issue:
        status, reason = "launch_error", issue
    elif not binary.is_file() or not os.access(binary, os.X_OK):
        status = "unsupported" if case["engine"] == "esmf" else "launch_error"
        reason = f"Native executable unavailable: {binary}"
    elif not Path(case["fixture"]).is_dir():
        status, reason = "launch_error", f"Missing MPI fixture directory: {case['fixture']}"
    else:
        if job_id:
            _capture(["scontrol", "show", "job", job_id], logs / "slurm-job.txt")
            nodelist = os.environ.get("SLURM_JOB_NODELIST")
            if nodelist:
                _capture(["scontrol", "show", "node", nodelist], logs / "slurm-nodes.txt")
        launch_started = time.monotonic()
        try:
            with (
                (logs / "stdout.txt").open("w") as stdout,
                (logs / "stderr.txt").open("w") as stderr,
            ):
                result = subprocess.run(
                    command,
                    env=env,
                    stdout=stdout,
                    stderr=stderr,
                    check=False,
                    timeout=case.get("timeout_seconds"),
                )
        except subprocess.TimeoutExpired as error:
            status, reason = "timeout", str(error)
        except KeyboardInterrupt:
            status, reason = "interrupted", "MPI launch interrupted"
        except OSError as error:
            status, reason = "launch_error", str(error)
        else:
            status = {
                0: "complete",
                4: "unsupported",
                6: "numerical_failure",
            }.get(result.returncode, "launch_error")
            if status == "launch_error":
                stderr_text = (logs / "stderr.txt").read_text(errors="replace").lower()
                if any(
                    token in stderr_text for token in ("oom_kill", "out_of_memory", "out of memory")
                ):
                    status = "oom"
            reason = (
                f"Native MPI exit status {result.returncode}; see logs"
                if result.returncode
                else None
            )
        launch_duration = time.monotonic() - launch_started
        if job_id:
            _capture(
                [
                    "sacct",
                    "-j",
                    job_id,
                    "-P",
                    "--noheader",
                    "--format=JobIDRaw,State,ExitCode,ElapsedRaw,AllocCPUS,ReqMem,MaxRSS",
                ],
                logs / "slurm-accounting.txt",
            )
        try:
            observations = _native_timings(native, launch_id)
            report = _native_report(native)
        except (OSError, KeyError, TypeError, ValueError) as error:
            if status == "complete":
                status, reason = "launch_error", f"Cannot read native MPI evidence: {error}"
        if status == "complete":
            issue = _placement_issue(report, nodes, ranks, threads)
            if issue:
                status, reason = "launch_error", issue
            elif report.get("normalization", case["normalization"]) != case["normalization"]:
                status, reason = "launch_error", "Native normalization differs from the manifest"
            elif report.get("passed") is not True:
                status, reason = "numerical_failure", "Native MPI quality report did not pass"
            elif not observations:
                status, reason = "launch_error", "Native timings are missing"
        if report:
            resources.update(
                observed_hosts=report.get("hosts"),
                observed_ranks=report.get("ranks"),
                observed_threads_min=report.get("threads_min"),
                observed_threads_max=report.get("threads_max"),
            )
            metadata["engine_version"] = report.get("engine_version")
        launcher_observation = {
            "phase": "launcher_wall",
            "scope": "native_process_with_launch_and_io",
            "seconds": launch_duration,
            "trial": 0,
            "launch_id": launch_id,
            "warmup": False,
            "fields": 0,
        }
        rss = report.get("peak_rank_rss_bytes")
        if rss is not None:
            launcher_observation.update(peak_memory_bytes=int(rss), memory_scope="peak_rank_rss")
        observations.append(launcher_observation)

    if case.get("cells") is not None:
        for observation in observations:
            observation["cells"] = case["cells"]
    quality = {
        "passed": report.get("passed") if isinstance(report.get("passed"), bool) else None,
        "metrics": report,
        "oracle_id": case.get("oracle_id"),
    }
    write_run(output, metadata, observations, quality, status, reason)
    return {"status": status, "reason": reason, "output": str(output)}
