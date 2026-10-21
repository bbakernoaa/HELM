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

Choose AXIS when fields on one horizontal mesh need mapping to another. AXIS
provides four interpolation/reconstruction methods and two area-overlap methods:
bilinear, nearest-neighbor, bicubic, patch, first-order conservative, and
second-order conservative. Their assumptions differ, so choose from the field's
meaning, geometry, and desired invariant rather than treating the method as a
performance switch.

## Workflow

Describe both meshes, including coordinates and cell geometry; configure the
interpolation method and policies; generate weights; prepare the sparse matrix;
then apply it to fields with matching source extent. Verify a numerical invariant
suited to the chosen method. Weight generation depends on geometry and settings,
so reuse the matrix for compatible fields and regenerate it if those inputs change.

A constant-field check is useful, but does not prove area conservation or
accuracy for every field.

| Field meaning / goal | Starting method | What it does and what to check |
| --- | --- | --- |
| Smooth point-like field | Bilinear | Interpolates from a local source neighborhood; compare with an analytic or trusted solution. |
| Discrete labels or nearest-sample semantics | Nearest-neighbor | Copies one source-centroid value; check distance and coverage, especially near boundaries. |
| Smooth field where a wider stencil is acceptable | Bicubic | Fits a local cubic polynomial to nearby centroids; check overshoot and behavior on irregular or seam-crossing grids. |
| Smooth field on an irregular mesh where local polynomial recovery is useful | Patch | Fits a least-squares quadratic over a local patch; check conditioning, extrema, and spatial error. |
| Cell means, densities, or extensive totals whose area integral matters | First-order conservative | Integrates source/destination cell overlap; compare area-weighted totals over the same covered region. |
| Smooth cell means where lower diffusion is useful | Second-order conservative | Integrates a linearly reconstructed source field over overlaps; check conservation and extrema, with and without the limiter. |

Nearest-neighbor is appropriate for categorical values when nearest-centroid
assignment matches the intended semantics. It is not area conservative. The
higher-order interpolation methods can overshoot; inspect extrema before
accepting results.

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
