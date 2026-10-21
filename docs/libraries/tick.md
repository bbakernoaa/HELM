---
type: reference
category: reference
tags: [helm, tick, navigation]
---

# TICK — Time Integration & Chronology Kernel

TICK represents temporal offsets and intervals using integer duration values.
It provides calendar conversion, alarms, synchronization periods and
accumulation windows for Earth-system models.

`tick::Duration` and `tick::Time_Point` use integer nanoseconds by default.
Factories such as `seconds`, `hours` and `days` make unit choice explicit.
A time point is an offset from TICK's epoch, not a calendar date; use a calendar
engine to convert civil fields.

Gregorian, NoLeap and Cal360 calendars have different date rules. Select the
one that matches the model and its data. Do not interpret a 360-day date as
Gregorian. Arithmetic checks overflow for the core operators.

`compute_heartbeat` returns the greatest common divisor of model timesteps;
`compute_sync_period` returns the least common multiple. The former provides
a cadence capable of representing all timestep boundaries; the latter marks
when zero-phase schedules meet. `is_phase_aligned` tests a time relative to a
base and step. Interval and absolute alarms represent recurring and one-shot
events; Time_Window describes accumulation periods.

For 300-second and 420-second model steps, the heartbeat is 60 seconds and the
zero-phase synchronization period is 2,100 seconds. Use the heartbeat when a
coupler must visit each component step boundary; use the synchronization period
when it needs the next shared boundary. Non-zero phases require an explicit
alignment check.

The C++ library target is `HELM::TICK`; C callers can use `HELM::TICK_C`.
`TICK_BUILD_FORTRAN` enables its Fortran wrapper and
`TICK_BUILD_TESTING` its tests. `TICK_RESOLUTION` configures seconds or
nanoseconds for the build.

Try [the coupling clock](../tutorials/tick.md), follow
[the Fortran recipe](../how-to/tick.md), consult
[type and function details](../reference/tick.md), and read
[why time is integer-based](../explanation/tick.md).
