---
type: tutorial
category: tutorials
tags: [helm, blend]
---

# BLEND: Tutorial: blend two constant fields

[Library overview](../libraries/blend.md) · [All libraries](../README.md)

## Before you start

Allow 25–35 minutes. Keep the first exercise in its own directory:
`mkdir -p /tmp/helm-blend-tutorial`, then `cd /tmp/helm-blend-tutorial`.
Create the two files shown below there. Replace the HELM path in CMake with
your real checkout path. Allocations use the configured Kokkos memory space;
we copy results to a host mirror before inspecting them.


## 1. Build and run a first example

**Goal:** blend values 2 and 6 with a weight of 0.25 and observe the result 3.
Complete the [environment setup](../README.md#prepare-a-development-environment).
You need C++20, CMake, and Kokkos.

In a temporary directory, save this complete program as `main.cpp`:

```cpp
#include <blend/helm_math_blend.hpp>
#include <iostream>

int main(int argc, char** argv) {
    Kokkos::ScopeGuard kokkos(argc, argv);
    Kokkos::View<double*> left("left", 4), right("right", 4), out("out", 4);
    Kokkos::deep_copy(left, 2.0);
    Kokkos::deep_copy(right, 6.0);
    span::FieldView l(left.data(), 4), r(right.data(), 4), o(out.data(), 4);
    blend::LinearBlendKernel::apply(l, r, o, 0.25);
    auto host = Kokkos::create_mirror_view_and_copy(Kokkos::HostSpace{}, out);
    for (int i = 0; i < 4; ++i) std::cout << host(i) << '\n';
}
```

Save this `CMakeLists.txt` beside it, replacing the checkout path:

```cmake
cmake_minimum_required(VERSION 3.21)
project(blend_tutorial LANGUAGES CXX)
add_subdirectory(/path/to/HELM/libs/blend blend-build)
add_executable(blend_tutorial main.cpp)
target_link_libraries(blend_tutorial PRIVATE HELM::BLEND)
```

Run `cmake -S . -B build`, then `cmake --build build --parallel`, then
`./build/blend_tutorial`. Expect four lines containing `3`.
Change alpha to zero and run again: all four values become `2`.

## 2. Compare interpolation and step selection

After the first example works, replace its complete `main.cpp` with this
version. It exercises three linear weights, the step threshold, and an invalid
extent. The owning arrays stay alive until every operation finishes.

```cpp
#include <blend/helm_math_blend.hpp>
#include <cmath>
#include <iostream>
#include <stdexcept>

int main(int argc, char** argv) {
    Kokkos::ScopeGuard kokkos(argc, argv);
    Kokkos::View<double*> left("left", 4), right("right", 4), out("out", 4);
    Kokkos::deep_copy(left, 2.0);
    Kokkos::deep_copy(right, 6.0);
    span::FieldView l(left.data(), 4), r(right.data(), 4), o(out.data(), 4);

    const auto check = [&](double expected) {
        const auto host =
            Kokkos::create_mirror_view_and_copy(Kokkos::HostSpace{}, out);
        for (int i = 0; i < 4; ++i) {
            if (std::abs(host(i) - expected) > 1e-12) {
                throw std::runtime_error("Unexpected blended value");
            }
        }
        std::cout << "all four values=" << expected << '\n';
    };

    for (double alpha : {0.0, 0.25, 1.0}) {
        blend::execute_blend(l, r, o, alpha, blend::BlendProfile::Linear);
        check(2.0 * (1.0 - alpha) + 6.0 * alpha);
    }
    blend::execute_blend(l, r, o, 0.49, blend::BlendProfile::Step);
    check(2.0);
    blend::execute_blend(l, r, o, 0.5, blend::BlendProfile::Step);
    check(6.0);

    bool rejected = false;
    try {
        span::FieldView too_short(out.data(), 3);
        blend::LinearBlendKernel::apply(l, r, too_short, 0.25);
    } catch (const std::invalid_argument&) {
        rejected = true;
    }
    if (!rejected) throw std::runtime_error("Extent mismatch was accepted");
    std::cout << "extent mismatch rejected\n";
}
```

Build and run explicitly:

```bash
cmake --build build --parallel
./build/blend_tutorial
```

**Checkpoint:** the values printed in order are 2, 3, 6, 2, and 6, followed by
`extent mismatch rejected`. At the exact threshold of 0.5, step selection
chooses the right bookend.

## 3. Predict an intermediate value

Change the linear weight list to `{0.0, 0.5, 0.75, 1.0}`.
Before rebuilding, calculate each result on paper:

| Alpha | Calculation | Expected value |
| --- | --- | --- |
| 0 | 2 × 1 + 6 × 0 | 2 |
| 0.5 | 2 × 0.5 + 6 × 0.5 | 4 |
| 0.75 | 2 × 0.25 + 6 × 0.75 | 5 |
| 1 | 2 × 0 + 6 × 1 | 6 |

Rebuild and confirm. The check function compares every array element, so a
correct first element alone is insufficient.

## 4. Observe extrapolation

Add 1.5 to the linear weight list. The expected result is 8, outside the input
range [2, 6]. BLEND does not clamp alpha. Keep weights between zero and one when
your intended operation is interpolation.

Restore the original weights when you finish this experiment.

## 5. Separate input ownership from output

The unmanaged views wrap pointers from the owning Kokkos arrays. They allocate
no new field data. In this example, l, r, and o are three wrappers, while left,
right, and out retain the storage.

Keep output separate from both inputs. The shape check does not establish that
arbitrary overlapping allocations are safe. Do not substitute a host stack array
when the configured kernel executes on a device.

## If you get stuck

| Symptom | Check |
| --- | --- |
| Kokkos package not found | Use the development container or its installed prefix |
| Invalid host access on GPU | Inspect the host mirror, not out directly |
| Mismatch exception | All three extents must agree |
| Conflicting FieldView declaration | Keep this exercise separate from SPAN headers; BLEND currently defines its own alias |

## Practice

Change the two constants to 270 and 290. At alpha 0.25, predict 275 before running.
Then change alpha to 0.5 and compare linear and step results: 280 versus 290.
Explain which behavior fits a smoothly varying forcing field and which fits a
categorical nearest-snapshot selection.

Use the [BLEND reference](../reference/blend.md) for the interface contract.
