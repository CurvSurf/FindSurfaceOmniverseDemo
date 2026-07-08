import json
import math
import os
import re
from importlib import import_module
from dataclasses import dataclass, field

from .app_state import (
    TRANSACTION_APPLY_DETECTION,
    DetectionRecord,
    PointCloudState,
    StateTransaction,
)
from .point_cloud import PointCloudData
from .surface_preview import (
    SURFACE_SOLID_COLOR,
    SURFACE_WIRE_COLOR,
    SURFACE_WIRE_THICKNESS,
    SurfaceResult,
    build_surface_preview_mesh,
)
from findsurface.bootstrap import usd_schema


APP_ID = "com.curvsurf.findsurface_omniverse"
APP_SCHEMA_VERSION = 1
USD_KIND_WORKSPACE = "workspace"
USD_KIND_GEOMETRY_EXPORT = "geometry_export"
PAYLOAD_BEGIN = "# FIND_SURFACE_DATA_BEGIN"
PAYLOAD_END = "# FIND_SURFACE_DATA_END"
GEOMETRY_EXPORT_ROOT_PRIM = "FindSurfaceExport"
GEOMETRY_EXPORT_LOOKS_PRIM = "Looks"
GEOMETRY_EXPORT_SOLID_MATERIAL = "TransparentSolid"
GEOMETRY_EXPORT_WIRE_MATERIAL = "Wire"
GEOMETRY_EXPORT_SCHEMA_WRITER_ENV = "FINDSURFACE_GEOMETRY_EXPORT_SCHEMA_WRITER"
GEOMETRY_EXPORT_SCHEMA_WRITER_MODULES = (
    "findsurface_usd_schema",
    "findsurface.usd_schema",
    "findsurface.bootstrap.usd_schema",
)
GEOMETRY_EXPORT_SCHEMA_WRITER_NAMES = (
    "write_geometry_export_schema_usda_lines",
    "geometry_export_schema_usda_lines",
)
_geometry_export_schema_writer = None
_geometry_export_schema_writer_discovered = False


class WorkspaceError(ValueError):
    pass


@dataclass
class WorkspaceDocument:
    path: str
    point_cloud: PointCloudData
    state: PointCloudState
    detection_type: str = "Auto"
    metadata: dict = field(default_factory=dict)


def write_workspace(path, state, detection_type="Auto", settings=None):
    if state is None:
        raise WorkspaceError("No workspace state is available to save.")
    payload = _base_payload(USD_KIND_WORKSPACE)
    payload.update(
        {
            "detection_type": detection_type,
            "settings": _json_safe(settings or {}),
            "point_cloud": _point_cloud_to_dict(state.cloud),
            "active_mask": list(state.active_mask),
            "generation": int(state.generation),
            "results": [_surface_result_to_dict(result) for result in state.results],
            "transactions": [_state_transaction_to_dict(transaction) for transaction in state.transaction_log],
            "transaction_index": int(state.transaction_index),
        }
    )
    _write_payload(path, payload)


def read_workspace(path):
    payload = _read_payload(path)
    _validate_payload(payload, USD_KIND_WORKSPACE)

    cloud_payload = payload.get("point_cloud") or {}
    points = _vec3_list(cloud_payload.get("points") or [])
    cloud = PointCloudData(path, points, metadata=cloud_payload.get("metadata") or {})
    state = PointCloudState(cloud)

    result_records = []
    for result_payload in payload.get("results") or []:
        result = _surface_result_from_dict(result_payload)
        removed = sorted({index for index in result.inlier_indices if 0 <= index < state.point_count})
        result_records.append(DetectionRecord(result.id, int(result.active_generation), removed, result))
    state.result_log = result_records

    active_mask = payload.get("active_mask")
    if active_mask is not None:
        if len(active_mask) != cloud.count:
            raise WorkspaceError("Workspace active mask does not match point count.")
        state.active_mask = [bool(value) for value in active_mask]
    else:
        for record in result_records:
            for index in record.removed_indices:
                if 0 <= index < state.point_count:
                    state.active_mask[index] = False

    state.generation = int(payload.get("generation", _next_generation_after_records(result_records)))
    transaction_payloads = payload.get("transactions")
    if transaction_payloads is not None:
        state.transaction_log = [_state_transaction_from_dict(transaction) for transaction in transaction_payloads]
    else:
        state.transaction_log = [_apply_transaction_from_record(record) for record in result_records]
    state.transaction_index = max(
        0,
        min(len(state.transaction_log), int(payload.get("transaction_index", len(state.transaction_log)))),
    )

    return WorkspaceDocument(
        path=path,
        point_cloud=cloud,
        state=state,
        detection_type=payload.get("detection_type") or "Auto",
        metadata=payload,
    )


def write_geometry_export(path, state, include_visualization_meshes=False):
    if state is None:
        raise WorkspaceError("No workspace state is available to export.")
    if not state.results:
        raise WorkspaceError("There are no detected geometries to export.")
    payload = _base_payload(USD_KIND_GEOMETRY_EXPORT)
    payload.update(
        {
            "source_point_count": state.point_count,
            "includes_visualization_meshes": bool(include_visualization_meshes),
            "results": [
                _geometry_result_to_dict(state, result, include_visualization_meshes=include_visualization_meshes)
                for result in state.results
            ],
        }
    )
    _write_payload(path, payload, extra_lines=_geometry_export_usda_lines(payload))


def read_payload_kind(path):
    return _read_payload(path).get("kind")


def set_geometry_export_schema_writer(writer):
    if writer is not None and not callable(writer):
        raise TypeError("Geometry export schema writer must be callable or None.")
    global _geometry_export_schema_writer
    previous = _geometry_export_schema_writer
    _geometry_export_schema_writer = writer
    return previous


def reset_geometry_export_schema_writer_discovery():
    global _geometry_export_schema_writer_discovered
    _geometry_export_schema_writer_discovered = False


def _base_payload(kind):
    return {
        "app_id": APP_ID,
        "schema_version": APP_SCHEMA_VERSION,
        "kind": kind,
    }


def _validate_payload(payload, expected_kind):
    if payload.get("app_id") != APP_ID:
        raise WorkspaceError("The selected USD is not a FindSurface workspace file.")
    if payload.get("schema_version") != APP_SCHEMA_VERSION:
        raise WorkspaceError("Unsupported FindSurface workspace schema version.")
    if payload.get("kind") != expected_kind:
        actual = payload.get("kind") or "unknown"
        raise WorkspaceError(f"Expected a {expected_kind} USD, but found {actual}.")


def _point_cloud_to_dict(cloud):
    return {
        "path": getattr(cloud, "path", None),
        "points": _json_safe(getattr(cloud, "points", [])),
        "metadata": _json_safe(getattr(cloud, "metadata", {})),
    }


def _surface_result_to_dict(result):
    return {
        "id": result.id,
        "type": result.type,
        "seed_position": _json_safe(result.seed_position),
        "seed_index": int(result.seed_index),
        "inlier_indices": [int(index) for index in result.inlier_indices],
        "active_generation": int(result.active_generation),
        "measurement_accuracy": float(result.measurement_accuracy),
        "rms_error": float(result.rms_error),
        "confidence": result.confidence,
        "parameters": _json_safe(result.parameters),
        "mesh_visible": bool(getattr(result, "mesh_visible", True)),
        "inliers_visible": bool(getattr(result, "inliers_visible", True)),
    }


def _surface_result_from_dict(data):
    result = SurfaceResult(
        id=str(data.get("id") or "Surface"),
        type=str(data.get("type") or "Unknown"),
        seed_position=tuple(_vec3(data.get("seed_position") or (0.0, 0.0, 0.0))),
        seed_index=int(data.get("seed_index", -1)),
        inlier_indices=[int(index) for index in data.get("inlier_indices") or []],
        active_generation=int(data.get("active_generation", 0)),
        measurement_accuracy=float(data.get("measurement_accuracy", 0.0)),
        rms_error=float(data.get("rms_error", 0.0)),
        confidence=data.get("confidence"),
        parameters=data.get("parameters") or {},
    )
    result.mesh_visible = bool(data.get("mesh_visible", True))
    result.inliers_visible = bool(data.get("inliers_visible", True))
    return result


def _detection_record_to_dict(record):
    return {
        "result_id": record.result_id,
        "generation_before": int(record.generation_before),
        "removed_indices": [int(index) for index in record.removed_indices],
        "surface_result": _surface_result_to_dict(record.surface_result),
    }


def _detection_record_from_dict(data):
    result = _surface_result_from_dict(data.get("surface_result") or {})
    return DetectionRecord(
        str(data.get("result_id") or result.id),
        int(data.get("generation_before", result.active_generation)),
        [int(index) for index in data.get("removed_indices") or []],
        result,
    )


def _state_transaction_to_dict(transaction):
    data = {
        "event_type": transaction.event_type,
        "generation_before": int(transaction.generation_before),
        "generation_after": int(transaction.generation_after),
    }
    if transaction.result_id is not None:
        data["result_id"] = transaction.result_id
    if transaction.result_log_index is not None:
        data["result_log_index"] = int(transaction.result_log_index)
    if transaction.detection_record is not None:
        data["detection_record"] = _detection_record_to_dict(transaction.detection_record)
    if transaction.detection_records is not None:
        data["detection_records"] = [_detection_record_to_dict(record) for record in transaction.detection_records]
    if transaction.active_mask_before is not None:
        data["active_mask_before"] = [bool(value) for value in transaction.active_mask_before]
    if transaction.state_before is not None:
        data["state_before"] = _json_safe(transaction.state_before)
    if transaction.state_after is not None:
        data["state_after"] = _json_safe(transaction.state_after)
    return data


def _state_transaction_from_dict(data):
    detection_record = data.get("detection_record")
    detection_records = data.get("detection_records")
    active_mask_before = data.get("active_mask_before")
    result_log_index = data.get("result_log_index")
    return StateTransaction(
        event_type=str(data.get("event_type") or TRANSACTION_APPLY_DETECTION),
        generation_before=int(data.get("generation_before", 0)),
        generation_after=int(data.get("generation_after", 0)),
        result_id=data.get("result_id"),
        result_log_index=int(result_log_index) if result_log_index is not None else None,
        detection_record=_detection_record_from_dict(detection_record) if detection_record else None,
        detection_records=[_detection_record_from_dict(record) for record in detection_records]
        if detection_records is not None
        else None,
        active_mask_before=[bool(value) for value in active_mask_before] if active_mask_before is not None else None,
        state_before=data.get("state_before"),
        state_after=data.get("state_after"),
    )


def _apply_transaction_from_record(record):
    return StateTransaction(
        TRANSACTION_APPLY_DETECTION,
        int(record.generation_before),
        int(record.generation_before) + 1,
        result_id=record.result_id,
        detection_record=record,
    )


def _next_generation_after_records(records):
    if not records:
        return 0
    return max(int(record.generation_before) for record in records) + 1


def _geometry_result_to_dict(state, result, include_visualization_meshes=False):
    data = _surface_result_to_dict(result)
    data["inlier_points"] = [
        _json_safe(state.points[index])
        for index in result.inlier_indices
        if 0 <= index < state.point_count
    ]
    if include_visualization_meshes:
        mesh = build_surface_preview_mesh(result)
        data["visualization_mesh"] = _surface_mesh_to_dict(mesh) if mesh else None
    return data


def _surface_mesh_to_dict(mesh):
    return {
        "points": _json_safe(mesh.points),
        "colors": _json_safe(mesh.colors),
        "vertex_counts": [int(value) for value in mesh.vertex_counts],
        "vertex_indices": [int(value) for value in mesh.vertex_indices],
        "wire_lines": _json_safe(mesh.wire_lines),
    }


def _geometry_export_usda_lines(payload):
    lines = [
        f'def Xform "{GEOMETRY_EXPORT_ROOT_PRIM}" (',
        *_findsurface_api_schema_usda_lines(usd_schema.ROLE_GEOMETRY_EXPORT, indent=4),
        f'    kind = "{USD_KIND_GEOMETRY_EXPORT}"',
        ")",
        "{",
        f"    custom string findsurface:app_id = {_usd_string(payload.get('app_id'))}",
        f"    custom int findsurface:schema_version = {int(payload.get('schema_version', 0))}",
        f"    custom string findsurface:kind = {_usd_string(payload.get('kind'))}",
        f"    custom int findsurface:source_point_count = {int(payload.get('source_point_count', 0))}",
        f"    custom bool findsurface:includes_visualization_meshes = {_usd_bool(payload.get('includes_visualization_meshes'))}",
    ]
    if payload.get("includes_visualization_meshes"):
        lines.extend(_geometry_export_material_usda_lines(indent=4))

    used_names = set()
    for index, result in enumerate(payload.get("results") or [], start=1):
        lines.extend(_geometry_result_usda_lines(result, index, used_names, indent=4))
    lines.extend(_geometry_export_schema_usda_lines(payload, indent=4))

    lines.append("}")
    return lines


def _geometry_export_schema_usda_lines(payload, indent=0):
    writer = _geometry_export_schema_writer or _discover_geometry_export_schema_writer()
    if writer is None:
        return []
    schema_lines = writer(payload)
    if not schema_lines:
        return []
    prefix = " " * indent
    result = []
    for line in schema_lines:
        if not isinstance(line, str):
            raise WorkspaceError("Geometry export schema writer returned a non-string USDA line.")
        result.append(f"{prefix}{line}" if line else "")
    return result


def _discover_geometry_export_schema_writer():
    global _geometry_export_schema_writer
    global _geometry_export_schema_writer_discovered
    if _geometry_export_schema_writer_discovered:
        return _geometry_export_schema_writer
    _geometry_export_schema_writer_discovered = True

    configured = os.environ.get(GEOMETRY_EXPORT_SCHEMA_WRITER_ENV)
    if configured:
        _geometry_export_schema_writer = _schema_writer_from_configured_name(configured)
        return _geometry_export_schema_writer

    for module_name in GEOMETRY_EXPORT_SCHEMA_WRITER_MODULES:
        try:
            writer = _schema_writer_from_module(import_module(module_name))
        except ImportError:
            continue
        if writer is not None:
            _geometry_export_schema_writer = writer
            return _geometry_export_schema_writer
    return None


def _schema_writer_from_configured_name(configured):
    module_name, separator, function_name = configured.partition(":")
    if not module_name:
        raise WorkspaceError(f"{GEOMETRY_EXPORT_SCHEMA_WRITER_ENV} must name a Python module or module:function.")
    try:
        module = import_module(module_name)
    except ImportError as exc:
        raise WorkspaceError(f"Failed to import geometry export schema writer module '{module_name}'.") from exc
    writer = getattr(module, function_name, None) if separator else _schema_writer_from_module(module)
    if not callable(writer):
        target = configured if separator else module_name
        raise WorkspaceError(f"Geometry export schema writer '{target}' was not found or is not callable.")
    return writer


def _schema_writer_from_module(module):
    for name in GEOMETRY_EXPORT_SCHEMA_WRITER_NAMES:
        writer = getattr(module, name, None)
        if callable(writer):
            return writer
    return None


def _geometry_export_material_usda_lines(indent=0):
    prefix = " " * indent
    child = " " * (indent + 4)
    shader = " " * (indent + 8)
    solid_color = _rgb_from_rgba(SURFACE_SOLID_COLOR)
    solid_opacity = max(_alpha_from_rgba(SURFACE_SOLID_COLOR), 0.18)
    wire_color = _rgb_from_rgba(SURFACE_WIRE_COLOR)
    return [
        f'{prefix}def Scope "{GEOMETRY_EXPORT_LOOKS_PRIM}"',
        f"{prefix}{{",
        f'{child}def Material "{GEOMETRY_EXPORT_SOLID_MATERIAL}"',
        f"{child}{{",
        (
            f"{shader}token outputs:surface.connect = "
            f"</{GEOMETRY_EXPORT_ROOT_PRIM}/{GEOMETRY_EXPORT_LOOKS_PRIM}/"
            f"{GEOMETRY_EXPORT_SOLID_MATERIAL}/PreviewSurface.outputs:surface>"
        ),
        f'{shader}def Shader "PreviewSurface"',
        f"{shader}{{",
        f'{shader}    uniform token info:id = "UsdPreviewSurface"',
        f"{shader}    color3f inputs:diffuseColor = {_usd_vec3(solid_color)}",
        f"{shader}    float inputs:opacity = {_usd_number(solid_opacity)}",
        f"{shader}    float inputs:roughness = 0.55",
        f"{shader}    token outputs:surface",
        f"{shader}}}",
        f"{child}}}",
        f'{child}def Material "{GEOMETRY_EXPORT_WIRE_MATERIAL}"',
        f"{child}{{",
        (
            f"{shader}token outputs:surface.connect = "
            f"</{GEOMETRY_EXPORT_ROOT_PRIM}/{GEOMETRY_EXPORT_LOOKS_PRIM}/"
            f"{GEOMETRY_EXPORT_WIRE_MATERIAL}/PreviewSurface.outputs:surface>"
        ),
        f'{shader}def Shader "PreviewSurface"',
        f"{shader}{{",
        f'{shader}    uniform token info:id = "UsdPreviewSurface"',
        f"{shader}    color3f inputs:diffuseColor = {_usd_vec3(wire_color)}",
        f"{shader}    float inputs:opacity = {_usd_number(_alpha_from_rgba(SURFACE_WIRE_COLOR))}",
        f"{shader}    float inputs:roughness = 0.35",
        f"{shader}    token outputs:surface",
        f"{shader}}}",
        f"{child}}}",
        f"{prefix}}}",
    ]


def _geometry_result_usda_lines(result, index, used_names, indent=0):
    prefix = " " * indent
    child = " " * (indent + 4)
    prim_name = _unique_prim_name(_usd_identifier(result.get("id") or result.get("type") or "Geometry", index), used_names)
    lines = [
        *_usd_prim_header_lines("Xform", prim_name, usd_schema.ROLE_DETECTION_RESULT, indent),
        f"{prefix}{{",
        f"{child}custom string findsurface:id = {_usd_string(result.get('id'))}",
        f"{child}custom string findsurface:geometry_type = {_usd_string(result.get('type'))}",
        f"{child}custom double findsurface:rms_error = {_usd_number(result.get('rms_error'))}",
        f"{child}custom double findsurface:measurement_accuracy = {_usd_number(result.get('measurement_accuracy'))}",
        f"{child}custom int findsurface:seed_index = {int(result.get('seed_index', -1))}",
        f"{child}custom double3 findsurface:seed_position = {_usd_vec3(result.get('seed_position') or (0.0, 0.0, 0.0))}",
        f"{child}custom int[] findsurface:inlier_indices = {_usd_int_array(result.get('inlier_indices') or [])}",
    ]
    if result.get("confidence") is not None:
        lines.append(f"{child}custom double findsurface:confidence = {_usd_number(result.get('confidence'))}")
    lines.extend(_geometry_parameter_usda_lines(result.get("parameters") or {}, indent + 4))
    lines.extend(_inlier_points_usda_lines(result, indent + 4))
    mesh = result.get("visualization_mesh")
    if mesh:
        lines.extend(_visualization_mesh_usda_lines(mesh, indent + 4))
        lines.extend(_visualization_wire_usda_lines(mesh, indent + 4))
    lines.append(f"{prefix}}}")
    return lines


def _geometry_parameter_usda_lines(parameters, indent=0):
    lines = []
    prefix = " " * indent
    for key in sorted(parameters):
        attr_name = _usd_property_identifier(key)
        value = parameters[key]
        attr_type, attr_value = _usd_attribute_value(value)
        if attr_type is None:
            continue
        lines.append(f"{prefix}custom {attr_type} findsurface:param:{attr_name} = {attr_value}")
    if parameters:
        lines.append(f"{prefix}custom string findsurface:parameters_json = {_usd_string(json.dumps(_json_safe(parameters), sort_keys=True))}")
    return lines


def _inlier_points_usda_lines(result, indent=0):
    prefix = " " * indent
    child = " " * (indent + 4)
    return [
        *_usd_prim_header_lines("Points", "Inliers", usd_schema.ROLE_INLIER_POINTS, indent),
        f"{prefix}{{",
        f"{child}int64[] ids = {_usd_int_array(result.get('inlier_indices') or [])}",
        f"{child}point3f[] points = {_usd_vec3_array(result.get('inlier_points') or [])}",
        f"{prefix}}}",
    ]


def _visualization_mesh_usda_lines(mesh, indent=0):
    prefix = " " * indent
    child = " " * (indent + 4)
    colors = _usd_color3_array(mesh.get("colors") or [])
    opacity = _surface_opacity_from_mesh(mesh)
    display_color = _surface_color_from_mesh(mesh)
    lines = [
        *_usd_prim_header_lines("Mesh", "VisualizationMesh", usd_schema.ROLE_VISUALIZATION, indent),
        f"{prefix}{{",
        f'{child}uniform token subdivisionScheme = "none"',
        f"{child}uniform bool doubleSided = true",
        (
            f"{child}rel material:binding = "
            f"</{GEOMETRY_EXPORT_ROOT_PRIM}/{GEOMETRY_EXPORT_LOOKS_PRIM}/{GEOMETRY_EXPORT_SOLID_MATERIAL}>"
        ),
        f"{child}point3f[] points = {_usd_vec3_array(mesh.get('points') or [])}",
        f"{child}int[] faceVertexCounts = {_usd_int_array(mesh.get('vertex_counts') or [])}",
        f"{child}int[] faceVertexIndices = {_usd_int_array(mesh.get('vertex_indices') or [])}",
        f"{child}color3f[] primvars:displayColor = [{_usd_vec3(display_color)}] (",
        f'{child}    interpolation = "constant"',
        f"{child})",
        f"{child}float[] primvars:displayOpacity = [{_usd_number(opacity)}] (",
        f'{child}    interpolation = "constant"',
        f"{child})",
    ]
    if colors != "[]":
        lines.append(f"{child}color3f[] primvars:findsurface:faceDisplayColor = {colors} (")
        lines.append(f'{child}    interpolation = "faceVarying"')
        lines.append(f"{child})")
    lines.append(f"{prefix}}}")
    return lines


def _visualization_wire_usda_lines(mesh, indent=0):
    wire_lines = mesh.get("wire_lines") or []
    points = [point for line in wire_lines for point in line]
    if not points:
        return []
    prefix = " " * indent
    child = " " * (indent + 4)
    return [
        *_usd_prim_header_lines("BasisCurves", "VisualizationWire", usd_schema.ROLE_VISUALIZATION, indent),
        f"{prefix}{{",
        (
            f"{child}rel material:binding = "
            f"</{GEOMETRY_EXPORT_ROOT_PRIM}/{GEOMETRY_EXPORT_LOOKS_PRIM}/{GEOMETRY_EXPORT_WIRE_MATERIAL}>"
        ),
        f'{child}token type = "linear"',
        f'{child}token wrap = "nonperiodic"',
        f"{child}int[] curveVertexCounts = {_usd_int_array(len(line) for line in wire_lines)}",
        f"{child}point3f[] points = {_usd_vec3_array(points)}",
        f"{child}float[] widths = [{_usd_number(_wire_width_usd())}]",
        f"{child}color3f[] primvars:displayColor = [{_usd_vec3(_rgb_from_rgba(SURFACE_WIRE_COLOR))}] (",
        f'{child}    interpolation = "constant"',
        f"{child})",
        f"{child}float[] primvars:displayOpacity = [{_usd_number(_alpha_from_rgba(SURFACE_WIRE_COLOR))}] (",
        f'{child}    interpolation = "constant"',
        f"{child})",
        f"{prefix}}}",
    ]


def _usd_prim_header_lines(type_name, prim_name, schema_role=None, indent=0):
    prefix = " " * indent
    schema_lines = _findsurface_api_schema_usda_lines(schema_role, indent + 4)
    if not schema_lines:
        return [f'{prefix}def {type_name} "{prim_name}"']
    return [
        f'{prefix}def {type_name} "{prim_name}" (',
        *schema_lines,
        f"{prefix})",
    ]


def _findsurface_api_schema_usda_lines(schema_role, indent=0):
    if not schema_role:
        return []
    return usd_schema.api_schemas_metadata_lines(schema_role, indent=indent)


def _surface_color_from_mesh(mesh):
    colors = mesh.get("colors") or []
    if colors and isinstance(colors[0], (list, tuple)) and len(colors[0]) >= 3:
        return _rgb_from_rgba(colors[0])
    return _rgb_from_rgba(SURFACE_SOLID_COLOR)


def _surface_opacity_from_mesh(mesh):
    colors = mesh.get("colors") or []
    if colors and isinstance(colors[0], (list, tuple)) and len(colors[0]) >= 4:
        return max(_alpha_from_rgba(colors[0]), 0.18)
    return max(_alpha_from_rgba(SURFACE_SOLID_COLOR), 0.18)


def _rgb_from_rgba(value):
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        return (1.0, 1.0, 1.0)
    return (float(value[0]), float(value[1]), float(value[2]))


def _alpha_from_rgba(value):
    if not isinstance(value, (list, tuple)) or len(value) < 4:
        return 1.0
    return float(value[3])


def _wire_width_usd():
    return max(float(SURFACE_WIRE_THICKNESS) * 0.0025, 0.002)


def _usd_attribute_value(value):
    if isinstance(value, bool):
        return "bool", _usd_bool(value)
    if isinstance(value, int) and not isinstance(value, bool):
        return "int", str(int(value))
    if isinstance(value, float):
        return "double", _usd_number(value)
    if isinstance(value, str):
        return "string", _usd_string(value)
    if _is_vec3(value):
        return "double3", _usd_vec3(value)
    if _is_number_sequence(value):
        return "double[]", _usd_number_array(value)
    if _is_vec3_sequence(value):
        return "double3[]", _usd_vec3_array(value)
    return None, None


def _is_vec3(value):
    return isinstance(value, (list, tuple)) and len(value) == 3 and all(_is_number(item) for item in value)


def _is_number_sequence(value):
    return isinstance(value, (list, tuple)) and all(_is_number(item) for item in value)


def _is_vec3_sequence(value):
    return isinstance(value, (list, tuple)) and all(_is_vec3(item) for item in value)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _unique_prim_name(name, used_names):
    candidate = name
    suffix = 2
    while candidate in used_names:
        candidate = f"{name}_{suffix}"
        suffix += 1
    used_names.add(candidate)
    return candidate


def _usd_identifier(value, fallback_index=1):
    text = str(value or "").strip()
    text = re.sub(r"[^A-Za-z0-9_]+", "_", text).strip("_")
    if not text:
        text = f"Geometry_{fallback_index}"
    if not re.match(r"^[A-Za-z_]", text):
        text = f"Geometry_{text}"
    return text


def _usd_property_identifier(value):
    return _usd_identifier(value, fallback_index=1)


def _usd_string(value):
    return json.dumps("" if value is None else str(value))


def _usd_bool(value):
    return "true" if bool(value) else "false"


def _usd_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    if not math.isfinite(number):
        number = 0.0
    return format(number, ".12g")


def _usd_vec3(value):
    values = list(value)
    if len(values) != 3:
        values = [0.0, 0.0, 0.0]
    return f"({_usd_number(values[0])}, {_usd_number(values[1])}, {_usd_number(values[2])})"


def _usd_vec3_array(values):
    return "[" + ", ".join(_usd_vec3(value) for value in values) + "]"


def _usd_color3_array(values):
    colors = []
    for value in values:
        if not isinstance(value, (list, tuple)) or len(value) < 3:
            continue
        colors.append(f"({_usd_number(value[0])}, {_usd_number(value[1])}, {_usd_number(value[2])})")
    return "[" + ", ".join(colors) + "]"


def _usd_int_array(values):
    return "[" + ", ".join(str(int(value)) for value in values) + "]"


def _usd_number_array(values):
    return "[" + ", ".join(_usd_number(value) for value in values) + "]"


def _write_payload(path, payload, extra_lines=None):
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True)
    lines = ["#usda 1.0", PAYLOAD_BEGIN]
    lines.extend(f"# {line}" if line else "#" for line in text.splitlines())
    lines.append(PAYLOAD_END)
    if extra_lines:
        lines.append("")
        lines.extend(extra_lines)
    lines.append("")
    with open(path, "w", encoding="utf-8", newline="\n") as file:
        file.write("\n".join(lines))


def _read_payload(path):
    collecting = False
    json_lines = []
    with open(path, "r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.rstrip("\n")
            if line == PAYLOAD_BEGIN:
                collecting = True
                continue
            if line == PAYLOAD_END:
                break
            if collecting:
                json_lines.append(line[2:] if line.startswith("# ") else line.lstrip("#"))
    if not json_lines:
        raise WorkspaceError("The selected USD does not contain FindSurface workspace metadata.")
    try:
        return json.loads("\n".join(json_lines))
    except json.JSONDecodeError as exc:
        raise WorkspaceError(f"Invalid FindSurface workspace metadata: {exc}") from exc


def _json_safe(value):
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return value


def _vec3_list(points):
    return [tuple(_vec3(point)) for point in points]


def _vec3(point):
    if len(point) != 3:
        raise WorkspaceError("Expected a 3D point in workspace metadata.")
    return (float(point[0]), float(point[1]), float(point[2]))
