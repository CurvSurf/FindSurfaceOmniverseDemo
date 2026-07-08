import os
import random
import re
from ctypes import c_float
from dataclasses import dataclass


Float3 = c_float * 3
APP_MAX_POINTS = 200_000
DEFAULT_SAMPLE_TARGET = 100_000
USD_EXTENSIONS = {".usd", ".usda", ".usdc"}
TEXT_EXTENSIONS = {".xyz", ".pts", ".ptx", ".ply", ".pcd", ".obj"}
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | USD_EXTENSIONS
PROGRESS_INTERVAL_POINTS = 10_000


class ImportCanceledError(RuntimeError):
    pass


class ImportCancelToken:
    def __init__(self):
        self._canceled = False

    def cancel(self):
        self._canceled = True

    def is_canceled(self):
        return self._canceled


@dataclass(frozen=True)
class ImportProgress:
    phase: str
    current: int | None = None
    total: int | None = None
    path: str | None = None
    message: str | None = None


class PointCloudSizeError(ValueError):
    def __init__(self, message, source_point_count=None, max_points=None, target_points=None, path=None):
        super().__init__(message)
        self.source_point_count = source_point_count
        self.max_points = max_points
        self.target_points = target_points
        self.path = path


@dataclass(frozen=True)
class ImportOptions:
    max_points: int = APP_MAX_POINTS
    target_points: int = DEFAULT_SAMPLE_TARGET
    overflow_policy: str = "ask"
    sample_seed: int | None = None
    usd_time_code: object | None = None
    include_mesh_vertices: bool = False
    retain_sampled_source_indices: bool = False
    max_source_index_mapping_points: int = APP_MAX_POINTS

    def normalized(self):
        max_points = max(1, int(self.max_points))
        target_points = max(1, min(int(self.target_points), max_points))
        max_source_index_mapping_points = max(0, int(self.max_source_index_mapping_points))
        policy = str(self.overflow_policy or "sample").lower()
        if policy not in {"ask", "sample", "reject"}:
            raise ValueError(f"Unsupported point-cloud overflow policy: {self.overflow_policy}")
        return ImportOptions(
            max_points=max_points,
            target_points=target_points,
            overflow_policy=policy,
            sample_seed=self.sample_seed,
            usd_time_code=self.usd_time_code,
            include_mesh_vertices=bool(self.include_mesh_vertices),
            retain_sampled_source_indices=bool(self.retain_sampled_source_indices),
            max_source_index_mapping_points=max_source_index_mapping_points,
        )


class PointCloudData:
    def __init__(self, path, points, metadata=None):
        self.path = path
        self.points = points
        self.metadata = dict(metadata or {})
        self.point_buffer = self._build_point_buffer(points)
        self.bounds_min, self.bounds_max = self._compute_bounds(points)

    @property
    def count(self):
        return len(self.points)

    @staticmethod
    def _build_point_buffer(points):
        array_type = Float3 * len(points)
        return array_type(*[Float3(float(point[0]), float(point[1]), float(point[2])) for point in points])

    @staticmethod
    def _compute_bounds(points):
        if not points:
            return [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
        mins = list(points[0])
        maxs = list(points[0])
        for point in points[1:]:
            for axis in range(3):
                mins[axis] = min(mins[axis], point[axis])
                maxs[axis] = max(maxs[axis], point[axis])
        return mins, maxs


def load_point_cloud(path, options=None, progress_callback=None, cancel_token=None):
    options = (options or ImportOptions()).normalized()
    source_count = None
    if options.overflow_policy == "ask":
        source_count = _count_points(path, options, progress_callback, cancel_token)
        if source_count > options.max_points:
            raise PointCloudSizeError(
                f"Point cloud has {source_count:,} points, exceeding the {options.max_points:,} point limit.",
                source_point_count=source_count,
                max_points=options.max_points,
                target_points=options.target_points,
                path=path,
            )
    ext = os.path.splitext(path)[1].lower()
    point_iter = _iter_points_for_path(path, ext, options)
    _emit_progress(progress_callback, "parsing", 0, source_count, path)
    points, metadata = _collect_points(point_iter, options, progress_callback, cancel_token, path, source_count)
    if not points:
        raise ValueError("No XYZ points were found in the selected file.")
    _emit_progress(progress_callback, "finalizing", len(points), source_count or metadata.get("source_point_count"), path)
    metadata.update(
        {
            "source_path": path,
            "source_format": ext.lstrip("."),
            "imported_point_count": len(points),
        }
    )
    return PointCloudData(path, points, metadata)


def _iter_points_for_path(path, ext, options):
    if ext == ".obj":
        return _iter_obj(path)
    elif ext == ".ply":
        return _iter_ply(path)
    elif ext == ".pcd":
        return _iter_pcd(path)
    elif ext in {".xyz", ".pts", ".ptx"}:
        return _iter_plain_xyz(path)
    elif ext in USD_EXTENSIONS:
        return _iter_usd_points(path, options.usd_time_code, options.include_mesh_vertices)
    else:
        raise ValueError(f"Unsupported point-cloud format: {ext}")


def _count_points(path, options, progress_callback=None, cancel_token=None):
    ext = os.path.splitext(path)[1].lower()
    count = 0
    _emit_progress(progress_callback, "counting", count, None, path)
    for _point in _iter_points_for_path(path, ext, options):
        count += 1
        if count % PROGRESS_INTERVAL_POINTS == 0:
            _check_canceled(cancel_token)
            _emit_progress(progress_callback, "counting", count, None, path)
    _check_canceled(cancel_token)
    _emit_progress(progress_callback, "counting", count, count, path)
    return count


def _collect_points(point_iter, options, progress_callback=None, cancel_token=None, path=None, expected_total=None):
    all_points = []
    reservoir = None
    source_indices = None
    total_count = 0
    rng = random.Random(options.sample_seed)
    sample_seed = options.sample_seed

    for point in point_iter:
        total_count += 1
        if total_count % PROGRESS_INTERVAL_POINTS == 0:
            _check_canceled(cancel_token)
            _emit_progress(
                progress_callback,
                "sampling" if reservoir is not None else "parsing",
                total_count,
                expected_total,
                path,
            )
        if reservoir is not None:
            replacement_index = rng.randrange(total_count)
            if replacement_index < options.target_points:
                reservoir[replacement_index] = point
                source_indices[replacement_index] = total_count - 1
            continue

        if total_count <= options.max_points:
            all_points.append(point)
            continue

        if options.overflow_policy in {"ask", "reject"}:
            raise PointCloudSizeError(
                f"Point cloud has more than {options.max_points:,} points. "
                "Import with sampling enabled or choose a smaller file.",
                source_point_count=total_count,
                max_points=options.max_points,
                target_points=options.target_points,
            )

        if sample_seed is None:
            sample_seed = rng.randrange(0, 2**32)
            rng.seed(sample_seed)
        indexed_points = list(enumerate(all_points))
        indexed_points.append((total_count - 1, point))
        rng.shuffle(indexed_points)
        indexed_points = indexed_points[: options.target_points]
        source_indices = [index for index, _point in indexed_points]
        reservoir = [_point for _index, _point in indexed_points]
        all_points = None
        _emit_progress(progress_callback, "sampling", total_count, expected_total, path)

    _check_canceled(cancel_token)
    if reservoir is None:
        return all_points, {
            "source_point_count": total_count,
            "sampling_policy": "none",
            "sample_seed": None,
            "sampled_source_indices": None,
            "sampled_source_indices_retained": False,
            "sampled_source_indices_omitted_reason": None,
        }

    sampled = sorted(zip(source_indices, reservoir), key=lambda item: item[0])
    retain_mapping = (
        options.retain_sampled_source_indices
        and len(sampled) <= options.max_source_index_mapping_points
    )
    omitted_reason = None
    if not retain_mapping:
        omitted_reason = "memory_limit" if options.retain_sampled_source_indices else "disabled"
    return [point for _index, point in sampled], {
        "source_point_count": total_count,
        "sampling_policy": "reservoir",
        "sample_seed": sample_seed,
        "sampled_source_indices": [index for index, _point in sampled] if retain_mapping else None,
        "sampled_source_indices_retained": retain_mapping,
        "sampled_source_indices_omitted_reason": omitted_reason,
    }


def _emit_progress(callback, phase, current=None, total=None, path=None, message=None):
    if not callback:
        return
    callback(ImportProgress(phase=phase, current=current, total=total, path=path, message=message))


def _check_canceled(cancel_token):
    if not cancel_token:
        return
    is_canceled = getattr(cancel_token, "is_canceled", None)
    canceled = is_canceled() if callable(is_canceled) else bool(getattr(cancel_token, "canceled", False))
    if canceled:
        raise ImportCanceledError("Import canceled.")


def _try_point(parts):
    if len(parts) < 3:
        return None
    try:
        return [float(parts[0]), float(parts[1]), float(parts[2])]
    except ValueError:
        return None


def _iter_plain_xyz(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as stream:
        for line in stream:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            point = _try_point(stripped.replace(",", " ").split())
            if point:
                yield point


def _iter_obj(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as stream:
        for line in stream:
            if not line.startswith("v "):
                continue
            point = _try_point(line.split()[1:4])
            if point:
                yield point


def _iter_ply(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as stream:
        vertex_count = 0
        ascii_format = False
        for line in stream:
            stripped = line.strip()
            if stripped == "format ascii 1.0":
                ascii_format = True
            elif stripped.startswith("element vertex "):
                vertex_count = int(stripped.split()[-1])
            elif stripped == "end_header":
                break
        if not ascii_format:
            raise ValueError("Only ASCII PLY point clouds are supported in this minimal loader.")
        for _ in range(vertex_count):
            point = _try_point(stream.readline().split())
            if point:
                yield point


def _iter_pcd(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as stream:
        fields = []
        data_mode = ""
        for line in stream:
            stripped = line.strip()
            lower = stripped.lower()
            if lower.startswith("fields "):
                fields = stripped.split()[1:]
            elif lower.startswith("data "):
                data_mode = lower.split()[-1]
                break
        if data_mode != "ascii":
            raise ValueError("Only ASCII PCD point clouds are supported in this minimal loader.")
        try:
            indices = [fields.index("x"), fields.index("y"), fields.index("z")]
        except ValueError as exc:
            raise ValueError("PCD file must contain x, y, and z fields.") from exc

        for line in stream:
            parts = line.split()
            if len(parts) <= max(indices):
                continue
            point = _try_point([parts[index] for index in indices])
            if point:
                yield point


def _iter_usd_points(path, time_code=None, include_mesh_vertices=False):
    try:
        from pxr import Gf, Usd, UsdGeom
    except ImportError as exc:
        if _looks_like_text_usd(path):
            yield from _iter_text_usd_points(path, include_mesh_vertices=include_mesh_vertices)
            return
        raise ValueError(
            "USD point import requires the pxr USD Python modules. "
            "Make sure the omni.usd extension is enabled."
        ) from exc

    stage = Usd.Stage.Open(path)
    if not stage:
        raise ValueError(f"Failed to open USD stage: {path}")

    if time_code is None:
        time_code = Usd.TimeCode.Default()
    xform_cache = UsdGeom.XformCache(time_code)
    found_points = False

    for prim in stage.Traverse():
        points_schema = UsdGeom.Points(prim)
        if points_schema:
            points_attr = points_schema.GetPointsAttr()
        elif include_mesh_vertices:
            mesh_schema = UsdGeom.Mesh(prim)
            if not mesh_schema:
                continue
            points_attr = mesh_schema.GetPointsAttr()
        else:
            continue

        points = points_attr.Get(time_code)
        if not points:
            continue
        found_points = True
        transform = xform_cache.GetLocalToWorldTransform(prim)
        for point in points:
            transformed = transform.Transform(Gf.Vec3d(point[0], point[1], point[2]))
            yield [float(transformed[0]), float(transformed[1]), float(transformed[2])]

    if not found_points:
        return


_TEXT_USD_POINT_PATTERN = re.compile(
    r"\(\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*,\s*"
    r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*,\s*"
    r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*\)"
)
_TEXT_USD_POINTS_PRIM_PATTERN = re.compile(r'\b(?:def|over|class)\s+Points\s+"')
_TEXT_USD_POINTS_OR_MESH_PRIM_PATTERN = re.compile(r'\b(?:def|over|class)\s+(?:Points|Mesh)\s+"')
_TEXT_USD_POINTS_ATTR_PATTERN = re.compile(r"\b(?:point3[fd]|float3|double3)\[\]\s+points\s*=\s*\[")


def _looks_like_text_usd(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as stream:
            for line in stream:
                stripped = line.strip()
                if not stripped:
                    continue
                return stripped.startswith("#usda")
    except OSError:
        return False
    return False


def _iter_text_usd_points(path, include_mesh_vertices=False):
    point_source_prim_pattern = (
        _TEXT_USD_POINTS_OR_MESH_PRIM_PATTERN if include_mesh_vertices else _TEXT_USD_POINTS_PRIM_PATTERN
    )
    in_points_prim = False
    pending_points_prim = False
    points_prim_depth = 0
    in_points_attr = False
    bracket_depth = 0
    brace_depth = 0
    found_points = False
    with open(path, "r", encoding="utf-8", errors="ignore") as stream:
        for line in stream:
            stripped = line.strip()
            if stripped.startswith("#"):
                continue

            opens = line.count("{")
            closes = line.count("}")
            depth_after_line = brace_depth + opens - closes

            if not in_points_prim:
                if point_source_prim_pattern.search(line):
                    pending_points_prim = True
                if pending_points_prim and opens:
                    in_points_prim = True
                    pending_points_prim = False
                    points_prim_depth = depth_after_line

            if in_points_prim:
                search_line = line
                if not in_points_attr:
                    attr_match = _TEXT_USD_POINTS_ATTR_PATTERN.search(line)
                    if attr_match:
                        in_points_attr = True
                        found_points = True
                        search_line = line[attr_match.end() :]
                        bracket_depth = 1

                if in_points_attr:
                    for match in _TEXT_USD_POINT_PATTERN.finditer(search_line):
                        yield [float(match.group(1)), float(match.group(2)), float(match.group(3))]

                    bracket_depth += search_line.count("[") - search_line.count("]")
                    if bracket_depth <= 0:
                        in_points_attr = False
                        bracket_depth = 0

            brace_depth = depth_after_line
            if in_points_prim and brace_depth < points_prim_depth:
                in_points_prim = False
                in_points_attr = False
                bracket_depth = 0
                points_prim_depth = 0
    if not found_points:
        return
