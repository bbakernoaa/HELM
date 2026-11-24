# SPDX-License-Identifier: Apache-2.0
"""Build deterministic synthetic evidence in the same format as Slurm results."""

from benchmark_evidence import write_run


def create_example(root):
    for pathway, reference in (("mpi", "esmf"), ("python", "xesmf")):
        for nodes in (1, 2):
            for sample, factor in enumerate((0.95, 1.0, 1.1), start=1):
                allocation = f"example-{pathway}-{nodes}-{sample}"
                for engine, fit, apply in (("axis", 8, 2), (reference, 6, 3)):
                    _write(
                        root,
                        pathway,
                        engine,
                        nodes,
                        allocation,
                        setup=fit * factor / nodes**0.8,
                        apply=apply * factor / nodes**0.9,
                    )
    for nodes in (1, 2):
        _write(
            root,
            "python",
            "axis",
            nodes,
            f"example-weak-{nodes}",
            setup=8 * nodes**0.1,
            apply=2 * nodes**0.15,
            fixture=f"synthetic-weak-{nodes}",
            scaling="weak",
            cells=100_000 * nodes,
        )
    _write(
        root,
        "python",
        "axis",
        4,
        "example-failed",
        setup=0,
        apply=0,
        status="oom",
        reason="Synthetic worker memory failure",
    )
    _write(root, "python", "xesmf", 4, "example-unmatched", setup=5, apply=1.2, scope="includes-io")


def _write(
    root,
    pathway,
    engine,
    nodes,
    allocation,
    *,
    setup,
    apply,
    fixture="synthetic-fixed",
    scaling="strong",
    cells=100_000,
    status="complete",
    reason=None,
    scope="in-memory",
):
    run_id = f"{allocation}-{engine}"
    resources = {"nodes": nodes, "cores": nodes * 8, "node_type": "example"}
    if pathway == "mpi":
        resources.update(ranks=nodes * 8, threads=1)
    else:
        resources.update(workers=nodes * 4, threads_per_worker=2)
    metadata = {
        "run_id": run_id,
        "allocation_id": allocation,
        "pathway": pathway,
        "engine": engine,
        "fixture_id": fixture,
        "workload_id": "illustrative-workload",
        "method": "conservative",
        "normalization": "dstarea",
        "edge_model": "great_circle",
        "unmapped": "zero",
        "precision": "float64",
        "timing_scope": scope,
        "scaling": scaling,
        "resources": resources,
        "synthetic": True,
    }
    observations = []
    if status == "complete":
        for phase, seconds in (("setup", setup), ("apply", apply)):
            for trial, factor in enumerate((1.0, 0.98, 1.0, 1.04)):
                observations.append(
                    {
                        "phase": phase,
                        "seconds": seconds * factor,
                        "trial": trial,
                        "launch_id": "synthetic-launch",
                        "warmup": int(trial == 0),
                        "fields": 1,
                        "cells": cells,
                        "peak_memory_bytes": int(800 * 2**20 / nodes),
                        "memory_scope": "per rank" if pathway == "mpi" else "per worker",
                        "spill_bytes": 0 if pathway == "python" else None,
                        "tasks": nodes * 20 if pathway == "python" else None,
                    }
                )
    quality = {
        "passed": status == "complete",
        "metrics": {"rmse": 1e-9, "conservation_error": 1e-10} if observations else {},
    }
    write_run(root / run_id, metadata, observations, quality, status, reason)
