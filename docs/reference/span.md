---
type: reference
category: reference
tags: [helm, span]
---

# SPAN: field-view and buffer API reference

[Library overview](../libraries/span.md) · [Tutorial](../tutorials/span.md) ·
[How-to](../how-to/span.md) · [All libraries](../README.md)

Include `<span/span.hpp>` for the C++ interface or
[`field_view.hpp`](https://github.com/NOAA-EMC/HELM/blob/develop/libs/span/include/span/field_view.hpp)
for `span::FieldView<T, Rank>`. SPAN wraps caller-owned host and/or device
memory; it does not allocate field storage or take ownership of the pointers.

## FieldView construction and access

| Construction | Meaning |
| --- | --- |
| `FieldView(host_ptr, extents)` | Host-only memory |
| `FieldView(nullptr, device_ptr, extents)` | Device-only memory |
| `FieldView(host_ptr, device_ptr, extents)` | Dual-pointer host/device copies; either pointer may be null |

An empty default-constructed view is invalid. Valid construction requires
positive extents and at least one non-null pointer. The `extents_type` is a
fixed-size array with one extent per `Rank`.

Metadata methods include `size()`, `extent(dim)`, `extents()`, `rank()`,
`valid()`, `has_host_ptr()`, `has_device_ptr()`, `memory_space()`, and
`coherency_state()`. `extent(dim)` throws `std::out_of_range` for an invalid
dimension. `view()` returns a host `std::mdspan` with `layout_left` and throws
if the view has no host pointer; it follows column-major/Fortran indexing.

Kokkos adapters are unmanaged and flat, with `size()` elements. They share the
original allocation and do not change coherency state. Keep the original
allocation alive for every adapter and kernel that uses it. Use
`to_kokkos_device_view()` only when a device pointer is present; its absence is
reported as `std::invalid_argument`.

## Host/device coherency

| Operation | State transition and effect |
| --- | --- |
| `mark_host_dirty()` | Mark host as newer; device copy is stale |
| `mark_device_dirty()` | Mark device as newer; host copy is stale |
| `sync_for_device()` | If host is dirty and both pointers exist, copy host to device and mark clean |
| `sync_for_host()` | If device is dirty and both pointers exist, copy device to host and mark clean |

Mark the side after writing through a raw pointer or Kokkos adapter. At most
one side is considered dirty. Synchronization is a no-op for a one-pointer
view, so it cannot migrate data between unrelated allocations or recover an
unavailable copy. The caller is responsible for ordering device kernels before
requesting a copy and for not reading the stale side before synchronization.

## TripleBuffer

`span::TripleBuffer<T>` rotates three externally allocated, distinct buffers
through Write, Read, and IO roles. Construction requires non-null pointers and
a positive element count. `write_ptr()`, `read_ptr()`, and `io_ptr()` expose the
current track pointers; `size()` returns the element count.

After `swap_buffers_for_amio()` succeeds, the old Write becomes the latest Read,
the old Read becomes IO, and the old IO becomes the new Write. The operation
returns `false` without rotating while IO is locked. Once the I/O consumer
finishes using `io_ptr()`, it must call `release_io()` before the next swap.
The lock state is protected by a mutex; the underlying data pointers are not
owned or copied. Synchronize access to the actual buffer contents according to
the model/I/O handoff, and keep all three allocations alive while the buffer is
in use. `FieldView::attach_triple_buffer()` stores a non-owning pointer, so the
`TripleBuffer` must outlive that attachment.

## C constants and build

[`span_constants.h`](https://github.com/NOAA-EMC/HELM/blob/develop/libs/span/include/span/span_constants.h)
defines memory-space tokens, error constants, and `HELM_SPAN_MAX_RANK` for the
C/Fortran boundary. The C++ template layer is header-only and exports
`HELM::SPAN`; Kokkos is its only required third-party dependency.
`SPAN_BUILD_C_API` optionally builds `HELM::SPAN_CAPI`, while
`SPAN_BUILD_TESTING` enables GTest and RapidCheck. See
the [CMake definition](https://github.com/NOAA-EMC/HELM/blob/develop/libs/span/CMakeLists.txt).
