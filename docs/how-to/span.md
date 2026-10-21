---
type: howto
category: how_to
tags: [helm, span]
---

# SPAN: Wrap existing storage for Kokkos access

[Library overview](../libraries/span.md) · [All libraries](../README.md)

Use a SPAN FieldView when another component owns the memory and you need a
shape-aware C++ view without transferring ownership.

## Host memory

~~~cpp
double* model_field = get_fortran_field_pointer();
span::FieldView<double, 2> field(model_field, {nx, ny});
auto md = field.view();
~~~

The pointer and extents must describe valid contiguous memory. The mdspan uses
column-major `layout_left`, matching Fortran ordering. The FieldView does not
extend the lifetime of the Fortran allocation.

## Kokkos host and device views

For a host pointer, use `to_kokkos_view()`; for a registered device pointer,
use `to_kokkos_device_view()`. These are flat unmanaged views over the same
allocations. A rank-two field therefore has `size() == nx * ny`, but the
adapter's rank is one. Use the extents or mdspan when dimensional indexing
matters.

Do not use a host view in a device kernel or a device pointer on the host.
The pointer's memory space and Kokkos execution space must agree.

## Synchronize two registered copies

When both host and device pointers are present, mark the side modified after
writes. Then call `sync_for_device()` after host changes or
`sync_for_host()` after device changes. Synchronization is a no-op for a
single-pointer view. It does not allocate the missing copy.

## Check lifetime and shape

Keep the original allocation alive until kernels and asynchronous consumers
finish. Keep any attached TripleBuffer alive too. SPAN cannot verify the actual
allocation length behind a raw pointer; the caller must provide correct extents.
See [FieldView's public definition](https://github.com/NOAA-EMC/HELM/blob/develop/libs/span/include/span/field_view.hpp).
