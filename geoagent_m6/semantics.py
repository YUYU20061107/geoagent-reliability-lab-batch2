"""GIS semantics for GeoAgent M6.

Units, CRS, coordinate order, ellipsoidal metre/degree conversion, geometry
validity, area and shape deviation, matrix shape/direction, and snapping limits.

All length/degree conversions are WGS84-ellipsoid based and latitude dependent.
A fixed "1 degree = 111 km" style ratio is never used as an exact conversion.
Numerical meridian integration is used for the inverse problem; the local
linear approximation is reported side by side so its error is visible.

This module performs validation once at the entry point. It does not catch
programming errors with broad try/except blocks.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence

from .outcomes import (
    EVIDENCE_MISSING,
    INVALID_ARGUMENT,
    SAFE_ABSTENTION,
    SEMANTIC_CONFLICT,
    SUCCESS,
    Verdict,
    verdict,
)

WGS84_A = 6378137.0
WGS84_F = 1.0 / 298.257223563
WGS84_E2 = WGS84_F * (2.0 - WGS84_F)
EARTH_RADIUS_M = 6371008.8

MAX_LOCAL_APPROX_DISTANCE_M = 50_000.0
MAX_LOCAL_PLANE_EXTENT_M = 20_000.0
MIN_ABS_COS_LATITUDE = 0.02


class LengthUnit(str, Enum):
    METER = "meter"
    KILOMETRE = "kilometre"
    DEGREE = "degree"
    RADIAN = "radian"
    FOOT = "foot"
    MILE = "mile"
    UNKNOWN = "unknown"


class Crs(str, Enum):
    WGS84 = "EPSG:4326"
    WEB_MERCATOR = "EPSG:3857"
    UNKNOWN = "UNKNOWN"


class CoordOrder(str, Enum):
    LON_LAT = "lon,lat"
    LAT_LON = "lat,lon"


class DistanceModel(str, Enum):
    HAVERSINE_SPHERE = "haversine_sphere"
    WGS84_ELLIPSOID = "wgs84_ellipsoid"
    LOCAL_PLANAR = "local_plane"
    ROAD_NETWORK = "road_network"
    UNKNOWN = "unknown"


_UNIT_ALIASES: dict[str, LengthUnit] = {
    "m": LengthUnit.METER,
    "meter": LengthUnit.METER,
    "meters": LengthUnit.METER,
    "metre": LengthUnit.METER,
    "metres": LengthUnit.METER,
    "km": LengthUnit.KILOMETRE,
    "kilometer": LengthUnit.KILOMETRE,
    "kilometre": LengthUnit.KILOMETRE,
    "kilometers": LengthUnit.KILOMETRE,
    "kilometres": LengthUnit.KILOMETRE,
    "deg": LengthUnit.DEGREE,
    "degree": LengthUnit.DEGREE,
    "degrees": LengthUnit.DEGREE,
    "rad": LengthUnit.RADIAN,
    "radian": LengthUnit.RADIAN,
    "radians": LengthUnit.RADIAN,
    "ft": LengthUnit.FOOT,
    "foot": LengthUnit.FOOT,
    "feet": LengthUnit.FOOT,
    "mi": LengthUnit.MILE,
    "mile": LengthUnit.MILE,
    "miles": LengthUnit.MILE,
}

# Unit-system words are deliberately not accepted as a length unit.
AMBIGUOUS_UNIT_SYSTEMS = frozenset({"metric", "imperial", "si", "default", "auto", ""})

_CRS_ALIASES: dict[str, Crs] = {
    "epsg:4326": Crs.WGS84,
    "wgs84": Crs.WGS84,
    "wgs 84": Crs.WGS84,
    "crs84": Crs.WGS84,
    "epsg:3857": Crs.WEB_MERCATOR,
    "web mercator": Crs.WEB_MERCATOR,
}

_ORDER_ALIASES: dict[str, CoordOrder] = {
    "lon,lat": CoordOrder.LON_LAT,
    "lonlat": CoordOrder.LON_LAT,
    "xy": CoordOrder.LON_LAT,
    "geojson": CoordOrder.LON_LAT,
    "lat,lon": CoordOrder.LAT_LON,
    "latlon": CoordOrder.LAT_LON,
    "yx": CoordOrder.LAT_LON,
}

_TO_METRES = {
    LengthUnit.METER: 1.0,
    LengthUnit.KILOMETRE: 1000.0,
    LengthUnit.FOOT: 0.3048,
    LengthUnit.MILE: 1609.344,
}


def parse_length_unit(value: Any) -> tuple[LengthUnit | None, str]:
    """Strict parsing. Returns (unit, reason). Ambiguous words are refused."""
    if not isinstance(value, str):
        return None, "UNIT_NOT_A_STRING"
    key = value.strip().lower()
    if key in AMBIGUOUS_UNIT_SYSTEMS:
        return None, "AMBIGUOUS_UNIT_SYSTEM_REFUSED"
    unit = _UNIT_ALIASES.get(key)
    if unit is None:
        return None, "UNKNOWN_LENGTH_UNIT"
    return unit, "OK"


def parse_crs(value: Any) -> tuple[Crs, str]:
    if value is None:
        return Crs.UNKNOWN, "CRS_NOT_DECLARED"
    if isinstance(value, Crs):
        return value, "OK"
    if isinstance(value, str):
        crs = _CRS_ALIASES.get(value.strip().lower())
        if crs is not None:
            return crs, "OK"
    return Crs.UNKNOWN, "UNKNOWN_CRS"


def parse_coord_order(value: Any) -> tuple[CoordOrder, str]:
    if value is None:
        return CoordOrder.LON_LAT, "ORDER_DEFAULTED_TO_GEOJSON"
    if isinstance(value, CoordOrder):
        return value, "OK"
    if isinstance(value, str):
        order = _ORDER_ALIASES.get(value.strip().lower())
        if order is not None:
            return order, "OK"
    return CoordOrder.LON_LAT, "UNKNOWN_ORDER_DEFAULTED_TO_GEOJSON"


def to_metres(value: float, unit: LengthUnit) -> float | None:
    factor = _TO_METRES.get(unit)
    return None if factor is None else value * factor


# ---------------------------------------------------------------------------
# WGS84 ellipsoid: latitude-dependent conversion
# ---------------------------------------------------------------------------


def meridian_radius_m(lat_deg: float) -> float:
    phi = math.radians(lat_deg)
    w = 1.0 - WGS84_E2 * math.sin(phi) ** 2
    return WGS84_A * (1.0 - WGS84_E2) / (w ** 1.5)


def prime_vertical_radius_m(lat_deg: float) -> float:
    phi = math.radians(lat_deg)
    w = 1.0 - WGS84_E2 * math.sin(phi) ** 2
    return WGS84_A / math.sqrt(w)


def metres_per_degree_lat(lat_deg: float) -> float:
    return meridian_radius_m(lat_deg) * math.pi / 180.0


def metres_per_degree_lon(lat_deg: float) -> float:
    return prime_vertical_radius_m(lat_deg) * math.cos(math.radians(lat_deg)) * math.pi / 180.0


def meridian_arc_m(lat1_deg: float, lat2_deg: float, *, steps: int = 64) -> float:
    """Numerical integral of M(phi) d(phi) between two latitudes (Simpson)."""
    if steps % 2:
        steps += 1
    a, b = math.radians(lat1_deg), math.radians(lat2_deg)
    if a == b:
        return 0.0
    h = (b - a) / steps
    total = meridian_radius_m(math.degrees(a)) + meridian_radius_m(math.degrees(b))
    for i in range(1, steps):
        phi = a + i * h
        total += (4.0 if i % 2 else 2.0) * meridian_radius_m(math.degrees(phi))
    return abs(total * h / 3.0)


def latitude_offset_deg(lat_deg: float, distance_m: float) -> float:
    """Invert the meridian arc numerically (bisection), northward."""
    if distance_m == 0.0:
        return 0.0
    high = 90.0 - lat_deg
    if meridian_arc_m(lat_deg, lat_deg + high) < distance_m:
        return high
    low = 0.0
    for _ in range(80):
        mid = (low + high) / 2.0
        if meridian_arc_m(lat_deg, lat_deg + mid) < distance_m:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


def longitude_offset_deg(lat_deg: float, distance_m: float) -> float:
    return math.degrees(distance_m / prime_vertical_radius_m(lat_deg) / math.cos(math.radians(lat_deg)))


@dataclass(frozen=True)
class DegreeTolerance:
    degrees: float
    latitude_deg: float
    distance_m: float
    model: str
    linear_approx_degrees: float
    divergence_pct: float
    applicable: bool
    verdict: Verdict

    def to_dict(self) -> dict[str, Any]:
        return {
            "degrees": self.degrees,
            "latitude_deg": self.latitude_deg,
            "distance_m": self.distance_m,
            "model": self.model,
            "linear_approx_degrees": self.linear_approx_degrees,
            "divergence_pct": self.divergence_pct,
            "applicable": self.applicable,
            "verdict": self.verdict.to_dict(),
        }


def degrees_for_distance(
    distance_m: float,
    latitude_deg: float,
    *,
    axis: str = "meridian",
) -> DegreeTolerance:
    """Convert a length into degrees at a stated latitude, with an error bound.

    Refuses to answer when the local linear model would be misleading: near the
    poles for east/west offsets, or for distances beyond the local envelope.
    """
    base = verdict(SUCCESS, "DEGREE_CONVERSION_OK")
    if not math.isfinite(distance_m) or distance_m < 0:
        return DegreeTolerance(0.0, latitude_deg, distance_m, "none", 0.0, 0.0, False,
                               verdict(INVALID_ARGUMENT, "DISTANCE_NOT_FINITE_NONNEGATIVE"))
    if not -90.0 <= latitude_deg <= 90.0:
        return DegreeTolerance(0.0, latitude_deg, distance_m, "none", 0.0, 0.0, False,
                               verdict(INVALID_ARGUMENT, "LATITUDE_OUT_OF_RANGE"))
    cos_lat = math.cos(math.radians(latitude_deg))
    if axis not in ("meridian", "parallel"):
        return DegreeTolerance(0.0, latitude_deg, distance_m, "none", 0.0, 0.0, False,
                               verdict(INVALID_ARGUMENT, "UNKNOWN_CONVERSION_AXIS"))
    if axis == "parallel" and abs(cos_lat) < MIN_ABS_COS_LATITUDE:
        return DegreeTolerance(0.0, latitude_deg, distance_m, "wgs84_numerical", 0.0, 0.0, False,
                               verdict(SAFE_ABSTENTION, "PARALLEL_CONVERSION_UNSTABLE_NEAR_POLE"))
    if distance_m > MAX_LOCAL_APPROX_DISTANCE_M:
        return DegreeTolerance(0.0, latitude_deg, distance_m, "wgs84_numerical", 0.0, 0.0, False,
                               verdict(SAFE_ABSTENTION, "DISTANCE_EXCEEDS_LOCAL_CONVERSION_ENVELOPE"))

    if axis == "meridian":
        degrees = latitude_offset_deg(latitude_deg, distance_m)
        linear = distance_m / metres_per_degree_lat(latitude_deg)
    else:
        degrees = longitude_offset_deg(latitude_deg, distance_m)
        linear = distance_m / metres_per_degree_lon(latitude_deg)
    divergence = 0.0 if linear == 0 else abs(degrees - linear) / abs(linear) * 100.0
    return DegreeTolerance(degrees, latitude_deg, distance_m, "wgs84_numerical", linear, divergence, True, base)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dlm = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlm / 2) ** 2
    return 2.0 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


# ---------------------------------------------------------------------------
# Coordinates, CRS and order
# ---------------------------------------------------------------------------


def validate_lat_lon(lat: Any, lon: Any) -> Verdict | None:
    for name, value in (("lat", lat), ("lon", lon)):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return verdict(INVALID_ARGUMENT, "COORDINATE_NOT_NUMERIC", field=name)
        if not math.isfinite(float(value)):
            return verdict(INVALID_ARGUMENT, "COORDINATE_NOT_FINITE", field=name)
    if abs(float(lat)) > 90.0:
        return verdict(INVALID_ARGUMENT, "LATITUDE_OUT_OF_RANGE", hint="possible lat/lon swap", lat=lat, lon=lon)
    if abs(float(lon)) > 180.0:
        return verdict(INVALID_ARGUMENT, "LONGITUDE_OUT_OF_RANGE", hint="possible lat/lon swap", lat=lat, lon=lon)
    return None


def coordinate_from(value: Any, *, crs: Crs, order: CoordOrder) -> tuple[tuple[float, float] | None, Verdict | None]:
    """Read a coordinate without silently guessing. Returns ((lat, lon), verdict)."""
    if crs is not Crs.WGS84:
        return None, verdict(SAFE_ABSTENTION, "CRS_NOT_SUPPORTED_FOR_COORDINATE_READ", crs=crs.value)
    if isinstance(value, Mapping):
        if "lat" in value and "lon" in value:
            lat, lon = value["lat"], value["lon"]
        elif "latitude" in value and "longitude" in value:
            lat, lon = value["latitude"], value["longitude"]
        elif value.get("type") == "Point":
            coords = value.get("coordinates")
            if not isinstance(coords, (list, tuple)) or len(coords) < 2:
                return None, verdict(INVALID_ARGUMENT, "POINT_COORDINATES_MISSING")
            lat, lon = (coords[0], coords[1]) if order is CoordOrder.LAT_LON else (coords[1], coords[0])
        else:
            return None, verdict(EVIDENCE_MISSING, "COORDINATE_FIELDS_MISSING")
    elif isinstance(value, (list, tuple)) and len(value) >= 2:
        lat, lon = (value[0], value[1]) if order is CoordOrder.LAT_LON else (value[1], value[0])
    else:
        return None, verdict(INVALID_ARGUMENT, "COORDINATE_SHAPE_UNREADABLE")
    problem = validate_lat_lon(lat, lon)
    if problem is not None:
        return None, problem
    return (float(lat), float(lon)), None


def detect_lat_lon_swap(lat: float, lon: float, bbox: Sequence[float]) -> bool:
    """bbox = (min_lat, min_lon, max_lat, max_lon). True when the swapped pair fits
    the expected region and the given pair does not."""
    min_lat, min_lon, max_lat, max_lon = bbox

    def inside(a: float, b: float) -> bool:
        return min_lat <= a <= max_lat and min_lon <= b <= max_lon

    return not inside(lat, lon) and inside(lon, lat)


@dataclass(frozen=True)
class SemanticContext:
    crs: Crs
    length_unit: LengthUnit
    coordinate_order: CoordOrder
    distance_model: DistanceModel
    latitude_deg: float | None = None
    warnings: tuple[str, ...] = ()
    verdict: Verdict | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "crs": self.crs.value,
            "length_unit": self.length_unit.value,
            "coordinate_order": self.coordinate_order.value,
            "distance_model": self.distance_model.value,
            "latitude_deg": self.latitude_deg,
            "warnings": list(self.warnings),
            "verdict": self.verdict.to_dict() if self.verdict else None,
        }


def validate_context(arguments: Mapping[str, Any], *, require_length_unit: bool = False) -> SemanticContext:
    """Single entry-point validation. No repeated checks in deeper layers."""
    crs, crs_reason = parse_crs(arguments.get("crs"))
    order, order_reason = parse_coord_order(arguments.get("coordinate_order"))
    unit, unit_reason = parse_length_unit(arguments.get("units"))
    model_value = str(arguments.get("distance_model") or "").lower()
    model = DistanceModel.UNKNOWN
    for candidate in DistanceModel:
        if candidate.value == model_value:
            model = candidate
            break
    warnings: list[str] = []
    if crs is Crs.UNKNOWN:
        warnings.append("CRS_NOT_DECLARED_ASSUMED_WGS84")
        crs = Crs.WGS84
    if crs is Crs.WEB_MERCATOR:
        return SemanticContext(
            crs, unit or LengthUnit.UNKNOWN, order, model, None, tuple(warnings),
            verdict(SAFE_ABSTENTION, "WEB_MERCATOR_NOT_SUPPORTED_FOR_GEOMETRY_TOOLS"),
        )
    if order_reason != "OK":
        warnings.append(order_reason)
    if unit is None:
        warnings.append(unit_reason)
        if require_length_unit:
            return SemanticContext(
                crs, LengthUnit.UNKNOWN, order, model, None, tuple(warnings),
                verdict(INVALID_ARGUMENT, unit_reason, units=arguments.get("units")),
            )
    if crs_reason == "UNKNOWN_CRS":
        return SemanticContext(
            crs, unit or LengthUnit.UNKNOWN, order, model, None, tuple(warnings),
            verdict(INVALID_ARGUMENT, "UNKNOWN_CRS", crs=arguments.get("crs")),
        )
    lat = arguments.get("latitude_deg")
    lat_value = float(lat) if isinstance(lat, (int, float)) and not isinstance(lat, bool) else None
    return SemanticContext(crs, unit or LengthUnit.UNKNOWN, order, model, lat_value, tuple(warnings), None)


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


def _finite_pair(point: Any) -> tuple[float, float] | None:
    if not isinstance(point, (list, tuple)) or len(point) < 2:
        return None
    a, b = point[0], point[1]
    if isinstance(a, bool) or isinstance(b, bool) or not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        return None
    if not math.isfinite(float(a)) or not math.isfinite(float(b)):
        return None
    return float(a), float(b)


def local_plane(point: Sequence[float], origin_lat: float, origin_lon: float) -> tuple[float, float] | None:
    pair = _finite_pair(point)
    if pair is None:
        return None
    lon, lat = pair
    return (
        (lon - origin_lon) * metres_per_degree_lon(origin_lat),
        (lat - origin_lat) * metres_per_degree_lat(origin_lat),
    )


def _orientation(a: Sequence[float], b: Sequence[float], c: Sequence[float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _segments_cross(a: Sequence[float], b: Sequence[float], c: Sequence[float], d: Sequence[float]) -> bool:
    o1, o2 = _orientation(a, b, c), _orientation(a, b, d)
    o3, o4 = _orientation(c, d, a), _orientation(c, d, b)
    eps = 1e-12
    if ((o1 > eps and o2 < -eps) or (o1 < -eps and o2 > eps)) and (
        (o3 > eps and o4 < -eps) or (o3 < -eps and o4 > eps)
    ):
        return True
    return False


def ring_validity(ring: Any, *, origin_lat: float, origin_lon: float) -> list[str]:
    if not isinstance(ring, (list, tuple)) or len(ring) < 4:
        return ["RING_TOO_SHORT"]
    problems: list[str] = []
    first, last = _finite_pair(ring[0]), _finite_pair(ring[-1])
    if first is None or last is None:
        return ["RING_COORDINATE_INVALID"]
    if first != last:
        problems.append("RING_NOT_CLOSED")
    plane: list[tuple[float, float]] = []
    for raw in ring:
        p = local_plane(raw, origin_lat, origin_lon)
        if p is None:
            problems.append("RING_COORDINATE_INVALID")
            return problems
        plane.append(p)
    for i in range(len(plane) - 1):
        if plane[i] == plane[i + 1]:
            problems.append("DEGENERATE_SEGMENT")
    if any(abs(p[0]) > MAX_LOCAL_PLANE_EXTENT_M or abs(p[1]) > MAX_LOCAL_PLANE_EXTENT_M for p in plane):
        problems.append("GEOMETRY_EXCEEDS_LOCAL_PLANE_ENVELOPE")
    edges = len(plane) - 1
    for i in range(edges):
        for j in range(i + 2, edges):
            if i == 0 and j == edges - 1:
                continue
            if _segments_cross(plane[i], plane[i + 1], plane[j], plane[j + 1]):
                problems.append("SELF_INTERSECTION")
                return problems
    return problems


def geometry_origin(geom: Mapping[str, Any]) -> tuple[float, float] | None:
    coords: list[Any] = []
    kind = geom.get("type")
    raw = geom.get("coordinates")
    if isinstance(raw, (list, tuple)):
        if kind == "Point":
            coords = [raw]
        elif kind in ("LineString", "MultiPoint"):
            coords = list(raw)
        elif kind == "Polygon":
            coords = list(raw[0]) if raw and isinstance(raw[0], (list, tuple)) else []
        elif kind == "MultiLineString":
            for line in raw:
                if isinstance(line, (list, tuple)):
                    coords.extend(line)
        elif kind == "MultiPolygon":
            for poly in raw:
                if isinstance(poly, (list, tuple)) and poly and isinstance(poly[0], (list, tuple)):
                    coords.extend(poly[0])
    points = [p for p in (_finite_pair(c) for c in coords) if p is not None]
    if not points:
        return None
    return (
        sum(p[1] for p in points) / len(points),
        sum(p[0] for p in points) / len(points),
    )


def geometry_problems(geom: Any) -> list[str]:
    if not isinstance(geom, Mapping):
        return ["GEOMETRY_NOT_AN_OBJECT"]
    kind = geom.get("type")
    if kind == "Point":
        return [] if _finite_pair(geom.get("coordinates")) else ["POINT_COORDINATES_INVALID"]
    if kind == "LineString":
        raw = geom.get("coordinates")
        if not isinstance(raw, (list, tuple)) or len(raw) < 2:
            return ["LINESTRING_TOO_SHORT"]
        origin = geometry_origin(geom) or (0.0, 0.0)
        plane = [local_plane(p, origin[0], origin[1]) for p in raw]
        if any(p is None for p in plane):
            return ["LINESTRING_COORDINATE_INVALID"]
        if any(plane[i] == plane[i + 1] for i in range(len(plane) - 1)):
            return ["DEGENERATE_SEGMENT"]
        return []
    if kind in ("Polygon", "MultiPolygon"):
        origin = geometry_origin(geom)
        if origin is None:
            return ["NO_VALID_COORDINATES"]
        raw = geom.get("coordinates")
        polys = [raw] if kind == "Polygon" else (raw if isinstance(raw, (list, tuple)) else [])
        problems: list[str] = []
        for poly in polys:
            if not isinstance(poly, (list, tuple)) or not poly:
                problems.append("POLYGON_RING_MISSING")
                continue
            for ring_index, ring in enumerate(poly):
                issues = ring_validity(ring, origin_lat=origin[0], origin_lon=origin[1])
                problems.extend(f"ring{ring_index}:{issue}" for issue in issues)
        return problems
    if kind == "GeometryCollection":
        return ["GEOMETRY_COLLECTION_NOT_MEASURABLE"]
    return ["UNSUPPORTED_GEOMETRY_TYPE"]


def ring_area_m2(ring: Sequence[Any], origin_lat: float, origin_lon: float) -> float | None:
    plane = [local_plane(p, origin_lat, origin_lon) for p in ring]
    if any(p is None for p in plane):
        return None
    pts: list[tuple[float, float]] = [p for p in plane if p is not None]
    total = 0.0
    for i in range(len(pts) - 1):
        total += pts[i][0] * pts[i + 1][1] - pts[i + 1][0] * pts[i][1]
    return abs(total) / 2.0


def polygon_area_m2(geom: Mapping[str, Any]) -> tuple[float | None, Verdict | None]:
    """Local equal-area-ish projection at the geometry's own centroid latitude.

    Valid only for small geometries; larger ones are refused rather than given a
    confidently wrong number.
    """
    problems = geometry_problems(geom)
    if problems:
        return None, verdict(INVALID_ARGUMENT, "GEOMETRY_INVALID", problems=problems)
    origin = geometry_origin(geom)
    if origin is None:
        return None, verdict(EVIDENCE_MISSING, "GEOMETRY_ORIGIN_UNREADABLE")
    kind = geom.get("type")
    raw = geom.get("coordinates")
    polys = [raw] if kind == "Polygon" else (raw if isinstance(raw, (list, tuple)) else [])
    total = 0.0
    for poly in polys:
        for index, ring in enumerate(poly):
            area = ring_area_m2(ring, origin[0], origin[1])
            if area is None:
                return None, verdict(EVIDENCE_MISSING, "RING_AREA_UNREADABLE")
            total += area if index == 0 else -area
    return total, None


def max_vertex_displacement_m(
    original: Mapping[str, Any], simplified: Mapping[str, Any]
) -> tuple[float | None, Verdict | None]:
    def vertices(geom: Mapping[str, Any]) -> list[tuple[float, float]]:
        raw = geom.get("coordinates")
        if geom.get("type") == "Polygon" and raw and isinstance(raw[0], (list, tuple)):
            raw = raw[0]
        return [p for p in (_finite_pair(c) for c in (raw or [])) if p is not None]

    left, right = vertices(original), vertices(simplified)
    if not left or not right:
        return None, verdict(EVIDENCE_MISSING, "VERTEX_SET_EMPTY")
    origin = geometry_origin(original) or (0.0, 0.0)
    plane_left = [local_plane(p, origin[0], origin[1]) for p in left]
    if any(p is None for p in plane_left):
        return None, verdict(EVIDENCE_MISSING, "VERTEX_PROJECTION_FAILED")
    maximum = 0.0
    for point in right:
        projected = local_plane(point, origin[0], origin[1])
        if projected is None:
            return None, verdict(EVIDENCE_MISSING, "VERTEX_PROJECTION_FAILED")
        best = min(math.dist(projected, q) for q in plane_left if q is not None)
        maximum = max(maximum, best)
    return maximum, None


@dataclass(frozen=True)
class LineResidual:
    distance_m: float
    nearest_segment: int
    parameter_t: float
    nearest_point: tuple[float, float]
    degenerate_segments: int
    endpoint_hit: bool
    verdict: Verdict

    def to_dict(self) -> dict[str, Any]:
        return {
            "distance_m": self.distance_m,
            "nearest_segment": self.nearest_segment,
            "parameter_t": self.parameter_t,
            "nearest_point": list(self.nearest_point),
            "degenerate_segments": self.degenerate_segments,
            "endpoint_hit": self.endpoint_hit,
            "verdict": self.verdict.to_dict(),
        }


def point_line_residual(point: Any, line: Mapping[str, Any]) -> LineResidual | None:
    """Independent local checker for 'is this point on this line'.

    Uses a WGS84 local plane at the line's own centroid and an exact
    point-to-segment projection; no provider call and no borrowed truth.
    """
    pair = _finite_pair(point) if isinstance(point, (list, tuple)) else None
    if pair is None and isinstance(point, Mapping):
        pair = _finite_pair(point.get("coordinates"))
    if pair is None:
        return None
    if not isinstance(line, Mapping) or line.get("type") != "LineString":
        return None
    raw = line.get("coordinates")
    if not isinstance(raw, (list, tuple)) or len(raw) < 2:
        return None
    origin = geometry_origin(line) or (0.0, 0.0)
    p = local_plane(pair, origin[0], origin[1])
    segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
    degenerate = 0
    for a_raw, b_raw in zip(raw, raw[1:]):
        a, b = local_plane(a_raw, origin[0], origin[1]), local_plane(b_raw, origin[0], origin[1])
        if a is None or b is None:
            return None
        if a == b:
            degenerate += 1
            continue
        segments.append((a, b))
    if p is None or not segments:
        return None
    best_distance = float("inf")
    best_index, best_t = -1, 0.0
    best_point = (0.0, 0.0)
    for index, (a, b) in enumerate(segments):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length_sq = dx * dx + dy * dy
        t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length_sq))
        projection = (a[0] + t * dx, a[1] + t * dy)
        distance = math.dist(p, projection)
        if distance < best_distance:
            best_distance, best_index, best_t, best_point = distance, index, t, projection
    endpoint = best_t in (0.0, 1.0)
    return LineResidual(
        best_distance, best_index, best_t, best_point, degenerate, endpoint,
        verdict(SUCCESS, "RESIDUAL_COMPUTED", model="wgs84_local_plane"),
    )


def serialisation_loss_m(point: Sequence[float], digits: int, latitude_deg: float) -> float:
    """Worst-case positional loss from rounding coordinates to ``digits`` decimals."""
    half = 0.5 * 10.0 ** (-digits)
    lat_loss = half * metres_per_degree_lat(latitude_deg)
    lon_loss = half * metres_per_degree_lon(latitude_deg)
    return math.hypot(lat_loss, lon_loss)


# ---------------------------------------------------------------------------
# Matrices
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MatrixSemantics:
    rows: int
    cols: int
    expected_rows: int | None
    expected_cols: int | None
    rectangular: bool
    symmetric: bool
    direction_dependent: bool
    shape_matches_sources_targets: bool | None
    distance_units: str | None
    verdict: Verdict

    def to_dict(self) -> dict[str, Any]:
        return {
            "rows": self.rows,
            "cols": self.cols,
            "expected_rows": self.expected_rows,
            "expected_cols": self.expected_cols,
            "rectangular": self.rectangular,
            "symmetric": self.symmetric,
            "direction_dependent": self.direction_dependent,
            "shape_matches_sources_targets": self.shape_matches_sources_targets,
            "distance_units": self.distance_units,
            "verdict": self.verdict.to_dict(),
        }


def matrix_semantics(
    matrix: Any,
    *,
    sources: Sequence[Any] | None = None,
    targets: Sequence[Any] | None = None,
    distance_units: str | None = None,
    require_square: bool = False,
) -> MatrixSemantics:
    if not isinstance(matrix, (list, tuple)) or not matrix:
        return MatrixSemantics(0, 0, None, None, False, False, False, None, distance_units,
                               verdict(EVIDENCE_MISSING, "MATRIX_MISSING_OR_EMPTY"))
    rows = [row for row in matrix if isinstance(row, (list, tuple))]
    if len(rows) != len(matrix):
        return MatrixSemantics(0, 0, None, None, False, False, False, None, distance_units,
                               verdict(EVIDENCE_MISSING, "MATRIX_ROW_NOT_A_LIST"))
    widths = {len(row) for row in rows}
    if len(widths) != 1:
        return MatrixSemantics(len(rows), -1, None, None, False, False, False, None, distance_units,
                               verdict(SEMANTIC_CONFLICT, "RAGGED_MATRIX", widths=sorted(widths)))
    cols = widths.pop()
    exp_rows = len(sources) if sources is not None else None
    exp_cols = len(targets) if targets is not None else exp_rows
    shape_ok = None
    if exp_rows is not None:
        shape_ok = len(rows) == exp_rows and cols == exp_cols
    symmetric = False
    direction_dependent = False
    if len(rows) == cols:
        differences = 0
        for i in range(len(rows)):
            for j in range(cols):
                a, b = rows[i][j], rows[j][i]
                if a is None or b is None:
                    differences += 1
                elif a != b:
                    differences += 1
        symmetric = differences == 0
        direction_dependent = differences > 0
    else:
        direction_dependent = True
    problem = None
    if shape_ok is False:
        problem = verdict(INVALID_ARGUMENT, "MATRIX_SHAPE_DISAGREES_WITH_SOURCES_TARGETS",
                          rows=len(rows), cols=cols, expected=[exp_rows, exp_cols])
    elif require_square and len(rows) != cols:
        problem = verdict(INVALID_ARGUMENT, "NON_SQUARE_MATRIX_WHERE_SQUARE_REQUIRED",
                          rows=len(rows), cols=cols)
    elif cols == 0:
        problem = verdict(EVIDENCE_MISSING, "MATRIX_HAS_NO_COLUMNS")
    return MatrixSemantics(
        len(rows), cols, exp_rows, exp_cols, len(rows) != cols, symmetric,
        direction_dependent, shape_ok, distance_units,
        problem or verdict(SUCCESS, "MATRIX_SEMANTICS_OK",
                           direction_dependent=direction_dependent),
    )


# ---------------------------------------------------------------------------
# Route snapping
# ---------------------------------------------------------------------------

SNAP_CANDIDATES_M: tuple[float, ...] = (50.0, 150.0, 300.0)
MAX_SNAP_RADIUS_M = 300.0
MAX_SNAP_ATTEMPTS = len(SNAP_CANDIDATES_M)


@dataclass(frozen=True)
class SnappingPlan:
    candidates_m: tuple[float, ...]
    max_radius_m: float
    max_attempts: int
    unlimited_expansion_forbidden: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates_m": list(self.candidates_m),
            "max_radius_m": self.max_radius_m,
            "max_attempts": self.max_attempts,
            "unlimited_expansion_forbidden": self.unlimited_expansion_forbidden,
        }


def snapping_plan() -> SnappingPlan:
    return SnappingPlan(SNAP_CANDIDATES_M, MAX_SNAP_RADIUS_M, MAX_SNAP_ATTEMPTS)
