---
type: howto
category: how_to
tags: [helm, logs]
---

# LOGS: Add phase context to distributed log records

[Library overview](../libraries/logs.md) · [All libraries](../README.md)

Scoped context labels make a sequence of log records easier to associate with
one model phase. The label follows the C++ scope, so it is removed
automatically on normal exit and exception unwinding.

## Configure a logger and sink

~~~cpp
logs::Logger logger;
logger.configure_communicator(MPI_COMM_WORLD);
logger.set_threshold(logs::Severity_Level::INFO);
logger.add_sink(logs::Sink(std::cout));
~~~

Keep the output stream alive at least as long as the logger uses it. Configure
MPI after initialization; destroy logger objects before MPI finalization.

## Add nested scopes

~~~cpp
{
    logs::Scoped_Context advance("advance_model");
    logger.log(logs::Severity_Level::INFO, "Starting timestep");
    {
        logs::Scoped_Context forcing("read_forcing");
        logger.log(logs::Severity_Level::DEBUG, "Reading input fields");
    }
    logger.log(logs::Severity_Level::INFO, "Physics step complete");
}
~~~

At an INFO threshold, the debug record is filtered. Raise the threshold to DEBUG
to inspect it. Nested labels are captured when a record is submitted; they do
not change the global threshold.

## Consolidate consistently

If calling `logger.consolidate()` in an MPI program, every participant must
arrive at the collective consistently. Do not call it only on rank zero.
When no sink is registered, LOGS falls back to stderr. The exact formatting is
owned by `Logger` and the sink; avoid parsing display strings as a data format.

FATAL is a termination path. Never use it for ordinary error reporting that
should allow the job to continue. See the [logger interface](https://github.com/NOAA-EMC/HELM/blob/develop/libs/logs/include/logs/logger.hpp)
and [context type](https://github.com/NOAA-EMC/HELM/blob/develop/libs/logs/include/logs/scoped_context.hpp).
