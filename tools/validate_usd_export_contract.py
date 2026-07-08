import argparse
import importlib.util
import json
import os
import sys
import tempfile
import types
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXTENSION_REPO_ROOT = Path(os.environ.get("FINDSURFACE_EXTENSION_ROOT", PROJECT_ROOT))
if (EXTENSION_REPO_ROOT / "config" / "extension.toml").is_file():
    EXTENSION_ROOT = EXTENSION_REPO_ROOT
else:
    EXTENSION_ROOT = EXTENSION_REPO_ROOT / "source" / "extensions" / "com.findsurface.bootstrap"
APP_ROOT = (
    PROJECT_ROOT
    / "source"
    / "extensions"
    / "com.curvsurf.findsurface_omniverse"
    / "findsurface_omniverse"
)


def _load_app_module(name, relative_path):
    spec = importlib.util.spec_from_file_location(name, APP_ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_contract_modules():
    app_pkg = types.ModuleType("findsurface_omniverse")
    app_pkg.__path__ = [str(APP_ROOT)]
    sys.path.insert(0, str(EXTENSION_ROOT))
    sys.modules.setdefault("findsurface_omniverse", app_pkg)

    from findsurface.bootstrap import usd_schema

    app_state = _load_app_module("findsurface_omniverse.app_state", "app_state.py")
    point_cloud = _load_app_module("findsurface_omniverse.point_cloud", "point_cloud.py")
    surface_preview = _load_app_module("findsurface_omniverse.surface_preview", "surface_preview.py")
    workspace = _load_app_module("findsurface_omniverse.workspace", "workspace.py")
    return app_state, point_cloud, surface_preview, workspace, usd_schema


def _fixture_state(app_state, point_cloud, surface_preview):
    cloud = point_cloud.PointCloudData(
        "contract_fixture.xyz",
        [
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (2.0, 0.0, 0.0),
            (3.0, 0.0, 0.0),
        ],
    )
    state = app_state.PointCloudState(cloud)
    result = surface_preview.SurfaceResult(
        id="Plane_1",
        type="Plane",
        seed_position=(1.0, 0.0, 0.0),
        seed_index=1,
        inlier_indices=[1, 2],
        active_generation=0,
        measurement_accuracy=0.01,
        rms_error=0.001,
        parameters={"origin": (1.5, 0.0, 0.0), "normal": (0.0, 0.0, 1.0)},
    )
    state.apply_result(result)
    return state


def _require(condition, message):
    if not condition:
        raise AssertionError(message)


def _attr_value(prim, name):
    attr = prim.GetAttribute(name)
    _require(attr and attr.IsValid(), f"Missing attribute: {prim.GetPath()}.{name}")
    return attr.Get()


def _target_paths(rel):
    return [str(target) for target in rel.GetTargets()]


def _validate_stage(path, usd_schema):
    from pxr import Usd, UsdGeom

    stage = Usd.Stage.Open(str(path))
    _require(stage, f"Failed to open USD stage: {path}")

    root = stage.GetPrimAtPath("/FindSurfaceExport")
    _require(root and root.IsValid(), "Missing /FindSurfaceExport")
    _require(root.GetTypeName() == "Xform", "Root prim must be an Xform")
    _require(root.GetMetadata("kind") == "geometry_export", "Root prim kind must be geometry_export")
    _require(
        usd_schema.has_applied_api_schema(root, usd_schema.ROLE_GEOMETRY_EXPORT),
        "Root prim must have FindSurface geometry export API schema",
    )
    _require(_attr_value(root, "findsurface:app_id") == "com.curvsurf.findsurface_omniverse", "Unexpected app id")
    _require(_attr_value(root, "findsurface:kind") == "geometry_export", "Unexpected export kind")
    _require(_attr_value(root, "findsurface:schema_version") == 1, "Unexpected schema version")
    _require(_attr_value(root, "findsurface:source_point_count") == 4, "Unexpected source point count")
    _require(_attr_value(root, "findsurface:includes_visualization_meshes") is True, "Meshes flag must be true")

    plane = stage.GetPrimAtPath("/FindSurfaceExport/Plane_1")
    _require(plane and plane.IsValid(), "Missing Plane_1 prim")
    _require(plane.GetTypeName() == "Xform", "Geometry prim must be an Xform")
    _require(
        usd_schema.has_applied_api_schema(plane, usd_schema.ROLE_DETECTION_RESULT),
        "Geometry prim must have FindSurface detection result API schema",
    )
    _require(_attr_value(plane, "findsurface:id") == "Plane_1", "Unexpected geometry id")
    _require(_attr_value(plane, "findsurface:geometry_type") == "Plane", "Unexpected geometry type")
    _require(_attr_value(plane, "findsurface:seed_index") == 1, "Unexpected seed index")
    _require(list(_attr_value(plane, "findsurface:inlier_indices")) == [1, 2], "Unexpected inlier indices")

    inliers = stage.GetPrimAtPath("/FindSurfaceExport/Plane_1/Inliers")
    _require(inliers and inliers.IsValid(), "Missing Inliers prim")
    _require(UsdGeom.Points(inliers), "Inliers prim must satisfy UsdGeom.Points")
    _require(
        usd_schema.has_applied_api_schema(inliers, usd_schema.ROLE_INLIER_POINTS),
        "Inliers prim must have FindSurface inlier points API schema",
    )
    _require(len(UsdGeom.Points(inliers).GetPointsAttr().Get()) == 2, "Unexpected inlier point count")
    _require(list(_attr_value(inliers, "ids")) == [1, 2], "Unexpected inlier ids")

    solid = stage.GetPrimAtPath("/FindSurfaceExport/Looks/TransparentSolid")
    wire = stage.GetPrimAtPath("/FindSurfaceExport/Looks/Wire")
    _require(solid and solid.IsValid(), "Missing TransparentSolid material")
    _require(wire and wire.IsValid(), "Missing Wire material")

    mesh = stage.GetPrimAtPath("/FindSurfaceExport/Plane_1/VisualizationMesh")
    _require(mesh and mesh.IsValid(), "Missing VisualizationMesh prim")
    _require(UsdGeom.Mesh(mesh), "VisualizationMesh prim must satisfy UsdGeom.Mesh")
    _require(
        usd_schema.has_applied_api_schema(mesh, usd_schema.ROLE_VISUALIZATION),
        "Visualization mesh prim must have FindSurface visualization API schema",
    )
    _require(len(UsdGeom.Mesh(mesh).GetPointsAttr().Get()) > 0, "Mesh points must be authored")
    _require(list(_attr_value(mesh, "faceVertexCounts")), "Mesh faceVertexCounts must be authored")
    _require(list(_attr_value(mesh, "faceVertexIndices")), "Mesh faceVertexIndices must be authored")
    mesh_binding = mesh.GetRelationship("material:binding")
    _require("/FindSurfaceExport/Looks/TransparentSolid" in _target_paths(mesh_binding), "Mesh material binding missing")

    wire_prim = stage.GetPrimAtPath("/FindSurfaceExport/Plane_1/VisualizationWire")
    _require(wire_prim and wire_prim.IsValid(), "Missing VisualizationWire prim")
    _require(UsdGeom.BasisCurves(wire_prim), "VisualizationWire prim must satisfy UsdGeom.BasisCurves")
    _require(
        usd_schema.has_applied_api_schema(wire_prim, usd_schema.ROLE_VISUALIZATION),
        "Visualization wire prim must have FindSurface visualization API schema",
    )
    _require(len(UsdGeom.BasisCurves(wire_prim).GetPointsAttr().Get()) > 0, "Wire points must be authored")
    _require(list(_attr_value(wire_prim, "curveVertexCounts")), "Wire curveVertexCounts must be authored")
    _require(list(_attr_value(wire_prim, "widths")), "Wire widths must be authored")
    wire_binding = wire_prim.GetRelationship("material:binding")
    _require("/FindSurfaceExport/Looks/Wire" in _target_paths(wire_binding), "Wire material binding missing")

    return {
        "path": str(path),
        "root": str(root.GetPath()),
        "geometry": str(plane.GetPath()),
        "inlier_points": len(UsdGeom.Points(inliers).GetPointsAttr().Get()),
        "mesh_points": len(UsdGeom.Mesh(mesh).GetPointsAttr().Get()),
        "wire_points": len(UsdGeom.BasisCurves(wire_prim).GetPointsAttr().Get()),
    }


def _write_nested_import_fixture(path):
    from pxr import Gf, Usd, UsdGeom, Vt

    stage = Usd.Stage.CreateNew(str(path))

    root = UsdGeom.Xform.Define(stage, "/Root")
    root.AddTranslateOp().Set(Gf.Vec3d(10.0, 0.0, 0.0))

    nested = UsdGeom.Xform.Define(stage, "/Root/Nested")
    nested.AddTranslateOp().Set(Gf.Vec3d(0.0, 20.0, 0.0))

    points = UsdGeom.Points.Define(stage, "/Root/Nested/Samples")
    points.GetPointsAttr().Set(Vt.Vec3fArray([Gf.Vec3f(1.0, 2.0, 3.0), Gf.Vec3f(4.0, 5.0, 6.0)]))

    mesh_parent = UsdGeom.Xform.Define(stage, "/Root/MeshParent")
    mesh_parent.AddTranslateOp().Set(Gf.Vec3d(0.0, 0.0, 30.0))

    mesh = UsdGeom.Mesh.Define(stage, "/Root/MeshParent/MeshSamples")
    mesh.GetPointsAttr().Set(
        Vt.Vec3fArray(
            [
                Gf.Vec3f(7.0, 8.0, 9.0),
                Gf.Vec3f(10.0, 11.0, 12.0),
                Gf.Vec3f(13.0, 14.0, 15.0),
            ]
        )
    )
    mesh.GetFaceVertexCountsAttr().Set([3])
    mesh.GetFaceVertexIndicesAttr().Set([0, 1, 2])

    stage.GetRootLayer().Save()


def _rounded_points(points):
    return [[round(float(component), 6) for component in point] for point in points]


def _validate_nested_import_contract(path, point_cloud):
    _write_nested_import_fixture(path)

    points_only = point_cloud.load_point_cloud(str(path))
    _require(
        _rounded_points(points_only.points) == [[11.0, 22.0, 3.0], [14.0, 25.0, 6.0]],
        f"Unexpected nested Points import result: {points_only.points}",
    )

    with_mesh = point_cloud.load_point_cloud(
        str(path),
        point_cloud.ImportOptions(include_mesh_vertices=True),
    )
    _require(
        _rounded_points(with_mesh.points)
        == [
            [11.0, 22.0, 3.0],
            [14.0, 25.0, 6.0],
            [17.0, 8.0, 39.0],
            [20.0, 11.0, 42.0],
            [23.0, 14.0, 45.0],
        ],
        f"Unexpected nested Points+Mesh import result: {with_mesh.points}",
    )

    return {
        "path": str(path),
        "points_only_count": points_only.count,
        "points_and_mesh_count": with_mesh.count,
        "points_only": _rounded_points(points_only.points),
        "points_and_mesh": _rounded_points(with_mesh.points),
    }


def main():
    parser = argparse.ArgumentParser(description="Validate FindSurface geometry export USD prim contract.")
    parser.add_argument("--output", help="Optional geometry-export USDA output path to write and validate.")
    parser.add_argument("--import-fixture-output", help="Optional nested import fixture USDA path to write and validate.")
    args = parser.parse_args()

    try:
        import pxr  # noqa: F401
    except ImportError:
        print("pxr USD Python modules are unavailable. Run this with Kit Python or another USD-enabled runtime.")
        return 2

    app_state, point_cloud, surface_preview, workspace, usd_schema = _load_contract_modules()
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        workspace.write_geometry_export(
            str(output_path),
            _fixture_state(app_state, point_cloud, surface_preview),
            include_visualization_meshes=True,
        )
        export_result = _validate_stage(output_path, usd_schema)
    else:
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "geometry_export_contract.usda"
            workspace.write_geometry_export(
                str(output_path),
                _fixture_state(app_state, point_cloud, surface_preview),
                include_visualization_meshes=True,
            )
            export_result = _validate_stage(output_path, usd_schema)

    if args.import_fixture_output:
        import_fixture_path = Path(args.import_fixture_output)
        import_fixture_path.parent.mkdir(parents=True, exist_ok=True)
        import_result = _validate_nested_import_contract(import_fixture_path, point_cloud)
    else:
        with tempfile.TemporaryDirectory() as directory:
            import_fixture_path = Path(directory) / "nested_import_contract.usda"
            import_result = _validate_nested_import_contract(import_fixture_path, point_cloud)

    print(json.dumps({"export": export_result, "import": import_result}, indent=2, sort_keys=True))
    return 0


def _request_kit_shutdown():
    try:
        import omni.kit.app
    except Exception:
        return
    try:
        app = omni.kit.app.get_app()
        if hasattr(app, "post_quit"):
            app.post_quit()
    except Exception:
        return


if __name__ == "__main__":
    exit_code = 0
    try:
        exit_code = main()
    except Exception:
        exit_code = 1
        raise
    finally:
        _request_kit_shutdown()
    if exit_code:
        raise SystemExit(exit_code)
