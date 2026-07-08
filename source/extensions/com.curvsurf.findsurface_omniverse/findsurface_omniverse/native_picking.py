import ctypes
import math
import os
import platform
import shutil
import subprocess
from pathlib import Path


class _NativeHistogramResult(ctypes.Structure):
    _fields_ = [
        ("count", ctypes.c_int),
        ("source_count", ctypes.c_int),
        ("excluded_count", ctypes.c_int),
        ("bin_count", ctypes.c_int),
        ("negative_count", ctypes.c_int),
        ("zero_count", ctypes.c_int),
        ("positive_count", ctypes.c_int),
        ("max_bin_count", ctypes.c_int),
        ("minimum", ctypes.c_double),
        ("maximum", ctypes.c_double),
        ("mean", ctypes.c_double),
        ("sigma", ctypes.c_double),
        ("source_sigma", ctypes.c_double),
        ("range_min", ctypes.c_double),
        ("range_max", ctypes.c_double),
        ("mean_fraction", ctypes.c_double),
        ("zero_fraction", ctypes.c_double),
    ]


class NativePointPicker:
    def __init__(self, library_path=None, build_if_missing=True):
        self.library_path = Path(library_path) if library_path else default_library_path()
        if not self.library_path.exists() and library_path is None and build_if_missing:
            build_default_library()
        if not self.library_path.exists():
            raise FileNotFoundError(f"FindSurface picking library was not found: {self.library_path}")
        self._lib = ctypes.CDLL(str(self.library_path))
        self._bind_functions()

    def pick_orthographic(
        self,
        point_buffer,
        active_mask_buffer,
        point_count,
        camera,
        viewport_size,
        screen_xy,
        probe_radius_px,
        fallback_to_nearest=False,
    ):
        width, height = viewport_size
        if point_count <= 0 or width <= 0.0 or height <= 0.0:
            return None
        pixel_scale = min(width, height) * camera.zoom / max(camera.diameter, 1.0e-8)
        if pixel_scale <= 1.0e-8:
            return None
        active_ptr = ctypes.cast(active_mask_buffer, ctypes.POINTER(ctypes.c_uint8)) if active_mask_buffer else None
        index = self._lib.fs_pick_point_orthographic(
            ctypes.cast(point_buffer, ctypes.c_void_p),
            active_ptr,
            int(point_count),
            _float3(camera.position),
            _float3(camera.center),
            _float3(camera.right),
            _float3(camera.up),
            _float3(camera.forward),
            ctypes.c_float(float(width)),
            ctypes.c_float(float(height)),
            ctypes.c_float(float(screen_xy[0])),
            ctypes.c_float(float(screen_xy[1])),
            ctypes.c_float(float(probe_radius_px)),
            ctypes.c_float(float(pixel_scale)),
            ctypes.c_int(1 if fallback_to_nearest else 0),
        )
        return int(index) if index >= 0 else None

    def build_inlier_distance_histogram(
        self,
        point_buffer,
        point_count,
        inlier_indices,
        surface_type,
        surface_params,
        bin_count,
        measurement_accuracy=0.0,
        rms_error=0.0,
    ):
        histogram_func = getattr(self, "_histogram_func", None)
        if histogram_func is None or point_buffer is None or point_count <= 0:
            return None
        indices = [int(index) for index in (inlier_indices or [])]
        if not indices:
            return None
        params = [float(value) for value in (surface_params or [])]
        if not params:
            return None

        max_bins = 47
        index_array = (ctypes.c_int * len(indices))(*indices)
        param_array = (ctypes.c_double * len(params))(*params)
        result = _NativeHistogramResult()
        counts = (ctypes.c_int * max_bins)()
        starts = (ctypes.c_double * max_bins)()
        ends = (ctypes.c_double * max_bins)()
        centers = (ctypes.c_double * max_bins)()
        fractions = (ctypes.c_double * max_bins)()
        percents = (ctypes.c_double * max_bins)()
        sigma_offsets = (ctypes.c_double * max_bins)()
        sigma_offset_valid = (ctypes.c_uint8 * max_bins)()

        ok = histogram_func(
            ctypes.cast(point_buffer, ctypes.c_void_p),
            int(point_count),
            index_array,
            len(indices),
            int(surface_type),
            param_array,
            int(bin_count or 0),
            ctypes.c_double(float(measurement_accuracy or 0.0)),
            ctypes.c_double(float(rms_error or 0.0)),
            ctypes.byref(result),
            counts,
            starts,
            ends,
            centers,
            fractions,
            percents,
            sigma_offsets,
            sigma_offset_valid,
        )
        if not ok:
            return None
        bins = []
        for index in range(result.bin_count):
            bins.append(
                {
                    "start": starts[index],
                    "end": ends[index],
                    "center": centers[index],
                    "count": counts[index],
                    "fraction": fractions[index],
                    "percent": percents[index],
                    "sigma_offset": sigma_offsets[index] if sigma_offset_valid[index] else None,
                }
            )
        return {
            "count": result.count,
            "source_count": result.source_count,
            "excluded_count": result.excluded_count,
            "bin_count": result.bin_count,
            "min": result.minimum,
            "max": result.maximum,
            "mean": result.mean,
            "sigma": result.sigma,
            "source_sigma": result.source_sigma,
            "range_min": result.range_min,
            "range_max": result.range_max,
            "mean_fraction": result.mean_fraction,
            "zero_fraction": result.zero_fraction,
            "negative_count": result.negative_count,
            "zero_count": result.zero_count,
            "positive_count": result.positive_count,
            "max_bin_count": result.max_bin_count,
            "bins": bins,
        }

    def pick_perspective(
        self,
        point_buffer,
        active_mask_buffer,
        point_count,
        camera,
        viewport_size,
        screen_xy,
        probe_radius_px,
        camera_position,
        fallback_to_nearest=False,
    ):
        width, height = viewport_size
        if point_count <= 0 or width <= 0.0 or height <= 0.0:
            return None
        focal_px = height * 0.5 / max(math.tan(math.radians(camera.fov_degrees) * 0.5), 1.0e-8)
        if focal_px <= 1.0e-8:
            return None
        active_ptr = ctypes.cast(active_mask_buffer, ctypes.POINTER(ctypes.c_uint8)) if active_mask_buffer else None
        index = self._lib.fs_pick_point_perspective(
            ctypes.cast(point_buffer, ctypes.c_void_p),
            active_ptr,
            int(point_count),
            _float3(camera_position),
            _float3(camera.right),
            _float3(camera.up),
            _float3(camera.forward),
            ctypes.c_float(float(width)),
            ctypes.c_float(float(height)),
            ctypes.c_float(float(screen_xy[0])),
            ctypes.c_float(float(screen_xy[1])),
            ctypes.c_float(float(probe_radius_px)),
            ctypes.c_float(float(focal_px)),
            ctypes.c_int(1 if fallback_to_nearest else 0),
        )
        return int(index) if index >= 0 else None

    def _bind_functions(self):
        self._lib.fs_pick_point_orthographic.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_float),
            ctypes.POINTER(ctypes.c_float),
            ctypes.POINTER(ctypes.c_float),
            ctypes.POINTER(ctypes.c_float),
            ctypes.POINTER(ctypes.c_float),
            ctypes.c_float,
            ctypes.c_float,
            ctypes.c_float,
            ctypes.c_float,
            ctypes.c_float,
            ctypes.c_float,
            ctypes.c_int,
        ]
        self._lib.fs_pick_point_orthographic.restype = ctypes.c_int
        self._lib.fs_pick_point_perspective.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_float),
            ctypes.POINTER(ctypes.c_float),
            ctypes.POINTER(ctypes.c_float),
            ctypes.POINTER(ctypes.c_float),
            ctypes.c_float,
            ctypes.c_float,
            ctypes.c_float,
            ctypes.c_float,
            ctypes.c_float,
            ctypes.c_float,
            ctypes.c_int,
        ]
        self._lib.fs_pick_point_perspective.restype = ctypes.c_int
        self._histogram_func = getattr(self._lib, "fs_build_inlier_distance_histogram", None)
        if self._histogram_func is not None:
            self._histogram_func.argtypes = [
                ctypes.c_void_p,
                ctypes.c_int,
                ctypes.POINTER(ctypes.c_int),
                ctypes.c_int,
                ctypes.c_int,
                ctypes.POINTER(ctypes.c_double),
                ctypes.c_int,
                ctypes.c_double,
                ctypes.c_double,
                ctypes.POINTER(_NativeHistogramResult),
                ctypes.POINTER(ctypes.c_int),
                ctypes.POINTER(ctypes.c_double),
                ctypes.POINTER(ctypes.c_double),
                ctypes.POINTER(ctypes.c_double),
                ctypes.POINTER(ctypes.c_double),
                ctypes.POINTER(ctypes.c_double),
                ctypes.POINTER(ctypes.c_double),
                ctypes.POINTER(ctypes.c_uint8),
            ]
            self._histogram_func.restype = ctypes.c_int


def _float3(values):
    return (ctypes.c_float * 3)(float(values[0]), float(values[1]), float(values[2]))


def default_library_path():
    system = platform.system().lower()
    if system == "windows":
        relative_parts = ("data", "native", "windows-x86_64", "FindSurfacePicking.dll")
        legacy_parts = ("FindSurface", "bin", "FindSurfacePicking.dll")
    elif system == "linux":
        relative_parts = ("data", "native", "linux-x86_64", "libFindSurfacePicking.so")
        legacy_parts = ("FindSurface", "lib", "libFindSurfacePicking.so")
    else:
        raise RuntimeError(f"Unsupported FindSurface picking platform: {platform.system()}")

    resolved = Path(__file__).resolve()
    extension_root = resolved.parents[1]
    candidates = [extension_root.joinpath(*relative_parts)]
    candidates.extend(parent.joinpath(*legacy_parts) for parent in resolved.parents)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def default_source_path():
    resolved = Path(__file__).resolve()
    for parent in resolved.parents:
        candidate = parent / "source" / "native" / "FindSurfacePicking.cpp"
        if candidate.exists():
            return candidate
    return resolved.parents[1] / "data" / "native" / "FindSurfacePicking.cpp"


def default_build_command(compiler=None):
    compiler = compiler or os.environ.get("FINDSURFACE_PICKING_COMPILER") or "g++"
    system = platform.system().lower()
    command = [compiler, "-O3", "-std=c++17", "-shared"]
    if system == "windows":
        command.extend(["-static", "-static-libgcc", "-static-libstdc++"])
    elif system == "linux":
        command.append("-fPIC")
    else:
        raise RuntimeError(f"Unsupported FindSurface picking platform: {platform.system()}")
    command.extend(["-o", str(default_library_path()), str(default_source_path())])
    return command


def build_default_library(compiler=None):
    source = default_source_path()
    if not source.exists():
        raise FileNotFoundError(f"FindSurface picking source was not found: {source}")

    output = default_library_path()
    output.parent.mkdir(parents=True, exist_ok=True)
    command = default_build_command(compiler)
    executable = command[0]
    if shutil.which(executable) is None and not Path(executable).exists():
        raise FileNotFoundError(f"FindSurface picking compiler was not found: {executable}")

    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        message = f"FindSurface picking build failed with exit code {completed.returncode}: {' '.join(command)}"
        if detail:
            message = f"{message}\n{detail}"
        raise RuntimeError(message)
    if not output.exists():
        raise FileNotFoundError(f"FindSurface picking build did not create: {output}")
    return output
