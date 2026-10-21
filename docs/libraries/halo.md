---
type: reference
category: reference
tags: [helm, halo, navigation]
---

# HALO — Hardware-Abstracted Link Operations

HALO wraps MPI communicators, requests and windows with RAII types, and provides
reusable halo exchange plans. Kokkos handles packing and unpacking. Depending on
build and runtime support, device data travels directly or through host staging.

A `Structured_Halo_Plan<Rank>` records total local extents including ghost
cells, one neighbor per face, halo widths, and precomputed send/receive regions.
Face order is low then high for each dimension. Use `-1` or
`MPI_PROC_NULL` at a physical boundary. Reuse a plan for views with the same
shape.

Blocking exchanges return after transfer completes. An asynchronous exchange
returns a handle. While it is in flight, compute only the interior that does
not read incoming ghost cells; wait before computing boundary stencils. Keep the
communicator, plan, and view alive through completion.

The exchange describes neighboring ranks and memory regions, not the physical
boundary condition. Faces with no neighbor require application code to set
their ghost values. Multi-dimensional corner regions may need multiple ordered
exchanges or another stencil-specific policy.

Initialize HALO after MPI initialization before querying its MPI thread support.
Complete exchanges before destroying referenced objects or finalizing MPI.
`HALO_GPU_AWARE_MPI` defaults off; turning it on requires compatible MPI
support. `HALO_BUILD_FORTRAN` and `HALO_BUILD_TESTING` control optional
interfaces and tests. The exported target is `HELM::HALO`; MPI C++ and Kokkos
are required.

See the [two-rank tutorial](../tutorials/halo.md), [overlap recipe](../how-to/halo.md),
[types and options](../reference/halo.md), and
[plans and staging](../explanation/halo.md).
