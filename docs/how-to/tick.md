---
type: howto
category: how_to
tags: [helm, tick]
---

# TICK: Enable the TICK Fortran module

[Library overview](../libraries/tick.md) · [All libraries](../README.md)

The Fortran module is optional. It wraps the C API and is useful when gradually
introducing TICK into an existing Fortran model.

## Configure and build

From the repository root with a Fortran compiler available:

~~~bash
cmake -S libs/tick -B libs/tick/build -DTICK_BUILD_FORTRAN=ON
cmake --build libs/tick/build --parallel
~~~

CMake compiles `tick_mod.f90` and publishes the generated module directory.
When adding TICK as a subdirectory, link the consumer to
`HELM::TICK_Fortran`; this target links the C bridge and core library.

## Verify the module

Configure with tests enabled as well:

~~~bash
cmake -S libs/tick -B libs/tick/build   -DTICK_BUILD_FORTRAN=ON -DTICK_BUILD_TESTING=ON
cmake --build libs/tick/build --parallel
ctest --test-dir libs/tick/build --output-on-failure
~~~

The Fortran tests exercise the module integration. Do not copy generated
`.mod` files between compiler versions; module files are compiler-specific.

## Pick the resolution consciously

`TICK_RESOLUTION` selects `SECONDS` or `NANOSECONDS` in the configured
build. C++ core types represent integer nanoseconds; review C/Fortran boundary
conversions when changing resolution. Keep all consumers consistent with the
same build configuration.

For a pure C++ consumer link `HELM::TICK`; for the C API link
`HELM::TICK_C`. See the
[TICK CMake definition](https://github.com/NOAA-EMC/HELM/blob/develop/libs/tick/CMakeLists.txt).
