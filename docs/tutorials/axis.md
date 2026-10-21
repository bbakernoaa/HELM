---
type: tutorial
category: tutorials
tags: [helm, axis]
---

# AXIS: Tutorial: preserve a constant field while regridding

[Library overview](../libraries/axis.md) · [All libraries](../README.md)

**Goal:** remap a constant field from O48 to O96 and check that it remains one.
Complete the [environment setup](../README.md#prepare-a-development-environment)
first. The build requires Kokkos, MPI, KokkosKernels, and ArborX; CMake can fetch
some dependencies. See the [build definition](https://github.com/NOAA-EMC/HELM/blob/develop/libs/axis/CMakeLists.txt)
for discovery and optional PROJ/NetCDF support.

From the repository root:

```bash
cmake -S libs/axis -B libs/axis/build -DAXIS_BUILD_TESTING=ON -DAXIS_BUILD_EXAMPLES=ON
cmake --build libs/axis/build --target example_bilinear_regrid --parallel
./libs/axis/build/examples/example_bilinear_regrid
```

Read the [complete example](https://github.com/NOAA-EMC/HELM/blob/develop/libs/axis/examples/example_bilinear_regrid.cpp)
in order: create meshes, generate bilinear weights, convert to CSR, initialize
a source field to one, apply weights, and reduce the maximum error.

The example must exit successfully and print
`SUCCESS: Bilinear regridding preserves constant field.`
It rejects a maximum error above `1e-12`. This checks constant preservation
for this example; it does not establish accuracy for every grid or method.

## Before continuing

Allow 40–50 minutes. Start with the compiled example above so that dependency
and toolchain failures are separated from changes to your own application.
The O48/O96 named grids create data in memory; you do not need an external
NetCDF file for this exercise.

## 2. Build your own regridding application

Create a separate project so you can experiment without editing the repository's
example source:

```bash
mkdir -p /tmp/helm-axis-tutorial
cd /tmp/helm-axis-tutorial
```

Save this CMakeLists.txt, replacing the checkout path:

```cmake
cmake_minimum_required(VERSION 3.21)
project(axis_tutorial LANGUAGES CXX)
set(AXIS_BUILD_TESTING OFF CACHE BOOL "" FORCE)
set(AXIS_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
add_subdirectory(/path/to/HELM/libs/axis axis-build)
add_executable(axis_tutorial main.cpp)
target_link_libraries(axis_tutorial PRIVATE HELM::AXIS Kokkos::kokkos)
```

Save this complete main.cpp. It uses the same API sequence as the repository's
bilinear example, then applies the same matrix to two constant fields.

```cpp
#include <Kokkos_Core.hpp>
#include <axis/axis.hpp>
#include <iostream>

int main(int argc, char** argv) {
    Kokkos::ScopeGuard kokkos(argc, argv);
    auto source = axis::topology::NamedGridRegistry::generate("O48");
    auto destination = axis::topology::NamedGridRegistry::generate("O96");
    axis::solver::RegridConfig config;
    config.method = axis::solver::RegridMethod::Bilinear;
    axis::solver::WeightGenerator generator;
    auto weights = generator.generate(source, destination, config);
    weights.to_csr();
    std::cout << "source cells=" << source.n_cells()
              << " destination cells=" << destination.n_cells()
              << " matrix entries=" << weights.nnz() << '\n';

    Kokkos::View<double*> input("input", source.n_cells());
    Kokkos::View<double*> output("output", destination.n_cells());
    for (double value : {1.0, 2.0}) {
        Kokkos::deep_copy(input, value);
        axis::solver::apply(weights, input, output);
        double max_error = 0.0;
        Kokkos::parallel_reduce(
            "constant_error", destination.n_cells(),
            KOKKOS_LAMBDA(const int i, double& error) {
                const double difference = Kokkos::abs(output(i) - value);
                if (difference > error) error = difference;
            }, Kokkos::Max<double>(max_error));
        std::cout << "constant=" << value << " max error=" << max_error << '\n';
        if (max_error > 1e-12) return 1;
    }
    return 0;
}
```

Build and run from the tutorial directory:

```bash
cmake -S . -B build
cmake --build build --target axis_tutorial --parallel
./build/axis_tutorial
```

**Checkpoint:** source and destination have nonzero cell counts, the matrix has
nonzero entries, and both error checks are at most 1e-12. Exact printed errors
can depend on the backend and toolchain.

## 3. Follow the data through the program

Locate each of these stages in your source before modifying it:

| Stage | Object | Depends on field values? |
| --- | --- | --- |
| Build source geometry | source | No |
| Build destination geometry | destination | No |
| Generate weights | weights | No |
| Fill a source field | input | Yes |
| Apply interpolation | output | Yes |
| Compare with the known result | max_error | Yes |

The weight generator runs once, before the loop. Applying a new temperature
field on the same geometry does not require creating another matrix.

## 4. Add another constant-field checkpoint

Change the value list to {1.0, 2.0, 273.15}. Rebuild and rerun.

Predict the expected output field: every destination cell should be 273.15
within floating-point tolerance. The additional check exercises matrix reuse
with a value that is not exactly representable in binary floating point.

If only this check fails by a small amount, inspect the magnitude and choose
a tolerance justified by your intended computation. Do not remove the check.

## 5. Run the other maintained workflows

Return to the HELM root and build the two additional examples:

```bash
cmake --build libs/axis/build --target example_conservative_cache example_batch_apply --parallel
./libs/axis/build/examples/example_conservative_cache
./libs/axis/build/examples/example_batch_apply
```

The first demonstrates its own conservative/caching workflow. The second
demonstrates several fields in a batch. Read the examples alongside their output
to identify where weights are reused or reconstructed.

A constant-preservation check is not a conservation test. Do not conclude that
a method conserves an area integral just because it reproduces a constant field.

## 6. Describe a mesh when a named grid is not enough

Named grids are convenient when the grid is in AXIS's registry. For model-owned
grids, build a `GridDescriptor` from the grid's coordinates and polygon
connectivity, then create the mesh. The C++ interface expects Kokkos views and
an explicit coordinate system:

```cpp
axis::topology::GridDescriptor descriptor;
descriptor.cell_lon = cell_lon;       // Kokkos::View<const double*>
descriptor.cell_lat = cell_lat;       // Kokkos::View<const double*>
descriptor.connectivity = vertices;   // concatenated vertex indices
descriptor.offsets = cell_offsets;    // length n_cells + 1
descriptor.n_cells = n_cells;
descriptor.coord_system = axis::CoordSystem::SphericalDeg;
auto mesh = axis::topology::MeshFactory::from_descriptor(descriptor);
```

Connectivity uses CSR-style offsets: cell `i` uses the range from
`offsets(i)` through `offsets(i + 1)`. Validate that each index refers to a
valid vertex and that polygon vertices follow the required orientation. Use
`SphericalRad` when coordinate arrays are in radians; degree values passed with
the wrong enum can produce plausible but incorrect geometry. The complete
[mesh construction guide](https://github.com/NOAA-EMC/HELM/blob/develop/libs/axis/docs/mesh_construction.md)
covers named, rule-generated and structured grids as well.

## 7. Select a method and its unmapped policy

Choose the method from the meaning of the field and the conservation property
you need, then set the configuration explicitly:

| Method | Appropriate starting point | Validate with |
| --- | --- | --- |
| `Bilinear` | Smooth point-like fields | Analytic or trusted reference fields |
| `Conservative1stOrder` | Cell averages and extensive quantities | Area-weighted integral and coverage |
| `Conservative2ndOrder` | Smooth cell averages needing higher spatial accuracy | Integral, smooth-field error and extrema |

`normalization` controls how partially covered destination cells are treated;
`unmapped` controls destinations with no source contribution. With `Ignore`,
those output cells retain their previous value. Initialize the destination
field deliberately so an unmapped cell cannot be mistaken for a computed zero.
The maintained [weight-generation guide](https://github.com/NOAA-EMC/HELM/blob/develop/libs/axis/docs/weight_generation.md)
documents configuration members and method-specific assumptions.

## 8. Apply one or many fields

The matrix row count is the destination cell count and its column count is the
source cell count. A single-field apply therefore requires a source vector of
length `matrix.n_src()` and a destination vector of length `matrix.n_dst()`.
For multiple variables on the same mesh pair, use a rank-two view whose first
dimension is cells and second dimension is variables:

```cpp
Kokkos::View<double**> source_state("source_state", source.n_cells(), n_vars);
Kokkos::View<double**> destination_state(
    "destination_state", destination.n_cells(), n_vars);
axis::solver::batch_apply(weights, source_state, destination_state);
```

The source and destination cell counts must match the matrix, and both views
must use a compatible Kokkos memory space. See the
[apply guide](https://github.com/NOAA-EMC/HELM/blob/develop/libs/axis/docs/apply.md)
for COO/CSR dispatch and the distributed `HaloPattern` boundary.

## 9. Add masks without rebuilding model fields

Attach masks to meshes before generating weights. A zero mask value excludes a
cell; nonzero values mark active cells. A source mask removes contributions
from those cells. A destination mask suppresses weight rows, and apply leaves
masked destination values untouched. If masking leaves an active destination
with no coverage, the configured `unmapped` policy applies. Try source-only,
destination-only, and combined masks separately so you can identify which
coverage change produced a result. The detailed
[masking guide](https://github.com/NOAA-EMC/HELM/blob/develop/libs/axis/docs/masking.md)
includes ocean-only examples.

## 10. Cache weights only with their geometry contract

Weight generation is independent of field values, so a static source/destination
grid pair can reuse its matrix for every variable and timestep. For repeated
apply, convert to CSR once. To persist it, serialize the matrix to a byte buffer
with `axis::solver::WeightCache`; AXIS leaves filesystem or AMIO persistence to
the application. Cache keys should include a stable identity for both meshes,
the method, masks, normalization and other generation settings. Matching cell
counts alone is not enough to establish compatibility. See the
[cache guide](https://github.com/NOAA-EMC/HELM/blob/develop/libs/axis/docs/caching.md).

## 11. Move the whole operation to the intended memory space

For device execution, build meshes in the selected Kokkos `MemorySpace`,
generate weights from those meshes, and keep field arrays in that space through
apply. This avoids accidental host/device copies in the timestep loop. Check
the configured Kokkos backend before naming a space such as `CudaSpace` or
`HIPSpace`; those types are only available when the backend is enabled. Profile
the real mesh and field sizes before choosing CSR conversion, batching or a
device path. The
[performance guide](https://github.com/NOAA-EMC/HELM/blob/develop/libs/axis/docs/performance_tuning.md)
describes those tradeoffs.

## 12. Persist a matrix and reload it

If weights are expensive to build and the grid pair is stable across runs, use
`WeightCache` to serialize the matrix into application-owned bytes. This
example selects a deserialization memory space explicitly; choose the same
space your apply path will use:

```cpp
#include <axis/solver/weight_cache.hpp>
#include <vector>

const auto byte_count =
    axis::solver::WeightCache::serialize(weights, nullptr, 0);
std::vector<char> cache_bytes(byte_count);
axis::solver::WeightCache::serialize(
    weights, cache_bytes.data(), cache_bytes.size());

// Persist cache_bytes using your application's storage layer.
auto restored = axis::solver::WeightCache::deserialize<
    Kokkos::DefaultExecutionSpace::memory_space>(
        cache_bytes.data(), cache_bytes.size());
```

The cache stores matrix data and dimensions, not a proof that it matches the
current grid. Store a separate metadata record containing stable identities
for both grids, coordinate units, masks, method, normalization, unmapped
policy, limiter and relevant AXIS format/version information. Reject a cache
when any of those inputs differ. The
[cache reference](../reference/axis.md#interpolationmatrix-and-apply) and
[upstream cache guide](https://github.com/NOAA-EMC/HELM/blob/develop/libs/axis/docs/caching.md)
describe serialization and malformed-buffer failures.

## 13. Validate the scientific quantity you intend to preserve

Use more than one check when assessing a method. A constant field tests a
partition-of-unity property for covered cells. For conservative remapping,
compare source and destination area-weighted integrals over the same covered
region:

```text
source integral = sum(source[i] * source_area[i] * source_coverage[i])
destination integral = sum(destination[j] * destination_area[j]
                           * destination_coverage[j])
```

The matrix exposes cell areas and coverage fractions for these diagnostics;
the exact accessor names are in the installed `InterpolationMatrix` header.
Use an analytic smooth field to assess interpolation error, and inspect extrema
when using second-order reconstruction. Record the grid pair, method,
configuration, masks, coverage policy, expected tolerance and backend with the
results. Agreement between two AXIS calls using the same matrix only checks
repeatability; it is not an independent accuracy test.

## 14. Diagnose unmapped cells and masks separately

Run at least three distinct cases when coverage is incomplete: no masks,
source-only mask, and destination-only mask. Initialize the destination field
to a recognizable sentinel before each apply. A masked destination row remains
untouched; an active destination with no contributing source follows the
configured `unmapped` policy. These outcomes can look identical if the output
was initialized to zero, so inspect the masks, coverage fractions, and
diagnostic report as well as the field values.

When changing a mask, regenerate the weights. The matrix depends on geometry,
configuration and masks, but not on the values of the fields being regridded.
This lets you reuse one matrix for many variables or timesteps while keeping
each mask-specific operator distinct.

## If you get stuck

| Symptom | Check |
| --- | --- |
| Example target missing | Configure with AXIS_BUILD_EXAMPLES=ON in the repository build |
| Dependency download fails | Supply installed dependency prefixes and inspect the first CMake error |
| Field size mismatch | Input matches source cells; output matches destination cells |
| Nonzero error | Confirm every source value was filled and meshes/configuration were unchanged |
| Host/device access error | Keep allocation and execution spaces compatible |

## Practice

Generate O96 as the source and O48 as the destination, then run the constant
checks again. Identify which allocations must change size.
For a nonconstant field, choose an analytic function of position and calculate
an independent expected result rather than comparing only against another AXIS
call.

Continue to the [Python user guide](axis-python.md),
[weight reuse](../how-to/axis.md), and the [AXIS API reference](../reference/axis.md).
