---
type: reference
category: reference
tags: [helm, halo]
---

# HALO: MPI communication API reference

[Library overview](../libraries/halo.md) · [Overlap tutorial](../tutorials/halo.md) ·
[Thread-safety how-to](../how-to/halo.md) · [All libraries](../README.md)

HALO wraps MPI communication resources with C++ RAII types and supports host
and Kokkos device views. Public headers are in
[`include/halo`](https://github.com/NOAA-EMC/HELM/tree/develop/libs/halo/include/halo);
the project's [API overview](https://github.com/NOAA-EMC/HELM/blob/develop/libs/halo/README.md)
and [thread-safety guide](https://github.com/NOAA-EMC/HELM/blob/develop/libs/halo/docs/thread_safety.md)
provide additional operational detail.

## MPI environment and communicators

Initialize MPI with `MPI_Init_thread` before calling
`halo::Environment::initialize()`. HALO queries the granted thread level and
GPU-aware MPI support; `thread_support_level()`, `is_thread_multiple()`, and
`is_gpu_aware_mpi()` expose the detected capabilities. The granted level still
sets the application's rules: under `MPI_THREAD_FUNNELED`, for example, HALO's
internal serialization cannot make a call from a worker thread legal.

`halo::Communicator` is a move-only owner for communicators it creates. Keep a
communicator alive while plans, requests, or asynchronous handles depend on it,
and destroy those objects before `MPI_Finalize`. Predefined communicators such
as `MPI_COMM_WORLD` are not owned by HALO.

## Structured_Halo_Plan

`Structured_Halo_Plan<Rank>` supports ranks one through four. Construct it
once with the field's total extents (including ghost zones), neighbor ranks,
per-dimension halo widths, and a communicator reference. Reuse the plan across
steps when topology, extents, and halo widths remain fixed.

Neighbor ranks are ordered by dimension: entries `2*d` and `2*d+1` represent
the low and high face of dimension `d`. A negative rank or `MPI_PROC_NULL`
represents a missing neighbor. Send regions are the interior cells next to a
face; receive regions are the corresponding ghost cells. The communicator
must outlive the plan. The plan is move-only.

## Exchange interfaces

| Interface | Completion and use |
| --- | --- |
| `exchange_structured_blocking(plan, view)` | Packs, exchanges and unpacks before returning |
| `exchange_structured_async(plan, view)` | Returns a handle; call `wait()` before consuming updated ghost cells |
| `exchange_neighbor_collective(plan, view)` | Uses a graph-neighbor collective for a compatible symmetric topology; otherwise follows the documented fallback path |
| `Persistent_Halo_Handle(plan, view)` | Binds persistent requests to the plan and a stable view for repeated exchanges |

An asynchronous exchange holds work and view references until completion. Keep
the view, its allocation, and the plan alive until `handle.wait()` returns. In
that interval, interior computation can overlap communication; do not write
the ghost regions that completion will unpack, and do not read them expecting
the new neighbor values. Persistent handles bind to the view passed at
construction; they are move-only and should be reused only with that storage.

```cpp
auto exchange = halo::exchange_structured_async(plan, field);
compute_interior(field);   // reads/writes data independent of ghost cells
exchange.wait();           // received data is now unpacked
compute_boundary(field);   // may now consume the new halo values
```

The exchange transports data; it does not define the model's stencil, boundary
condition, or which owned points are independent of halo values. Those regions
depend on the application stencil and halo width.

## Thread and device behavior

HALO guards MPI calls. When MPI grants `MPI_THREAD_MULTIPLE`, independent
exchanges may run concurrently subject to distinct plans/views and MPI's own
rules. At lower thread levels, HALO serializes its MPI call sequences, but the
application must still obey MPI's thread identity restrictions. Concurrent
calls under `MPI_THREAD_SERIALIZED` will serialize and can add contention.

Kokkos memory-space dispatch selects device-aware or host-staged transfers
according to the build and runtime capability. Do not infer GPU-direct support
solely from a device pointer; check `is_gpu_aware_mpi()` and the configured
build. Staging keeps communication valid when direct device communication is
unavailable, with an additional copy cost.

## Diagnostics and build

The optional diagnostics callback reports exchange information such as elapsed
time, bytes, and neighbor counts. Set the callback before exchanges begin;
changing it concurrently with callback emission is not safe. HALO requires MPI
C++ and Kokkos and exports `HELM::HALO`. `HALO_GPU_AWARE_MPI`,
`HALO_BUILD_FORTRAN`, and `HALO_BUILD_TESTING` control optional behavior. See
the [CMake definition](https://github.com/NOAA-EMC/HELM/blob/develop/libs/halo/CMakeLists.txt).
