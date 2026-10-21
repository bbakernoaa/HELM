---
type: howto
category: how_to
tags: [helm, axis]
---

# AXIS: Reuse AXIS weights across fields

[Library overview](../libraries/axis.md) · [All libraries](../README.md)

Weight generation can be expensive. When source and destination geometry,
method, masks and other weight-generation settings stay fixed, construct the
weight matrix once and apply it to every compatible field.

## Generate once

Build both meshes and configure the method exactly as for the fields you intend
to process. Generate the matrix once. Both COO and CSR are supported by apply;
convert to CSR before repeated row-based apply when its conversion cost is
justified:

~~~cpp
axis::solver::RegridConfig config;
config.method = axis::solver::RegridMethod::Bilinear;
axis::solver::WeightGenerator generator;
auto weights = generator.generate(source_mesh, destination_mesh, config);
weights.to_csr();
~~~

The names and overloads above follow the maintained
[bilinear example](https://github.com/NOAA-EMC/HELM/blob/develop/libs/axis/examples/example_bilinear_regrid.cpp).

## Apply repeatedly

Allocate each input to the source mesh's cell count and each output to the
destination mesh's cell count. Refill the source field for each variable or
timestep, then call `axis::solver::apply(weights, source, destination)`.
Keep the weight matrix and mesh geometry alive for the whole sequence.

For multiple fields, compare a loop over `apply` with the dedicated
[batch-apply example](https://github.com/NOAA-EMC/HELM/blob/develop/libs/axis/examples/example_batch_apply.cpp).
For serialization, use the [caching guide](https://github.com/NOAA-EMC/HELM/blob/develop/libs/axis/docs/caching.md)
and [conservative cache example](https://github.com/NOAA-EMC/HELM/blob/develop/libs/axis/examples/example_conservative_cache.cpp).

## Know when weights are stale

Regenerate weights if mesh coordinates, cell connectivity, interpolation method,
masking or any other weight-generation setting changes. A matrix with matching
array sizes is not evidence that it matches the new geometry.

After loading cached weights, verify compatibility with the intended mesh and
method before use. Validate results with a field-specific invariant; constant
preservation alone does not establish conservation. See the
[masking](https://github.com/NOAA-EMC/HELM/blob/develop/libs/axis/docs/masking.md)
and [performance guides](https://github.com/NOAA-EMC/HELM/blob/develop/libs/axis/docs/performance_tuning.md).
