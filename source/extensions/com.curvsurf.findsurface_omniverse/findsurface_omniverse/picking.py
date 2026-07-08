import math

from .camera import dot, sub


def pick_point_orthographic(points, active_mask, camera, viewport_size, screen_xy, probe_radius_px):
    width, height = viewport_size
    if width <= 0.0 or height <= 0.0:
        return None
    screen_x, screen_y = screen_xy
    camera_position = camera.position
    pixel_scale = min(width, height) * camera.zoom / max(camera.diameter, 1.0e-8)
    best_index = None
    best_depth = float("inf")
    radius_sq = probe_radius_px * probe_radius_px
    for index, point in enumerate(points):
        if index >= len(active_mask) or not active_mask[index]:
            continue
        rel = sub(point, camera.center)
        px = width * 0.5 + dot(rel, camera.right) * pixel_scale
        py = height * 0.5 - dot(rel, camera.up) * pixel_scale
        dx = px - screen_x
        dy = py - screen_y
        if dx * dx + dy * dy > radius_sq:
            continue
        depth = dot(sub(point, camera_position), camera.forward)
        if depth < 0.0:
            continue
        if depth < best_depth:
            best_depth = depth
            best_index = index
    return best_index


def pick_point_perspective(points, active_mask, camera, viewport_size, screen_xy, probe_radius_px, camera_position=None):
    width, height = viewport_size
    if width <= 0.0 or height <= 0.0:
        return None
    screen_x, screen_y = screen_xy
    aspect = width / max(height, 1.0e-8)
    origin = camera_position or camera.perspective_position(aspect)
    focal_px = height * 0.5 / max(math.tan(math.radians(camera.fov_degrees) * 0.5), 1.0e-8)
    best_index = None
    best_depth = float("inf")
    best_screen_dist_sq = float("inf")
    radius_sq = probe_radius_px * probe_radius_px
    for index, point in enumerate(points):
        if index >= len(active_mask) or not active_mask[index]:
            continue
        rel = sub(point, origin)
        depth = dot(rel, camera.forward)
        if depth <= 1.0e-8:
            continue
        px = width * 0.5 + dot(rel, camera.right) * focal_px / depth
        py = height * 0.5 - dot(rel, camera.up) * focal_px / depth
        dx = px - screen_x
        dy = py - screen_y
        screen_dist_sq = dx * dx + dy * dy
        if screen_dist_sq > radius_sq:
            continue
        if screen_dist_sq < best_screen_dist_sq or (
            abs(screen_dist_sq - best_screen_dist_sq) <= 1.0e-8 and depth < best_depth
        ):
            best_screen_dist_sq = screen_dist_sq
            best_depth = depth
            best_index = index
    return best_index


__all__ = ["pick_point_orthographic", "pick_point_perspective"]
