---
type: howto
category: how_to
tags: [helm, blend]
---

# BLEND: Select or interpolate between two fields

[Library overview](../libraries/blend.md) · [All libraries](../README.md)

Use BLEND after another part of the model has selected the two bookend fields
and computed alpha. This recipe shows both supported profiles and the checks
the caller should make.

## Prepare the fields

Include `<blend/helm_math_blend.hpp>`, initialize Kokkos, and create three
equally sized device-accessible unmanaged views: left, right and target. The
owning allocations must outlive the call. Keep target separate from the inputs.

## Select a profile

For continuous interpolation:

~~~cpp
blend::execute_blend(left, right, target, alpha, blend::BlendProfile::Linear);
~~~

Linear mode computes each output from both inputs. Alpha is not clamped; values
outside [0, 1] extrapolate.

For nearest-bookend selection:

~~~cpp
blend::execute_blend(left, right, target, alpha, blend::BlendProfile::Step);
~~~

Step mode selects left for alpha below 0.5 and right otherwise.

## Handle preconditions and results

All three extents must agree or BLEND throws `std::invalid_argument`.
After dispatch, inspect device data through a host mirror when needed; do not
dereference a device pointer on the host. A constant-input check is a useful
smoke test: blending arrays filled with 2 and 6 at alpha 0.25 should produce 3.

The calls above match `execute_blend` in the
[public header](https://github.com/NOAA-EMC/HELM/blob/develop/libs/blend/include/blend/helm_math_blend.hpp).
See the [tutorial](../tutorials/blend.md) for a complete program and the
[reference](../reference/blend.md) for exact formulas.
