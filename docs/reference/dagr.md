---
type: reference
category: reference
tags: [helm, dagr]
---

# DAGR: public API and pipeline configuration

[Library overview](../libraries/dagr.md) · [Tutorial](../tutorials/dagr.md) ·
[How-to](../how-to/dagr.md) · [All libraries](../README.md)

The public declarations are in
[`pipeline_config.hpp`](https://github.com/NOAA-EMC/HELM/blob/develop/libs/dagr/include/dagr/pipeline_config.hpp),
[`dagr.hpp`](https://github.com/NOAA-EMC/HELM/blob/develop/libs/dagr/include/dagr/dagr.hpp),
and [`logging.hpp`](https://github.com/NOAA-EMC/HELM/blob/develop/libs/dagr/include/dagr/logging.hpp).
DAGR parses pipeline descriptions into a directed acyclic graph and exposes a
move-only orchestrator for running and draining that graph.

## Pipeline YAML

The parser accepts `streams`, `tasks`, and `dependencies`. A stream names an
input, its temporal behavior, dataset path, and snapshot interval. A dependency
uses task names; DAGR resolves them to zero-based indices in declaration
order. The parser validates required fields, duplicate names, positive stream
intervals, references, and cycles. It does not open the dataset path.

```yaml
streams:
  - name: temperature
    temporal_profile: linear       # linear or step
    out_of_bounds_policy: clamp    # clamp or cycle
    dataset_path: /data/temp.zarr
    snapshot_interval: 86400s
tasks:
  - name: fetch_temp
  - name: regrid_temp
dependencies:
  - from: fetch_temp
    to: regrid_temp
```

| Configuration type | Fields and constraints |
| --- | --- |
| `Stream_Descriptor` | `name` (up to 128 characters), `temporal_profile`, `oob_policy`, `dataset_path`, positive `snapshot_interval` |
| `Temporal_Profile` | `linear` interpolation or `step` selection |
| `OutOfBounds_Policy` | `clamp` to the coverage boundary or `cycle` within the last year of coverage |
| `Dependency_Edge` | `producer_id` to `consumer_id`; IDs index `Pipeline_Config::task_names` |
| `Pipeline_Config` | Ordered streams, task names, edges, and scheduler limits |

`max_concurrency` defaults to 64 and accepts 1–1024. `deadlock_timeout_s`
defaults to 30 seconds and accepts 1–3600. `shutdown_timeout_s` defaults to
30 seconds and bounds rank reclamation during shutdown. These are scheduler
settings, separate from a stream's snapshot interval.

## Parsing and validation errors

```cpp
#include <dagr/pipeline_config.hpp>

dagr::Pipeline_Config config = dagr::parse_pipeline("pipeline.yaml");
```

`parse_pipeline(path)` can propagate `conf::Conf_Error` for file and YAML
parsing failures, and throws `std::invalid_argument` for invalid pipeline
contents (for example, cycles, duplicates, missing fields, or out-of-range
settings). Keep parsing at the application boundary so a startup diagnostic can
include the pipeline path and the validation message.

## GraphOrchestrator lifecycle

Construct the orchestrator with a validated config and a moved HALO world
communicator. The object is move-only because it owns runtime and MPI-related
state.

| API | Contract |
| --- | --- |
| `GraphOrchestrator(config, halo::Communicator&&)` | Takes the config and communicator; rejects invalid graph references or settings |
| `run()` | Runs the event loop to completion; reports task failure after draining non-cancelled work |
| `advance_step()` | Runs one resolve/dispatch/complete scheduling cycle; `true` means all nodes completed |
| `shutdown()` | Drains in-flight work and releases state; safe to call more than once |
| `yield_ranks(set)` | Make model ranks available to the framework rank pool |
| `reclaim_ranks(set)` | Request returned ranks; reclamation may be deferred while ranks are allocated |
| `total_ranks()`, `available_ranks()`, `in_flight_count()` | Read scheduler state |
| `is_shutdown()` | Report whether shutdown has completed |

`run()` throws `std::runtime_error` when a task fails, after non-cancelled nodes
drain. Applications that need incremental progress can call `advance_step()`
and monitor `in_flight_count()`. Call `shutdown()` before tearing down objects
that active tasks use; the destructor also releases owned state.

## Integration boundaries

DAGR uses HALO communicator types and TICK durations, and its logging adapter
configures the shared LOGS logger. The parser only describes the DAG and stream
metadata; a dataset path is not proof that a backend is installed or that the
dataset exists. The orchestrator coordinates task execution and rank
availability; it does not replace the task libraries' field, I/O, or numerical
contracts.

The target is `HELM::DAGR`; `DAGR_BUILD_TESTING` enables GTest and RapidCheck.
See the [build definition](https://github.com/NOAA-EMC/HELM/blob/develop/libs/dagr/CMakeLists.txt)
and [parser tutorial](../tutorials/dagr.md).
