---
type: reference
category: reference
tags: [helm, logs]
---

# LOGS: operational logging API reference

[Library overview](../libraries/logs.md) · [Tutorial](../tutorials/logs.md) ·
[How-to](../how-to/logs.md) · [All libraries](../README.md)

Include `<logs/logs.hpp>` for the public API. LOGS adds MPI rank context to
records, buffers output for consolidation, supports scoped context labels, and
provides output sinks. It is a reporting boundary; it does not parse
configuration or discover stack symbols. The project
[README](https://github.com/NOAA-EMC/HELM/blob/develop/libs/logs/README.md)
lists the public type headers and a complete quick-start example.

## Configure and emit records

Create a `logs::Logger`, configure the communicator, set the minimum severity,
and register any sinks before writing records:

```cpp
#include <logs/logs.hpp>
#include <iostream>

logs::Logger logger;
logger.configure_communicator(MPI_COMM_WORLD);
logger.set_threshold(logs::Severity_Level::INFO);
logger.add_sink(logs::Sink(std::cout));
logger.log(logs::Severity_Level::INFO, "Initialization complete");
```

The ordered severities are `DEBUG`, `INFO`, `WARNING`, `ERROR`, and `FATAL`.
The threshold filters ordinary records below the selected level. FATAL is a
termination path: when a communicator is configured, it initiates an MPI
abort. Do not use it for a recoverable error or as a substitute for orderly
shutdown.

Without an explicit sink, formatted output falls back to `stderr`. A sink wraps
an output stream and does not own it; the stream must remain alive while the
logger can write to it. Register sinks during setup rather than modifying the
logger's output destinations while other threads are logging.

## Records, context, and stack data

| Type | Use |
| --- | --- |
| `Severity_Level` | Severity enum and string conversion |
| `Log_Record` | Immutable record value with rank and message metadata |
| `Sink` | Output-stream destination |
| `Scoped_Context` | RAII label attached to records in its lexical scope |
| `Source_Location` | Caller-supplied source annotation |
| `Stack_Frame` | Caller-supplied frame data for formatting |
| `Logger` | Thread-safe central logging entry point |

`Scoped_Context` nests and is cleaned up at scope exit, including stack
unwinding. Stack-trace helpers format frame data supplied by the caller; they
do not inspect binaries, resolve symbols, or collect a trace themselves.

## Distributed consolidation and MPI lifecycle

`consolidate()` consolidates matching records across ranks to reduce duplicate
output. Call it at a deliberate synchronization point from every participating
rank, in the same order relative to other collective communication. Configure
the logger only after MPI initialization. LOGS being thread-safe at its C++
boundary does not grant additional MPI thread support: calls that communicate
must follow the level returned by the application's `MPI_Init_thread` request.
Destroy or stop using the logger before finalizing MPI if its fatal or
consolidation paths may need MPI.

Public logger entry points are `noexcept`; failures are caught at the logging
boundary and may be reported as diagnostics. This keeps logging failures from
escaping through operational code, but cannot make an invalid MPI lifecycle or
concurrent stream access safe.

## Build

LOGS requires MPI C++ and exports `HELM::LOGS`. `LOGS_BUILD_TESTING` enables
GTest and RapidCheck tests. See the
[build definition](https://github.com/NOAA-EMC/HELM/blob/develop/libs/logs/CMakeLists.txt).
