---
type: explanation
category: explanation
tags: [helm, amio]
---

# AMIO: Why AMIO stages I/O through owned buffers

[Library overview](../libraries/amio.md) · [All libraries](../README.md)

AMIO separates the model's timestep from the storage system's write latency.
When `amio_write` succeeds, AMIO has copied the caller's host data into a
staging buffer and queued backend work. The model can reuse that input buffer
without waiting for disk I/O. A worker later serializes the staged values through
the selected driver.

This contract has two completion points. **Input ownership transfers at enqueue**
after a successful call; **output completion happens later** and must be observed
with `amio_wait`, `amio_flush`, or dataset close. Treating enqueue as file
completion can lose writes during shutdown or hide backend errors.

| Point in the write path | What the caller can rely on |
| --- | --- |
| `amio_write` returns `AMIO_OK` | AMIO has copied the host input into its staging pool |
| Worker finishes the operation | The backend has completed that write and can report its failure |
| `amio_wait`, `amio_flush`, or close completes | The caller has observed completion before relying on the output |

The distinction lets a timestep continue while storage is busy, but it also
means a program must collect asynchronous errors before declaring the run
successful.

## Pool size is a throughput and memory choice

The staging pool allows producers and storage workers to run concurrently.
Too few buffers can block the producer while the backend catches up; too much
capacity reserves unnecessary memory. Choose buffer count and capacity from
field sizes, expected in-flight writes and available memory, then measure the
actual workload.

Reads use staged views with a different ownership rule. A returned pointer
belongs to an AMIO view and remains valid only while that view is retained.
Release it to return memory to the pool. This is why AMIO's staged read view
should not be confused with a SPAN FieldView over caller-owned memory.

The pool is also a backpressure boundary. If producers submit work faster than
drivers can complete it, the pool fills and later submissions must wait or time
out according to configuration. Increasing the pool can absorb a burst, but it
cannot make a persistently slower backend keep up; it only raises memory use.

## Backends define storage semantics

The API hides some format-specific mechanics, but backend capabilities,
parallelism, metadata and available codecs still depend on the compiled driver
and its libraries. A successful configuration must not be assumed to enable
every backend. Check configure output and handle status errors at runtime.

AMIO therefore complements DAGR's orchestration and SPAN's memory-view layer:
it owns staging for storage work, while the model still owns its source fields.
See the [architecture guide](https://github.com/NOAA-EMC/HELM/blob/develop/libs/amio/docs/site/architecture.md)
and [integration guide](https://github.com/NOAA-EMC/HELM/blob/develop/libs/amio/docs/site/user-guide/model-integration.md).
