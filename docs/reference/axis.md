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
config.method = axis::solver::RegridMethod::Bilinear;
config.unmapped = axis::solver::UnmappedAction::Error;

axis::solver::WeightGenerator generator;
auto matrix = generator.generate(source, destination, config);
```

The method and options currently documented by AXIS are:

| Setting | Values | Contract |
| --- | --- | --- |
| `method` | `Bilinear`, `Conservative1stOrder`, `Conservative2ndOrder` | Select interpolation or conservative reconstruction |
| `normalization` | `DstArea`, `FracArea` | Select how overlap weights are normalized for partial coverage |
| `unmapped` | `Ignore`, `Zero`, `Error` | Decide what to do when an active destination receives no source contribution |
| `use_limiter` | `true`, `false` | Enable the documented monotonicity limiter for second-order conservative remapping |
| `pole_threshold_deg` | degrees | Configure polar handling threshold |

The documented defaults are bilinear, destination-area normalization,
`Ignore` for unmapped destinations, no second-order limiter, and an 85-degree
pole threshold. Set each option that affects your scientific result
explicitly, so changing defaults or upgrading AXIS cannot silently change the
intended method.

### Method behavior and normalization

| Method | Main property | Validate with |
| --- | --- | --- |
| Bilinear | Smooth-field interpolation; the implementation uses spherical geometry and may fall back to inverse-distance weights if its local solve does not converge | Analytic fields and known values; constant reproduction on covered destinations |
| First-order conservative | Area-overlap remapping intended to preserve the area-weighted integral | Compare covered source and destination integrals; inspect coverage |
| Second-order conservative | Adds local gradient reconstruction; optional limiter controls new extrema | Integral, smooth-field error, and extrema with limiter on/off |

For a destination cell `j`, the documented conservative normalization choices
are:

| `Normalization` | Weight interpretation | Typical use |
| --- | --- | --- |
| `DstArea` | `overlap_area(i,j) / destination_area(j)` | Normalize by full destination area |
| `FracArea` | `overlap_area(i,j) / (destination_area(j) * destination_coverage(j))` | Normalize over the covered part of a partially covered destination |

These choices differ on partial coverage. Record the setting with analysis
outputs and compare integrals over the same covered domain; a constant-field
test alone is not a substitute for a conservation test.

Bilinear is intended for smooth point-like fields. First-order conservative
remapping targets area-integrated quantities; second order reconstructs local
gradients and can use a limiter. These are numerical choices, not just speed
settings. `Ignore` leaves an unmapped output value untouched, so initialize
that field to a deliberate fill value before apply. `Error` reports incomplete
coverage; `Zero` writes zero for unmapped output.

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
and a destination mask suppresses writes to its rows. `Zero` writes zero to
unmapped active destinations; `Error` reports incomplete coverage.

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
