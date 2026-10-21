---
type: reference
category: reference
tags: [helm, tick]
---

# TICK: time and calendar API reference

[Library overview](../libraries/tick.md) · [Tutorial](../tutorials/tick.md) ·
[How-to](../how-to/tick.md) · [All libraries](../README.md)

Include `<tick/tick.hpp>` for the C++ umbrella API. TICK represents durations
and instants as signed integer offsets, then provides calendar engines,
alignment helpers, alarms, and interval windows. The default resolution is
nanoseconds; CMake can select seconds. The `tick::epoch` constant is the
2026-01-01T00:00:00 reference instant and has `nanos() == 0`.

## Duration and time-point arithmetic

`Duration` stores an integer number of nanoseconds and provides factories
`nanoseconds`, `microseconds`, `milliseconds`, `seconds`, `minutes`, `hours`,
and `days`. It supports comparisons and addition, subtraction, integer
multiplication, and integer division. Duration addition/subtraction and
multiplication use checked arithmetic; division by zero throws
`std::invalid_argument`.

`Time_Point` is an integer offset from the TICK epoch. Add or subtract a
`Duration` to move an instant; subtract two time points to get a `Duration`.
These are timeline values, not civil dates. Use a calendar engine to map
between `Time_Point` and `Date_Time`.

## Synchronization helpers

| API | Meaning |
| --- | --- |
| `compute_heartbeat(time_steps)` | Greatest common divisor of the model step durations |
| `compute_sync_period(time_steps)` | Least common multiple, the repeat period of aligned schedules |
| `is_phase_aligned(current, base, step)` | True when current is at a step boundary relative to base |

`is_phase_aligned` requires a positive step and returns false when `current`
precedes `base`. For example, 60-second and 90-second steps have a 30-second
heartbeat and a 180-second sync period. Advance a shared clock at a frequency
that visits every required event boundary; a heartbeat that is too coarse can
skip alarms or model steps.

## Alarms and windows

| Type or function | Contract |
| --- | --- |
| `Interval_Alarm(interval, reference)` | Requires a positive interval; rings at the reference and each interval after it |
| `Interval_Alarm::next_ring_at(t)` | Returns the next ring strictly after `t`; before the reference, returns the reference |
| `Absolute_Alarm(trigger)` | `is_ringing(t)` is true only at exact equality; `has_passed(t)` is true only after the trigger |
| `Time_Window(start, end)` | Requires `start < end`; contains `[start, end)` |
| `is_on_boundary(time, interval)` | Checks divisibility from the TICK epoch; interval must be positive |
| `compute_window(time, interval)` | Returns the enclosing half-open interval, including for negative offsets |

An `Absolute_Alarm` is a point-in-time test, not a latched event. If a loop can
advance past the trigger without visiting it, check `has_passed()` or align the
clock to that trigger. The interval alarm's reference is its phase origin.

## Civil calendars and date parsing

`Date_Time` is a plain aggregate of year, month, day, hour, minute, second, and
nanosecond fields. `parse_iso8601()` accepts exactly
`YYYY-MM-DDThh:mm:ss`; it sets nanoseconds to zero and checks basic field
ranges, but it does not check whether a day exists in a particular month.
`format_iso8601()` emits the same second-resolution form and discards the
nanosecond field.

The `Gregorian_Calendar`, `NoLeap_Calendar`, and `Cal360_Calendar` engines
convert between `Time_Point` and `Date_Time`. Use the calendar matching the
model dataset. A syntactically valid date can still be invalid for a calendar
(for example, February 30), and no-leap and 360-day calendars intentionally do
not follow Gregorian month lengths. The `Calendar` concept describes the
conversion and month/year-length operations required of a calendar type.

TICK also exposes `AliasedWindow` and `OutOfBoundsPolicy` for representing
time-dependent windows and dataset coverage policies. The policy enum values
are `clamp_to_edge`, `cycle_last_year`, `pure_climatology`, and `leap_hold`;
the consuming aliasing engine defines the specific data remapping behavior.

## Language interfaces and build

The C++ target is `HELM::TICK`, the C target is `HELM::TICK_C`, and optional
Fortran support exports `HELM::TICK_Fortran`. `TICK_RESOLUTION` accepts
`SECONDS` or `NANOSECONDS` (default); `TICK_BUILD_FORTRAN` and
`TICK_BUILD_TESTING` control optional targets. See
[TICK's CMake file](https://github.com/NOAA-EMC/HELM/blob/develop/libs/tick/CMakeLists.txt).
