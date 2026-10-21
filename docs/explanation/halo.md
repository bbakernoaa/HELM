---
type: explanation
category: explanation
tags: [helm, halo]
---

# HALO: Why halo plans and completion points matter

[Library overview](../libraries/halo.md) · [All libraries](../README.md)

A halo exchange moves values between the owned interior of one rank and the
ghost regions of its neighbors. The plan records this geometry once, so each
timestep does not need to reconstruct the same faces and slices.

## Logical faces, physical memory

For each dimension the plan distinguishes the interior slice to send from the
ghost slice to receive. Other axes span the full local extent as defined by the
plan. The logical ranges are independent of Kokkos layout; layout influences
how pack/unpack work maps onto memory.

Physical boundary faces have no neighbor. Those ghost values need an application
boundary condition; MPI_PROC_NULL does not invent a physical value. Multi-axis
corner ghosts also need a strategy appropriate to the stencil and exchange
ordering. A face exchange alone should not be assumed to fill every corner.

## Asynchrony changes when data is valid

Starting an asynchronous exchange means communication is in flight. It does
not mean receive halos are already usable. Interior work may overlap only if it
does not read those incoming regions. The handle's wait is the synchronization
point before dependent boundary work.

| Stage | Safe data to use |
| --- | --- |
| Before starting exchange | Owned interior; outgoing regions must contain current values |
| While exchange is in flight | Interior work whose stencil does not touch incoming ghosts |
| After the handle completes | Received ghost regions and boundary work that depends on them |

The exchange only transfers values. It does not choose the physical boundary
condition, refill ghosts at a domain edge, or guarantee corner values for a
multi-dimensional stencil.

GPU-aware MPI is a property of the MPI implementation and runtime configuration.
When it is unavailable, host staging can move data between device memory and
MPI. A Kokkos GPU backend alone does not prove that MPI accepts device pointers.

Thread support also matters: MPI calls from multiple threads must follow the
thread level negotiated by the application. Consult the
[thread-safety guide](https://github.com/NOAA-EMC/HELM/blob/develop/libs/halo/docs/thread_safety.md).
