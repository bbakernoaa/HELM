---
type: explanation
category: explanation
tags: [helm, logs]
---

# LOGS: Why rank context, sinks and collectives matter

[Library overview](../libraries/logs.md) · [All libraries](../README.md)

In an MPI job, a message without its source rank is difficult to act on.
LOGS stamps records with the configured communicator's rank and sends formatted
records to sinks. A sink is an output destination, not a durable event store:
if operational tooling needs structured machine-readable logs, use an appropriate
serialization layer at the application boundary.

## Filtering and scoped context

Severity thresholds reduce routine volume before sink dispatch. Scoped context
adds phase labels where records are submitted, making logs easier to associate
with timesteps, initialization or cleanup. RAII ensures a label does not leak
past its scope.

## Consolidation is collective

Consolidation gathers buffered records across the communicator and emits
representatives, which can reduce repetitive output. It also means all relevant
ranks must call it consistently. Calling a collective on only a subset can hang
the job. Message ordering across ranks is inherently nondeterministic.

| Operation | Scope | Operational consequence |
| --- | --- | --- |
| `log(level, message)` | Local record submission | Apply the threshold and associate rank/context |
| `consolidate()` | Communicator collective | All participating ranks must reach the call |
| `fatal(message)` | Job-wide failure path | Flush/report and request MPI termination |

FATAL is intentionally different from ordinary logging: it flushes output and
requests synchronized MPI termination. Use it only when continuing would leave
the application in an invalid state. LOGS catches internal failures at its
noexcept API boundary, but that cannot make an invalid MPI lifecycle safe.
