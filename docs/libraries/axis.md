---
type: reference
category: reference
tags: [helm, axis, navigation]
---

# AXIS — Arbitrary eXgrid Interpolation Solver

AXIS builds spatial interpolation weights between source and destination meshes
and applies those weights to field data. The engine is C++ and Kokkos based;
the repository also includes Fortran, Python, xarray/Dask and command-line
interfaces, depending on build configuration.

Choose AXIS when fields on one horizontal mesh need mapping to another. Select
a method based on the numerical property required: bilinear interpolation or
first- or second-order conservative remapping. Verify the installed AXIS
version's documented method set before planning other interpolation schemes.

## Workflow

Describe both meshes, including coordinates and cell geometry; configure the
interpolation method and policies; generate weights; prepare the sparse matrix;
then apply it to fields with matching source extent. Verify a numerical invariant
suited to the chosen method. Weight generation depends on geometry and settings,
so reuse the matrix for compatible fields and regenerate it if those inputs change.

A constant-field check is useful, but does not prove area conservation or
accuracy for every field.

| Field meaning | Method family to evaluate | Check beyond “it ran” |
| --- | --- | --- |
| Smooth point-like field | Bilinear | Compare with an analytic or trusted solution |
| Cell-average or extensive quantity | Conservative remapping | Compare area-weighted integrals and coverage |

AXIS does not list a categorical nearest-neighbor method in the documented
`RegridMethod` enum. Do not use bilinear interpolation for labels or other
discrete categories; use a library/version that explicitly supports the
required categorical remap.

These are starting points, not automatic scientific choices. Coordinate
conventions, masks, grid geometry, and acceptable error determine the method.

## Build and interfaces

The C++ target is `HELM::AXIS`. Kokkos, MPI, KokkosKernels and ArborX are
required; CMake can fetch selected dependencies. PROJ and NetCDF are optional.
Fortran and Python bindings are opt-in.

Important options include `AXIS_ENABLE_PROJ`, `AXIS_ENABLE_NETCDF`,
`AXIS_BUILD_TESTING`, `AXIS_BUILD_FORTRAN`, `AXIS_BUILD_PYTHON`,
`AXIS_BUILD_EXAMPLES`, and `AXIS_BUILD_BENCHMARKS`. Refer to the
[AXIS build definition](https://github.com/NOAA-EMC/HELM/blob/develop/libs/axis/CMakeLists.txt)
and [detailed guides](https://github.com/NOAA-EMC/HELM/tree/develop/libs/axis/docs)
for method assumptions, masking, caching and performance.

Use the [C++ user guide](../tutorials/axis.md) or
[Python user guide](../tutorials/axis-python.md) for a complete workflow. Then
[reuse weights](../how-to/axis.md), review the detailed
[API reference](../reference/axis.md), and read
[why geometry and field application are separate](../explanation/axis.md).
