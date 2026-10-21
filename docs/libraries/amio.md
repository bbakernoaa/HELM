---
type: reference
category: reference
tags: [helm, amio, navigation]
---

# AMIO — Asynchronous Multidimensional Input/Output

AMIO gives C and Fortran model code one API for multidimensional scientific
fields. Its drivers support NetCDF-4, Zarr, and GRIB2 when their build
dependencies are available.

**Choose AMIO** when a model needs backend-managed I/O, prefetched reads,
background writes, or format changes. AMIO handles storage; it does not schedule
model tasks or transform grids.

## Write lifecycle

Initialize a core from a manifest, open a dataset, describe each array's rank,
extents, and element type, then submit it with `amio_write`. A successful write
copies host data into AMIO's staging pool before returning. The backend may still
be writing, so wait on the I/O handle or flush the dataset before depending on
the file. Close the dataset, then finalize the core.

The staging pool bounds the amount of buffered data. Its buffer count and
capacity affect memory use and throughput. Read views point into AMIO-managed
staging memory; release each view when finished.

| Operation | Caller can reuse the source? | When is the result complete? |
| --- | --- | --- |
| Submit a write | After a successful call has staged the host data | Wait on its handle, flush, or close before relying on the file |
| Read into a view | Keep the view while consuming its data | Release the view to return its staging buffer |

This ownership boundary is useful when storage latency varies, but it means the
model must check both enqueue and completion errors. A successful enqueue alone
does not guarantee that a backend later finishes successfully.

## Interfaces and dependencies

The public C99 interface is `amio/amio.h`; `amio_mod` wraps it for Fortran.
CMake exports `AMIO::amio_core` and `AMIO::amio_fortran`. AMIO requires
installed CONF, HALO, and LOGS packages; NetCDF, MPI, TensorStore/NCZarr, and
GRIB2 libraries enable backend capabilities.

Options include `AMIO_BUILD_TESTING`, `AMIO_BUILD_PBT_ONLY`,
`AMIO_BUILD_EXAMPLES`, `AMIO_BUILD_DOCS`, and `AMIO_FORCE_NCZARR`.
See the [CMake configuration](https://github.com/NOAA-EMC/HELM/blob/develop/libs/amio/CMakeLists.txt).

Start with the [write tutorial](../tutorials/amio.md), then use
[backend integration recipes](../how-to/amio.md), consult
[API and manifest details](../reference/amio.md), and read
[buffer ownership and asynchronous behavior](../explanation/amio.md).
