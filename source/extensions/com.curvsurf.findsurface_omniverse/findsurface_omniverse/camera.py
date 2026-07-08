import math


EPSILON = 1.0e-8
PROJECTION_ORTHOGRAPHIC = "orthographic"
PROJECTION_PERSPECTIVE = "perspective"
MIN_FOV_DEGREES = 1.0
MAX_FOV_DEGREES = 160.0
DEFAULT_FIT_YAW_DEGREES = 18.0
DEFAULT_FIT_PITCH_DEGREES = 18.0


def add(a, b):
    return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]


def sub(a, b):
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def mul(v, s):
    return [v[0] * s, v[1] * s, v[2] * s]


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]


def length(v):
    return math.sqrt(dot(v, v))


def normalize(v, fallback=None):
    size = length(v)
    if size < EPSILON:
        return list(fallback or [0.0, 0.0, 0.0])
    return [v[0] / size, v[1] / size, v[2] / size]


def quat_normalize(q):
    size = math.sqrt(q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3])
    if size < EPSILON:
        return [1.0, 0.0, 0.0, 0.0]
    return [q[0] / size, q[1] / size, q[2] / size, q[3] / size]


def quat_multiply(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return quat_normalize(
        [
            aw * bw - ax * bx - ay * by - az * bz,
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
        ]
    )


def quat_from_axis_angle(axis, angle):
    axis = normalize(axis, [0.0, 1.0, 0.0])
    half = angle * 0.5
    s = math.sin(half)
    return quat_normalize([math.cos(half), axis[0] * s, axis[1] * s, axis[2] * s])


def quat_rotate(q, v):
    w, x, y, z = q
    qvec = [x, y, z]
    uv = cross(qvec, v)
    uuv = cross(qvec, uv)
    return add(v, add(mul(uv, 2.0 * w), mul(uuv, 2.0)))


def quat_from_basis(right, up, forward):
    # Local +Z points backward because the view direction is local -Z.
    m00, m01, m02 = right[0], up[0], -forward[0]
    m10, m11, m12 = right[1], up[1], -forward[1]
    m20, m21, m22 = right[2], up[2], -forward[2]
    trace = m00 + m11 + m22
    if trace > 0.0:
        s = math.sqrt(trace + 1.0) * 2.0
        return quat_normalize([(0.25 * s), (m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s])
    if m00 > m11 and m00 > m22:
        s = math.sqrt(1.0 + m00 - m11 - m22) * 2.0
        return quat_normalize([(m21 - m12) / s, 0.25 * s, (m01 + m10) / s, (m02 + m20) / s])
    if m11 > m22:
        s = math.sqrt(1.0 + m11 - m00 - m22) * 2.0
        return quat_normalize([(m02 - m20) / s, (m01 + m10) / s, 0.25 * s, (m12 + m21) / s])
    s = math.sqrt(1.0 + m22 - m00 - m11) * 2.0
    return quat_normalize([(m10 - m01) / s, (m02 + m20) / s, (m12 + m21) / s, 0.25 * s])


class OrbitCamera:
    def __init__(self, defaults=None):
        defaults = defaults or {}
        self.center = _float_list(defaults.get("center"), [0.0, 0.0, 0.0], 3)
        self.orientation = quat_normalize(_float_list(defaults.get("orientation"), [1.0, 0.0, 0.0, 0.0], 4))
        self.zoom = max(0.001, float(defaults.get("zoom", 1.0)))
        self.diameter = max(EPSILON, float(defaults.get("diameter", 1.0)))
        self.projection_mode = PROJECTION_PERSPECTIVE if defaults.get("projection_mode") == PROJECTION_PERSPECTIVE else PROJECTION_ORTHOGRAPHIC
        self.fov_degrees = 45.0
        self.default_fit_yaw_degrees = float(defaults.get("default_fit_yaw_degrees", DEFAULT_FIT_YAW_DEGREES))
        self.default_fit_pitch_degrees = float(defaults.get("default_fit_pitch_degrees", DEFAULT_FIT_PITCH_DEGREES))
        self.set_fov_degrees(defaults.get("fov_degrees", 45.0))

    @property
    def right(self):
        return normalize(quat_rotate(self.orientation, [1.0, 0.0, 0.0]), [1.0, 0.0, 0.0])

    @property
    def up(self):
        return normalize(quat_rotate(self.orientation, [0.0, 1.0, 0.0]), [0.0, 1.0, 0.0])

    @property
    def forward(self):
        return normalize(quat_rotate(self.orientation, [0.0, 0.0, -1.0]), [0.0, 0.0, -1.0])

    @property
    def position(self):
        distance = max(self.diameter, 1.0) * 2.0
        return sub(self.center, mul(self.forward, distance))

    @property
    def is_perspective(self):
        return self.projection_mode == PROJECTION_PERSPECTIVE

    def set_projection_mode(self, mode):
        self.projection_mode = PROJECTION_PERSPECTIVE if mode == PROJECTION_PERSPECTIVE else PROJECTION_ORTHOGRAPHIC

    def set_fov_degrees(self, fov_degrees):
        self.fov_degrees = max(MIN_FOV_DEGREES, min(MAX_FOV_DEGREES, float(fov_degrees)))

    def visible_fit_size(self):
        return max(self.diameter / max(self.zoom, EPSILON), EPSILON)

    def visible_height(self, aspect):
        fit_size = self.visible_fit_size()
        if aspect <= 1.0:
            return fit_size / max(aspect, EPSILON)
        return fit_size

    def perspective_distance(self, aspect):
        fov_radians = math.radians(self.fov_degrees)
        return max(self.visible_height(aspect) * 0.5 / max(math.tan(fov_radians * 0.5), EPSILON), EPSILON)

    def perspective_position(self, aspect):
        return sub(self.center, mul(self.forward, self.perspective_distance(aspect)))

    def fit(self, bounds_min, bounds_max):
        self.center = mul(add(bounds_min, bounds_max), 0.5)
        diagonal = sub(bounds_max, bounds_min)
        self.diameter = max(length(diagonal), 1.0)
        self.zoom = 1.0
        self._set_default_fit_orientation()

    def _set_default_fit_orientation(self):
        yaw = math.radians(self.default_fit_yaw_degrees)
        pitch = math.radians(self.default_fit_pitch_degrees)
        direction = [
            -math.sin(yaw) * math.cos(pitch),
            -math.sin(pitch),
            -math.cos(yaw) * math.cos(pitch),
        ]
        self.set_direction_up(direction, [0.0, 1.0, 0.0])

    def orbit_screen_drag(self, start_orientation, start_right, start_up, dx, dy):
        distance = math.sqrt(dx * dx + dy * dy)
        if distance < EPSILON:
            self.orientation = list(start_orientation)
            return
        axis = normalize(add(mul(start_right, -dy), mul(start_up, -dx)), start_up)
        delta = quat_from_axis_angle(axis, distance * 0.006)
        self.orientation = quat_multiply(delta, start_orientation)

    def orbit_pixels(self, dx, dy):
        distance = math.sqrt(dx * dx + dy * dy)
        if distance < EPSILON:
            return
        axis = normalize(add(mul(self.right, dy), mul(self.up, dx)), self.up)
        self.orientation = quat_multiply(quat_from_axis_angle(axis, distance * 0.006), self.orientation)

    def rotate_orientation_degrees(self, axis, degrees):
        angle = math.radians(float(degrees))
        if abs(angle) < EPSILON:
            return
        self.orientation = quat_multiply(quat_from_axis_angle(axis, angle), self.orientation)

    def roll_pixels(self, center_x, center_y, last_x, last_y, x, y):
        a = [last_x - center_x, center_y - last_y]
        b = [x - center_x, center_y - y]
        al = math.sqrt(a[0] * a[0] + a[1] * a[1])
        bl = math.sqrt(b[0] * b[0] + b[1] * b[1])
        if al < EPSILON or bl < EPSILON:
            return
        cross_z = a[0] * b[1] - a[1] * b[0]
        dot_ab = a[0] * b[0] + a[1] * b[1]
        angle = math.atan2(cross_z, dot_ab)
        self.orientation = quat_multiply(quat_from_axis_angle(self.forward, angle), self.orientation)

    def pan_pixels(self, dx, dy, pixel_scale):
        if pixel_scale < EPSILON:
            return
        self.center = sub(self.center, mul(self.right, dx / pixel_scale))
        self.center = add(self.center, mul(self.up, dy / pixel_scale))

    def zoom_steps(self, steps):
        self.zoom = max(0.001, min(1000.0, self.zoom * math.exp(steps * 0.12)))

    def set_position(self, position):
        forward = normalize(sub(self.center, position), self.forward)
        self.set_direction_up(forward, self.up)

    def set_direction_up(self, direction, up):
        forward = normalize(direction, self.forward)
        right = normalize(cross(forward, up), self.right)
        up = normalize(cross(right, forward), self.up)
        self.orientation = quat_from_basis(right, up, forward)


def _float_list(value, fallback, length):
    if not isinstance(value, (list, tuple)) or len(value) != length:
        value = fallback
    result = []
    for index in range(length):
        try:
            result.append(float(value[index]))
        except (TypeError, ValueError):
            result.append(float(fallback[index]))
    return result
