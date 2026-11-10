"""Versioned MCP adapter contract for GeoAgent M6.

Contract: ``geoagent.mcp-adapter/2.0.0``

The adapter consumes a *deserialised* MCP ``tools/call`` exchange (plus optional
raw bytes) and returns one StepResult carrying a single M6 Verdict. It never
declares success from the HTTP status alone, and never declares results exist
from ``provider.count`` alone.

Shape-tolerance for the flattened ``{count, results}`` replies, GeoJSON forms
and ``{type, data}`` scalar envelopes follows the measured M5 live pilot; this
module re-implements the extraction in the M6 package so the public core has
no dependency on private sealed code.

Every payload path actually read is recorded with a value digest, so Phase 2
can prove the executor consumed a response rather than merely receiving it.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from . import semantics as geo
from .outcomes import (
    CAPABILITY_UNAVAILABLE,
    EVIDENCE_MISSING,
    EMPTY_RESULT,
    INVALID_ARGUMENT,
    PROVIDER_ERROR,
    SEMANTIC_CONFLICT,
    SUCCESS,
    Outcome,
    Responsibility,
    StepResult,
    Verdict,
    digest,
    ok,
    verdict,
)

ADAPTER_CONTRACT_VERSION = "geoagent.mcp-adapter/2.0.0"

TOOL_FOR_CAPABILITY: dict[str, str] = {
    "geocode.forward": "geocode_address",
    "geocode.structured": "geocode_structured_address",
    "geocode.reverse": "reverse_geocode_coordinates",
    "places.search": "search_places",
    "places.categories": "list_place_categories",
    "route.route": "calculate_route",
    "route.matrix": "calculate_route_matrix",
    "spatial.relate": "evaluate_spatial_relation",
    "geometry.measure": "measure_geometry",
    "geometry.combine": "combine_geometries",
    "geometry.transform": "transform_geometry",
}

CAPABILITY_ALIASES: dict[str, str] = {
    "geocode.reverse_geocode": "geocode.reverse",
    "places.search_places": "places.search",
    "route.calculate": "route.route",
    "route.calculate_matrix": "route.matrix",
    "spatial.evaluate_relation": "spatial.relate",
    "geometry.measure_geometry": "geometry.measure",
}

_GEOCODING_TOOLS = frozenset(
    {"geocode_address", "geocode_structured_address", "reverse_geocode_coordinates", "search_places"}
)
_GEOMETRY_TOOLS = frozenset({"combine_geometries", "transform_geometry"})
_LIST_KEYS = ("results", "places", "items", "features", "data", "categories")
_GEOJSON_TYPES = frozenset(
    {"Point", "LineString", "Polygon", "MultiPoint", "MultiLineString", "MultiPolygon"}
)

_CAPABILITY_MISSING_MARKERS = (
    "unknown tool", "tool not found", "method not found", "not implemented",
    "not authorized", "unauthorised", "capability unavailable", "not enabled",
    "unsupported capability", "-32601",
)
_SERVICE_FAILURE_MARKERS = (
    "service unavailable", "temporarily unavailable", "internal server error",
    "upstream error", "bad gateway", "timeout", "-32603",
)


def resolve_tool(capability: str) -> tuple[str | None, Verdict | None]:
    key = CAPABILITY_ALIASES.get(capability, capability)
    tool = TOOL_FOR_CAPABILITY.get(key)
    if tool is None:
        return None, verdict(
            CAPABILITY_UNAVAILABLE, "CAPABILITY_NOT_IN_CONTRACT",
            Responsibility.TOOL_EXECUTOR, capability=capability,
            contract_version=ADAPTER_CONTRACT_VERSION,
        )
    return tool, None


class FieldReader:
    """Records each consumed payload path and the digest of the value read."""

    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.consumed: list[dict[str, Any]] = []

    def get(self, *path: str | int, default: Any = None) -> Any:
        node = self.payload
        for part in path:
            if isinstance(node, Mapping) and isinstance(part, str) and part in node:
                node = node[part]
            elif isinstance(node, Sequence) and not isinstance(node, (str, bytes)) and isinstance(part, int):
                if -len(node) <= part < len(node):
                    node = node[part]
                else:
                    self._record(path, None, False)
                    return default
            else:
                self._record(path, None, False)
                return default
        self._record(path, node, True)
        return node

    def has(self, *path: str | int) -> bool:
        marker = len(self.consumed)
        self.get(*path)
        found = self.consumed[marker]["present"]
        self.consumed.pop()
        return found

    def _record(self, path: tuple[str | int, ...], value: Any, present: bool) -> None:
        self.consumed.append(
            {
                "path": ".".join(str(p) for p in path),
                "present": present,
                "value_sha256": digest(value) if present else None,
                "json_type": type(value).__name__ if present else None,
            }
        )

    def note(self, path: str, value: Any) -> None:
        self.consumed.append(
            {"path": path, "present": True, "value_sha256": digest(value), "json_type": type(value).__name__}
        )


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _split_envelope(envelope: Any) -> tuple[Any, Any, dict[str, Any]]:
    """Return (jsonrpc_error, result_object, transport_meta)."""
    if not isinstance(envelope, Mapping):
        return None, None, {"envelope_type": type(envelope).__name__}
    meta = {
        "jsonrpc_id": envelope.get("id"),
        "envelope_keys": sorted(str(k) for k in envelope.keys())[:24],
    }
    error = envelope.get("error")
    result = envelope.get("result")
    if result is None and "structuredContent" in envelope:
        result = envelope
    return error, result, meta


def _marker_hit(text: str, markers: Sequence[str]) -> str | None:
    lowered = text.lower()
    for marker in markers:
        if marker in lowered:
            return marker
    return None


def _business_status(result: Mapping[str, Any], payload: Any, reader: FieldReader | None) -> tuple[Any, str | None]:
    for source, keys in ((result, ("statusCode", "status_code", "status")), (payload, ("statusCode", "status_code", "status"))):
        if not isinstance(source, Mapping):
            continue
        for key in keys:
            if key in source:
                if reader is not None and source is payload:
                    reader.note(f"payload.{key}", source[key])
                return source[key], key
    return None, None


def _status_is_failure(value: Any) -> bool:
    if isinstance(value, bool):
        return not value
    if isinstance(value, int) and not isinstance(value, bool):
        return not (200 <= value < 300)
    if isinstance(value, str):
        key = value.strip().lower()
        return key not in ("ok", "success", "200", "2xx", "true")
    return False


def _unwrap(result: Mapping[str, Any]) -> tuple[Any, str, Verdict | None]:
    """Read the MCP result body. Returns (payload, kind, problem)."""
    structured = result.get("structuredContent")
    if isinstance(structured, Mapping) and structured:
        return dict(structured), "structuredContent", None
    content = result.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, Mapping) and block.get("type") == "text" and isinstance(block.get("text"), str):
                text = block["text"]
                try:
                    return json.loads(text), "content.text/json", None
                except ValueError:
                    return {"__text__": text}, "content.text/plain", None
    if isinstance(content, list) and content:
        return {"__content__": content}, "content/other", verdict(
            EVIDENCE_MISSING, "MCP_CONTENT_BLOCK_UNREADABLE"
        )
    return None, "none", verdict(EVIDENCE_MISSING, "MCP_RESULT_BODY_MISSING")


def _typed_envelope(payload: Any) -> tuple[str | None, Any]:
    if isinstance(payload, Mapping) and "data" in payload and set(payload.keys()) <= {"type", "data", "units"}:
        return str(payload.get("type")), payload.get("data")
    return None, None


def _extract_geometry(payload: Any, reader: FieldReader | None = None) -> dict[str, Any] | None:
    declared, inner = _typed_envelope(payload)
    path: tuple[str | int, ...] = ()
    if declared in ("geometry", "geojson") and isinstance(inner, Mapping):
        payload = inner
        path = ("data",)
    node = payload
    for _ in range(6):
        if not isinstance(node, Mapping):
            return None
        if node.get("type") in _GEOJSON_TYPES:
            if reader is not None:
                if path:
                    reader.get(*path)
                else:
                    reader.note("payload", node)
            return dict(node)
        moved = False
        for key in ("geometry", "result", "feature", "data", "route", "shape"):
            if isinstance(node.get(key), Mapping):
                node = node[key]
                path += (key,)
                moved = True
                break
        if moved:
            continue
        features = node.get("features")
        if isinstance(features, list) and features and isinstance(features[0], Mapping):
            node = features[0]
            path += ("features", 0)
            continue
        return None
    return None


def _items(payload: Any, reader: FieldReader) -> tuple[list[Mapping[str, Any]], str]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, Mapping)], "bare_list"
    if isinstance(payload, Mapping):
        for key in _LIST_KEYS:
            value = reader.get(key)
            if isinstance(value, list):
                items: list[Mapping[str, Any]] = []
                for entry in value:
                    if not isinstance(entry, Mapping):
                        continue
                    properties = entry.get("properties")
                    geometry = entry.get("geometry")
                    if isinstance(properties, Mapping) and isinstance(geometry, Mapping):
                        merged = dict(properties)
                        coords = geometry.get("coordinates")
                        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
                            merged.setdefault("lon", coords[0])
                            merged.setdefault("lat", coords[1])
                        items.append(merged)
                    else:
                        items.append(entry)
                return items, key
    return [], "none"


def _record(item: Mapping[str, Any], reader: FieldReader, prefix: str) -> dict[str, Any]:
    lat = _finite_number(item.get("lat"))
    lon = _finite_number(item.get("lon"))
    if lat is None or lon is None:
        geom = item.get("geometry")
        if isinstance(geom, Mapping) and geom.get("type") == "Point":
            coords = geom.get("coordinates")
            if isinstance(coords, (list, tuple)) and len(coords) >= 2:
                lon, lat = _finite_number(coords[0]), _finite_number(coords[1])
    reader.note(f"{prefix}.lat_lon", [lat, lon])
    return {
        "place_id": item.get("place_id") or item.get("id"),
        "formatted": item.get("formatted") or item.get("address_line1"),
        "name": item.get("name") or item.get("address_line1"),
        "country_code": item.get("country_code"),
        "city": item.get("city"),
        "lat": lat,
        "lon": lon,
        "distance": _finite_number(item.get("distance")),
    }


def _normalise(tool: str, payload: Any, reader: FieldReader) -> dict[str, Any]:
    declared, inner = _typed_envelope(payload)
    if declared in ("number", "boolean") and inner is not None:
        reader.note("typed_envelope.data", inner)
        return {
            "scalar": inner,
            "value": inner,
            "declared_type": declared,
            "key_used": "typed_envelope.data",
            "units": payload.get("units") if isinstance(payload, Mapping) else None,
        }

    if tool == "list_place_categories":
        categories = reader.get("categories")
        category_list = categories if isinstance(categories, list) else None
        provider_count = reader.get("count") if isinstance(payload, Mapping) else None
        count_value = provider_count if isinstance(provider_count, int) and not isinstance(provider_count, bool) else None
        return {
            "result_count": len(category_list) if category_list is not None else 0,
            "provider_count": count_value,
            "count_matches_array": (count_value == len(category_list))
            if (count_value is not None and category_list is not None) else None,
            "category_count": len(category_list) if category_list is not None else None,
            "results": [],
            "top": None,
            "source_shape": "categories" if category_list is not None else "none",
        }

    if tool in _GEOCODING_TOOLS:
        items, source_key = _items(payload, reader)
        records = [_record(item, reader, f"{source_key}[{i}]") for i, item in enumerate(items)]
        provider_count = reader.get("count") if isinstance(payload, Mapping) else None
        count_value = provider_count if isinstance(provider_count, int) and not isinstance(provider_count, bool) else None
        return {
            "result_count": len(records),
            "provider_count": count_value,
            "count_matches_array": (count_value == len(records)) if count_value is not None else None,
            "results": records,
            "top": records[0] if records else None,
            "source_shape": source_key,
        }

    if tool == "calculate_route":
        items, source_key = _items(payload, reader)
        base = items[0] if items else (payload if isinstance(payload, Mapping) else {})
        distance = _finite_number(base.get("distance") or base.get("distance_m") or base.get("length"))
        duration = _finite_number(base.get("time") or base.get("duration") or base.get("time_s"))
        geom = _extract_geometry(payload)
        reader.note("route.distance", base.get("distance") or base.get("distance_m") or base.get("length"))
        reader.note("route.time", base.get("time") or base.get("duration") or base.get("time_s"))
        return {
            "distance_m": distance,
            "time_s": duration,
            "geometry_present": geom is not None,
            "geometry": geom,
            "source_shape": source_key,
        }

    if tool == "calculate_route_matrix":
        raw = None
        key_used = None
        if isinstance(payload, Mapping):
            for key in ("sources_to_targets", "matrix", "distances", "durations", "results"):
                candidate = reader.get(key)
                if isinstance(candidate, list):
                    raw, key_used = candidate, key
                    break
        matrix: list[list[float | None]] = []
        if isinstance(raw, list):
            for row in raw:
                if not isinstance(row, list):
                    continue
                line: list[float | None] = []
                for cell in row:
                    if isinstance(cell, Mapping):
                        line.append(_finite_number(cell.get("distance")))
                    else:
                        line.append(_finite_number(cell))
                matrix.append(line)
        sources = reader.get("sources") if isinstance(payload, Mapping) else None
        targets = reader.get("targets") if isinstance(payload, Mapping) else None
        return {
            "matrix_key": key_used,
            "matrix": matrix or None,
            "sources": sources if isinstance(sources, list) else None,
            "targets": targets if isinstance(targets, list) else None,
            "distance_units": payload.get("distance_units") if isinstance(payload, Mapping) else None,
        }

    if tool == "evaluate_spatial_relation":
        for key in ("value", "result", "relation", "is_related", "answer", "boolean"):
            if isinstance(payload, Mapping) and key in payload:
                return {"value": reader.get(key), "key_used": key, "operation": payload.get("operation")}
        if isinstance(payload, bool):
            return {"value": payload, "key_used": "bare_boolean"}
        return {"value": None, "key_used": None}

    if tool == "measure_geometry":
        for key in ("value", "result", "area", "length", "distance", "measurement"):
            if isinstance(payload, Mapping) and key in payload:
                return {"value": reader.get(key), "key_used": key, "units": payload.get("units")}
        return {"value": None, "key_used": None, "geometry": _extract_geometry(payload)}

    if tool in _GEOMETRY_TOOLS:
        return {"geometry": _extract_geometry(payload, reader), "operation": payload.get("operation") if isinstance(payload, Mapping) else None}

    return {"payload_type": type(payload).__name__}


def _validate_arguments(
    tool: str,
    arguments: Mapping[str, Any],
    context: geo.SemanticContext,
    expected_bbox: Sequence[float] | None,
) -> Verdict | None:
    """Argument-level semantics, checked once here and never again downstream."""
    if tool == "transform_geometry" and str(arguments.get("operation", "")).lower() == "simplify":
        if "tolerance" not in arguments:
            return verdict(EVIDENCE_MISSING, "SIMPLIFY_TOLERANCE_MISSING")
        raw_unit = arguments.get("tolerance_unit")
        if raw_unit is None:
            return verdict(
                INVALID_ARGUMENT, "SIMPLIFY_TOLERANCE_UNIT_MISSING",
                hint="a bare tolerance number has no unit; P2-M5 is retained as the negative case",
                tolerance=arguments.get("tolerance"), legacy_case="P2-M5",
            )
        unit, reason = geo.parse_length_unit(raw_unit)
        if unit is None:
            return verdict(
                INVALID_ARGUMENT, reason,
                hint="explicit tolerance_unit is required for simplify",
                tolerance=arguments.get("tolerance"), tolerance_unit=raw_unit,
            )
        tolerance = _finite_number(arguments.get("tolerance"))
        if tolerance is None or tolerance < 0:
            return verdict(INVALID_ARGUMENT, "SIMPLIFY_TOLERANCE_NOT_FINITE_NONNEGATIVE")
        if unit in (geo.LengthUnit.RADIAN, geo.LengthUnit.UNKNOWN):
            return verdict(INVALID_ARGUMENT, "SIMPLIFY_TOLERANCE_UNIT_NOT_ACTIONABLE", unit=unit.value)
    for key in ("waypoints", "points", "locations", "sources", "targets"):
        nodes = arguments.get(key)
        if not isinstance(nodes, (list, tuple)):
            continue
        for index, node in enumerate(nodes):
            pair, problem = geo.coordinate_from(node, crs=context.crs, order=context.coordinate_order)
            if problem is not None:
                return problem.with_evidence(argument_key=key, index=index)
            if pair is not None and expected_bbox and geo.detect_lat_lon_swap(pair[0], pair[1], expected_bbox):
                return verdict(
                    SEMANTIC_CONFLICT, "REQUEST_LAT_LON_SWAP_SUSPECTED",
                    argument_key=key, index=index, lat=pair[0], lon=pair[1],
                )
    return None


@dataclass
class AdaptResult:
    step: StepResult
    checks: list[dict[str, Any]] = field(default_factory=list)
    payload_kind: str = "none"
    transport_meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": ADAPTER_CONTRACT_VERSION,
            "step": self.step.to_dict(),
            "checks": self.checks,
            "payload_kind": self.payload_kind,
            "transport_meta": self.transport_meta,
        }


def adapt(
    envelope: Any,
    *,
    capability: str,
    tool: str | None = None,
    arguments: Mapping[str, Any] | None = None,
    http_status: int = 200,
    raw_bytes: bytes | None = None,
    step_id: str = "step",
    require_nonempty: bool = False,
    require_square_matrix: bool = False,
    expected_bbox: Sequence[float] | None = None,
) -> AdaptResult:
    """One call = one StepResult with a single terminal verdict."""
    arguments = dict(arguments or {})
    checks: list[dict[str, Any]] = []

    def check(name: str, outcome: Outcome, reason: str, **observed: Any) -> None:
        checks.append({"id": name, "outcome": outcome.value, "reason": reason, "observed": observed})

    def finish(v: Verdict, *, read: dict[str, Any] | None = None, payload: Any = None,
               consumed: list[dict[str, Any]] | None = None, kind: str = "none",
               meta: dict[str, Any] | None = None) -> AdaptResult:
        step = StepResult(
            step_id=step_id, capability=capability, tool=tool or "",
            verdict=v, read=read or {}, payload=payload,
            contract_version=ADAPTER_CONTRACT_VERSION, consumed=consumed or [],
        )
        return AdaptResult(step, checks, kind, meta or {})

    if tool is None:
        resolved, problem = resolve_tool(capability)
        if problem is not None:
            check("capability_resolution", CAPABILITY_UNAVAILABLE, problem.reason_code)
            return finish(problem)
        tool = resolved or ""
    check("capability_resolution", SUCCESS, "TOOL_RESOLVED", tool=tool)

    rpc_error, result, meta = _split_envelope(envelope)
    if raw_bytes is not None:
        import hashlib
        meta["raw_message_sha256"] = hashlib.sha256(raw_bytes).hexdigest()
        meta["raw_message_bytes"] = len(raw_bytes)
        meta["capture_layer"] = "MCP_CLIENT_OBSERVABLE"
    if rpc_error is not None:
        text = json.dumps(rpc_error, ensure_ascii=False, default=str)
        marker = _marker_hit(text, _CAPABILITY_MISSING_MARKERS)
        if marker:
            v = verdict(CAPABILITY_UNAVAILABLE, "MCP_RPC_CAPABILITY_MISSING", detail=marker)
        else:
            v = verdict(PROVIDER_ERROR, "MCP_RPC_ERROR", detail=text[:300])
        check("jsonrpc_layer", v.outcome, v.reason_code)
        return finish(v, kind="error", meta=meta)
    if not isinstance(result, Mapping):
        v = verdict(EVIDENCE_MISSING, "MCP_RESULT_ENVELOPE_MISSING")
        check("envelope", EVIDENCE_MISSING, v.reason_code)
        return finish(v, kind="none", meta=meta)
    if not (200 <= http_status < 300):
        v = verdict(PROVIDER_ERROR, "HTTP_NON_SUCCESS", http_status=http_status)
        check("http_layer", PROVIDER_ERROR, v.reason_code, http_status=http_status)
        return finish(v, kind="error", meta=meta)
    check("http_layer", SUCCESS, "HTTP_OK_NOT_SUFFICIENT", http_status=http_status)

    if result.get("isError") is True:
        detail = json.dumps(result.get("content"), ensure_ascii=False, default=str)[:300]
        marker = _marker_hit(detail, _CAPABILITY_MISSING_MARKERS)
        v = verdict(
            CAPABILITY_UNAVAILABLE if marker else PROVIDER_ERROR,
            "MCP_TOOL_REPORTED_ERROR_HTTP200" if not marker else "MCP_TOOL_CAPABILITY_MISSING",
            detail=detail, marker=marker,
        )
        check("is_error_layer", v.outcome, v.reason_code)
        return finish(v, kind="error", meta=meta)
    check("is_error_layer", SUCCESS, "IS_ERROR_FALSE")

    payload, kind, unwrap_problem = _unwrap(result)
    if unwrap_problem is not None and payload is None:
        check("unwrap", EVIDENCE_MISSING, unwrap_problem.reason_code)
        return finish(unwrap_problem, kind=kind, meta=meta)
    reader = FieldReader(payload)
    status_value, status_key = _business_status(result, payload, reader)
    if status_value is not None and _status_is_failure(status_value):
        v = verdict(PROVIDER_ERROR, "MCP_BUSINESS_STATUS_FAILURE",
                    status_key=status_key, status_value=status_value)
        check("business_status", PROVIDER_ERROR, v.reason_code, key=status_key, value=status_value)
        return finish(v, payload=payload, consumed=reader.consumed, kind=kind, meta=meta)
    check("business_status", SUCCESS, "BUSINESS_STATUS_OK_OR_ABSENT", key=status_key, value=status_value)

    if unwrap_problem is not None:
        check("unwrap", EVIDENCE_MISSING, unwrap_problem.reason_code)
        return finish(unwrap_problem, payload=payload, consumed=reader.consumed, kind=kind, meta=meta)

    read = _normalise(tool, payload, reader)
    consumed = reader.consumed

    context = geo.validate_context(arguments)
    if context.verdict is not None:
        check("semantic_context", context.verdict.outcome, context.verdict.reason_code)
        return finish(context.verdict, read=read, payload=payload, consumed=consumed, kind=kind, meta=meta)
    argument_problem = _validate_arguments(tool, arguments, context, expected_bbox)
    if argument_problem is not None:
        check("arguments", argument_problem.outcome, argument_problem.reason_code)
        return finish(argument_problem, read=read, payload=payload, consumed=consumed, kind=kind, meta=meta)
    check("arguments", SUCCESS, "ARGUMENT_SEMANTICS_VALID")

    declared_crs, _ = geo.parse_crs(payload.get("crs") if isinstance(payload, Mapping) else None)
    if declared_crs is not geo.Crs.UNKNOWN and declared_crs is not context.crs:
        v = verdict(SEMANTIC_CONFLICT, "CRS_DISAGREES_BETWEEN_REQUEST_AND_RESPONSE",
                    request_crs=context.crs.value, response_crs=declared_crs.value)
        check("crs", SEMANTIC_CONFLICT, v.reason_code)
        return finish(v, read=read, payload=payload, consumed=consumed, kind=kind, meta=meta)
    check("crs", SUCCESS, "CRS_CONSISTENT", crs=context.crs.value)

    snapping = arguments.get("snapping_radius_m")
    if snapping is not None:
        radius = _finite_number(snapping)
        if radius is None or radius < 0 or radius > geo.MAX_SNAP_RADIUS_M:
            v = verdict(INVALID_ARGUMENT, "SNAPPING_RADIUS_OUTSIDE_POLICY",
                        radius_m=radius, plan=geo.snapping_plan().to_dict())
            check("snapping", INVALID_ARGUMENT, v.reason_code)
            return finish(v, read=read, payload=payload, consumed=consumed, kind=kind, meta=meta)
    if arguments.get("expand_until_found") or arguments.get("unlimited_snapping"):
        v = verdict(INVALID_ARGUMENT, "UNLIMITED_SNAPPING_FORBIDDEN", plan=geo.snapping_plan().to_dict())
        check("snapping", INVALID_ARGUMENT, v.reason_code)
        return finish(v, read=read, payload=payload, consumed=consumed, kind=kind, meta=meta)
    check("snapping", SUCCESS, "SNAPPING_POLICY_SATISFIED", plan=geo.snapping_plan().to_dict())

    if tool in _GEOCODING_TOOLS or tool == "list_place_categories":
        if read.get("source_shape") == "none":
            v = verdict(EVIDENCE_MISSING, "RESULT_CONTAINER_FIELD_MISSING",
                        payload_keys=sorted(str(k) for k in payload.keys())[:20]
                        if isinstance(payload, Mapping) else [],
                        hint="no results/places/items/features/data/categories container")
            check("result_container", EVIDENCE_MISSING, v.reason_code)
            return finish(v, read=read, payload=payload, consumed=consumed, kind=kind, meta=meta)
        count_value = read.get("provider_count")
        array_length = read.get("result_count")
        if count_value is not None and count_value != array_length:
            v = verdict(SEMANTIC_CONFLICT, "PROVIDER_COUNT_DISAGREES_WITH_ARRAY",
                        provider_count=count_value, array_length=array_length)
            check("count_vs_array", SEMANTIC_CONFLICT, v.reason_code,
                  provider_count=count_value, array_length=array_length)
            return finish(v, read=read, payload=payload, consumed=consumed, kind=kind, meta=meta)
        check("count_vs_array", SUCCESS, "COUNT_MATCHES_ARRAY_OR_NOT_DECLARED",
              provider_count=count_value, array_length=array_length)
        for index, item in enumerate(read.get("results") or []):
            problem = geo.validate_lat_lon(item.get("lat"), item.get("lon"))
            if problem is not None:
                check("coordinate_range", problem.outcome, problem.reason_code, index=index)
                return finish(problem, read=read, payload=payload, consumed=consumed, kind=kind, meta=meta)
            lat, lon = item.get("lat"), item.get("lon")
            if lat is not None and lon is not None and expected_bbox and geo.detect_lat_lon_swap(lat, lon, expected_bbox):
                v = verdict(SEMANTIC_CONFLICT, "LAT_LON_SWAP_SUSPECTED", index=index, lat=lat, lon=lon)
                check("coordinate_order", SEMANTIC_CONFLICT, v.reason_code)
                return finish(v, read=read, payload=payload, consumed=consumed, kind=kind, meta=meta)
        check("coordinate_range", SUCCESS, "COORDINATES_VALID")
        if array_length == 0:
            v = verdict(EMPTY_RESULT, "NO_RESULTS_RETURNED", provider_count=count_value)
            check("result_presence", EMPTY_RESULT, v.reason_code)
            return finish(v, read=read, payload=payload, consumed=consumed, kind=kind, meta=meta)
        check("result_presence", SUCCESS, "RESULTS_PRESENT", array_length=array_length)

    if tool == "calculate_route_matrix":
        matrix = read.get("matrix")
        sem = geo.matrix_semantics(
            matrix, sources=read.get("sources"), targets=read.get("targets"),
            distance_units=read.get("distance_units"), require_square=require_square_matrix,
        )
        read["matrix_semantics"] = sem.to_dict()
        if sem.verdict.outcome is not SUCCESS:
            check("matrix_semantics", sem.verdict.outcome, sem.verdict.reason_code)
            return finish(sem.verdict, read=read, payload=payload, consumed=consumed, kind=kind, meta=meta)
        check("matrix_semantics", SUCCESS, "MATRIX_SEMANTICS_OK",
              rectangular=sem.rectangular, symmetric=sem.symmetric,
              direction_dependent=sem.direction_dependent)

    if tool == "calculate_route":
        if read.get("distance_m") is None:
            v = verdict(EVIDENCE_MISSING, "ROUTE_DISTANCE_FIELD_MISSING")
            check("route_distance", EVIDENCE_MISSING, v.reason_code)
            return finish(v, read=read, payload=payload, consumed=consumed, kind=kind, meta=meta)
        check("route_distance", SUCCESS, "ROUTE_DISTANCE_READ", distance_m=read["distance_m"])
        if context.distance_model is geo.DistanceModel.UNKNOWN:
            check("distance_model", SUCCESS, "DISTANCE_MODEL_UNDECLARED_RECORDED",
                  hint="road_network distance must not be compared to straight-line geodesic")
        elif context.distance_model is geo.DistanceModel.HAVERSINE_SPHERE:
            v = verdict(SEMANTIC_CONFLICT, "GEODESIC_MODEL_DECLARED_FOR_ROAD_ROUTE")
            check("distance_model", SEMANTIC_CONFLICT, v.reason_code)
            return finish(v, read=read, payload=payload, consumed=consumed, kind=kind, meta=meta)

    if tool in ("evaluate_spatial_relation", "measure_geometry"):
        if read.get("value") is None:
            v = verdict(EVIDENCE_MISSING, "EXPECTED_VALUE_FIELD_MISSING", key_used=read.get("key_used"))
            check("value_presence", EVIDENCE_MISSING, v.reason_code)
            return finish(v, read=read, payload=payload, consumed=consumed, kind=kind, meta=meta)
        check("value_presence", SUCCESS, "VALUE_READ", key_used=read.get("key_used"))

    if require_nonempty and tool in _GEOMETRY_TOOLS and not read.get("geometry"):
        v = verdict(EMPTY_RESULT, "GEOMETRY_RESULT_EMPTY")
        check("geometry_presence", EMPTY_RESULT, v.reason_code)
        return finish(v, read=read, payload=payload, consumed=consumed, kind=kind, meta=meta)

    if unwrap_problem is not None:
        return finish(unwrap_problem, read=read, payload=payload, consumed=consumed, kind=kind, meta=meta)

    return finish(
        ok("ADAPTER_SUCCESS", contract_version=ADAPTER_CONTRACT_VERSION,
           source_layer=Responsibility.TOOL_EXECUTOR.value),
        read=read, payload=payload, consumed=consumed, kind=kind, meta=meta,
    )
