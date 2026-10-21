---
type: tutorial
category: tutorials
tags: [helm, halo]
---

# HALO: Tutorial: explore a structured halo exchange

[Library overview](../libraries/halo.md) · [All libraries](../README.md)

**Goal:** identify the plan, communication, and completion stages of an exchange.
Complete the [environment setup](../README.md#prepare-a-development-environment).
You need C++20, CMake, MPI, Kokkos, GTest, and RapidCheck.

## 1. Build and inspect the maintained exchange example

Build the CPU/staged path from the repository root:

```bash
cmake -S libs/halo -B libs/halo/build -DHALO_BUILD_TESTING=ON -DHALO_BUILD_FORTRAN=OFF -DHALO_GPU_AWARE_MPI=OFF
cmake --build libs/halo/build --parallel
ctest --test-dir libs/halo/build --output-on-failure --no-tests=error
```

The test suite should report passing exchanges. Read the
[structured exchange example](https://github.com/NOAA-EMC/HELM/blob/develop/libs/halo/README.md#structured-halo-exchange-api).
Locate the 132-by-68 allocation: its 128-by-64 owned region has a two-cell halo
on each side. Identify the four neighbor ranks and the precomputed plan.

Trace the blocking call and then the asynchronous variant. The asynchronous
variant returns a handle; `handle.wait()` completes communication and unpacks
received values. Before proceeding, identify which computations can run before
that wait without reading incoming halos. The
[overlap guide](https://github.com/NOAA-EMC/HELM/blob/develop/libs/halo/docs/overlap_pattern.md) supplies a worked stencil
example.

## 2. Create a two-rank exercise

Allow 40 minutes for the complete walkthrough. The test run above checks your
toolchain. Now create an application directory:

```bash
mkdir -p /tmp/helm-halo-tutorial
cd /tmp/helm-halo-tutorial
```

Save this CMakeLists.txt, replacing the checkout path:

```cmake
cmake_minimum_required(VERSION 3.21)
project(halo_tutorial LANGUAGES CXX)
set(HALO_BUILD_FORTRAN OFF CACHE BOOL "" FORCE)
set(HALO_BUILD_TESTING OFF CACHE BOOL "" FORCE)
set(HALO_GPU_AWARE_MPI OFF CACHE BOOL "" FORCE)
add_subdirectory(/path/to/HELM/libs/halo halo-build)
add_executable(halo_tutorial main.cpp)
target_link_libraries(halo_tutorial PRIVATE HELM::HALO)
```

Each rank owns four cells and two ghost cells. Rank zero's right neighbor is
rank one; rank one's left neighbor is rank zero. The exterior boundaries have
no neighbor and retain the sentinel value -1.

## 3. Exchange one boundary value in each direction

Save this complete main.cpp:

```cpp
#include <mpi.h>
#include <Kokkos_Core.hpp>
#include <halo/communicator.hpp>
#include <halo/environment.hpp>
#include <halo/exchange_structured.hpp>
#include <halo/structured_halo_plan.hpp>
#include <array>
#include <iostream>
#include <stdexcept>

int main(int argc, char** argv) {
    int provided = 0;
    MPI_Init_thread(&argc, &argv, MPI_THREAD_SERIALIZED, &provided);
    int failed = 0;
    try {
        Kokkos::ScopeGuard kokkos(argc, argv);
        halo::Environment::initialize();
        halo::Communicator world(MPI_COMM_WORLD);
        if (world.size() != 2) {
            throw std::runtime_error("Launch this tutorial with exactly two ranks");
        }
        const int rank = world.rank();
        const std::array<int, 2> neighbors =
            rank == 0 ? std::array<int, 2>{-1, 1}
                      : std::array<int, 2>{0, -1};
        halo::Structured_Halo_Plan<1> plan({6}, neighbors, {1}, world);
        Kokkos::View<double*> field("field", 6);
        auto host = Kokkos::create_mirror_view(field);
        for (int i = 0; i < 6; ++i) host(i) = -1;
        for (int i = 1; i <= 4; ++i) host(i) = rank * 100 + i;
        Kokkos::deep_copy(field, host);

        halo::exchange_structured_blocking(plan, field);
        Kokkos::deep_copy(host, field);
        const bool correct = rank == 0
            ? host(0) == -1 && host(5) == 101
            : host(0) == 4 && host(5) == -1;
        failed = !correct;
        std::cout << "rank " << rank << " left=" << host(0)
                  << " right=" << host(5) << '\n';
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        MPI_Abort(MPI_COMM_WORLD, 1);
        return 1;
    }
    int any_failed = 0;
    MPI_Allreduce(&failed, &any_failed, 1, MPI_INT, MPI_MAX, MPI_COMM_WORLD);
    MPI_Finalize();
    return any_failed;
}
```

Build and launch from the tutorial directory:

```bash
cmake -S . -B build
cmake --build build --parallel
mpiexec -n 2 ./build/halo_tutorial
```

**Checkpoint:** these two lines appear, possibly in the opposite order:

```text
rank 0 left=-1 right=101
rank 1 left=4 right=-1
```

The shared interface exchanges rank zero's last owned value, 4, with rank one's
first owned value, 101. Both outside ghost cells remain -1. A nonzero exit status
means an expected value was not observed.

## 4. Repeat the exercise asynchronously

Replace the single blocking exchange statement with:

```cpp
auto exchange = halo::exchange_structured_async(plan, field);
// Independent work may be placed here; do not read incoming ghost cells.
exchange.wait();
```

Rebuild and launch with two ranks again.

**Checkpoint:** ghost-cell results are unchanged. The completion wait must occur
before copying received values back for inspection. This tiny example creates
an overlap opportunity but performs no useful independent computation in it.

## 5. Predict a different boundary

Change the owned-cell initialization from rank*100+i to rank*1000+i.
Predict the new received values before running: rank zero's right ghost becomes
1001, while rank one's left ghost remains 4.

Update the expected-value check from 101 to 1001 and rerun. Without updating
the check, the executable should return a failure even though communication
succeeded.

Do not simply increase halo width: both total extents and expected receive
regions would need to change. Sketch the larger layout first.

## If you get stuck

| Symptom | Check |
| --- | --- |
| Process-count error | Launch with exactly two ranks |
| Exchange hangs | Both ranks must exchange on matching topology and communicator |
| Stale ghost values | Wait for the asynchronous handle before inspection |
| Outside ghosts stay -1 | That is expected at faces with neighbor -1 |
| GPU pointer errors | Keep GPU-aware MPI OFF for this staged-path tutorial |

## Practice

Print all six values on each rank and verify that owned cells are unchanged.
Then use the [overlap guide](https://github.com/NOAA-EMC/HELM/blob/develop/libs/halo/docs/overlap_pattern.md)
to identify a stencil's independent interior. Keep communicator, plan, and field
alive until the exchange completes.
