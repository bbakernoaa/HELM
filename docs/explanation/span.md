---
type: explanation
category: explanation
tags: [helm, span]
---

# SPAN: Why a view is not an allocation

[Library overview](../libraries/span.md) · [All libraries](../README.md)

SPAN carries a pointer, extents and coherency metadata. It does not own the
storage behind its pointer. This is what lets it wrap memory allocated by a
Fortran model without copying the array or changing who frees it.

Zero-copy has a trade-off: callers must preserve the allocation lifetime and
report correct extents. A view cannot verify that the pointer really addresses
enough elements. It also cannot make host memory accessible to a GPU merely by
wrapping the pointer.

## Coherency is a caller-maintained state machine

When both host and device pointers are registered, a write to one side makes the
other stale. The caller marks which side changed and requests synchronization
before reading stale data. Synchronization uses Kokkos deep_copy and returns the
state to clean when a transfer occurs.

If only one pointer is present, a sync request is a no-op. This is deliberate:
SPAN does not invent missing storage or select an allocation policy. Asynchronous
work must complete before the owning allocation is released.

| Last write | Mark operation | Next consumer | Required action |
| --- | --- | --- | --- |
| Host code | `mark_host_dirty()` | Device kernel | `sync_for_device()` before launch |
| Device kernel | `mark_device_dirty()` | Host code | `sync_for_host()` after kernel completion |
| Either side | No mark | Other side | SPAN cannot infer the changed data; the caller risks a stale read |

The dirty state is a statement from the caller, not automatic observation of
stores through the raw pointer. Mark the side after a write and synchronize only
when a later reader needs the other copy.

## Triple buffering protects producer/consumer overlap

A triple buffer allows a producer, consumer and in-flight I/O operation to use
separate roles so a producer does not overwrite data still being written. The
attachment is non-owning too, so the buffer lifetime must cover the view's use.
This complements AMIO staging, which copies data into AMIO-owned buffers.
