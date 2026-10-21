---
type: howto
category: how_to
tags: [helm, amio]
---

# AMIO: Build and integrate a C writer

[Library overview](../libraries/amio.md) · [All libraries](../README.md)

This recipe builds AMIO's maintained NetCDF-4 C example and shows how a
downstream CMake project links against the installed API.

## Prerequisites

Install AMIO's required CONF, HALO, LOGS, NetCDF-4, MPI and Fortran toolchain
dependencies first. The AMIO configure step uses `find_package` for its
required sibling packages; put their installation prefixes on
`CMAKE_PREFIX_PATH`. See the [installation guide](https://github.com/NOAA-EMC/HELM/blob/develop/libs/amio/docs/site/getting-started/installation.md).

## Build the maintained example

From the HELM root, configure AMIO and turn on its examples:

~~~bash
cmake -S libs/amio -B libs/amio/build   -DCMAKE_PREFIX_PATH="/path/to/dependency-prefix"   -DAMIO_BUILD_EXAMPLES=ON
cmake --build libs/amio/build --target example_netcdf4_write_c --parallel
~~~

Replace the prefix with the actual install location. The example expects its
manifest at `examples/manifests/netcdf4_manifest.yaml` relative to its working
directory; use the example's configured working directory or copy the manifest
to the directory from which you launch it.

The program reports the stages of initialization, open, write, flush, close
and finalization. It writes `temperature` to the path in the manifest.

## Link your own CMake target

After installing AMIO, add it to a consumer project:

~~~cmake
find_package(AMIO REQUIRED)
add_executable(model_io writer.c)
target_link_libraries(model_io PRIVATE AMIO::amio_core)
~~~

Link through the exported target so AMIO's include paths and transitive
dependencies are carried through. For Fortran, use `AMIO::amio_fortran`.

## Keep the lifecycle correct

Check every `amio_status_t` result. After `amio_write` succeeds, the caller
may reuse its input buffer because AMIO has copied it into staging, but backend
completion still requires `amio_wait` or `amio_flush`. Release read views
before closing the dataset. Close datasets before finalizing the core.

For manifest fields, file formats, selective reads, and error handling, continue
to the [C API guide](https://github.com/NOAA-EMC/HELM/blob/develop/libs/amio/docs/site/user-guide/c-api.md),
[configuration reference](https://github.com/NOAA-EMC/HELM/blob/develop/libs/amio/docs/site/user-guide/configuration.md),
and [model integration guide](https://github.com/NOAA-EMC/HELM/blob/develop/libs/amio/docs/site/user-guide/model-integration.md).
