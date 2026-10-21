---
type: howto
category: how_to
tags: [helm, dagr]
---

# DAGR: Validate a DAGR pipeline before constructing the orchestrator

[Library overview](../libraries/dagr.md) · [All libraries](../README.md)

Call `dagr::parse_pipeline` during startup, before transferring control to the
graph executor. This catches structural errors while they can still be reported
as configuration problems.

## Define a valid graph

A YAML configuration contains streams, tasks and dependencies. A dependency
uses task names and points from producer to consumer:

~~~yaml
streams:
  - name: temperature
    temporal_profile: linear
    out_of_bounds_policy: clamp
    dataset_path: /data/temperature.zarr
    snapshot_interval: 3600s
tasks:
  - name: read
  - name: remap
  - name: write
dependencies:
  - from: read
    to: remap
  - from: remap
    to: write
~~~

The stream interval is a positive number of seconds with an `s` suffix.
Temporal profiles are `linear` or `step`; policies are `clamp` or `cycle`.
Dataset existence is checked by the runtime I/O layer, not by this parser.

## Parse and report errors

~~~cpp
try {
    const auto pipeline = dagr::parse_pipeline("pipeline.yaml");
    // Validate application-specific limits before constructing the executor.
} catch (const conf::Conf_Error& error) {
    // YAML syntax or file-loading failure.
} catch (const std::invalid_argument& error) {
    // Missing fields, invalid values, duplicates, dangling tasks or cycles.
}
~~~

A graph must be acyclic. Every dependency endpoint must name a declared task,
and every task and stream name must be unique. The parser returns task indices
in declaration order; edges refer to those indices.

## Test a cycle

Add a reverse edge from write to read. The resulting cycle must be rejected.
The repository's unit test demonstrates this case:

~~~bash
./libs/dagr/build/tests/test_yaml_parser --gtest_filter=YamlParser.CycleDetectionThrows
~~~

This command requires the DAGR parser test target and its sibling dependencies
to have been built. See the [test build rules](https://github.com/NOAA-EMC/HELM/blob/develop/libs/dagr/tests/CMakeLists.txt).

Only construct `GraphOrchestrator` after parsing and application validation.
The orchestrator takes a `Pipeline_Config` and moved HALO communicator; see
[dagr.hpp](https://github.com/NOAA-EMC/HELM/blob/develop/libs/dagr/include/dagr/dagr.hpp).
