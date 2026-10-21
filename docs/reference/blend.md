---
type: reference
category: reference
tags: [helm, blend]
---

# BLEND: BLEND function reference

[Library overview](../libraries/blend.md) · [Tutorial](../tutorials/blend.md) ·
[How-to](../how-to/blend.md) · [All libraries](../README.md)

BLEND provides two stateless element-wise operations over unmanaged Kokkos
views. Its public declarations are in
[`blend/helm_math_blend.hpp`](https://github.com/NOAA-EMC/HELM/blob/develop/libs/blend/include/blend/helm_math_blend.hpp).
The implementation uses the default Kokkos execution space and fences before
returning.

## Types and operations

| API | Result for each element | Behavior |
| --- | --- | --- |
| `LinearBlendKernel::apply(left, right, target, alpha)` | `left[i] * (1 - alpha) + right[i] * alpha` | Linear interpolation or extrapolation |
| `StepBlendKernel::apply(left, right, target, alpha)` | `alpha < 0.5 ? left[i] : right[i]` | Selects one complete input field |
| `execute_blend(left, right, target, alpha, profile)` | Dispatches by `BlendProfile` | `Linear` or `Step` |

`BlendProfile` has the values `Linear` and `Step`. The `alpha` argument is one
scalar shared by every element, not an array of per-cell weights. Linear mode
does not clamp the value: `alpha < 0` or `alpha > 1` extrapolates. Step mode
selects `right` at exactly `alpha == 0.5`.

## Call contract

The arguments are `span::FieldView` aliases for unmanaged rank-one Kokkos
views of `double`. They do not own storage. Every view must refer to memory
accessible to the active Kokkos execution space, and all three extents must
match. The target must not overlap either input. Keep the allocations alive
until the call returns; the operation fences before returning, so the output is
ready for subsequent host or device work consistent with its memory space.

The BLEND header currently declares its rank-one alias as `span::FieldView`,
while the SPAN library also defines `span::FieldView<T, Rank>` as a template.
Those declarations cannot be combined in one translation unit. Until the
public types are reconciled in the source, include and use the BLEND interface
without also including SPAN's `field_view.hpp` in that translation unit.

```cpp
#include <Kokkos_Core.hpp>
#include <blend/helm_math_blend.hpp>

Kokkos::View<double*> left("left", n);
Kokkos::View<double*> right("right", n);
Kokkos::View<double*> target("target", n);
// Initialize left and right on the active backend first.
blend::execute_blend(left, right, target, 0.25, blend::BlendProfile::Linear);
```

The kernel throws `std::invalid_argument` for mismatched extents. The unified
entry point also throws for an unrecognized enum value. BLEND does not allocate
field storage, synchronize SPAN host/device copies, interpret timestamps, or
choose an interpolation policy; callers own those decisions.

## Performance characteristics

Each element reads two doubles and writes one double. Both operations are
usually memory-bandwidth-bound for large arrays; for small arrays, Kokkos
launch overhead can dominate. Reuse caller-owned views and avoid surrounding
the call with unnecessary host/device copies. BLEND has no batch or in-place
API; use non-overlapping output storage.

## Build and dependencies

BLEND is header-only and exports `HELM::BLEND`; Kokkos is required. The
`BLEND_BUILD_TESTING` option defaults to OFF. With tests enabled, GTest and
RapidCheck are required. See the
[build file](https://github.com/NOAA-EMC/HELM/blob/develop/libs/blend/CMakeLists.txt).
