---
type: reference
category: reference
tags: [helm, blend, navigation]
---

# BLEND — Stateless Array Blending Kernels

BLEND provides element-wise linear weighted blending and step selection through
Kokkos. It is useful when the caller has already chosen two input fields and an
alpha value and needs a portable array operation.

For each index, linear mode computes `left * (1 - alpha) + right * alpha`.
Step mode chooses the left field when alpha is below 0.5 and the right field
otherwise. Linear mode does not clamp alpha, so values outside [0, 1] extrapolate.

BLEND's current header uses a non-owning, unmanaged rank-one Kokkos view of
doubles. It does not allocate storage. Keep the input and output allocations
alive and accessible from the active execution space. The three extents must
match; a mismatch throws `std::invalid_argument`. Give output its own storage.

The header's `span::FieldView` alias is distinct from SPAN's templated
`span::FieldView<T, Rank>`. Avoid including both interfaces in the same
translation unit until that API boundary is reconciled.

BLEND does not choose bookends or derive alpha. A caller may use TICK or its
own schedule to find the neighboring snapshots and compute a normalized weight,
then pass those fields and that weight to BLEND. For values 2 and 6, linear
blending at alpha 0.25 yields 3; step selection at the same alpha yields 2.

BLEND exports the header-only target `HELM::BLEND`; Kokkos is required.
`BLEND_BUILD_TESTING` enables GTest and RapidCheck tests.

Work through the [array tutorial](../tutorials/blend.md), follow
[step selection](../how-to/blend.md), use the [API reference](../reference/blend.md),
and read [the design explanation](../explanation/blend.md).
