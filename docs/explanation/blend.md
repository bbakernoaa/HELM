---
type: explanation
category: explanation
tags: [helm, blend]
---

# BLEND: Why BLEND stays stateless

[Library overview](../libraries/blend.md) · [All libraries](../README.md)

BLEND's job is to combine two arrays after a caller has selected the inputs and
computed a weight. It does not know about time, calendars, grid geometry or
scientific meaning. That narrow contract lets the same kernels serve multiple
model workflows.

## Linear and step profiles

Linear mode computes a weighted arithmetic combination independently at each
index. Alpha zero returns the left value; alpha one returns the right value.
Intermediate values interpolate when alpha is within [0, 1]. Outside that range
the formula extrapolates, because the kernel does not clamp.

Step mode is categorical: alpha below 0.5 chooses the left input, and alpha at
or above 0.5 chooses the right. At the midpoint the right side wins. This
threshold is part of the API, so callers should compute alpha and select the
profile according to their temporal or domain policy.

| Alpha | Linear profile | Step profile |
| ---: | --- | --- |
| 0 | Copy left | Select left |
| 0.25 | 75% left + 25% right | Select left |
| 0.5 | Equal weighted average | Select right |
| 1 | Copy right | Select right |
| Outside [0, 1] | Extrapolate | Threshold rule still applies |

The same alpha can therefore mean different things under the two profiles.
The calling code should choose the profile based on the data semantics rather
than treating `Step` as a cheaper approximation of `Linear`.

## Memory responsibility

BLEND's Kokkos views are unmanaged. They describe memory owned by someone else,
so BLEND does not allocate, resize or retain the field arrays. The caller must
supply matching extents and memory accessible from the active execution space.
Using a distinct output avoids dependence on in-place or overlapping-view
behavior.

The current BLEND header supplies its own `span::FieldView` alias. SPAN also
uses that namespace for a templated class; the two headers are not currently a
single unified interface. Keep the distinction visible at integration points.
