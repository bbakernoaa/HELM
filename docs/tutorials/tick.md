---
type: tutorial
category: tutorials
tags: [helm, tick]
---

# TICK: build a small model-coupling clock

[Library overview](../libraries/tick.md) · [All libraries](../README.md)

You will coordinate models with 60-second and 90-second timesteps, advance a
shared clock, and trigger output every two minutes. By the end you will have
a program that prints a schedule and checks its timing with assertions.

Allow about 25 minutes. You need a complete HELM checkout and a C++20 compiler.
This tutorial links TICK directly from source, so it needs no MPI, Kokkos,
CMake, or test framework. Follow the [development setup](../README.md#prepare-a-development-environment)
if you want to use the project container.

## 1. Create a place for the exercise

Start at the HELM repository root:

```bash
mkdir -p /tmp/helm-tick-tutorial
```

All compilation commands below run from that repository root. The tutorial
sources and executable live in the temporary directory.

## 2. Find when the models can run

Save this as `/tmp/helm-tick-tutorial/main.cpp`:

```cpp
#include <array>
#include <cassert>
#include <iostream>
#include <tick/sync.hpp>

int main() {
    const std::array steps{tick::seconds(60), tick::seconds(90)};
    const auto heartbeat = tick::compute_heartbeat(steps);
    const auto coupling = tick::compute_sync_period(steps);
    assert(heartbeat == tick::seconds(30));
    assert(coupling == tick::seconds(180));
    std::cout << "heartbeat=30s, coupling=180s\n";
}
```

Compile and run:

```bash
c++ -std=c++20 -I libs/tick/include /tmp/helm-tick-tutorial/main.cpp libs/tick/src/sync.cpp -o /tmp/helm-tick-tutorial/clock
/tmp/helm-tick-tutorial/clock
```

**Checkpoint:** the program exits successfully and prints:

```text
heartbeat=30s, coupling=180s
```

A 30-second heartbeat can represent both schedules. Both models have a timestep
boundary at 180 seconds. Their individual timesteps remain 60 and 90 seconds.

## 3. Advance the clock and attach an output alarm

Replace the entire program with this version:

```cpp
#include <array>
#include <cassert>
#include <iostream>
#include <tick/interval_alarm.hpp>
#include <tick/sync.hpp>

int main() {
    const std::array steps{tick::seconds(60), tick::seconds(90)};
    const auto heartbeat = tick::compute_heartbeat(steps);
    const auto coupling = tick::compute_sync_period(steps);
    const tick::Time_Point start{0};
    const auto finish = start + tick::seconds(360);
    const tick::Interval_Alarm output(tick::seconds(120), start);
    int output_count = 0;
    int coupling_count = 0;

    for (auto now = start; now <= finish; now += heartbeat) {
        const auto elapsed = (now - start).nanos() / tick::nanos_per_second;
        const bool atmosphere = tick::is_phase_aligned(now, start, steps[0]);
        const bool ocean = tick::is_phase_aligned(now, start, steps[1]);
        const bool exchange = tick::is_phase_aligned(now, start, coupling);
        const bool write = output.is_ringing(now);
        output_count += write;
        coupling_count += exchange;
        std::cout << elapsed << "s atmosphere=" << atmosphere
                  << " ocean=" << ocean << " couple=" << exchange
                  << " output=" << write << '\n';
    }
    assert(output_count == 4);
    assert(coupling_count == 3);
    assert(output.next_ring_at(start + tick::seconds(120))
           == start + tick::seconds(240));
}
```

Run the same compilation command, then the executable again.

**Checkpoint:** there are 13 schedule rows, from 0 through 360 seconds.
At 0, all four flags are one. At 30, all are zero. At 120, the atmosphere
and output flags are one; ocean and coupling are zero. At 180, both models and
coupling are one, while output is zero.

The counts include the initial instant: output fires at 0, 120, 240, and 360.
`next_ring_at` returns the next ring strictly after an instant that is
already on an alarm boundary.

## 4. Predict a changed schedule

Change the ocean timestep from 90 to 120 seconds. Before running, write down
the new heartbeat and coupling period.

The answers are 60 and 120 seconds. Update any initial assertions if you retained
the first program. In the second program, change the coupling-count assertion
from 3 to 4. The schedule now has seven rows, and each output event is also a
coupling event.

## 5. Observe invalid input safely

Add this block before the end of `main`:

```cpp
bool rejected = false;
try {
    const tick::Interval_Alarm invalid(tick::seconds(0), start);
} catch (const std::invalid_argument&) {
    rejected = true;
}
assert(rejected);
```

Rebuild and run. A successful exit now also confirms that an alarm with a
nonpositive interval is rejected.

## If you get stuck

| Symptom | Check |
| --- | --- |
| A TICK header cannot be found | Run the compile command from the HELM root |
| Undefined synchronization functions | Include `libs/tick/src/sync.cpp` in the compile command |
| An assertion fails after changing a timestep | Recompute expected event counts, including time zero |
| Output is skipped with a larger heartbeat | Use a heartbeat that visits every required event boundary |

## Practice

Extend the finish time to 600 seconds. With the original 60/90 timesteps,
predict six output events and four coupling events, including zero, then verify.
Add a third model with a 45-second timestep and recalculate the heartbeat.
Keep the exercise in integer durations; do not convert the clock to floating-point.

You have built a schedule, not an executor: no model work runs when a flag is
printed. Continue to [DAGR](dagr.md) to learn about dependency configuration,
or consult the [TICK reference](../reference/tick.md) for calendar APIs.
