import asyncio
import gc
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXTENSION_REPO_ROOT = Path(os.environ.get("FINDSURFACE_EXTENSION_ROOT", PROJECT_ROOT))
if (EXTENSION_REPO_ROOT / "config" / "extension.toml").is_file():
    EXTENSION_ROOT = EXTENSION_REPO_ROOT
else:
    EXTENSION_ROOT = EXTENSION_REPO_ROOT / "source" / "extensions" / "com.findsurface.bootstrap"
APP_EXTENSION_ROOT = PROJECT_ROOT / "source" / "extensions" / "com.curvsurf.findsurface_omniverse"

for module_root in (APP_EXTENSION_ROOT, EXTENSION_ROOT):
    if str(module_root) not in sys.path:
        sys.path.insert(0, str(module_root))

from findsurface.bootstrap.core import DETECTION_TYPES
from findsurface_omniverse import extension as extension_module
from findsurface_omniverse.camera import PROJECTION_ORTHOGRAPHIC, PROJECTION_PERSPECTIVE
from findsurface_omniverse.surface_preview import SurfaceResult
from findsurface_omniverse.workspace import read_workspace


def _require(condition, message):
    if not condition:
        raise AssertionError(message)


def _button_selected(button):
    return bool(getattr(button, "selected", False) or getattr(button, "checked", False))


def _button_image_url(button):
    return str(getattr(button, "image_url", "") or "")


def _find_extension_instance():
    candidates = []
    for obj in gc.get_objects():
        try:
            if isinstance(obj, extension_module.FindSurfaceBootstrapExtension):
                candidates.append(obj)
        except Exception:
            continue
    live = [
        obj
        for obj in candidates
        if getattr(obj, "_viewport", None) is not None and not getattr(obj, "_app_shutting_down", False)
    ]
    if live:
        live.sort(key=lambda obj: getattr(obj, "_ext_id", "") == extension_module.EXTENSION_ID, reverse=True)
        return live[0]
    return candidates[0] if candidates else None


def _startup_smoke(ext):
    expected_windows = {
        ext.WINDOW_TOOLBAR,
        ext.WINDOW_STATUS_BAR,
        ext.WINDOW_VIEWPORT,
        ext.WINDOW_FINDSURFACE,
        ext.WINDOW_SETTINGS,
        ext.WINDOW_CAMERA,
        ext.WINDOW_GEOMETRIES,
        ext.WINDOW_TRANSACTIONS,
        ext.WINDOW_TUTORIAL,
    }
    windows = getattr(ext, "_windows", {})
    _require(getattr(ext, "_viewport", None) is not None, "Viewport was not constructed.")
    _require(expected_windows.issubset(set(windows)), "Not all application windows were constructed.")
    _require(set(getattr(ext, "_toolbar_detection_buttons", {})) == set(DETECTION_TYPES), "Detection toolbar buttons are incomplete.")
    _require(set(getattr(ext, "_toolbar_projection_buttons", {})) == {PROJECTION_ORTHOGRAPHIC, PROJECTION_PERSPECTIVE}, "Projection toolbar buttons are incomplete.")
    _require(set(getattr(ext, "_visibility_buttons", {})) == {"outliers", "meshes", "inliers"}, "Visibility toolbar buttons are incomplete.")
    _require(getattr(ext, "_save_button", None) is not None, "Save toolbar button was not created.")
    _require(getattr(ext, "_toolbar_capture_button", None) is not None, "Capture toolbar button was not created.")
    _require(getattr(ext, "_toolbar_undo_button", None) is not None, "Undo toolbar button was not created.")
    _require(ext.TOOLBAR_BUTTON_SIZE <= 40, "Toolbar button size is no longer compact.")
    _require(ext.TOOLBAR_WINDOW_THICKNESS <= 48, "Toolbar window thickness is no longer compact.")
    _require(ext.SIDE_PANEL_MIN_WIDTH >= 348, "Property window minimum width is below the expected compact minimum.")
    return {
        "windows": sorted(expected_windows),
        "detection_buttons": list(DETECTION_TYPES),
        "toolbar_button_size": ext.TOOLBAR_BUTTON_SIZE,
        "toolbar_window_thickness": ext.TOOLBAR_WINDOW_THICKNESS,
        "side_panel_min_width": ext.SIDE_PANEL_MIN_WIDTH,
    }


def _write_xyz_fixture(path):
    path.write_text(
        "\n".join(
            [
                "0.0 0.0 0.0",
                "1.0 0.0 0.0",
                "0.0 1.0 0.0",
                "0.0 0.0 1.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _import_smoke(ext, directory):
    cloud_path = directory / "smoke_cloud.xyz"
    _write_xyz_fixture(cloud_path)
    cloud = ext._load_point_cloud(
        str(cloud_path),
        ext._import_options(max_points=200000, target_points=100000, overflow_policy="reject"),
    )
    _require(cloud.count == 4, "Point-cloud import returned an unexpected point count.")
    _require(ext._apply_imported_point_cloud(str(cloud_path), cloud) is True, "Imported point cloud was not applied.")
    _require(ext._state is not None, "Import did not create app state.")
    _require(ext._state.point_count == 4, "Imported app state has the wrong point count.")
    _require(ext._viewport.point_cloud is not None and ext._viewport.point_cloud.count == 4, "Viewport did not receive the imported point cloud.")
    _require(ext._dataset_name == cloud_path.name, "Dataset name was not updated after import.")
    _require(ext._is_dirty is False, "Fresh import should reset dirty tracking.")
    return {"path": str(cloud_path), "point_count": ext._state.point_count}


def _capture_undo_redo_smoke(ext):
    preview = SurfaceResult(
        id="SmokePreview",
        type="Plane",
        seed_position=(0.0, 0.0, 0.0),
        seed_index=0,
        inlier_indices=[0, 1],
        active_generation=ext._state.generation,
        measurement_accuracy=0.003,
        rms_error=0.001,
        parameters={
            "origin": (0.5, 0.0, 0.0),
            "normal": (0.0, 0.0, 1.0),
            "width": 1.0,
            "height": 1.0,
        },
    )
    ext._selected_index = 0
    ext._auto_detect_result = preview
    ext._auto_detect_source = "selected"
    ext._sync_detection_surfaces()
    ext._refresh_detection_panel()
    _require(ext._can_capture_selected_preview(), "Synthetic selected preview is not capturable.")
    _require(getattr(ext._toolbar_capture_button, "enabled", False), "Capture toolbar button did not enable.")

    ext._capture_selected_preview()
    _require(len(ext._state.results) == 1, "Capture did not add one confirmed result.")
    _require(ext._state.results[0].id == "Plane_1", "Captured result id was not assigned from state.")
    _require(ext._state.active_count == 2, "Capture did not remove inlier points from the active mask.")
    _require(ext._state.can_undo, "Capture did not create an undoable transaction.")
    _require(getattr(ext._toolbar_undo_button, "enabled", False), "Undo toolbar button did not enable after capture.")

    ext._undo_last()
    _require(len(ext._state.results) == 0, "Undo did not remove the confirmed result.")
    _require(ext._state.active_count == 4, "Undo did not restore active points.")
    _require(ext._state.can_redo, "Undo did not expose redo.")

    ext._redo_last()
    _require(len(ext._state.results) == 1, "Redo did not restore the confirmed result.")
    _require(ext._state.active_count == 2, "Redo did not remove inlier points again.")
    return {
        "captured_result": ext._state.results[0].id,
        "active_count_after_redo": ext._state.active_count,
        "transactions": len(ext._state.transaction_log),
    }


def _workspace_export_smoke(ext, directory):
    workspace_path = directory / "smoke_workspace.usda"
    export_path = directory / "smoke_export.usda"

    _require(ext._save_workspace_to_path(str(workspace_path)), "Workspace save failed.")
    _require(workspace_path.exists(), "Workspace file was not written.")
    _require(ext._is_dirty is False, "Workspace save did not clear dirty state.")

    saved = read_workspace(str(workspace_path))
    _require(saved.state.point_count == 4, "Saved workspace has the wrong point count.")
    _require(len(saved.state.results) == 1, "Saved workspace did not preserve the captured result.")
    _require(saved.detection_type in DETECTION_TYPES, "Saved workspace detection type is invalid.")

    ext._export_include_visualization_meshes = True
    _require(ext._export_geometries_to_path(str(export_path)), "Geometry export failed.")
    export_text = export_path.read_text(encoding="utf-8")
    _require("geometry_export" in export_text, "Geometry export payload kind is missing.")
    _require("/FindSurfaceExport" in export_text or 'def Xform "FindSurfaceExport"' in export_text, "Geometry export USD prims are missing.")

    _require(ext._load_workspace_from_path(str(workspace_path)) is True, "Workspace load failed.")
    _require(ext._workspace_path == str(workspace_path), "Workspace path was not restored after load.")
    _require(len(ext._state.results) == 1, "Workspace load did not restore captured results.")
    _require(ext._is_dirty is False, "Workspace load should reset dirty tracking.")

    return {
        "workspace": str(workspace_path),
        "export": str(export_path),
        "loaded_results": len(ext._state.results),
    }


def _toolbar_visibility_smoke(ext):
    ext._set_projection_mode(PROJECTION_PERSPECTIVE)
    _require(ext._viewport.camera.projection_mode == PROJECTION_PERSPECTIVE, "Perspective projection was not applied.")
    _require(_button_selected(ext._toolbar_projection_buttons[PROJECTION_PERSPECTIVE]), "Perspective toolbar button is not selected.")

    ext._set_projection_mode(PROJECTION_ORTHOGRAPHIC)
    _require(ext._viewport.camera.projection_mode == PROJECTION_ORTHOGRAPHIC, "Orthographic projection was not restored.")
    _require(_button_selected(ext._toolbar_projection_buttons[PROJECTION_ORTHOGRAPHIC]), "Orthographic toolbar button is not selected.")

    ext._set_detection_type("Cylinder")
    _require(ext._detection_type == "Cylinder", "Detection type did not change from the toolbar path.")
    _require(_button_selected(ext._toolbar_detection_buttons["Cylinder"]), "Cylinder detection toolbar button is not selected.")

    ext._toggle_global_visibility("outliers")
    _require(ext._viewport.outlier_points_visible is False, "Outlier visibility did not toggle off.")
    _require("off.svg" in _button_image_url(ext._visibility_buttons["outliers"]), "Outlier toolbar icon did not switch to the off state.")

    ext._toggle_global_visibility("outliers")
    _require(ext._viewport.outlier_points_visible is True, "Outlier visibility did not toggle back on.")
    _require("on.svg" in _button_image_url(ext._visibility_buttons["outliers"]), "Outlier toolbar icon did not switch to the on state.")
    return {
        "projection": ext._viewport.camera.projection_mode,
        "detection_type": ext._detection_type,
        "outliers_visible": ext._viewport.outlier_points_visible,
    }


def _parameter_pad_smoke(ext):
    x_name, y_name = ext._parameter_pad_axis_pair()
    key = ext._parameter_pad_key(x_name, y_name)
    current_u = ext._parameter_pad_normalized_for_model(x_name)
    current_v = ext._parameter_pad_normalized_for_model(y_name)
    target_u = 0.0 if current_u >= 0.5 else 1.0
    target_v = 0.0 if current_v >= 0.5 else 1.0
    before = {
        x_name: ext._parameter_pad_model_value(x_name),
        y_name: ext._parameter_pad_model_value(y_name),
    }
    changed = ext._apply_parameter_pad_normalized(x_name, y_name, target_u, target_v)
    _require(ext._parameter_pad_positions.get(key) == (target_u, target_v), "Parameter pad position was not recorded.")
    after = {
        x_name: ext._parameter_pad_model_value(x_name),
        y_name: ext._parameter_pad_model_value(y_name),
    }
    for name in (x_name, y_name):
        spec = ext._parameter_pad_spec(name)
        value = after[name]
        _require(spec["minimum"] <= value <= spec["maximum"], "Parameter pad value is outside its configured range.")
    return {
        "axis_pair": [x_name, y_name],
        "changed": bool(changed),
        "before": before,
        "after": after,
        "position": list(ext._parameter_pad_positions[key]),
    }


def _scale_ruler_smoke(ext):
    viewport = ext._viewport
    viewport.camera.set_projection_mode(PROJECTION_ORTHOGRAPHIC)
    spec = viewport._scale_ruler_spec(width=800.0, height=600.0)
    _require(spec is not None, "Orthographic scale ruler spec is missing.")
    _require(spec["world_length"] > 0.0, "Orthographic scale ruler world length is invalid.")
    _require(bool(spec["label"]), "Orthographic scale ruler label is empty.")

    viewport._set_scale_ruler_position(500.0, 500.0, width=320.0, height=220.0)
    clamped = viewport._scale_ruler_spec(width=320.0, height=220.0)
    _require(clamped["left"] >= 0.0 and clamped["right"] <= 320.0, "Scale ruler did not clamp horizontally.")
    _require(clamped["label_top"] >= 0.0 and clamped["baseline"] <= 220.0, "Scale ruler did not clamp vertically.")

    viewport.camera.set_projection_mode(PROJECTION_PERSPECTIVE)
    _require(viewport._scale_ruler_spec(width=800.0, height=600.0) is None, "Scale ruler should be hidden in perspective projection.")
    viewport.camera.set_projection_mode(PROJECTION_ORTHOGRAPHIC)
    return {
        "label": spec["label"],
        "world_length": spec["world_length"],
        "clamped_left": clamped["left"],
        "clamped_baseline": clamped["baseline"],
    }


def run_smoke():
    ext = _find_extension_instance()
    _require(ext is not None, "FindSurface extension instance was not found in the Kit runtime.")
    _require(getattr(ext, "_viewport", None) is not None, "FindSurface extension is running without viewport/UI.")

    with tempfile.TemporaryDirectory(prefix="findsurface_ui_smoke_") as tmp:
        directory = Path(tmp)
        return {
            "startup": _startup_smoke(ext),
            "import": _import_smoke(ext, directory),
            "capture_undo_redo": _capture_undo_redo_smoke(ext),
            "workspace_export": _workspace_export_smoke(ext, directory),
            "toolbar_visibility": _toolbar_visibility_smoke(ext),
            "parameter_pad": _parameter_pad_smoke(ext),
            "scale_ruler": _scale_ruler_smoke(ext),
        }


async def _post_quit_after_updates(app, exit_code, frame_count=8):
    for _ in range(frame_count):
        await app.next_update_async()
    app.post_quit(exit_code)


def _request_kit_shutdown(exit_code=0):
    try:
        ext = _find_extension_instance()
        if ext is not None:
            ext._allow_shutdown_once = True
            if getattr(ext, "_is_dirty", False):
                ext._clear_dirty_tracking()
    except Exception:
        pass
    try:
        import omni.kit.app
    except Exception:
        return
    try:
        app = omni.kit.app.get_app()
        if hasattr(app, "next_update_async"):
            try:
                asyncio.ensure_future(_post_quit_after_updates(app, exit_code))
                return
            except Exception:
                pass
        if hasattr(app, "post_quit"):
            app.post_quit(exit_code)
    except Exception:
        return


if __name__ == "__main__":
    exit_code = 0
    try:
        result = run_smoke()
        print(json.dumps({"ui_smoke": result}, indent=2, sort_keys=True))
    except Exception:
        exit_code = 1
        traceback.print_exc()
    finally:
        _request_kit_shutdown(exit_code)
