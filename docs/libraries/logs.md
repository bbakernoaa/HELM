---
type: reference
category: reference
tags: [helm, logs, navigation]
---

# LOGS — Lightweight Operational Global Status

LOGS provides thread-safe severity filtering, rank-aware records, scoped context,
and output sinks for MPI programs. It avoids making every model implement its
own rank prefixing and status plumbing.

Construct a `logs::Logger`, configure its communicator, set a threshold and
add one or more `logs::Sink` objects. Messages submitted with `log` are
filtered below the threshold. A `Scoped_Context` labels messages during its
lifetime, including nested phases.

Records are buffered for consolidation. Treat collective consolidation points
as MPI collectives: every participating rank must reach them consistently.
Configure loggers and destroy them while MPI remains active. FATAL is reserved
for unrecoverable failure and triggers the synchronized abort path; it is never
a safe verbosity experiment.

Treat `log` calls as local record submission and `consolidate` as a collective
communication point. A pattern that conditionally consolidates only on rank
zero can deadlock even though that is where the output is ultimately wanted.
Use a sink to control the destination and a threshold to control volume; do not
parse the formatted output as a stable data interchange format.

LOGS depends on C++20 and MPI, not Kokkos. Its target is `HELM::LOGS`;
`LOGS_BUILD_TESTING` enables GTest and RapidCheck tests. Output goes to
registered sinks, with stderr as the fallback when no sink is registered.

Read the [rank-aware tutorial](../tutorials/logs.md), [context how-to](../how-to/logs.md),
[API reference](../reference/logs.md), and [distributed logging explanation](../explanation/logs.md).
