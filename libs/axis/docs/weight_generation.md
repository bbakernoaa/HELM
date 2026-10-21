# Weight Generation {#weight_generation}

Weight generation builds a sparse operator from source cells to destination
cells. It depends on mesh coordinates, connectivity, masks, geometry settings,
and `RegridConfig`, but not on field values. Generate once and reuse the matrix
for fields on the same grid pair. AXIS implements six methods; four interpolate
at destination locations and two integrate over source/destination overlap.

## Choose a method

| Method | Algorithm | Typical use | Main checks |
| --- | --- | --- | --- |
| `Bilinear` | Local interpolation weights; regular latitude/longitude grids use a 2×2 cell-center stencil and index arithmetic. The general path uses local geometry to locate and weight the containing source neighborhood. | Smooth point-like fields | Analytic-field error, constant reproduction, poles and longitude seams |
| `NearestNeighbor` | Spatial search over source-cell centroids; each destination receives the value of its closest centroid with weight 1. Regular grids can use direct indexing; spherical searches represent points in 3-D unit-sphere coordinates. | Categories, flags, or nearest-sample semantics | Category preservation, nearest distances, coverage and boundaries |
| `Bicubic` | Queries up to 16 nearby source centroids and constructs a local polynomial interpolation operator with up to 16 terms. It reduces polynomial order when fewer samples are available. | Smooth fields where a wider stencil is appropriate | Analytic-field error, overshoot, edges and irregular stencil conditioning |
| `Patch` | Queries up to 16 nearby centroids, fits a six-term quadratic `[1, x, y, xy, x², y²]` by least squares, then evaluates the fit at the destination centroid. | Smooth fields on irregular meshes where local recovery is useful | Fit residuals, analytic-field error, extrema and stencil geometry |
| `Conservative1stOrder` | Intersects source and destination cell polygons and weights by overlap area. Regular/rectilinear grids have analytic overlap fast paths; general grids use spatial candidate search and polygon clipping. | Cell means, densities and extensive quantities | Area-weighted integral, coverage fractions and constant fields |
| `Conservative2ndOrder` | Reconstructs a linear variation inside each source cell from neighboring values, then integrates that reconstruction over cell overlaps. An optional Barth–Jespersen limiter restrains new extrema. | Smooth cell means where first order is too diffusive | Conservation, smooth-field error, extrema, limiter on/off |

The methods have different numerical contracts. Nearest-neighbor preserves
source categories but is discontinuous and not conservative. Bilinear, bicubic
and patch are interpolation methods, not area-integral preserving methods.
Higher-order polynomial interpolation can overshoot. First-order conservative
is usually more diffusive but robust; second-order reduces diffusion and needs
additional gradient and limiter checks.

## C++ configuration

The public enum is `axis::solver::InterpolationMethod`. The `RegridConfig`
members are `method`, `norm_type`, `line_type`, `unmapped`, `use_limiter`, and
`extrap_method`:

```cpp
axis::solver::RegridConfig config;
config.method = axis::solver::InterpolationMethod::Conservative2ndOrder;
config.norm_type = axis::solver::NormType::FracArea;
config.line_type = axis::solver::LineType::GreatCircle;
config.unmapped = axis::solver::UnmappedAction::Error;
config.use_limiter = true;

auto matrix = axis::solver::WeightGenerator::generate(src_mesh, dst_mesh, config);
```

| Setting | Values | Effect |
| --- | --- | --- |
| `method` | `Bilinear`, `NearestNeighbor`, `Bicubic`, `Patch`, `Conservative1stOrder`, `Conservative2ndOrder` | Selects the operator |
| `norm_type` | `DstArea`, `FracArea` | Controls conservative partial-coverage normalization |
| `line_type` | `GreatCircle`, `Cartesian` | Selects spherical or planar overlap geometry for conservative methods |
| `unmapped` | `Ignore`, `Error` | Keeps an empty row or rejects incomplete active destination coverage |
| `use_limiter` | `false`, `true` | Applies the Barth–Jespersen limiter to second-order conservative reconstruction |
| `extrap_method` | `None`, `NearestWet` | Controls handling of completely dry destination cells |

`DstArea` divides overlap contribution by the full destination area. With
`FracArea`, the contribution is normalized over the covered part of a
partially-covered destination. This changes partial-coverage values, so record
the normalization with the result. `Ignore` leaves an unmapped output row
empty; C++ apply leaves the caller's value unchanged for that row. Initialize
outputs to an intentional fill value. `Error` throws during generation when
an active destination has no source coverage. A masked destination is distinct
from an active-but-unmapped destination.

## Python method names

The low-level `axis.WeightGenerator.generate` binding accepts method strings:

| Python string | C++ enum |
| --- | --- |
| `"bilinear"` | `Bilinear` |
| `"nearest_neighbor"` | `NearestNeighbor` |
| `"bicubic"` | `Bicubic` |
| `"patch"` | `Patch` |
| `"conservative"` | `Conservative1stOrder` |
| `"conservative2nd"` | `Conservative2ndOrder` |

It accepts `norm_type` (`"dstarea"`, `"fracarea"`), `line_type`
(`"great_circle"`, `"cartesian"`), `unmapped` (`"ignore"`, `"error"`),
and `use_limiter` in the configuration dictionary. The higher-level Python
`Regridder` wrapper also exposes methods and options; consult its current
constructor for wrapper-specific aliases and defaults.

```python
config = {
    "method": "conservative2nd",
    "norm_type": "fracarea",
    "line_type": "great_circle",
    "unmapped": "error",
    "use_limiter": True,
}
matrix = axis.WeightGenerator.generate(src, dst, config)
```

## Conservative normalization and validation

For destination cell `j`, first-order conservative weights are based on
`overlap_area(i, j)`. `DstArea` uses the full destination area in the
denominator; `FracArea` uses the covered destination area. Coverage fractions
are also retained on the matrix. Compare source and destination integrals over
the same covered domain; do not compare a partially covered source domain with
a full destination domain and call the difference a conservation error.

For a field `q`, a representative check is:

```text
source integral = sum(q_src[i] * area_src[i] * source_coverage[i])
destination integral = sum(q_dst[j] * area_dst[j] * destination_coverage[j])
```

Second-order reconstruction adds local gradients and can still conserve the
integral when the overlap integration and reconstruction are applied
consistently. The limiter constrains reconstructed values using neighboring
source values; sharp fronts can cause the limiter to reduce the local order.
Inspect both integral error and extrema, and validate on a field representative
of the scientific application.

## Geometry, search and diagnostics

Conservative methods first find candidate source/destination overlaps. For
general grids, AXIS uses ArborX bounding-volume queries; polygon clipping then
computes overlap contributions. Great-circle mode treats spherical boundaries
as arcs on the unit sphere. Regular and rectilinear lat/lon pairs can bypass
the BVH with index-based overlap calculations. These accelerations do not
change the intended area-overlap definition, but different arithmetic paths
can produce small floating-point differences.

Interpolation methods use destination and source centroids to identify local
samples. Bilinear has a regular-grid fast path; nearest-neighbor uses a nearest
query; bicubic and patch use a local multi-point stencil. Since the stencil is
selected in coordinate space, pay particular attention to global longitude
seams and polar or highly distorted meshes. Validate with known fields rather
than assuming that “higher order” always means lower error.

Degenerate cells can be excluded during generation and reported in the matrix
diagnostic report. Review those diagnostics, destination coverage fractions,
and mesh masks alongside field results. A successful matrix build does not
prove complete coverage or scientific accuracy.
