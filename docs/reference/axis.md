---
type: reference
category: reference
tags: [helm, axis]
---

# AXIS: C++, Python and build API reference

[Library overview](../libraries/axis.md) · [C++ user guide](../tutorials/axis.md) ·
[Python user guide](../tutorials/axis-python.md) · [All libraries](../README.md)

This page summarizes the public AXIS workflow and the contracts that matter
when calling it. The public C++ declarations are under
[`include/axis`](https://github.com/NOAA-EMC/HELM/tree/develop/libs/axis/include/axis);
the [source guide](https://github.com/NOAA-EMC/HELM/tree/develop/libs/axis/docs)
has worked examples. If a signature differs between a downstream package and
the `develop` branch, follow the headers installed with that package.

## API map

| Layer | Main API | Responsibility |
| --- | --- | --- |
| Geometry | `axis::topology::GridDescriptor`, `MeshFactory`, `UnstructuredMesh` | Describe and validate source/destination cells |
| Grid generation | `NamedGridRegistry`, `RuleGenerator`, `StructuredGrid` | Create supported grids without file I/O |
| Configuration | `axis::solver::RegridConfig` | Select method, normalization, unmapped action and limiter |
| Weight generation | `axis::solver::WeightGenerator` | Create the sparse source-to-destination operator |
| Matrix | `axis::solver::InterpolationMatrix` | Hold COO/CSR weights, fractions, areas and diagnostics |
| Field application | `axis::solver::apply`, `batch_apply` | Apply one or many fields to a mesh pair |
| Utilities | `WeightCache`, `HaloPattern`, `conservation` | Persist weights, describe remote data needs, assess results |

## Geometry API

### Supported construction paths

| API | Use it when | Important input |
| --- | --- | --- |
| `MeshFactory::from_descriptor(descriptor)` | Geometry comes from a model or file reader | Coordinates, offsets, connectivity and coordinate system |
| `NamedGridRegistry::generate(name)` | A registered standard grid matches the case | Grid identifier such as `O48` or `N128` |
| `RuleGenerator::generate(spec)` | A supported grid can be described by a rule | Grid type and rule parameter |
| `StructuredGrid(...).to_unstructured()` | A regular grid can be generated from dimensions and spacing | Cell counts and longitude/latitude origin and increments |

The `GridDescriptor` connectivity uses an offset array: cell `i` occupies the
vertex-index range between consecutive offsets. Coordinate units must match
`CoordSystem` (`SphericalDeg`, `SphericalRad`, or `Cartesian3D`). For spherical
polygons, vertex order and seam/pole handling affect geometry and therefore
the weights. Validate descriptor lengths and indices before weight generation.

Meshes expose cell count, vertex count, cell area, centroids, vertices and
optional per-cell masks. `MeshFactory` and grid generators are parameterized by
Kokkos memory space; source and destination meshes should use compatible
spaces for the selected generator and later apply calls.

Header references:
[mesh factory](https://github.com/NOAA-EMC/HELM/blob/develop/libs/axis/include/axis/topology/mesh_factory.hpp),
[named grids](https://github.com/NOAA-EMC/HELM/blob/develop/libs/axis/include/axis/topology/named_grid_registry.hpp),
[mesh type](https://github.com/NOAA-EMC/HELM/blob/develop/libs/axis/include/axis/topology/unstructured_mesh.hpp),
[grid descriptor](https://github.com/NOAA-EMC/HELM/blob/develop/libs/axis/include/axis/ingest/grid_descriptor.hpp).

## Weight-generation API

Create one `RegridConfig`, then pass the source mesh, destination mesh and
configuration to `WeightGenerator::generate`:

```cpp
axis::solver::RegridConfig config;
config.method = axis::solver::InterpolationMethod::Bilinear;
config.unmapped = axis::solver::UnmappedAction::Error;

axis::solver::WeightGenerator generator;
auto matrix = generator.generate(source, destination, config);
```

The six methods implemented by `InterpolationMethod` are listed below. Names
and configuration members are taken from the public C++ header and Python
nanobind parser on `develop`.

| Setting | Values | Contract |
| --- | --- | --- |
| `method` | `Bilinear`, `NearestNeighbor`, `Bicubic`, `Patch`, `Conservative1stOrder`, `Conservative2ndOrder` | Select one of the six operators described below |
| `norm_type` | `DstArea`/`dstarea`, `FracArea`/`fracarea` | Select how conservative overlap weights treat partial destination coverage |
| `line_type` | `GreatCircle`/`great_circle`, `Cartesian`/`cartesian` | Select spherical great-circle or planar geometry for overlap methods |
| `unmapped` | `Ignore`/`ignore`, `Error`/`error` | Leave an uncovered destination row empty or throw during generation |
| `use_limiter` | `true`, `false` | Enable the Barth–Jespersen limiter for second-order conservative reconstruction |

The C++ defaults are bilinear, `DstArea`, `GreatCircle`, `Ignore`, and no
limiter. Set each option that affects your scientific result explicitly.

### Method behavior and normalization

| Method | Algorithm and output behavior | Good fit | Validate with |
| --- | --- | --- | --- |
| `Bilinear` | Locates a source neighborhood and forms local interpolation weights; regular lat/lon grids have an analytic index-arithmetic fast path. General meshes use a local spherical/tangent-plane solve and a fallback when the solve fails. | Smooth point-like fields | Analytic fields, constant reproduction, and seam/polar cases relevant to the grid |
| `NearestNeighbor` | Builds a spatial index over source-cell centroids and assigns each destination centroid the closest source cell with weight 1. Regular grids can use direct index arithmetic; spherical searches use 3-D unit-sphere coordinates. | Categories, flags, or nearest-sample semantics | Category preservation, nearest-distance distribution, and uncovered/boundary behavior |
| `Bicubic` | Queries up to 16 nearby source centroids and computes weights from a local polynomial fit with up to 16 terms; with fewer samples it reduces polynomial order. It is not an area-overlap method. | Smooth fields where a wider stencil is appropriate | Analytic smooth fields, extrema/overshoot, and irregular-grid conditioning |
| `Patch` | Queries a local patch (up to 16 nearby centroids) and fits a six-term quadratic basis `[1, x, y, xy, x², y²]` by least squares, then evaluates that fit at the destination centroid. | Smooth fields on irregular meshes where local recovery is useful | Analytic fields, residuals, extrema, and sensitivity to patch geometry |
| `Conservative1stOrder` | Computes source/destination polygon intersections and weights from overlap area. Regular and rectilinear grids use specialized overlap paths; general grids use spatial candidate search and polygon clipping. | Cell means, densities, and extensive quantities | Area-weighted integral over the same covered domain, coverage fractions, and constant fields |
| `Conservative2ndOrder` | Reconstructs a linear field in each source cell from neighboring-cell gradients, optionally limits the reconstruction, and integrates it over each overlap. | Smooth cell means where first order is too diffusive | Area-weighted integral, smooth-field error, extrema, and limiter-on/off behavior |

The methods do not all share the same geometry path. Conservative methods use
`line_type` to select great-circle or Cartesian overlap geometry. Bilinear has
a dedicated regular-grid path. Nearest-neighbor and polynomial methods select
nearby cell centroids; for global spherical grids, inspect how the coordinate
system and longitude seam affect that neighborhood. Do not infer a method's
accuracy from its name alone: evaluate it on representative grids and fields.

For a destination cell `j`, the documented conservative normalization choices
are:

| `NormType` (`norm_type`) | Weight interpretation | Typical use |
| --- | --- | --- |
| `DstArea` | `overlap_area(i,j) / destination_area(j)` | Normalize by full destination area |
| `FracArea` | `overlap_area(i,j) / (destination_area(j) * destination_coverage(j))` | Normalize over the covered part of a partially covered destination |

These choices differ on partial coverage. Record the setting with analysis
outputs and compare integrals over the same covered domain; a constant-field
test alone is not a substitute for a conservation test.

For a conservative matrix, `DstArea` stores overlap divided by the full
destination area. `FracArea` normalizes by the covered destination area, so a
constant field remains constant on a partially covered destination. The choice
changes the result when coverage is incomplete and must be recorded with the
weights. `Ignore` leaves an uncovered row empty; the C++ apply call therefore
leaves that caller-provided output value unchanged. Initialize output to a
deliberate fill value. `Error` throws during generation when an active
destination is uncovered. A masked destination row is distinct: apply leaves
it untouched.

Header references:
[configuration](https://github.com/NOAA-EMC/HELM/blob/develop/libs/axis/include/axis/solver/regrid_config.hpp) and
[weight generator](https://github.com/NOAA-EMC/HELM/blob/develop/libs/axis/include/axis/solver/weight_generator.hpp).
See the [weight-generation guide](https://github.com/NOAA-EMC/HELM/blob/develop/libs/axis/docs/weight_generation.md)
for method behavior and validation properties.

## InterpolationMatrix and apply

The generated matrix maps a source vector to a destination vector:

| Matrix property | Meaning |
| --- | --- |
| `n_src()` | Required source field length |
| `n_dst()` | Required destination field length |
| `nnz()` | Number of nonzero weights |
| `is_csr()` | Whether row-compressed storage is active |
| `to_csr()` | Convert generated COO entries to CSR for row-based apply |
| `diagnostic_report()` | Inspect degenerate-cell and generation diagnostics |

Generation produces COO storage. `solver::apply(matrix, src, dst)` supports
that form; call `matrix.to_csr()` once before repeated applies when its
conversion cost is justified. The CSR path is row-parallel and avoids COO's
scatter atomics. Use `solver::batch_apply(matrix, src2d, dst2d)` for multiple
variables on the same mesh pair, with shapes `[n_src, n_variables]` and
`[n_dst, n_variables]`.

The apply functions validate leading extents and throw `std::invalid_argument`
when the field sizes do not match the matrix. Source, destination and matrix
memory spaces must be compatible. Apply performs no MPI exchange; use a
`HaloPattern` with HALO or application code to gather remote source values for a
distributed decomposition.

`batch_apply` uses `[cell, variable]` layout. Its source and destination first
extents must match `n_src()` and `n_dst()`, and the variable counts must agree.
The output field must be allocated and initialized when a policy can leave
values unchanged: `Ignore` leaves active but unmapped destinations untouched,
and a destination mask suppresses writes to its rows. With `Error`, generation
reports incomplete coverage. The C++ `UnmappedAction` enum has no `Zero`
member; initialize the output to zero when that fill behavior is required.

### Matrix representation and diagnostics

Newly generated weights use coordinate (COO) entries. `to_csr()` converts them
to compressed sparse rows; call it once when row-based apply will be reused
enough to justify conversion. COO apply uses scatter accumulation, while CSR
apply is destination-row based. Both represent the same operator, though
floating-point accumulation order can differ slightly.

The matrix also carries source/destination area and coverage data used for
conservative checks, and a diagnostic report for degenerate geometry. Treat
those diagnostics as part of weight-generation review: a matrix can be
structurally valid while cells were excluded or destinations only partly
covered. `WeightCache` serializes bytes but does not store a reliable identity
for the original geometry/configuration; maintain that identity separately.

Header references:
[matrix](https://github.com/NOAA-EMC/HELM/blob/develop/libs/axis/include/axis/solver/interpolation_matrix.hpp),
[apply](https://github.com/NOAA-EMC/HELM/blob/develop/libs/axis/include/axis/solver/apply.hpp),
[halo pattern](https://github.com/NOAA-EMC/HELM/blob/develop/libs/axis/include/axis/solver/halo_pattern.hpp).

## Masks, diagnostics and cache

Attach cell masks before generating weights. Zero marks a cell inactive;
nonzero marks it active. Source masks remove contributions. Destination masks
remove rows and `apply` leaves those destination values unchanged. A masked
destination and an active-but-unmapped destination are different cases: the
unmapped policy applies only to the latter.

`WeightCache` serializes a matrix to a caller-owned byte buffer; AXIS does not
choose a filesystem path or manage persistence. The cache format carries
dimensions and a version, but a valid byte stream does not establish that its
source/destination geometry, masks or `RegridConfig` match the current run.
Store those identities alongside the cache and invalidate it whenever any
weight-generation input changes. Deserialization or malformed buffers can
raise `std::runtime_error`.

Header references:
[cache](https://github.com/NOAA-EMC/HELM/blob/develop/libs/axis/include/axis/solver/weight_cache.hpp),
[conservation helpers](https://github.com/NOAA-EMC/HELM/blob/develop/libs/axis/include/axis/solver/conservation.hpp).

## Python module API

Build with `AXIS_BUILD_PYTHON=ON`; the module is imported as `axis`. The
documented high-level objects and calls are:

| Python API | Purpose |
| --- | --- |
| `axis.NamedGridRegistry.generate(name)` | Create a registered grid |
| `axis.MeshFactory.from_descriptor(...)` | Build a mesh from arrays |
| `axis.WeightGenerator.generate(src, dst, config)` | Generate an `InterpolationMatrix` |
| `axis.apply(matrix, src_field)` | Return one destination field |
| `axis.batch_apply(matrix, src_fields)` | Return a batch with destination-cell leading extent |
| `matrix.to_bytes()` / `InterpolationMatrix.from_bytes(blob)` | Serialize and restore weights |

NumPy input is expected to use `float64`. Batch arrays use
`[n_cells, n_variables]`; Fortran-order arrays match the column-major layout
and avoid the conversion that may be needed for C-order inputs. Invalid
arguments commonly surface as `ValueError`, runtime failures as `RuntimeError`,
and Kokkos allocation failures as `MemoryError`. See the
[Python user guide](../tutorials/axis-python.md) for installation and complete
examples.

## Build options and dependencies

| CMake option | Default | Effect |
| --- | --- | --- |
| `AXIS_ENABLE_PROJ` | ON | Enable optional PROJ coordinate transforms when found |
| `AXIS_ENABLE_NETCDF` | ON | Enable optional NetCDF I/O and weight egress when available |
| `AXIS_BUILD_TESTING` | OFF | Build unit and property tests |
| `AXIS_BUILD_FORTRAN` | OFF | Build Fortran interoperability |
| `AXIS_BUILD_PYTHON` | OFF | Build nanobind Python bindings |
| `AXIS_BUILD_EXAMPLES` | OFF | Build examples |
| `AXIS_BUILD_BENCHMARKS` | OFF | Build benchmarks |
| `AXIS_FETCH_KOKKOS` | ON | Fetch Kokkos if no package is found |
| `AXIS_FETCH_KOKKOSKERNELS` | ON | Fetch KokkosKernels if no package is found |

The exported target is `HELM::AXIS`. Kokkos, KokkosKernels, MPI C++, and
ArborX are required; CMake can fetch Kokkos and KokkosKernels when enabled.
PROJ, NetCDF, Fortran and Python support are optional. AXIS's CMake file is the
source of truth for dependency discovery and option defaults.
