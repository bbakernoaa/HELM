---
type: reference
category: reference
tags: [helm, span, navigation]
---

# SPAN — Shared Pointer & Array Network

SPAN's `span::FieldView<T, Rank>` wraps caller-owned host and/or device
pointers with extents, mdspan access, Kokkos adapters and coherency state.
It is a metadata view: construction neither allocates nor copies field data.

Host mdspan access uses column-major `layout_left`, matching Fortran array
layout. `to_kokkos_view` and `to_kokkos_device_view` create flat unmanaged
views over registered pointers. The backing allocation must outlive each view
and be valid for the execution space that uses it.

After host writes call `mark_host_dirty`; after device writes call
`mark_device_dirty`. Synchronization copies between host and device only when
both pointers are present and the corresponding side is dirty. A one-pointer
view has nothing to synchronize. Extents are caller-supplied and must describe
the allocation accurately.

For a dual-pointer view, the caller is responsible for three actions: keep
both allocations alive, mark each side after writing it, and synchronize before
reading from a stale side. SPAN tracks those declarations but cannot detect raw
pointer writes or verify the real allocation length.

A FieldView can attach a non-owning TripleBuffer; that buffer must also outlive
its use. SPAN exports `HELM::SPAN`, a Kokkos-backed interface target.
`SPAN_BUILD_C_API` and `SPAN_BUILD_TESTING` enable optional targets.

Note that BLEND currently has a separate rank-one `span::FieldView` alias.
Check header compatibility before combining BLEND and SPAN in one translation
unit.

Start with [wrapping an array](../tutorials/span.md), then
[expose storage to Kokkos](../how-to/span.md), consult
[state/API details](../reference/span.md), and read
[the ownership explanation](../explanation/span.md).
