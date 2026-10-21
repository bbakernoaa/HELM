---
type: explanation
category: explanation
tags: [helm, tick]
---

# TICK: Why integer time and explicit calendars matter

[Library overview](../libraries/tick.md) · [All libraries](../README.md)

Repeatedly adding floating-point timesteps can accumulate rounding error. TICK
represents durations and time offsets as integers, making comparisons and
alignment tests exact within the supported range. Checked arithmetic reports
overflow instead of silently wrapping for the core operations.

## A time point is not a calendar date

A Time_Point is an offset from TICK's epoch. Calendar engines translate between
that representation and civil fields. Gregorian, NoLeap and Cal360 calendars
define different mappings: the same month/day or year length does not mean the
same elapsed duration in every model calendar.

Choosing a calendar is part of the model-data contract. A 30-day month in
Cal360 is not an approximate Gregorian month; it belongs to a different
calendar system. Keep calendar identity explicit when reading dates or writing
metadata.

## Heartbeat and synchronization period

The GCD heartbeat is the finest fixed cadence that divides every supplied
timestep. It is useful when a coupling loop must visit each model's step
boundary. The LCM is the period after which zero-phase schedules align again.
Large or relatively prime timesteps can produce a long synchronization period,
so calculate it with the actual model schedule and account for integer range.

For model steps of 300 seconds and 420 seconds, the heartbeat is 60 seconds and
the zero-phase synchronization period is 2,100 seconds. The heartbeat says when
either model may reach a boundary; the synchronization period says when both
step schedules meet again. A non-zero initial phase changes alignment and must
be handled with the phase-aware APIs rather than inferred from the LCM alone.

An alarm determines when an event is due; a time window determines which
accumulation interval contains a point. Neither executes model work. DAGR or
application code acts on those decisions, while BLEND computes field values.
