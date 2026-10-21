---
type: howto
category: how_to
tags: [helm, halo]
---

# HALO: Overlap computation with halo communication

[Library overview](../libraries/halo.md) · [All libraries](../README.md)

Start a structured exchange before computing the part of a stencil that depends
only on locally owned values. Wait before reading ghost cells received from
neighbors.

## 1. Build a reusable plan

Choose the total view extents including halos, the halo width for every axis,
and one neighbor rank for each face. For a two-dimensional rank, face order is
low/high for dimension 0, then low/high for dimension 1. Use `-1` on physical
boundaries. The plan and its referenced communicator must remain alive together.

## 2. Initiate exchange and do independent work

~~~cpp
auto exchange = halo::exchange_structured_async(plan, field);
compute_interior(field, halo_width); // Must not read incoming ghost cells.
exchange.wait();
compute_boundary(field, halo_width); // Ghost cells are now available.
~~~

Choose the interior bounds from the actual stencil radius and the allocation's
halo width. For a stencil with radius `h`, each boundary value whose stencil
touches a ghost cell must wait. Do not copy bounds blindly from an example with
a different layout or stencil.

## 3. Keep data alive and test safely

The view and plan must remain valid until `wait` completes. If the code can
throw or exit early after starting the transfer, ensure the handle is completed
before destroying its referenced storage. Verify correctness by initializing
owned cells with rank- and index-specific values, exchanging, then checking
each receive region.

Use the full [overlap example](https://github.com/NOAA-EMC/HELM/blob/develop/libs/halo/docs/overlap_pattern.md)
and read [thread-safety requirements](https://github.com/NOAA-EMC/HELM/blob/develop/libs/halo/docs/thread_safety.md)
before issuing MPI calls from multiple threads. GPU-aware MPI is a separate
capability from selecting a GPU Kokkos backend.
