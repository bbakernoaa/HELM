---
type: reference
category: reference
tags: [helm, dagr, navigation]
---

# DAGR — Directed Acyclic Graph Router

DAGR parses pipeline YAML, validates streams and task dependencies, then
coordinates readiness through an asynchronous event loop. It handles
orchestration and rank-pool concerns; lower-tier libraries perform model I/O
and numerical work.

`dagr::parse_pipeline(path)` returns a validated `Pipeline_Config` containing
stream descriptors, ordered task names and dependency edges. It detects missing
fields, duplicates, dangling references, invalid intervals and cycles.
File/YAML errors propagate as `conf::Conf_Error`; semantic errors throw
`std::invalid_argument`.

A `GraphOrchestrator` takes a config and a moved `halo::Communicator`.
Use `run` for full execution, `advance_step` for caller-managed progression,
and `shutdown` to drain and release state. The orchestrator is move-only.

A valid graph does not prove that datasets exist, algorithms are scientifically
appropriate, or rank budgets fit deployment. A dependency edge means only that
the consumer must wait for its producer. DAGR routes work; it does not calculate.

Think of the YAML as three related declarations: streams describe external
time-varying data, tasks name units of work, and edges state readiness rules.
For example, `read → regrid → write` encodes ordering only; task code still has
to bind those names to implementations and decide which HELM APIs to call.

The build-tree target is `HELM::DAGR`. DAGR discovers optional MPI and sibling
HELM packages. Public pipeline types refer to TICK durations, so downstream
builds need that interface available. Standalone tests also expect prebuilt
sibling artifacts; see the [test CMake file](https://github.com/NOAA-EMC/HELM/blob/develop/libs/dagr/tests/CMakeLists.txt).

Use the [pipeline tutorial](../tutorials/dagr.md), [validation recipe](../how-to/dagr.md),
[API reference](../reference/dagr.md), and [orchestration explanation](../explanation/dagr.md).
