---
type: reference
category: reference
tags: [helm, amio]
---

# AMIO: AMIO C and Fortran API reference

[Library overview](../libraries/amio.md) · [All libraries](../README.md)

AMIO's exported C declarations are in
[`amio/amio.h`](https://github.com/NOAA-EMC/HELM/blob/develop/libs/amio/include/amio/amio.h);
error constants and `amio_strerror` are provided by
[`amio_errors.h`](https://github.com/NOAA-EMC/HELM/tree/develop/libs/amio/include/amio).
The Fortran wrapper is documented in the
[Fortran guide](https://github.com/NOAA-EMC/HELM/blob/develop/libs/amio/docs/site/user-guide/fortran-api.md).

## Lifecycle calls

| Call | Purpose and ownership |
| --- | --- |
| `amio_init(path, &core)` | Parse a manifest and create a core handle |
| `amio_open_dataset(core, path, mode, &dataset)` | Open a dataset using its configuration |
| `amio_write(dataset, name, data, dtype, shape, &io)` | Copy host data into staging and enqueue a write |
| `amio_read(dataset, name, timestep, bbox, &view)` | Read into a staged view |
| `amio_wait(io, timeout_ms)` | Wait for one operation; zero means no timeout |
| `amio_flush(dataset, timeout_ms)` | Wait for pending dataset writes |
| `amio_close_dataset(dataset)` | Close and release dataset resources |
| `amio_finalize(core)` | Stop workers and release core resources |

Check every returned `amio_status_t` against `AMIO_OK`. A successful
`amio_write` makes its input host buffer reusable because AMIO stages a copy;
it does not mean the file write has completed.

### Opaque handle lifetimes

| Handle | Created by | Released by | Rule |
| --- | --- | --- | --- |
| `amio_core_handle` | `amio_init` | `amio_finalize` | Close all datasets before finalizing |
| `amio_dataset_handle` | `amio_open_dataset` | `amio_close_dataset` | Open in read or write mode for its configured dataset |
| `amio_io_handle` | `amio_read` / `amio_write` | Completion or error | Pass to `amio_wait` if completion of this operation matters |
| `amio_view_handle` | `amio_read` | `amio_release_view` | Data pointer is valid only while the view is retained |

Handles are opaque values; do not dereference or reuse a released handle.
`amio_close_dataset` flushes pending writes, but explicitly checking `amio_flush`
or each relevant I/O handle gives the caller a place to report completion errors.

## Read views

After `amio_read`, use `amio_view_data`, `amio_view_shape`, and
`amio_view_dtype` to inspect a view. The data pointer remains valid until
`amio_release_view`. Release outstanding views before closing their dataset.
Do not retain the pointer after release.

## Shapes and element types

`amio_shape_t` identifies rank, extents, and optional strides. Zero strides
denote contiguous storage where documented by the API. Make the number of
elements and the declared shape agree with the supplied buffer. Consult the
header for supported ranks, bounds-box semantics, dtype enumerators and exact
function signatures.

The public API's shape rank is one through seven and each extent must be
positive. The supported scalar dtype tags cover signed and unsigned 8-, 16-,
32-, and 64-bit integers plus 32- and 64-bit floating point. `amio_bbox_t`
limits a read to a requested subregion; pass `NULL` to read the full variable.
The bbox indexes and strides must be compatible with that variable's rank.

## Completion and error results

| Result | Meaning and response |
| --- | --- |
| `AMIO_OK` | Call completed or operation was accepted successfully |
| `AMIO_ERR_TIMEOUT` | Wait/flush deadline expired; operation may still be in progress |
| `AMIO_ERR_BACKEND_FAILURE` | Driver reported an I/O failure; capture it before declaring success |
| `AMIO_ERR_STAGING_BACKPRESSURE` | Bounded staging pool cannot accept the request within configured patience |

Use `amio_strerror(status)` to format diagnostics. A timeout is not equivalent
to a failed or cancelled write; follow the handle's documented lifecycle and
retry policy before releasing related resources.

## Backends and manifest ownership

The backend and output path are selected by the manifest. The compiled driver
set depends on discovered dependencies; merely naming a backend does not add a
missing driver to the build. The manifest also controls staging capacity,
worker concurrency, read prefetch and driver-specific settings. Keep a copy of
the effective manifest with run metadata so a dataset can be interpreted later.

AMIO's C API has no C++ types in its boundary. The Fortran module wraps those
same calls through `iso_c_binding`; use the exported Fortran target rather than
manually duplicating handle representations.

## Build targets and options

CMake targets include `AMIO::amio_core`, `AMIO::amio_fortran`, and
backend driver targets. Options include `AMIO_BUILD_TESTING`,
`AMIO_BUILD_PBT_ONLY`, `AMIO_BUILD_EXAMPLES`, `AMIO_BUILD_DOCS`, and
`AMIO_FORCE_NCZARR`. Dependencies and defaults are maintained in
[AMIO's CMake file](https://github.com/NOAA-EMC/HELM/blob/develop/libs/amio/CMakeLists.txt).

For lifecycle examples see [the tutorial](../tutorials/amio.md); for manifest
semantics see [configuration](https://github.com/NOAA-EMC/HELM/blob/develop/libs/amio/docs/site/user-guide/configuration.md).
