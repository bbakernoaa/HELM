---
type: tutorial
category: tutorials
tags: [helm, axis, python]
---

# AXIS Python guide: regrid fields with NumPy

[Library overview](../libraries/axis.md) · [C++ workflow](axis.md) · [All libraries](../README.md)

This guide builds the AXIS Python module, creates a source/destination grid
pair, generates weights, applies them to one and several NumPy fields, and
persists the weights. It is suited to prototyping, analysis and workflow
integration. The same mesh and numerical choices still need scientific
validation before operational use.

## 1. Build the Python module

AXIS's Python bindings are optional and built with nanobind. Use a dedicated
environment so the Python interpreter, NumPy, and the interpreter selected by
CMake are the same installation:

```bash
python3 -m venv .venv-axis
source .venv-axis/bin/activate
python -m pip install --upgrade pip numpy
```

From the HELM repository root, configure and build the binding:

```bash
cmake -S libs/axis -B libs/axis/build-python \
  -DCMAKE_BUILD_TYPE=Release \
  -DAXIS_BUILD_PYTHON=ON \
  -DPython_EXECUTABLE="$(python -c 'import sys; print(sys.executable)')"
cmake --build libs/axis/build-python --parallel
python -m pip install libs/axis/build-python/python
python -c 'import axis; print(axis.__file__)'
```

If configuration cannot find nanobind or Python development files, confirm
that the virtual environment is active and inspect the first CMake dependency
error. The module is optional; a C++-only AXIS build does not create `import
axis`. See the [AXIS build options](../reference/axis.md#build-options-and-dependencies) and
[Python API source guide](https://github.com/NOAA-EMC/HELM/blob/develop/libs/axis/docs/python_api.md).

## 2. Create a mesh pair

For a first run, use named grids so the exercise focuses on the regridding
workflow rather than geometry ingestion:

```python
import axis
import numpy as np

source = axis.NamedGridRegistry.generate("O48")
destination = axis.NamedGridRegistry.generate("O96")

print("source cells:", source.n_cells)
print("destination cells:", destination.n_cells)
```

AXIS also supports descriptor-based and rule-generated meshes. When bringing
your own grid, record its coordinate system, units, cell bounds/connectivity,
and orientation with the descriptor. A mesh with plausible cell counts can
still have invalid geometry. The
[mesh construction guide](https://github.com/NOAA-EMC/HELM/blob/develop/libs/axis/docs/mesh_construction.md)
describes those inputs and supported named-grid families.

## 3. Generate weights for the field you have

Choose the method by the data's meaning. This example uses bilinear weights for
a smooth field and makes the unmapped-destination policy explicit:

```python
config = {
    "method": "bilinear",
    "unmapped": "error",
}
weights = axis.WeightGenerator.generate(source, destination, config)
```

The low-level `axis.WeightGenerator` accepts all six native methods. Its
`method` strings are `bilinear`, `nearest_neighbor`, `bicubic`, `patch`,
`conservative` (first order), and `conservative2nd`. The supported options are
`norm_type` (`dstarea` or `fracarea`), `line_type` (`great_circle` or
`cartesian`), `unmapped` (`ignore` or `error`), and `use_limiter` (second order
conservative only). The parser accepts the lower-case spellings shown and the
corresponding C++ enum spellings where applicable.

```python
method_names = [
    "bilinear",
    "nearest_neighbor",
    "bicubic",
    "patch",
    "conservative",
    "conservative2nd",
]

for method in method_names:
    config = {
        "method": method,
        "line_type": "great_circle",
        "norm_type": "fracarea",
        "unmapped": "error",
        "use_limiter": method == "conservative2nd",
    }
    weights = axis.WeightGenerator.generate(source, destination, config)
    result = axis.apply(weights, source_field)
    # Compare result with a known solution or method-appropriate invariant.
```

Use nearest-neighbor for discrete categories only when nearest source centroid
is the rule you want. Bicubic uses a local cubic polynomial fit from up to 16
nearby centroids; patch uses a local least-squares quadratic fit. Both can
overshoot smooth extrema and should be checked against an analytic field on
representative meshes. First-order conservative uses overlap areas. Second
order adds a neighbor-derived linear gradient and can apply a limiter. For the
conservative methods, choose `norm_type` deliberately and compare area-weighted
integrals over the same covered region. The
[method and configuration reference](../reference/axis.md#weight-generation-api)
explains the algorithm and its limits.

## 4. Apply one field and inspect the result

Field lengths follow the grid pair: source data has one value per source cell;
the output has one value per destination cell.

```python
source_field = np.ones(source.n_cells, dtype=np.float64)
destination_field = axis.apply(weights, source_field)

assert destination_field.shape == (destination.n_cells,)
max_error = np.max(np.abs(destination_field - 1.0))
print(f"constant-field max error: {max_error:.3e}")
```

For this fully covered example, the constant field should be preserved within a
floating-point tolerance. This is a useful interpolation check, but it is not a
conservation proof. For conservative remapping, independently compare
area-weighted integrals over the covered region and inspect any unmapped cells.

For this return-value API, use `unmapped: "error"` if incomplete coverage
should stop the operation, or `"zero"` when zero is the intended fill. The
`"ignore"` policy leaves an unmapped output slot untouched; since this call
returns a newly allocated output, do not rely on a particular fill value for
those slots. Section 9 explains the difference from C++ calls that receive an
output view from the caller.

## 5. Reuse weights for multiple variables

Generating weights depends on geometry and configuration, not on the field
values. Generate the matrix once, then use `batch_apply` for a two-dimensional
array whose axes are `[cell, variable]`:

```python
n_variables = 5
source_state = np.asfortranarray(
    np.random.default_rng(7).normal(size=(source.n_cells, n_variables))
)
destination_state = axis.batch_apply(weights, source_state)

assert destination_state.shape == (destination.n_cells, n_variables)
```

Fortran-order arrays match the column-major layout expected by the binding and
can avoid a layout conversion. A C-order array may be accepted with a copy;
pass `strict_layout=True` to `axis.apply` when you want a layout mismatch to
fail instead of silently allocating.

## 6. Save and load the generated matrix

The Python matrix interface serializes to bytes. Persistence remains normal
Python I/O, so you can store the bytes in a local file or hand them to another
storage layer:

```python
blob = weights.to_bytes()
with open("o48-to-o96-axis-weights.bin", "wb") as stream:
    stream.write(blob)

with open("o48-to-o96-axis-weights.bin", "rb") as stream:
    restored = axis.InterpolationMatrix.from_bytes(stream.read())

restored_field = axis.apply(restored, source_field)
assert np.array_equal(restored_field, destination_field)
```

Use cache metadata that identifies source and destination geometry, masks,
method, normalization, unmapped behavior and limiter settings. Equal source and
destination sizes do not prove a cache belongs to the current meshes. The
[caching guide](https://github.com/NOAA-EMC/HELM/blob/develop/libs/axis/docs/caching.md)
describes the versioned representation and cache lifecycle.

## 7. Troubleshoot common integration issues

| Symptom | Check |
| --- | --- |
| `ModuleNotFoundError: axis` | Activate the environment used by CMake and install the built `python/` package |
| Import error mentions NumPy or Python ABI | Rebuild with the same interpreter that runs the program |
| `ValueError` on apply | The field's first dimension must match the source cell count |
| Unexpected output dimensions | For batch input use `[n_source_cells, n_variables]` |
| Small constant-field error | Check coverage, method configuration and an appropriate tolerance |
| Different results from a cached matrix | Verify cache metadata includes the full geometry and configuration |

Python exceptions translate common C++ failures into `ValueError` for invalid
arguments and `RuntimeError` for runtime failures. Catch those at the boundary
where your workflow can add grid, method and field context.

## 8. Wrap the repeated workflow in a function

Build the meshes and matrix outside the timestep or variable loop. This keeps
geometry work out of the hot path and makes the dimensions of each field
explicit at the application boundary:

```python
def make_regridder(source, destination, config):
    matrix = axis.WeightGenerator.generate(source, destination, config)

    def regrid(field):
        values = np.asarray(field, dtype=np.float64)
        if values.ndim != 1 or values.shape[0] != source.n_cells:
            raise ValueError(
                f"expected ({source.n_cells},), got {values.shape}"
            )
        return axis.apply(matrix, values)

    return matrix, regrid


matrix, regrid_temperature = make_regridder(
    source, destination, {"method": "bilinear", "unmapped": "error"}
)
destination_temperature = regrid_temperature(source_field)
```

For a state array, validate its leading cell dimension once and call
`batch_apply` with `[cell, variable]`. Keep a stable variable ordering and
record units and names alongside the array; AXIS treats each column as a
separate scalar field and does not know whether a column is temperature,
velocity, or a categorical quantity.

## 9. Choose a coverage policy that matches Python's output contract

The Python `apply` and `batch_apply` calls return newly allocated arrays. With
`unmapped: "ignore"`, AXIS leaves an unmapped output slot untouched; there is
no caller-provided destination array in these return-value calls to prefill
with a sentinel. For Python workflows, prefer `"error"` when incomplete
coverage should stop the run, or `"zero"` when zero is the intended fill. Use
`"ignore"` only when you have independently established full coverage or the
binding version you use provides a way to initialize the destination.

This differs from the C++ apply API, where the caller supplies a destination
view and can initialize values before applying. Masked destination cells also
remain untouched. If output cells may be intentionally masked, keep a separate
destination mask so downstream code can distinguish them from valid zeros.

## 10. Validate interpolation and conservation separately

Before using production fields, test at least a constant field and a known
smooth field. A constant field checks reproduction on covered cells; for
conservative methods it does not by itself prove integral conservation. For a
conservative case, compare the area-weighted source and destination integrals
over the same coverage, using the mesh areas and coverage fractions exposed by
the matrix/mesh API. Keep a separate tolerance for each test and note the
method, grid IDs, masks and normalization with the result.

For second-order conservative remapping, also inspect extrema with and without
the limiter. The limiter trades some local accuracy near sharp gradients for
monotonic behavior. It does not make invalid geometry or incomplete coverage
correct.

## 11. Persist matrices with identity metadata

The serialized bytes do not encode the full scientific identity of the input
meshes and choices. Store a small sidecar record with the source and
destination grid identifiers or checksums, mask checksums, method,
normalization, unmapped policy, limiter setting, AXIS cache format version,
and any coordinate-system details. Rebuild when one of those values changes.
Do not use just `(n_source_cells, n_destination_cells)` as a cache key: two
different grids can have the same dimensions.

Cache persistence is useful when startup weight generation dominates a run.
For a short exploratory job, first measure whether saving and loading the
matrix is cheaper than regenerating it. Store the bytes with normal Python I/O
or your application's storage system; AXIS does not manage paths or atomic
replacement of cache files.

## Practice

Change the field from all ones to a smooth function of cell position, then
compare the output with the same analytic function evaluated on the destination
mesh. Repeat with a conservative method and compare area-weighted integrals.
Keep the test field, grid pair, tolerance and coverage mask fixed when
comparing methods so the result answers one numerical question at a time.

For lower-level mesh control and device-resident execution, continue with the
[C++ workflow](axis.md) and the [AXIS API reference](../reference/axis.md).
