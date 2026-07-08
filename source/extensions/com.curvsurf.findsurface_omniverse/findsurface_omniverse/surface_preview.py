from dataclasses import dataclass, field
from math import cos, floor, pi, sin, sqrt
from typing import Any, Callable


Vec3 = tuple[float, float, float]
TransformPoint = Callable[[Vec3], Vec3]


@dataclass
class SurfaceResult:
    id: str
    type: str
    seed_position: Vec3
    seed_index: int = -1
    inlier_indices: list[int] = field(default_factory=list)
    active_generation: int = 0
    measurement_accuracy: float = 0.0
    rms_error: float = 0.0
    confidence: float | None = None
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class SurfacePreviewMesh:
    points: list[list[float]]
    colors: list[list[float]]
    vertex_counts: list[int]
    vertex_indices: list[int]
    wire_lines: list[list[list[float]]]


SURFACE_SOLID_COLOR = [0.72, 0.96, 0.92, 0.055]
SURFACE_WIRE_COLOR = [0.15, 1.0, 0.65, 1.0]
SURFACE_WIRE_THICKNESS = 2.5


def build_surface_preview_mesh(
    result: SurfaceResult,
    transform: TransformPoint | None = None,
    solid_color: list[float] | None = None,
    solid_alpha: float | None = None,
) -> SurfacePreviewMesh | None:
    transform = transform or (lambda point: point)
    if result.type == "Plane":
        mesh = _build_plane(result.parameters)
    elif result.type == "Sphere":
        mesh = _build_sphere(result.parameters, result.seed_position)
    elif result.type == "Cylinder":
        mesh = _build_cylinder(result.parameters, result.seed_position)
    elif result.type == "Cone":
        mesh = _build_cone(result.parameters, result.seed_position)
    elif result.type == "Torus":
        mesh = _build_torus(result.parameters, result.seed_position)
    else:
        return None

    points, vertex_counts, vertex_indices, wire_lines = mesh
    display_points = [_as_list(transform(point)) for point in points]
    display_wire_lines = [[_as_list(transform(point)) for point in line] for line in wire_lines]
    color = list(solid_color or SURFACE_SOLID_COLOR)
    if solid_alpha is not None:
        color[3] = float(solid_alpha)
    colors = [color[:] for _ in vertex_indices]
    return SurfacePreviewMesh(display_points, colors, vertex_counts, vertex_indices, display_wire_lines)


def demo_surface_results() -> list[SurfaceResult]:
    return [
        SurfaceResult(
            id="DemoPlane",
            type="Plane",
            seed_position=(-9.0, 0.0, 0.0),
            parameters={
                "corners": [
                    (-10.4, -0.8, 0.0),
                    (-7.6, -0.8, 0.0),
                    (-7.6, 0.8, 0.0),
                    (-10.4, 0.8, 0.0),
                ]
            },
        ),
        SurfaceResult(
            id="DemoSphere",
            type="Sphere",
            seed_position=(-4.5, 0.0, 0.0),
            parameters={"center": (-4.5, 0.0, 0.0), "radius": 0.85},
        ),
        SurfaceResult(
            id="DemoCylinder",
            type="Cylinder",
            seed_position=(0.0, 0.0, 0.0),
            parameters={"bottom": (0.0, 0.0, -1.2), "top": (0.0, 0.0, 1.2), "radius": 0.65},
        ),
        SurfaceResult(
            id="DemoCone",
            type="Cone",
            seed_position=(4.5, 0.0, 0.0),
            parameters={
                "bottom": (4.5, 0.0, -1.2),
                "top": (4.5, 0.0, 1.2),
                "bottom_radius": 0.75,
                "top_radius": 0.22,
            },
        ),
        SurfaceResult(
            id="DemoTorus",
            type="Torus",
            seed_position=(9.0, 0.0, 0.0),
            parameters={
                "center": (9.0, 0.0, 0.0),
                "x_axis": (1.0, 0.0, 0.0),
                "y_axis": (0.0, 1.0, 0.0),
                "z_axis": (0.0, 0.0, 1.0),
                "major_radius": 0.8,
                "tube_radius": 0.18,
                "sweep_angle": pi * 1.5,
            },
        ),
    ]


def mesh_bounds(meshes: list[SurfacePreviewMesh]) -> tuple[list[float], list[float]] | None:
    points = [point for mesh in meshes for point in mesh.points]
    if not points:
        return None
    return (
        [min(point[axis] for point in points) for axis in range(3)],
        [max(point[axis] for point in points) for axis in range(3)],
    )


def _build_plane(params: dict) -> tuple[list[Vec3], list[int], list[int], list[list[Vec3]]]:
    corners = list(params.get("corners") or [])
    if len(corners) != 4 and all(
        key in params for key in ("lower_left", "lower_right", "upper_right", "upper_left")
    ):
        corners = [
            params["lower_left"],
            params["lower_right"],
            params["upper_right"],
            params["upper_left"],
        ]
    if len(corners) != 4 and all(key in params for key in ("origin", "x_axis", "y_axis", "width", "height")):
        origin = tuple(params["origin"])
        x_axis = normalize(tuple(params["x_axis"]), (1.0, 0.0, 0.0))
        y_axis = normalize(tuple(params["y_axis"]), (0.0, 1.0, 0.0))
        width_offset = mul(x_axis, float(params["width"]) * 0.5)
        height_offset = mul(y_axis, float(params["height"]) * 0.5)
        corners = [
            sub(sub(origin, width_offset), height_offset),
            add(sub(origin, height_offset), width_offset),
            add(add(origin, width_offset), height_offset),
            add(sub(origin, width_offset), height_offset),
        ]
    if len(corners) != 4:
        center = tuple(params.get("center", params.get("origin", (0.0, 0.0, 0.0))))
        width = float(params.get("width", 1.0))
        height = float(params.get("height", 1.0))
        corners = [
            (center[0] - width * 0.5, center[1] - height * 0.5, center[2]),
            (center[0] + width * 0.5, center[1] - height * 0.5, center[2]),
            (center[0] + width * 0.5, center[1] + height * 0.5, center[2]),
            (center[0] - width * 0.5, center[1] + height * 0.5, center[2]),
        ]

    c0, c1, _, c3 = [tuple(corner) for corner in corners]
    u = sub(c1, c0)
    v = sub(c3, c0)
    u_len = max(distance(c1, c0), 1e-6)
    v_len = max(distance(c3, c0), 1e-6)
    unit = min(u_len, v_len) / 3.0
    u_breaks = _axis_breaks(u_len, unit)
    v_breaks = _axis_breaks(v_len, unit)

    points = []
    for v_value in v_breaks:
        for u_value in u_breaks:
            points.append(add(add(c0, mul(u, u_value / u_len)), mul(v, v_value / v_len)))

    column_count = len(u_breaks)
    vertex_counts = []
    vertex_indices = []
    for row in range(len(v_breaks) - 1):
        for column in range(len(u_breaks) - 1):
            a = row * column_count + column
            _append_double_sided_face(vertex_counts, vertex_indices, [a, a + 1, a + column_count + 1, a + column_count])

    wire_lines = _grid_lines(points, len(u_breaks), len(v_breaks))
    return points, vertex_counts, vertex_indices, wire_lines


def _build_sphere(params: dict, fallback_center: Vec3) -> tuple[list[Vec3], list[int], list[int], list[list[Vec3]]]:
    center = tuple(params.get("center", params.get("origin", fallback_center)))
    radius = float(params.get("radius", 1.0))
    lon_segments = 18
    lat_segments = 9
    points = []
    for lat_index in range(lat_segments + 1):
        latitude = -pi * 0.5 + pi * lat_index / lat_segments
        z = sin(latitude) * radius
        ring_radius = cos(latitude) * radius
        for lon_index in range(lon_segments):
            longitude = 2.0 * pi * lon_index / lon_segments
            points.append(
                (
                    center[0] + cos(longitude) * ring_radius,
                    center[1] + sin(longitude) * ring_radius,
                    center[2] + z,
                )
            )
    vertex_counts, vertex_indices = _ring_quad_faces(lat_segments + 1, lon_segments)
    wire_lines = _ring_wire_lines(points, lat_segments + 1, lon_segments, closed=True)
    return points, vertex_counts, vertex_indices, wire_lines


def _build_cylinder(params: dict, fallback_center: Vec3) -> tuple[list[Vec3], list[int], list[int], list[list[Vec3]]]:
    start, end = _axis_endpoints(params, fallback_center)
    radius = float(params.get("radius", 1.0))
    return _build_conical_frustum(start, end, radius, radius, height_segments=3, radial_segments=18)


def _build_cone(params: dict, fallback_center: Vec3) -> tuple[list[Vec3], list[int], list[int], list[list[Vec3]]]:
    start, end = _axis_endpoints(params, fallback_center)
    start_radius = float(params.get("start_radius", params.get("bottom_radius", 1.0)))
    end_radius = float(params.get("end_radius", params.get("top_radius", 0.0)))
    return _build_conical_frustum(start, end, start_radius, end_radius, height_segments=2, radial_segments=18)


def _build_torus(params: dict, fallback_center: Vec3) -> tuple[list[Vec3], list[int], list[int], list[list[Vec3]]]:
    center = tuple(params.get("center", params.get("origin", fallback_center)))
    x_axis, y_axis, z_axis = _frame_axes(params)
    major_radius = float(params.get("major_radius", params.get("mean_radius", 1.0)))
    tube_radius = float(params.get("tube_radius", params.get("minor_radius", 0.2)))
    sweep = max(min(abs(_sweep_radians(float(params.get("sweep_angle", 2.0 * pi)))), 2.0 * pi), 1e-6)
    major_angles = _angle_breaks(sweep, pi / 18.0)
    tube_segments = 18

    points = []
    for theta in major_angles:
        radial = add(mul(x_axis, cos(theta)), mul(y_axis, sin(theta)))
        ring_center = add(center, mul(radial, major_radius))
        for tube_index in range(tube_segments):
            phi = 2.0 * pi * tube_index / tube_segments
            points.append(add(ring_center, add(mul(radial, cos(phi) * tube_radius), mul(z_axis, sin(phi) * tube_radius))))

    vertex_counts, vertex_indices = _ring_quad_faces(len(major_angles), tube_segments)
    if sweep < 2.0 * pi - 1e-5:
        start_face = list(reversed(range(tube_segments)))
        end_offset = (len(major_angles) - 1) * tube_segments
        end_face = [end_offset + index for index in range(tube_segments)]
        _append_double_sided_face(vertex_counts, vertex_indices, start_face)
        _append_double_sided_face(vertex_counts, vertex_indices, end_face)
    wire_lines = _torus_wire_lines(points, len(major_angles), tube_segments)
    return points, vertex_counts, vertex_indices, wire_lines


def _build_conical_frustum(
    start: Vec3,
    end: Vec3,
    start_radius: float,
    end_radius: float,
    height_segments: int,
    radial_segments: int,
) -> tuple[list[Vec3], list[int], list[int], list[list[Vec3]]]:
    axis = normalize(sub(end, start), (0.0, 0.0, 1.0))
    x_axis, y_axis = _perpendicular_frame(axis)
    points = []
    for h_index in range(height_segments + 1):
        t = h_index / height_segments
        ring_center = add(start, mul(sub(end, start), t))
        radius = start_radius * (1.0 - t) + end_radius * t
        if radius <= 1e-8:
            points.extend([ring_center] * radial_segments)
        else:
            for radial_index in range(radial_segments):
                angle = 2.0 * pi * radial_index / radial_segments
                points.append(add(ring_center, add(mul(x_axis, cos(angle) * radius), mul(y_axis, sin(angle) * radius))))

    vertex_counts, vertex_indices = _ring_quad_faces(height_segments + 1, radial_segments)
    if start_radius > 1e-8:
        _append_double_sided_face(vertex_counts, vertex_indices, list(reversed(range(radial_segments))))
    if end_radius > 1e-8:
        end_offset = height_segments * radial_segments
        _append_double_sided_face(vertex_counts, vertex_indices, [end_offset + index for index in range(radial_segments)])
    wire_lines = _ring_wire_lines(points, height_segments + 1, radial_segments, closed=True)
    return points, vertex_counts, vertex_indices, wire_lines


def _axis_endpoints(params: dict, fallback_center: Vec3) -> tuple[Vec3, Vec3]:
    start = params.get("start", params.get("bottom"))
    end = params.get("end", params.get("top"))
    if start is not None and end is not None:
        return tuple(start), tuple(end)
    center = tuple(params.get("center", params.get("origin", fallback_center)))
    axis = normalize(tuple(params.get("axis", params.get("z_axis", (0.0, 0.0, 1.0)))), (0.0, 0.0, 1.0))
    height = float(params.get("height", 1.0))
    return add(center, mul(axis, -height * 0.5)), add(center, mul(axis, height * 0.5))


def _frame_axes(params: dict) -> tuple[Vec3, Vec3, Vec3]:
    z_axis = normalize(tuple(params.get("z_axis", params.get("axis", (0.0, 0.0, 1.0)))), (0.0, 0.0, 1.0))
    x_axis = params.get("x_axis")
    y_axis = params.get("y_axis")
    if x_axis is not None and y_axis is not None:
        return normalize(tuple(x_axis), (1.0, 0.0, 0.0)), normalize(tuple(y_axis), (0.0, 1.0, 0.0)), z_axis
    x, y = _perpendicular_frame(z_axis)
    return x, y, z_axis


def _perpendicular_frame(axis: Vec3) -> tuple[Vec3, Vec3]:
    helper = (0.0, 0.0, 1.0) if abs(axis[2]) < 0.9 else (0.0, 1.0, 0.0)
    x_axis = normalize(cross(helper, axis), (1.0, 0.0, 0.0))
    y_axis = normalize(cross(axis, x_axis), (0.0, 1.0, 0.0))
    return x_axis, y_axis


def _axis_breaks(length: float, unit: float) -> list[float]:
    if length <= 0.0:
        return [0.0, 0.0]
    unit = max(unit, 1e-9)
    full_segments = max(int(floor(length / unit)), 1)
    remainder = length - full_segments * unit
    if remainder <= length * 1e-6:
        return [min(index * unit, length) for index in range(full_segments + 1)]
    values = [0.0, remainder]
    values.extend(remainder + unit * index for index in range(1, full_segments + 1))
    values[-1] = length
    return values


def _angle_breaks(sweep: float, unit: float) -> list[float]:
    full_segments = int(floor(sweep / unit))
    values = [index * unit for index in range(full_segments + 1)]
    if not values or abs(values[-1] - sweep) > 1e-6:
        values.append(sweep)
    return values


def _ring_quad_faces(ring_count: int, ring_segments: int) -> tuple[list[int], list[int]]:
    vertex_counts = []
    vertex_indices = []
    for ring in range(ring_count - 1):
        next_ring = ring + 1
        for segment in range(ring_segments):
            next_segment = (segment + 1) % ring_segments
            face = [
                ring * ring_segments + segment,
                ring * ring_segments + next_segment,
                next_ring * ring_segments + next_segment,
                next_ring * ring_segments + segment,
            ]
            _append_double_sided_face(vertex_counts, vertex_indices, face)
    return vertex_counts, vertex_indices


def _append_double_sided_face(vertex_counts: list[int], vertex_indices: list[int], face: list[int]) -> None:
    vertex_counts.append(len(face))
    vertex_indices.extend(face)
    vertex_counts.append(len(face))
    vertex_indices.extend(reversed(face))


def _ring_wire_lines(points: list[Vec3], ring_count: int, ring_segments: int, closed: bool) -> list[list[Vec3]]:
    lines = []
    for ring in range(ring_count):
        offset = ring * ring_segments
        ring_line = [points[offset + index] for index in range(ring_segments)]
        if closed:
            ring_line.append(ring_line[0])
        lines.append(ring_line)
    step = max(1, ring_segments // 6)
    for segment in range(0, ring_segments, step):
        lines.append([points[ring * ring_segments + segment] for ring in range(ring_count)])
    return lines


def _torus_wire_lines(points: list[Vec3], major_count: int, tube_segments: int) -> list[list[Vec3]]:
    lines = []
    major_indices = list(range(0, major_count, 3))
    if major_count > 0 and (major_count - 1) not in major_indices:
        major_indices.append(major_count - 1)
    for ring in major_indices:
        offset = ring * tube_segments
        ring_line = [points[offset + index] for index in range(tube_segments)]
        ring_line.append(ring_line[0])
        lines.append(ring_line)
    tube_step = max(1, tube_segments // 6)
    for segment in range(0, tube_segments, tube_step):
        lines.append([points[ring * tube_segments + segment] for ring in range(major_count)])
    return lines


def _grid_lines(points: list[Vec3], column_count: int, row_count: int) -> list[list[Vec3]]:
    lines = []
    for row in range(row_count):
        lines.append([points[row * column_count + column] for column in range(column_count)])
    for column in range(column_count):
        lines.append([points[row * column_count + column] for row in range(row_count)])
    return lines


def _sweep_radians(value: float) -> float:
    if abs(value) <= 2.0 * pi + 1e-6:
        return value
    return value * pi / 180.0


def add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def mul(a: Vec3, scale: float) -> Vec3:
    return (a[0] * scale, a[1] * scale, a[2] * scale)


def dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def length(a: Vec3) -> float:
    return sqrt(dot(a, a))


def distance(a: Vec3, b: Vec3) -> float:
    return length(sub(a, b))


def normalize(a: Vec3, fallback: Vec3 = (0.0, 0.0, 1.0)) -> Vec3:
    size = length(a)
    if size <= 1e-12:
        return fallback
    return (a[0] / size, a[1] / size, a[2] / size)


def _as_list(point: Vec3) -> list[float]:
    return [float(point[0]), float(point[1]), float(point[2])]
