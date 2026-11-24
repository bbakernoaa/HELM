# SPDX-License-Identifier: Apache-2.0

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import slurm_cluster as slurm


@pytest.fixture
def profile():
    return {
        "account": "allocation",
        "queue": "batch",
        "qos": "normal",
        "cores": 4,
        "processes": 2,
        "memory": "8 GiB",
        "walltime": "00:10:00",
        "interface": "eth0",
        "scheduler_interface": "ib0",
        "local_directory": "/scratch/workers",
        "cluster": "c6",
        "job_script_prologue": ["module load python"],
        "job_extra_directives": ["--constraint=test"],
        "worker_timeout_s": 30,
    }


def test_render_without_a_scheduler(profile, monkeypatch):
    def no_submit():
        pytest.fail("Render must not load a cluster or submit jobs")

    monkeypatch.setattr(slurm, "_load_dependencies", no_submit)
    rendered = slurm.render_cluster(profile, 2)
    settings = rendered["cluster_kwargs"]
    assert rendered["workers"] == 4
    assert settings["cores"] == 4
    assert settings["scheduler_options"]["interface"] == "ib0"
    assert settings["job_extra_directives"] == [
        "--nodes=1",
        "--exclusive",
        "--clusters=c6",
        "--qos=normal",
        "--constraint=test",
    ]
    assert settings["job_script_prologue"][0] == "module load python"
    assert settings["job_script_prologue"][-1].startswith("export OMP_NUM_THREADS=1")


def test_render_rejects_conflicting_job_layout(profile):
    profile["job_extra_directives"] = ["--nodes=4"]
    with pytest.raises(ValueError, match="managed by"):
        slurm.render_cluster(profile, 2)


def test_render_rejects_uneven_process_layout(profile):
    profile["cores"] = 5
    with pytest.raises(ValueError, match="multiple"):
        slurm.render_cluster(profile, 2)


@pytest.fixture
def cluster_fakes(monkeypatch):
    events = []
    fake = {"hosts": ["node-a", "node-b"], "timed_out": False, "stubborn_job": False}

    class Cluster:
        def __init__(self, **kwargs):
            self.workers = {}
            fake["cluster_kwargs"] = kwargs

        def job_script(self):
            return "#!/bin/sh\n#SBATCH --exclusive\n"

        def scale(self, *, jobs):
            events.append(("scale", jobs))

        def close(self, *, timeout):
            assert timeout == 30
            events.append("closed-cluster")

    class Client:
        def __init__(self, cluster, *, timeout):
            pass

        def wait_for_workers(self, n_workers, *, timeout):
            events.append(("wait", n_workers, timeout))
            if fake["timed_out"]:
                raise TimeoutError("worker startup timeout")

        def scheduler_info(self, *, n_workers):
            return {
                "workers": {
                    f"worker-{idx}": {"nthreads": 2, "memory_limit": 100} for idx in range(4)
                }
            }

        def run(self, inspection, *, workers):
            return {
                worker: {
                    "host": fake["hosts"][idx // 2],
                    "pid": idx + 100,
                    "job_id": str(idx // 2 + 900),
                    "local_directory": f"/scratch/worker-{idx}",
                }
                for idx, worker in enumerate(workers)
            }

        def close(self, *, timeout):
            assert timeout == 30
            events.append("closed-client")

    def queue_jobs(job_name, cluster):
        assert job_name.startswith("axis-dask-")
        assert cluster == "c6"
        if "closed-cluster" not in events or fake["stubborn_job"]:
            return {"900", "901"}
        return set()

    def cancel_jobs(job_ids, cluster):
        events.append(("cancel", job_ids, cluster))
        fake["stubborn_job"] = False

    monkeypatch.setattr(slurm, "_load_dependencies", lambda: (Cluster, Client))
    monkeypatch.setattr(slurm, "_queue_jobs", queue_jobs)
    monkeypatch.setattr(slurm, "_cancel_jobs", cancel_jobs)
    return events, fake


def test_managed_cluster_records_actual_hosts_and_closes(profile, cluster_fakes, tmp_path):
    events, fake = cluster_fakes
    with slurm.managed_cluster(profile, 2, minimum_hosts=2, log_dir=tmp_path) as (_, metadata):
        assert metadata["hosts"] == ["node-a", "node-b"]
        assert metadata["job_ids"] == ["900", "901"]
        assert {worker["nthreads"] for worker in metadata["workers"].values()} == {2}
        assert metadata["provisioning_seconds"] >= 0
        assert "closed-cluster" not in events
    assert events == [("scale", 2), ("wait", 4, 30), "closed-client", "closed-cluster"]
    assert fake["cluster_kwargs"]["log_directory"] == str(tmp_path)
    assert (tmp_path / "dask-worker.sbatch").is_file()
    saved = json.loads((tmp_path / "dask-cluster.json").read_text())
    assert saved["cleanup_verified"] is True


def test_managed_cluster_closes_on_timeout(profile, cluster_fakes, tmp_path):
    events, fake = cluster_fakes
    fake["timed_out"] = True
    fake["stubborn_job"] = True
    with (
        pytest.raises(TimeoutError, match="worker startup timeout"),
        slurm.managed_cluster(profile, 2, minimum_hosts=2, log_dir=tmp_path),
    ):
        pytest.fail("Timed-out cluster was yielded")
    assert events == [
        ("scale", 2),
        ("wait", 4, 30),
        "closed-client",
        "closed-cluster",
        ("cancel", {"900", "901"}, "c6"),
    ]
    saved = json.loads((tmp_path / "dask-cluster.json").read_text())
    assert saved["job_ids"] == ["900", "901"]
    assert saved["cleanup_verified"] is True


def test_managed_cluster_refuses_workers_on_the_same_host(profile, cluster_fakes, tmp_path):
    events, fake = cluster_fakes
    fake["hosts"] = ["node-a", "node-a"]
    with (
        pytest.raises(RuntimeError, match="distinct hosts"),
        slurm.managed_cluster(profile, 2, minimum_hosts=2, log_dir=tmp_path),
    ):
        pytest.fail("Colocated workers were accepted")
    assert events[-2:] == ["closed-client", "closed-cluster"]
