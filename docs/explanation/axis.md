---
type: explanation
category: explanation
tags: [helm, axis]
---

# AXIS: Why AXIS separates geometry, weights and fields

[Library overview](../libraries/axis.md) · [All libraries](../README.md)

Spatial regridding has three different inputs: source geometry, destination
geometry and field values. AXIS keeps them distinct so that spatial search and
weight construction can be reused across many variables and timesteps.

## Geometry determines the matrix

Mesh coordinates, connectivity, masks, interpolation method and policy settings
determine which source cells contribute to each destination cell and with what
weights. Once these inputs are fixed, the resulting sparse matrix represents
that mapping. Applying the matrix to a field is a separate operation and should
not repeat geometry work.

This separation makes weight caching possible, but cached weights are meaningful
only for compatible geometry and settings. Equal array lengths do not guarantee
that a cached matrix is appropriate for a new grid.

| Change between two applications | Reuse the matrix? |
| --- | --- |
| New field values on the same source mesh | Yes |
| A new variable with the same source and destination meshes | Yes |
| Different coordinates, cell bounds, connectivity, or masks | Generate new weights |
| Different method or geometric policy | Generate new weights |

Cache metadata should identify the geometry and settings that produced the
matrix. A successful deserialize only proves the bytes could be read; it does
not prove scientific compatibility.

## Methods answer different scientific questions

Nearest selection chooses a source value; smooth interpolation estimates values
between locations; conservative remapping targets area-integrated quantities.
These properties are not interchangeable. Constant preservation is a useful
check for interpolation, while conservation requires comparing appropriate
area-weighted integrals and coverage behavior. Masks and coastal treatment
affect which destination values are supported.

Coordinate conventions, cell bounds and periodic seams matter. Validate with
representative fields and known analytical or conservation properties before
using results scientifically. AXIS performance claims are workload and hardware
dependent; benchmark the same method, mesh, precision and backend you intend to
deploy.

For example, a constant field can test whether an interpolation path preserves
constants over covered cells. It cannot show that an extensive quantity such as
mass is conserved. For a conservative method, compare area-weighted integrals
over the common covered domain and inspect uncovered cells separately.

See the method-specific [weight-generation guide](https://github.com/NOAA-EMC/HELM/blob/develop/libs/axis/docs/weight_generation.md),
[masking guide](https://github.com/NOAA-EMC/HELM/blob/develop/libs/axis/docs/masking.md),
and [performance guide](https://github.com/NOAA-EMC/HELM/blob/develop/libs/axis/docs/performance_tuning.md).
