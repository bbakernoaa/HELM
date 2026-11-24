"""Partition checked spherical fixtures for native MPI and Dask benchmarks."""

import hashlib
import json
import threading
from dataclasses import dataclass
from functools import partial
from pathlib import Path

import numpy as np
from netCDF4 import Dataset

# The NetCDF-C library is not safe to use concurrently in one worker process.
_NETCDF_LOCK = threading.Lock()
_MESH_ARRAYS = (
    "lon",
    "lat",
    "center_lon",
    "center_lat",
    "area",
    "offsets",
    "indices",
    "mask",
    "cell_id",
)


def _checksum(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _write_mesh(file, name, mesh, split, owners, rank, values, fractions):
    first, last = split[rank : rank + 2]
    offsets = mesh["offsets"][first : last + 1]
    global_nodes, local_indices = np.unique(
        mesh["indices"][offsets[0] : offsets[-1]], return_inverse=True
    )
    group = file.createGroup(name)
    arrays = {
        "lon": mesh["lon"][global_nodes],
        "lat": mesh["lat"][global_nodes],
        "offsets": offsets - offsets[0],
        "indices": local_indices.astype(np.int32),
        "node_id": global_nodes.astype(np.int32),
        "node_owner": owners[global_nodes],
        **{
            key: mesh[key][first:last]
            for key in ("center_lon", "center_lat", "area", "mask", "cell_id")
        },
        ("field" if name == "source" else "expected"): values[first:last],
    }
    if fractions is not None:
        arrays["expected_fraction"] = fractions[first:last]
    for key, array in arrays.items():
        group.createDimension(f"{key}_n", len(array))
        group.createVariable(key, array.dtype, (f"{key}_n",))[:] = array


def _partition(mesh, ranks, grid=None):
    count = len(mesh["cell_id"])
    if count < ranks:
        raise ValueError("Each rank must own at least one cell")
    if len(np.unique(mesh["cell_id"])) != count:
        raise ValueError("Mesh cell IDs must be unique")
    rows = len(grid["latitude_centers"]) if grid else 0
    splits = (
        np.linspace(0, rows, ranks + 1, dtype=np.int64) * (count // rows)
        if rows >= ranks
        else np.linspace(0, count, ranks + 1, dtype=np.int64)
    )
    owners = np.full(len(mesh["lon"]), ranks, dtype=np.int32)
    for rank, (first, last) in enumerate(zip(splits[:-1], splits[1:])):
        nodes = mesh["indices"][mesh["offsets"][first] : mesh["offsets"][last]]
        np.minimum.at(owners, nodes, rank)
    return splits, owners


def _write_fixture(
    output, ranks, meshes, fields, fractions, *, case_id, norm, tolerance, oracle, structured=None
):
    if ranks < 1:
        raise ValueError("Ranks must be positive")
    if norm not in {"dstarea", "fracarea"}:
        raise ValueError("Invalid normalization")
    partitions = [
        _partition(mesh, ranks, structured[group] if structured else None)
        for group, mesh in zip(("source", "destination"), meshes, strict=True)
    ]
    for mesh, field, fraction in zip(meshes, fields, fractions):
        count = len(mesh["cell_id"])
        if field.shape != (count,) or not np.isfinite(field).all():
            raise ValueError("Field and mesh extents must agree and field must be finite")
        if fraction is not None and (
            fraction.shape != (count,)
            or not np.isfinite(fraction).all()
            or np.any((fraction < 0) | (fraction > 1 + tolerance))
        ):
            raise ValueError("Coverage fractions must be finite and within [0, 1] up to tolerance")
    logical = hashlib.sha256(
        json.dumps([case_id, norm, tolerance, oracle, structured], sort_keys=True).encode()
    )
    for mesh, field, fraction in zip(meshes, fields, fractions, strict=True):
        for array in [*(mesh[key] for key in _MESH_ARRAYS), field, fraction]:
            if array is not None:
                canonical = np.ascontiguousarray(
                    array.astype(array.dtype.newbyteorder("<"), copy=False)
                )
                logical.update(repr((canonical.shape, canonical.dtype.str)).encode())
                logical.update(memoryview(canonical).cast("B"))
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    attributes = {
        "schema_version": "1",
        "geometry": "great_circle",
        "norm": norm,
        "case_id": case_id,
        "ranks": str(ranks),
        "benchmark_abs_tolerance": str(tolerance),
    }
    shards = []
    for rank in range(ranks):
        path = output / f"rank-{rank}.nc"
        with Dataset(path, "w") as file:
            file.setncatts(attributes)
            for name, mesh, (splits, owners), field, fraction in zip(
                ("source", "destination"), meshes, partitions, fields, fractions, strict=True
            ):
                _write_mesh(file, name, mesh, splits, owners, rank, field, fraction)
        shard = {"file": path.name, "sha256": _checksum(path)}
        for name, (splits, _) in zip(
            ("source_cells", "destination_cells"), partitions, strict=True
        ):
            shard[name] = int(splits[rank + 1] - splits[rank])
        shards.append(shard)
    manifest = {
        "schema_version": 1,
        "case_id": case_id,
        "edge_model": "great_circle",
        "normalization": norm,
        "unmapped": "zero",
        "ranks": ranks,
        "abs_tolerance": tolerance,
        "oracle": oracle,
        "shards": shards,
        "fixture_id": logical.hexdigest(),
    }
    if structured is not None:
        manifest["structured"] = structured
    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    manifest["manifest_sha256"] = hashlib.sha256(payload.encode()).hexdigest()
    path = output / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return path


def _structured_grid(mesh):
    """Describe an equivalent CF rectilinear grid only when topology proves it."""
    lon, lat = mesh["lon"], mesh["lat"]
    split = np.flatnonzero(lat != lat[0])
    if not len(split) or np.any(np.diff(mesh["offsets"]) != 4):
        return None
    width = int(split[0])
    if width < 2 or len(lon) % width:
        return None
    xb, yb = lon[:width], lat[::width]
    if not (np.all(np.diff(xb) > 0) and np.all(np.diff(yb) > 0)):
        return None
    nx, ny = len(xb) - 1, len(yb) - 1
    if nx * ny != len(mesh["cell_id"]):
        return None
    if not (
        np.array_equal(lon.reshape(-1, width), np.broadcast_to(xb, (ny + 1, width)))
        and np.array_equal(lat.reshape(-1, width), np.broadcast_to(yb[:, None], (ny + 1, width)))
    ):
        return None
    first = (np.arange(ny)[:, None] * width + np.arange(nx)[None, :]).ravel()
    nodes = first[:, None] + np.array([0, 1, width, width + 1])
    if not np.array_equal(np.sort(mesh["indices"].reshape(-1, 4), axis=1), nodes):
        return None
    lc, bc = mesh["center_lon"].reshape(ny, nx), mesh["center_lat"].reshape(ny, nx)
    if not (
        np.allclose(lc, lc[0], rtol=0, atol=1e-10)
        and np.allclose(bc, bc[:, :1], rtol=0, atol=1e-10)
    ):
        return None
    return {
        "longitude_bounds": xb.tolist(),
        "latitude_bounds": yb.tolist(),
        "longitude_centers": lc[0].tolist(),
        "latitude_centers": bc[:, 0].tolist(),
    }


def prepare_tiny_fixture(
    output, ranks=2, masked=False, *, nx=8, ny=8, norm="dstarea", field_kind="constant"
):
    """Write a local spherical identity oracle with structured mesh coordinates."""
    from prepare_cases import assemble

    if nx < 3 or ny < 3:
        raise ValueError("An identity fixture requires at least three cells per dimension")
    xb = np.linspace(0, 8, nx + 1)
    yb = np.linspace(5, 13, ny + 1)
    lon, lat = np.meshgrid(xb, yb)
    first = (np.arange(ny)[:, None] * (nx + 1) + np.arange(nx)[None, :]).ravel()
    cells = first[:, None] + np.array([0, 1, nx + 2, nx + 1])
    mesh = assemble(lon.ravel(), lat.ravel(), cells, "great_circle")
    mesh["cell_id"] -= 1
    if masked:
        mesh["mask"][nx * (ny // 2) - 1 : nx * (ny // 2) + 1] = 0
    if field_kind == "constant":
        field = np.ones(nx * ny)
    elif field_kind == "smooth":
        field = np.sin(np.deg2rad(mesh["center_lon"]) * 8) + np.cos(
            np.deg2rad(mesh["center_lat"]) * 9
        )
    else:
        raise ValueError(f"Unknown identity fixture field: {field_kind}")
    expected = np.where(mesh["mask"] != 0, field, 0.0)
    fractions = mesh["mask"].astype(np.float64)
    return _write_fixture(
        output,
        ranks,
        (mesh, mesh),
        (field, expected),
        (fractions, fractions),
        case_id=f"identity-{nx}x{ny}-{field_kind}-{'masked' if masked else 'unmasked'}",
        norm=norm,
        tolerance=1e-8,
        oracle={"kind": "analytic_spherical_identity"},
        structured={group: _structured_grid(mesh) for group in ("source", "destination")},
    )


def prepare_paper_fixture(output, case, reference, ranks, *, abs_tolerance):
    """Convert prepared paper case and reference files to owned MPI/Dask shards."""
    case, reference = Path(case), Path(reference)
    if not np.isfinite(abs_tolerance) or abs_tolerance <= 0:
        raise ValueError("Specify a positive finite absolute tolerance")
    with Dataset(case) as file:
        if file.getncattr("geometry") != "great_circle":
            raise ValueError("The distributed benchmark currently requires great-circle geometry")
        meshes = [
            {key: np.asarray(file[name][key][:]) for key in _MESH_ARRAYS}
            for name in ("source", "destination")
        ]
        norm, case_id = file.getncattr("norm"), file.getncattr("case_id")
    with Dataset(reference) as file:
        if file.getncattr("status") != "complete":
            raise ValueError("The reference must be complete")
        source = np.asarray(file["src"][:])
        destination = np.asarray(file["dst"][:])
        covered = (np.asarray(file["src_covered"][:]), np.asarray(file["dst_covered"][:]))
        reference_areas = (np.asarray(file["src_area"][:]), np.asarray(file["dst_area"][:]))
    for mesh, area in zip(meshes, reference_areas, strict=True):
        if mesh["area"].shape != area.shape or not np.allclose(
            mesh["area"], area, rtol=1e-8, atol=1e-12
        ):
            raise ValueError("Reference and case cell areas differ")
    fractions = tuple(
        coverage / area for coverage, area in zip(covered, reference_areas, strict=True)
    )
    destination = np.where((meshes[1]["mask"] != 0) & (covered[1] > 0), destination, 0)
    grids = {
        group: _structured_grid(mesh)
        for group, mesh in zip(("source", "destination"), meshes, strict=True)
    }
    return _write_fixture(
        output,
        ranks,
        meshes,
        (source, destination),
        fractions,
        case_id=case_id,
        norm=norm,
        tolerance=abs_tolerance,
        oracle={
            "kind": "paper_reference",
            "case_sha256": _checksum(case),
            "reference_sha256": _checksum(reference),
        },
        structured=grids if all(grids.values()) else None,
    )


def load_manifest(path, *, verify=True):
    path = Path(path).resolve()
    manifest = json.loads(path.read_text())
    if manifest.get("schema_version") != 1 or len(manifest.get("shards", [])) != manifest.get(
        "ranks"
    ):
        raise ValueError("Invalid benchmark fixture manifest")
    identity = manifest["manifest_sha256"]
    payload = json.dumps(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"},
        sort_keys=True,
        separators=(",", ":"),
    )
    if hashlib.sha256(payload.encode()).hexdigest() != identity:
        raise ValueError("Fixture manifest checksum mismatch")
    seen = set()
    for rank, shard in enumerate(manifest["shards"]):
        file = path.parent / f"rank-{rank}.nc"
        if shard["file"] != file.name:
            raise ValueError("Fixture shards must be named and ordered by rank")
        if not verify:
            continue
        if _checksum(file) != shard["sha256"]:
            raise ValueError(f"Fixture checksum mismatch: {file.name}")
        with _NETCDF_LOCK, Dataset(file) as dataset:
            if dataset.getncattr("case_id") != manifest["case_id"]:
                raise ValueError(f"Fixture case ID differs: {file.name}")
            for group in ("source", "destination"):
                ids = np.asarray(dataset[group]["cell_id"][:])
                if len(ids) != shard[f"{group}_cells"]:
                    raise ValueError(f"Fixture cell count differs: {file.name}")
                for identifier in ids:
                    key = (group, int(identifier))
                    if key in seen:
                        raise ValueError(f"Duplicate {group} cell ID: {identifier}")
                    seen.add(key)
    return manifest


def _tile(path, group):
    with _NETCDF_LOCK, Dataset(path) as file:
        mesh = file[group]
        nodes = np.asfortranarray(np.column_stack((mesh["lon"][:], mesh["lat"][:])))
        return (
            nodes,
            np.asarray(mesh["offsets"][:]),
            np.asarray(mesh["indices"][:]),
            np.asarray(mesh["mask"][:]),
            np.asarray(mesh["node_id"][:]),
        )


def _read(path, group, name):
    with _NETCDF_LOCK, Dataset(path) as file:
        return np.asarray(file[group][name][:])


@dataclass
class TiledFixture:
    source_tiles: list
    destination_tiles: list
    field: object
    expected: np.ndarray
    destination_ids: np.ndarray
    source_mask: np.ndarray
    destination_mask: np.ndarray
    source_area: np.ndarray
    destination_area: np.ndarray
    manifest: dict
    source_fraction: np.ndarray | None
    destination_fraction: np.ndarray | None


def load_dask_fixture(path, *, verified_manifest=None, include_mesh_tiles=True):
    import dask.array as da
    import xarray as xr
    from dask import delayed

    path = Path(path).resolve()
    manifest = verified_manifest if verified_manifest is not None else load_manifest(path)
    shards = manifest["shards"]
    files = [path.parent / shard["file"] for shard in shards]

    def tiles(group):
        if not include_mesh_tiles:
            return []
        from axis import MeshTile

        return [
            MeshTile(shard[f"{group}_cells"], partial(_tile, file, group))
            for file, shard in zip(files, shards, strict=True)
        ]

    values = [
        da.from_delayed(
            delayed(_read)(file, "source", "field"),
            shape=(shard["source_cells"],),
            dtype=np.float64,
        )
        for file, shard in zip(files, shards, strict=True)
    ]

    def concatenate(group, name):
        return np.concatenate([_read(file, group, name) for file in files])

    def fractions(group):
        with _NETCDF_LOCK, Dataset(files[0]) as file:
            available = "expected_fraction" in file[group].variables
        return concatenate(group, "expected_fraction") if available else None

    return TiledFixture(
        tiles("source"),
        tiles("destination"),
        xr.DataArray(da.concatenate(values), dims=("cell",)),
        concatenate("destination", "expected"),
        concatenate("destination", "cell_id"),
        concatenate("source", "mask"),
        concatenate("destination", "mask"),
        concatenate("source", "area"),
        concatenate("destination", "area"),
        manifest,
        fractions("source"),
        fractions("destination"),
    )


def serial_axis_reference(fixture, method, normalization="dstarea"):
    """Reference the untiled native AXIS kernel for small integration tests."""
    from axis import axis_py

    def make_mesh(tiles):
        nodes, indices, masks, offsets = [], [], [], [0]
        node_start = 0
        for tile in tiles:
            xy, ends, conn, mask, _ = tile.load()
            nodes.append(xy)
            indices.append(conn + node_start)
            masks.append(mask)
            offsets.extend(ends[1:] + offsets[-1])
            node_start += len(xy)
        return axis_py.make_ugrid_mesh(
            np.asfortranarray(np.concatenate(nodes)),
            np.asarray(offsets),
            np.concatenate(indices),
            np.concatenate(masks),
        )

    matrix = axis_py._generate_local_weight_block(
        make_mesh(fixture.source_tiles),
        make_mesh(fixture.destination_tiles),
        {
            "method": method,
            "line_type": "great_circle",
            "unmapped": "ignore",
            "norm_type": normalization,
            "extrap_method": "none",
        },
    )
    return axis_py.apply_weights(matrix, np.asarray(fixture.field.compute()))
