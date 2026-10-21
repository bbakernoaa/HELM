---
type: explanation
category: explanation
tags: [helm, dagr]
---

# DAGR: Why DAGR models work as a dependency graph

[Library overview](../libraries/dagr.md) · [All libraries](../README.md)

A coupling pipeline is easier to reason about when each task declares what must
finish before it may run. An edge from producer to consumer expresses that
prerequisite. The graph makes ordering explicit without hard-coding one
sequential script for every deployment.

For a graph `read → remap → write`, DAGR can establish that `remap` waits for
`read` and `write` waits for `remap`. The graph does not specify the numerical
meaning of those tasks, the buffers they exchange, or which files they open;
those contracts belong to task implementations and the libraries they call.

## Acyclic structure enables progress

A directed cycle has no first task that can satisfy all of its prerequisites.
DAGR rejects cycles and unresolved task names during parsing or construction
rather than allowing an executor to stall later. This validation establishes
structural consistency, not that every task is implemented or every dataset is
available.

Streams describe temporal inputs and policies; task nodes represent work;
dependency edges encode readiness. The task implementation owns domain work.
DAGR routes and schedules it. This division keeps mathematical operations out
of the orchestration layer.

## Runtime graph and rank pool

Because topology is read from YAML, a model can rewire dependencies without
recompiling task code. Rank-pool operations let the framework yield and reclaim
resources as stages need them. These runtime choices must still obey the actual
MPI allocation and application constraints.

Use `advance_step` when a host framework needs control at scheduling
boundaries; use `run` when DAGR should process the graph to completion.
Shutdown must drain work and release ranks in an orderly way. A configured
max-concurrency value is a policy limit, not a guarantee that hardware or MPI
will provide that many useful workers.

This separation helps narrow failures: a parse error points to the pipeline
description, a dependency stall points to readiness or task completion, and a
wrong field value points to an implementation or its data contracts. Successful
graph validation only addresses the first category.
