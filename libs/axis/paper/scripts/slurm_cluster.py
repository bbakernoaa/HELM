# SPDX-License-Identifier: Apache-2.0
"""Render and manage fixed Dask worker jobs in a reviewed Slurm allocation."""

from __future__ import annotations

import getpass
import json
import os
import re
import socket
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

_REQUIRED = {
    "account",
    "queue",
    "cores",
    "processes",
    "memory",
    "walltime",
    "interface",
    "local_directory",
}
_OPTIONAL = {
    "qos",
    "cluster",
    "scheduler_interface",
    "worker_timeout_s",
    "log_directory",
    "job_script_prologue",
    "job_extra_directives",
}
_MANAGED_DIRECTIVES = {
    "--account",
    "--clusters",
    "--cpus-per-task",
    "--error",
    "--exclusive",
    "--job-name",
    "--mem",
    "--mem-per-cpu",
    "--nodes",
    "--ntasks",
    "--ntasks-per-node",
    "--output",
    "--oversubscribe",
    "--partition",
    "--qos",
    "--share",
    "--time",
}


def read_profile(path: str | Path) -> dict:
    """Read a JSON profile. Render it before using it to submit jobs."""
    profile = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(profile, dict):
        raise TypeError("Slurm profile must be a JSON object")
    return profile


def _positive_int(value, label):
    if type(value) is not int or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _single_line(value, label):
    if (
        not isinstance(value, str)
        or not value.strip()
        or any(character in value for character in ("\n", "\r", "\0"))
    ):
        raise ValueError(f"{label} must be nonempty text on one line")
    return value


def render_cluster(profile: dict, jobs: int) -> dict:
    """Validate and render jobqueue arguments without starting Dask or submitting jobs."""
    missing = _REQUIRED - profile.keys()
    unknown = profile.keys() - _REQUIRED - _OPTIONAL
    if missing:
        raise ValueError(f"Missing Slurm profile keys: {', '.join(sorted(missing))}")
    if unknown:
        raise ValueError(f"Unknown Slurm profile keys: {', '.join(sorted(unknown))}")
    _positive_int(jobs, "jobs")
    cores = _positive_int(profile["cores"], "cores")
    processes = _positive_int(profile["processes"], "processes")
    if cores % processes:
        raise ValueError("cores must be a multiple of processes")
    timeout = _positive_int(profile.get("worker_timeout_s", 180), "worker_timeout_s")
    kwargs = {"cores": cores, "processes": processes}
    for key in ("account", "queue", "memory", "walltime", "interface", "local_directory"):
        kwargs[key] = _single_line(profile[key], key)
    for key in ("account", "queue", "walltime", "interface"):
        if kwargs[key].startswith("-") or any(char.isspace() for char in kwargs[key]):
            raise ValueError(f"{key} must be a single Slurm or interface value")
    for key in ("local_directory", "log_directory"):
        if key in profile:
            path = _single_line(profile[key], key)
            if not Path(path).is_absolute() or not re.fullmatch(r"[\w./@+-]+", path):
                raise ValueError(f"{key} must be an absolute path without shell metacharacters")
            kwargs[key] = path
    kwargs["scheduler_options"] = {
        "interface": _single_line(
            profile.get("scheduler_interface", kwargs["interface"]), "scheduler_interface"
        ),
        "dashboard_address": None,
    }

    directives = ["--nodes=1", "--exclusive"]
    for key, flag in (("cluster", "clusters"), ("qos", "qos")):
        if key in profile:
            value = _single_line(profile[key], key)
            if not re.fullmatch(r"[\w.-]+", value):
                raise ValueError(f"{key} must name a single Slurm {key}")
            directives.append(f"--{flag}={value}")
    for key in ("job_script_prologue", "job_extra_directives"):
        lines = profile.get(key, [])
        if not isinstance(lines, list):
            raise TypeError(f"{key} must be a list of strings")
        kwargs[key] = [_single_line(line, key) for line in lines]
    for directive in kwargs["job_extra_directives"]:
        option = re.split(r"[=\s]", directive.lstrip(), maxsplit=1)[0]
        if not option.startswith("--") or option in _MANAGED_DIRECTIVES:
            raise ValueError(f"Directive {option!r} is managed by the Slurm profile")
        directives.append(directive)
    kwargs["job_extra_directives"] = directives
    kwargs["job_script_prologue"].append(
        "export OMP_NUM_THREADS=1 KOKKOS_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1"
    )
    return {
        "jobs": jobs,
        "workers": jobs * processes,
        "worker_timeout_s": timeout,
        "cluster_kwargs": kwargs,
    }


def _load_dependencies():
    from dask_jobqueue import SLURMCluster
    from distributed import Client

    return SLURMCluster, Client


def _queue_jobs(job_name, cluster):
    command = [
        "squeue",
        "--noheader",
        f"--name={job_name}",
        f"--user={getpass.getuser()}",
        "--format=%i",
    ]
    if cluster:
        command.append(f"--clusters={cluster}")
    result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=10)
    ids = set()
    for line in result.stdout.splitlines():
        value = line.strip()
        if value.isdecimal():
            ids.add(value)
        elif value and not value.upper().startswith("CLUSTER:"):
            raise RuntimeError(f"Unexpected squeue output for {job_name}: {value}")
    return ids


def _cancel_jobs(job_ids, cluster):
    command = ["scancel"]
    if cluster:
        command.append(f"--clusters={cluster}")
    subprocess.run(command + sorted(job_ids), check=True, capture_output=True, timeout=10)


def _worker_layout(client):
    # Local function so cloudpickle can send it to workers without requiring a
    # copy of this orchestration module in each worker's Python environment.
    def inspect_worker(dask_worker):
        return {
            "host": socket.gethostname(),
            "pid": os.getpid(),
            "job_id": os.environ.get("SLURM_JOB_ID"),
            "local_directory": dask_worker.local_directory,
        }

    workers = client.scheduler_info(n_workers=-1)["workers"]
    observed = client.run(inspect_worker, workers=list(workers))
    return {
        address: {
            **identity,
            "nthreads": workers[address]["nthreads"],
            "memory_limit": workers[address]["memory_limit"],
        }
        for address, identity in observed.items()
    }


def _validate_layout(workers, rendered, minimum_hosts):
    hosts = sorted({worker["host"] for worker in workers.values()})
    if len(hosts) < minimum_hosts or len(hosts) != rendered["jobs"]:
        raise RuntimeError(
            f"Expected {rendered['jobs']} distinct hosts (minimum {minimum_hosts}); found {hosts}"
        )
    kwargs = rendered["cluster_kwargs"]
    processes = kwargs["processes"]
    expected_threads = kwargs["cores"] // processes
    if len(workers) != rendered["workers"]:
        raise RuntimeError(f"Expected {rendered['workers']} workers; found {len(workers)}")
    by_job = {}
    for worker in workers.values():
        job_id = worker["job_id"]
        if not isinstance(job_id, str) or not job_id.isdecimal():
            raise RuntimeError("Every Dask worker must report a Slurm job ID")
        if worker["nthreads"] != expected_threads:
            raise RuntimeError(f"Unexpected thread count for job {job_id}: {worker['nthreads']}")
        by_job.setdefault(job_id, set()).add((worker["host"], worker["pid"]))
    if len(by_job) != rendered["jobs"] or any(
        len(process_layout) != processes or len({host for host, _ in process_layout}) != 1
        for process_layout in by_job.values()
    ):
        raise RuntimeError("Observed worker processes do not match one worker job per host")
    return hosts, set(by_job)


def _verify_cleanup(job_name, slurm_name, known_ids):
    active = _queue_jobs(job_name, slurm_name)
    known_ids.update(active)
    if not active:
        return
    try:
        _cancel_jobs(active, slurm_name)
    except subprocess.CalledProcessError:
        # A job can finish between the queue query and cancellation.
        if _queue_jobs(job_name, slurm_name):
            raise
        return
    deadline = time.monotonic() + 30
    while active := _queue_jobs(job_name, slurm_name):
        known_ids.update(active)
        if time.monotonic() >= deadline:
            raise RuntimeError(f"Worker jobs remain active: {', '.join(sorted(active))}")
        time.sleep(1)


@contextmanager
def managed_cluster(profile, jobs, *, minimum_hosts, log_dir):
    """Yield (client, metadata) and verify cleanup of all worker jobs for this run."""
    rendered = render_cluster(profile, jobs)
    if _positive_int(minimum_hosts, "minimum_hosts") > jobs:
        raise ValueError("minimum_hosts cannot exceed jobs")
    cluster_factory, client_factory = _load_dependencies()
    log_dir = Path(log_dir).resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    job_name = f"axis-dask-{uuid4().hex[:16]}"
    kwargs = rendered["cluster_kwargs"]
    kwargs.setdefault("log_directory", str(log_dir))
    kwargs["job_name"] = job_name
    slurm_name = profile.get("cluster")
    timeout = rendered["worker_timeout_s"]
    metadata = {
        "job_name": job_name,
        "requested_jobs": jobs,
        "requested_workers": rendered["workers"],
        "slurm_cluster": slurm_name,
        "worker_log_directory": kwargs["log_directory"],
        "job_ids": [],
        "status": "starting",
        "cleanup_verified": False,
    }
    metadata_path = log_dir / "dask-cluster.json"

    def save_metadata():
        scratch = metadata_path.with_suffix(".tmp")
        scratch.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        scratch.replace(metadata_path)

    save_metadata()
    cluster = client = primary_error = None
    known_ids = set()
    submission_started = False
    start = time.monotonic()
    try:
        cluster = cluster_factory(**kwargs)
        (log_dir / "dask-worker.sbatch").write_text(cluster.job_script(), encoding="utf-8")
        client = client_factory(cluster, timeout=timeout)
        submission_started = True
        cluster.scale(jobs=jobs)
        client.wait_for_workers(rendered["workers"], timeout=timeout)
        metadata["workers"] = _worker_layout(client)
        metadata["hosts"], worker_ids = _validate_layout(
            metadata["workers"], rendered, minimum_hosts
        )
        known_ids.update(worker_ids)
        known_ids.update(_queue_jobs(job_name, slurm_name))
        metadata["job_ids"] = sorted(known_ids)
        metadata["provisioning_seconds"] = time.monotonic() - start
        metadata["status"] = "ready"
        save_metadata()
        yield client, metadata
        metadata["status"] = "complete"
    except BaseException as exc:
        primary_error = exc
        metadata["status"] = "failed"
        metadata["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        cleanup_errors = []
        if cluster is not None:
            known_ids.update(
                str(job_id)
                for worker in tuple(cluster.workers.values())
                if (job_id := getattr(worker, "job_id", None)) is not None
            )
        for resource in (client, cluster):
            if resource is not None:
                try:
                    resource.close(timeout=30)
                except Exception as exc:  # noqa: BLE001 - continue cleanup and record failures
                    cleanup_errors.append(exc)
        try:
            if submission_started:
                _verify_cleanup(job_name, slurm_name, known_ids)
            metadata["cleanup_verified"] = True
        except Exception as exc:  # noqa: BLE001 - continue cleanup and record failures
            cleanup_errors.append(exc)
        metadata["job_ids"] = sorted(known_ids)
        if cleanup_errors:
            metadata["status"] = "failed"
            metadata["cleanup_errors"] = [f"{type(exc).__name__}: {exc}" for exc in cleanup_errors]
        save_metadata()
        if cleanup_errors:
            message = "Dask cleanup did not finish cleanly: " + "; ".join(
                metadata["cleanup_errors"]
            )
            if primary_error is None:
                raise RuntimeError(message) from cleanup_errors[0]
            if hasattr(primary_error, "add_note"):
                primary_error.add_note(message)
