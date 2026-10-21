---
type: tutorial
category: tutorials
tags: [helm, span]
---

# SPAN: Tutorial: wrap an array without copying it

[Library overview](../libraries/span.md) · [All libraries](../README.md)

## Before you start

Allow about 30 minutes. Put the two initial files in
`/tmp/helm-span-tutorial`. All remaining build commands run from that
directory. The first exercise uses host storage only, so it requires no GPU.
For the following Kokkos adapter exercise, initialize Kokkos before constructing
the adapter and dispatching kernels.


## 1. Build and run a first example

**Goal:** change one value through a view and observe it in the original array.
Complete the [environment setup](../README.md#prepare-a-development-environment).
You need C++20, CMake, Kokkos, and an mdspan implementation discoverable as
`<mdspan/mdspan.hpp>` when the standard header is unavailable.

Save this complete program as `main.cpp` in a temporary directory:

```cpp
#include <span/field_view.hpp>
#include <iostream>

int main() {
    double values[4] = {1, 2, 3, 4};
    span::FieldView<double, 1> field(values, {4});
    field.data()[0] = 9;
    std::cout << field.size() << " " << values[0] << '\n';
}
```

Save this `CMakeLists.txt` beside it, replacing the checkout path:

```cmake
cmake_minimum_required(VERSION 3.21)
project(span_tutorial LANGUAGES CXX)
add_subdirectory(/path/to/HELM/libs/span span-build)
add_executable(span_tutorial main.cpp)
target_link_libraries(span_tutorial PRIVATE HELM::SPAN)
```

Run `cmake -S . -B build`, `cmake --build build --parallel`, and
`./build/span_tutorial`. Expect `4 9`: the view reports four elements, and
writing through its pointer changes the original allocation.

## 2. Prove that two views share one allocation

Replace `main.cpp` with this complete program:

```cpp
#include <span/field_view.hpp>
#include <cassert>
#include <iostream>

int main(int argc, char** argv) {
    Kokkos::ScopeGuard kokkos(argc, argv);
    double values[6] = {1, 2, 3, 4, 5, 6};
    span::FieldView<double, 2> field(values, {2, 3});
    const auto flat = field.to_kokkos_view();
    assert(field.data() == values);
    assert(flat.data() == values);
    assert(field.size() == 6);
    assert(field.extent(0) == 2);
    assert(field.extent(1) == 3);

    using HostExecution = Kokkos::DefaultHostExecutionSpace;
    Kokkos::parallel_for(
        "double_host_values",
        Kokkos::RangePolicy<HostExecution>(0, 6),
        KOKKOS_LAMBDA(const int i) { flat(i) *= 2.0; });
    Kokkos::fence();

    for (int i = 0; i < 6; ++i) {
        assert(values[i] == 2.0 * (i + 1));
        std::cout << values[i] << (i == 5 ? '\n' : ' ');
    }
    field.mark_host_dirty();
    assert(field.coherency_state() == span::CoherencyState::HOST_DIRTY);
    field.sync_for_device();
    assert(field.coherency_state() == span::CoherencyState::HOST_DIRTY);
    std::cout << "host-only synchronization is a no-op\n";
}
```

Rebuild and run:

```bash
cmake --build build --parallel
./build/span_tutorial
```

**Checkpoint:**

```text
2 4 6 8 10 12
host-only synchronization is a no-op
```

The adapter is flat even though field has rank two. Its memory space is host;
the explicit host execution policy keeps the kernel compatible with that memory.

## 3. Map the multidimensional indices

The field has extents [2, 3] and a column-major mdspan layout. For this exercise,
the original linear array maps as follows before doubling:

| Index pair | Flat offset | Original value |
| --- | --- | --- |
| (0, 0) | 0 | 1 |
| (1, 0) | 1 | 2 |
| (0, 1) | 2 | 3 |
| (1, 1) | 3 | 4 |
| (0, 2) | 4 | 5 |
| (1, 2) | 5 | 6 |

Change the extents to {3, 2}. The flat results stay the same, but the interpretation
of multidimensional indices changes. Check `extent(0)` and
`extent(1)` against the new dimensions and update the assertions.

The view records the shape you supply. It cannot infer a different shape from a
raw pointer.

## 4. Observe an invalid shape

Restore {2, 3}. Add this block before the end of main:

```cpp
bool rejected = false;
try {
    span::FieldView<double, 2> invalid(values, {0, 3});
} catch (const std::invalid_argument&) {
    rejected = true;
}
assert(rejected);
std::cout << "zero extent rejected\n";
```

Rebuild and verify the final message. The constructor rejects this zero extent;
it does not inspect whether a non-null pointer actually owns enough elements.

## 5. Understand what did not synchronize

After the kernel modifies values, we explicitly mark the host copy dirty.
Calling sync_for_device does not allocate a missing device array. With only a
host pointer, it does nothing and retains the dirty state.

A real host/device exercise needs two valid allocations, both pointers registered
with the view, and matching memory spaces. Do not fake a device pointer by
passing an arbitrary host address.

## If you get stuck

| Symptom | Check |
| --- | --- |
| mdspan header missing | Install the mdspan headers expected by the library/toolchain |
| Host view accessed from the wrong execution space | Use DefaultHostExecutionSpace for this exercise |
| Values are incorrect | Keep the backing array alive and fence before inspecting it |
| Dirty state remains after synchronization | A host-only view has no device allocation to synchronize |

## Practice

Add one to every value instead of doubling it and update the assertions.
Construct a second view over values and verify pointer equality between the two.
Keep the allocation in the outer scope; do not return a view over a destroyed
local array.

Continue with the [SPAN explanation](../explanation/span.md) for ownership and
the [reference](../reference/span.md) for dual-pointer synchronization.
