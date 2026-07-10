import copy
import json
import os


SCHEMA_VERSION = 1
CONFIG_FILE_NAME = "app_defaults.json"


DEFAULT_APP_CONFIG = {
    "schema_version": SCHEMA_VERSION,
    "_notes": [
        "Edit this file to change initial FindSurface app values.",
        "If this file is deleted, the app recreates it from built-in defaults.",
        "Workspace files can still restore their own saved settings after these defaults are applied.",
        "File dialog directories in this shared config should be extension-relative; local external paths are kept for the current session only.",
    ],
    "detection": {
        "detection_type": "Auto",
        "range_parameters": {
            "measurement_accuracy": {
                "label": "Measurement\nAccuracy",
                "value": 0.003,
                "slider_index": None,
                "min": 0.001,
                "max": 0.05,
            },
            "mean_distance": {
                "label": "Mean\nDistance",
                "value": 0.05,
                "slider_index": None,
                "min": 0.01,
                "max": 0.05,
            },
            "seed_radius": {
                "label": "Seed\nRadius",
                "value": 0.15,
                "slider_index": None,
                "min": 0.05,
                "max": 0.50,
            },
        },
        "radial_expansion": 5,
        "lateral_extension": 5,
        "auto_detect": True,
    },
    "display": {
        "point_size": 1.0,
        "point_color": [1.0, 1.0, 1.0, 1.0],
        "selected_point_color": [0.16, 0.17, 0.19, 1.0],
        "surface_color": [0.72, 0.96, 0.92, 0.055],
        "surface_wire_color": [0.15, 1.0, 0.65, 1.0],
        "inlier_negative_color": [0.0, 0.22, 1.0, 1.0],
        "inlier_zero_color": [1.0, 1.0, 0.0, 1.0],
        "inlier_positive_color": [1.0, 0.02, 0.0, 1.0],
        "inlier_negative_sigma": -1.0,
        "inlier_positive_sigma": 1.0,
        "global_visibility": {
            "outlier_points": True,
            "surface_meshes": True,
            "inlier_points": True,
        },
    },
    "picking": {
        "probe_radius_px": 6.0,
        "pick_nearest_on_probe_miss": True,
    },
    "preview": {
        "sticky_auto_preview": True,
        "sticky_auto_preview_timeout_ms": 500,
    },
    "parameter_pad": {
        "default_axes": {
            "x": "seed_radius",
            "y": "measurement_accuracy",
        },
    },
    "import": {
        "max_points": 200000,
        "target_points": 100000,
        "overflow_policy": "ask",
        "sample_seed": None,
        "include_mesh_vertices": False,
    },
    "recent_file_directories": {
        "import_points": None,
        "load_workspace": None,
        "save_workspace": None,
        "export_geometries": None,
    },
    "preset_file_directories": {
        "import_points": "data/presets/pointclouds",
        "load_workspace": "data/presets/workspaces",
    },
    "camera": {
        "projection_mode": "orthographic",
        "center": [0.0, 0.0, 0.0],
        "orientation": [1.0, 0.0, 0.0, 0.0],
        "zoom": 1.0,
        "diameter": 1.0,
        "fov_degrees": 45.0,
        "default_fit_yaw_degrees": 18.0,
        "default_fit_pitch_degrees": 18.0,
    },
}


class AppConfigError(ValueError):
    pass


def default_config_path():
    return os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "config", CONFIG_FILE_NAME))


def load_app_config(path=None):
    path = os.path.normpath(path or default_config_path())
    created = False
    if not os.path.exists(path):
        write_app_config(path, DEFAULT_APP_CONFIG)
        created = True
        data = {}
    else:
        try:
            with open(path, "r", encoding="utf-8") as file:
                data = json.load(file)
        except json.JSONDecodeError as exc:
            raise AppConfigError(f"Invalid JSON in app defaults file '{path}': {exc}") from exc
        except OSError as exc:
            raise AppConfigError(f"Failed to read app defaults file '{path}': {exc}") from exc
        if not isinstance(data, dict):
            raise AppConfigError(f"App defaults file '{path}' must contain a JSON object.")

    config = _deep_merge(DEFAULT_APP_CONFIG, data)
    config["schema_version"] = int(config.get("schema_version") or SCHEMA_VERSION)
    return config, path, created


def write_app_config(path, config):
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    text = json.dumps(config, indent=2, sort_keys=False)
    with open(path, "w", encoding="utf-8", newline="\n") as file:
        file.write(text)
        file.write("\n")


def range_parameter_defaults(config, fallback, slider_steps=10, minimum_step=0.0001):
    range_config = _dict_at(config, ("detection", "range_parameters"))
    defaults = {}
    for name, fallback_values in fallback.items():
        fallback_label, fallback_value, fallback_minimum, fallback_maximum = fallback_values
        item = range_config.get(name, {}) if isinstance(range_config.get(name), dict) else {}
        label = str(item.get("label", fallback_label))
        value = _as_float(item.get("value"), fallback_value)
        minimum = _as_float(item.get("min"), fallback_minimum)
        maximum = _as_float(item.get("max"), fallback_maximum)
        if maximum < minimum:
            minimum, maximum = maximum, minimum
        if item.get("slider_index") is not None:
            value = _range_slider_value_for_index(
                item.get("slider_index"),
                minimum,
                maximum,
                slider_steps=slider_steps,
                minimum_step=minimum_step,
            )
        else:
            value = max(minimum, min(maximum, value))
        defaults[name] = (label, value, minimum, maximum)
    return defaults


def parameter_pad_default_axes(config, fallback, allowed_parameters):
    axes = _dict_at(config, ("parameter_pad", "default_axes"))
    result = dict(fallback)
    allowed = set(allowed_parameters)
    for axis in ("x", "y"):
        value = axes.get(axis)
        if value in allowed:
            result[axis] = value
    return result


def config_value(config, path, fallback=None):
    current = config
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return fallback
        current = current[key]
    return current


def config_bool(config, path, fallback=False):
    value = config_value(config, path, fallback)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return bool(fallback if value is None else value)


def config_float(config, path, fallback=0.0, minimum=None, maximum=None):
    value = _as_float(config_value(config, path, fallback), fallback)
    if minimum is not None:
        value = max(float(minimum), value)
    if maximum is not None:
        value = min(float(maximum), value)
    return value


def config_int(config, path, fallback=0, minimum=None, maximum=None):
    try:
        value = int(config_value(config, path, fallback))
    except (TypeError, ValueError):
        value = int(fallback)
    if minimum is not None:
        value = max(int(minimum), value)
    if maximum is not None:
        value = min(int(maximum), value)
    return value


def config_rgba(config, path, fallback):
    source = config_value(config, path, fallback)
    if not isinstance(source, (list, tuple)):
        source = fallback
    values = list(source)
    while len(values) < 4:
        values.append(1.0)
    return [max(0.0, min(1.0, _as_float(values[index], fallback[index]))) for index in range(4)]


def config_float_list(config, path, fallback, length):
    source = config_value(config, path, fallback)
    if not isinstance(source, (list, tuple)):
        source = fallback
    values = list(source)
    if len(values) != length:
        values = list(fallback)
    return [_as_float(values[index], fallback[index]) for index in range(length)]


def _deep_merge(defaults, overrides):
    result = copy.deepcopy(defaults)
    for key, value in (overrides or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _dict_at(config, path):
    value = config_value(config, path, {})
    return value if isinstance(value, dict) else {}


def _as_float(value, fallback):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(fallback)


def _range_slider_value_for_index(index, minimum, maximum, slider_steps=10, minimum_step=0.0001):
    minimum = float(minimum)
    maximum = float(maximum)
    count = _range_slider_index_count(minimum, maximum, slider_steps, minimum_step)
    if count <= 0:
        return max(float(minimum_step), minimum)
    try:
        index = int(index)
    except (TypeError, ValueError):
        index = 0
    index = max(0, min(count, index))
    if index == count:
        return maximum
    value = minimum + _range_slider_value_step(minimum, maximum, slider_steps, minimum_step) * index
    return max(minimum, min(maximum, value))


def _range_slider_index_count(minimum, maximum, slider_steps=10, minimum_step=0.0001):
    interval = max(float(maximum) - float(minimum), 0.0)
    if interval <= 0.0:
        return 0
    step = _range_slider_value_step(minimum, maximum, slider_steps, minimum_step)
    if step <= 0.0:
        return 0
    return max(1, int(round(interval / step)))


def _range_slider_value_step(minimum, maximum, slider_steps=10, minimum_step=0.0001):
    interval = max(float(maximum) - float(minimum), 0.0)
    slider_steps = max(1, int(slider_steps))
    minimum_step = max(0.0, float(minimum_step))
    if interval < minimum_step * slider_steps:
        return minimum_step
    return interval / slider_steps
