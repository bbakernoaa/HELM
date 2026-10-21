---
type: tutorial
category: tutorials
tags: [helm, logs]
---

# LOGS: Tutorial: emit an MPI-aware status message

[Library overview](../libraries/logs.md) · [All libraries](../README.md)

## Before you start

Allow about 30 minutes. Create `/tmp/helm-logs-tutorial` and save the two
initial files there. All following build and launch commands run from that
directory. Use a user account permitted by your MPI launcher. Distributed output
may arrive in a different order from run to run.


## 1. Build and run a first example

**Goal:** emit an INFO message while filtering a DEBUG message.
Complete the [environment setup](../README.md#prepare-a-development-environment).
You need C++20, CMake, and MPI.

Save this complete program as `main.cpp` in a temporary directory:

```cpp
#include <mpi.h>
#include <iostream>
#include <logs/logs.hpp>

int main(int argc, char** argv) {
    MPI_Init(&argc, &argv);
    {
        logs::Logger logger;
        logger.add_sink(logs::Sink(std::cout));
        logger.configure_communicator(MPI_COMM_WORLD);
        logger.set_threshold(logs::Severity_Level::INFO);
        logger.log(logs::Severity_Level::INFO, "Initialization complete");
        logger.log(logs::Severity_Level::DEBUG, "Debug detail");
        logger.consolidate();
    }
    MPI_Finalize();
}
```

Save this `CMakeLists.txt` alongside it, replacing the checkout path:

```cmake
cmake_minimum_required(VERSION 3.21)
project(logs_tutorial LANGUAGES CXX)
add_subdirectory(/path/to/HELM/libs/logs logs-build)
add_executable(logs_tutorial main.cpp)
target_link_libraries(logs_tutorial PRIVATE HELM::LOGS)
```

Run `cmake -S . -B build`, `cmake --build build --parallel`, and
`mpiexec -n 2 ./build/logs_tutorial`. Expect the initialization message with
rank context; `Debug detail` should be absent. Exact formatting and consolidated
record count depend on logger behavior.

## 2. Observe a single rank before adding more

Run the initial program with one rank:

```bash
mpiexec -n 1 ./build/logs_tutorial
```

Find the initialization message. There should be no DEBUG message because the
configured threshold is INFO.

Now run with two ranks:

```bash
mpiexec -n 2 ./build/logs_tutorial
```

Both processes execute the same application. The explicit stdout sink makes
the destination visible; each log call emits a record, and consolidate may emit
additional representative records. Rank context lets you attribute
records to their origin; consolidation can combine repeated messages. Check
message content and rank coverage rather than expecting a fixed line order.

## 3. Add a scoped model phase and enable debug output

Replace the complete main.cpp with:

```cpp
#include <mpi.h>
#include <iostream>
#include <logs/logs.hpp>
#include <string>

int main(int argc, char** argv) {
    MPI_Init(&argc, &argv);
    int rank = 0;
    MPI_Comm_rank(MPI_COMM_WORLD, &rank);
    {
        logs::Logger logger;
        logger.add_sink(logs::Sink(std::cout));
        logger.configure_communicator(MPI_COMM_WORLD);
        logger.set_threshold(logs::Severity_Level::DEBUG);
        logger.log(logs::Severity_Level::INFO, "Initialization complete");
        {
            logs::Scoped_Context phase("advance_model");
            for (int step = 0; step < 2; ++step) {
                logger.log(logs::Severity_Level::DEBUG,
                           "rank=" + std::to_string(rank) +
                           " step=" + std::to_string(step));
            }
        }
        logger.log(logs::Severity_Level::INFO, "Model phase complete");
        logger.consolidate();
    }
    MPI_Finalize();
}
```

Rebuild and run with two ranks:

```bash
cmake --build build --parallel
mpiexec -n 2 ./build/logs_tutorial
```

**Checkpoint:** locate messages for rank=0 step=0, rank=0 step=1,
rank=1 step=0, and rank=1 step=1. The step records are emitted inside the
advance_model context. The final INFO record occurs after that context exits.

Do not require a particular order between ranks. Each rank's code has a clear
local order, but independent processes do not share a single execution clock.

## 4. Filter the phase records without changing call sites

Change the threshold from DEBUG to INFO, rebuild, and rerun.

**Checkpoint:** initialization and completion remain visible. The four distinct
step messages disappear. The calls still exist in the program; the logger's
threshold controls whether they are emitted.

Change the completion record to WARNING, then set the threshold to WARNING.
Predict that initialization disappears and completion remains. Rebuild to check.

## 5. Make repeated and rank-specific messages distinguishable

Restore DEBUG. Add this line inside the loop after the step record:

```cpp
logger.log(logs::Severity_Level::INFO, "Shared timestep checkpoint");
```

Run with one, then two ranks. The shared message has identical text on every
rank; the existing step messages contain different rank values. Observe how
consolidation handles those cases in the installed version.

Every rank reaches consolidate in the same control-flow position. Do not move
it into a branch executed only on rank zero.

## 6. Follow resource shutdown

The logger is inside an inner scope. Its destructor runs before MPI_Finalize.
The context object is in an even smaller scope, so its label is removed before
the completion record.

Trace those closing braces before adding longer-lived loggers to a real model.
Keep this tutorial at DEBUG, INFO, and WARNING; FATAL invokes distributed
termination rather than serving as another verbosity experiment.

## If you get stuck

| Symptom | Check |
| --- | --- |
| MPI C++ package missing | Configure in the HELM container or with the intended MPI toolchain |
| No DEBUG records | Verify the rebuilt executable sets the threshold to DEBUG |
| Unexpected ordering | Compare content and rank coverage, not interleaving |
| Job waits at consolidation | Confirm every participating rank reaches the same consolidation point |
| Launcher rejects the process count | Request enough slots or use the platform's allocation workflow |

## Practice

Add a nested context named output_prepare inside advance_model and emit one
record there. Then change the launch to four ranks and predict which message
texts remain identical across ranks.

Consult the [LOGS reference](../reference/logs.md) for sink and record interfaces.
