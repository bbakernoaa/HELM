---
type: tutorial
category: tutorials
tags: [helm, dagr]
---

# DAGR: Tutorial: understand a two-task pipeline

[Library overview](../libraries/dagr.md) · [All libraries](../README.md)

**Goal:** parse one stream and a producer-to-consumer dependency. Allow about
40 minutes for the full walkthrough. It uses the maintained parser tests first,
then experiments with a copy outside the repository. The parser validates
configuration; it does not run task implementations or start an MPI workflow.

Complete the [environment setup](../README.md#prepare-a-development-environment).
DAGR needs its sibling interfaces; standalone tests also look for prebuilt
CONF and LOGS artifacts under their `build` directories. Inspect the
[test build definition](https://github.com/NOAA-EMC/HELM/blob/develop/libs/dagr/tests/CMakeLists.txt) for those paths.

Build those siblings first, then DAGR, from the repository root.

## 1. Build and run a minimal pipeline test

```bash
cmake -S libs/conf -B libs/conf/build -DCONF_BUILD_FORTRAN=OFF
cmake --build libs/conf/build --parallel
cmake -S libs/logs -B libs/logs/build
cmake --build libs/logs/build --parallel
cmake -S libs/dagr -B libs/dagr/build -DDAGR_BUILD_TESTING=ON
cmake --build libs/dagr/build --target test_yaml_parser --parallel
./libs/dagr/build/tests/test_yaml_parser --gtest_filter=YamlParser.ValidMinimalConfigParsesSuccessfully
```

The test should pass with one stream, two tasks, and one directed edge. Read its
[complete YAML fixture](https://github.com/NOAA-EMC/HELM/blob/develop/libs/dagr/tests/test_yaml_parser.cpp), reproduced here:

```yaml
streams:
  - name: temperature
    temporal_profile: linear
    out_of_bounds_policy: clamp
    dataset_path: /data/temp.zarr
    snapshot_interval: 86400s
tasks:
  - name: fetch_temp
  - name: regrid_temp
dependencies:
  - from: fetch_temp
    to: regrid_temp
```

Parsing does not read the dataset at the illustrative path. The test verifies
that the stream interval is 86,400 seconds and that the edge goes from task 0
to task 1. This exercise checks configuration, not a complete model-coupling run.

## 2. Run each validation case separately

After the initial build, return to the HELM root. List the available parser
tests:

```bash
./libs/dagr/build/tests/test_yaml_parser --gtest_list_tests
```

Locate these cases under YamlParser:

- ValidMinimalConfigParsesSuccessfully
- CycleDetectionThrows
- MissingTemporalProfileThrows
- DuplicateStreamNamesThrow
- ZeroSnapshotIntervalThrowsWithStreamName

Run the cycle test:

```bash
./libs/dagr/build/tests/test_yaml_parser --gtest_filter=YamlParser.CycleDetectionThrows
```

**Checkpoint:** the test passes because cyclic input was rejected. Passing this
test does not mean a cyclic configuration was accepted.

Run the complete parser suite:

```bash
./libs/dagr/build/tests/test_yaml_parser --gtest_filter='YamlParser.*'
```

**Checkpoint:** all selected parser cases should pass. Inspect the summary to
confirm that tests actually ran, rather than accepting an empty filter.

## 3. Trace a successful configuration

Read the minimal YAML above and fill in this table before opening the fixture's
assertions:

| Question | Expected result |
| --- | --- |
| How many streams? | One |
| How many task names? | Two |
| Which task is the producer? | fetch_temp |
| Which task is the consumer? | regrid_temp |
| What is the stream interval? | 86,400 seconds |
| How is a time outside coverage handled? | clamp |
| Does parsing open /data/temp.zarr? | No |

Now open the
[parser fixture source](https://github.com/NOAA-EMC/HELM/blob/develop/libs/dagr/tests/test_yaml_parser.cpp)
and compare each answer with ValidMinimalConfigParsesSuccessfully.
The assertions show how YAML names become indices in the dependency edge.

## 4. Experiment without editing the repository's tests

Create a separate directory and copy the existing parser fixture:

```bash
mkdir -p /tmp/helm-dagr-tutorial
cp libs/dagr/tests/test_yaml_parser.cpp /tmp/helm-dagr-tutorial/parser_experiments.cpp
cd /tmp/helm-dagr-tutorial
```

Save this CMakeLists.txt, replacing the checkout path:

```cmake
cmake_minimum_required(VERSION 3.21)
project(dagr_parser_tutorial LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 20)
set(CONF_BUILD_FORTRAN OFF CACHE BOOL "" FORCE)
add_subdirectory(/path/to/HELM/libs/conf conf-build)
add_subdirectory(/path/to/HELM/libs/logs logs-build)
find_package(GTest REQUIRED)
add_executable(parser_experiments
    parser_experiments.cpp
    /path/to/HELM/libs/dagr/src/parse_pipeline.cpp
    /path/to/HELM/libs/dagr/src/logging.cpp)
target_include_directories(parser_experiments PRIVATE
    /path/to/HELM/libs/dagr/include
    /path/to/HELM/libs/tick/include)
target_link_libraries(parser_experiments PRIVATE HELM::CONF HELM::LOGS GTest::gtest_main)
```

This target compiles the actual DAGR parser implementation with CONF and its shared LOGS diagnostics. It is a
focused parser learning harness; it does not build or run the orchestrator,
rank pool, or event loop.

Configure and run the unchanged copy first:

```bash
cmake -S . -B build
cmake --build build --parallel
./build/parser_experiments --gtest_filter='YamlParser.*'
```

**Checkpoint:** the copied tests pass before your experiments.

## 5. Change a valid interval and update its expectation

In parser_experiments.cpp, locate only the
ValidMinimalConfigParsesSuccessfully test. Change its YAML snapshot_interval
from 86400s to 3600s and its expected tick::seconds(86400) to
tick::seconds(3600). Leave other fixtures unchanged.

Rebuild and run only that test:

```bash
cmake --build build --parallel
./build/parser_experiments --gtest_filter=YamlParser.ValidMinimalConfigParsesSuccessfully
```

**Checkpoint:** it still passes, now confirming a one-hour interval.

Try changing only the expected value back to 86400. Rebuild and run again.
The test should fail because your asserted interpretation disagrees with the
parsed value. Restore 3600 in both places.

## 6. Build a cycle and predict the failure

In the same successful test, add a reverse dependency to the YAML:

```yaml
  - from: regrid_temp
    to: fetch_temp
```

The new edge closes a cycle: fetch_temp requires regrid_temp, which already
requires fetch_temp. Rebuild and rerun the successful-config test.

**Checkpoint:** it fails with a parsing/validation exception because the test
expects success. Compare this with CycleDetectionThrows, whose expectation is
an exception and therefore passes for cyclic input. Remove the reverse edge
and confirm the successful test passes again.

## 7. Observe required fields and unique identifiers

In the successful fixture, temporarily remove temporal_profile. Run that one
test and observe rejection. Restore it.

Next, duplicate the temperature stream block without changing its name.
Predict rejection for a duplicate identifier. Compare the failure with the
maintained DuplicateStreamNamesThrow fixture, then restore your successful YAML.

Make only one change at a time so you can connect each failure with its cause.

## If you get stuck

| Symptom | Check |
| --- | --- |
| Standalone DAGR link errors | Build sibling artifacts in the expected paths, or use the focused parser harness |
| GTest not found | Use the development container or its package prefix |
| No tests run | List tests and copy the exact filter name |
| Valid YAML is rejected | Inspect required fields, duplicate names, interval, and graph cycles |
| Fixture unexpectedly still passes | Confirm you edited the intended test and rebuilt the executable |

## Practice

Add a third task named write_temp and the edge regrid_temp -> write_temp.
Update the successful test's expected task count to three and edge count to two.
Verify that the stream configuration remains unchanged.

You have learned to configure and validate dependencies. Integrating task
implementations and managing MPI rank lifetimes is a separate step; consult
the [DAGR reference](../reference/dagr.md) and
[explanation](../explanation/dagr.md) before attempting a model-coupling run.
