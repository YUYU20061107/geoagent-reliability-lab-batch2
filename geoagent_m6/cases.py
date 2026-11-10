"""Engineering handling of the three retained live failures.

Historical IDs P2-M5, P2-S4 and P3-X6 are preserved verbatim together with
their original reported outcome (a *reported* outcome, not an M6 measurement).
Every M6 treatment is registered as an independent new version. Nothing here
rewrites, deletes or retroactively upgrades a sealed failure.

No provider call is made by this module. All measurements are local recomputations.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Mapping

from . import semantics as geo
from .outcomes import (
    EVIDENCE_MISSING,
    INVALID_ARGUMENT,
    PROVIDER_ERROR,
    SAFE_ABSTENTION,
    SEMANTIC_CONFLICT,
    Responsibility,
    Verdict,
    ok,
    verdict,
)

RETAINED_FAILURES: dict[str, dict[str, Any]] = {
    "P2-M5": {
        "reported_title": "Simplification preserves area",
        "reported_failure": "simplify(tolerance=5) interpreted as 5 metres; tolerance is in degrees; ~62.9% area change",
        "original_chain": "02_WORKFLOWS/workflows.json#workflows[id=P2-M5]",
        "evidence_status": "UPSTREAM_REPORT_NOT_INDEPENDENTLY_REMEASURED_BY_M6",
        "m6_treatment_version": "P2-M5-V2",
    },
    "P2-S4": {
        "reported_title": "Nearest point on a route lies on the route",
        "reported_failure": "nearest_point_on_line result judged false by point_on_line",
        "original_chain": "02_WORKFLOWS/workflows.json#workflows[id=P2-S4]",
        "evidence_status": "UPSTREAM_REPORT_NOT_INDEPENDENTLY_REMEASURED_BY_M6",
        "m6_treatment_version": "P2-S4-V2",
    },
    "P3-X6": {
        "reported_title": "Long cross-city route",
        "reported_failure": "No suitable edges near location",
        "original_chain": "02_WORKFLOWS/workflows.json#workflows[id=P3-X6]",
        "evidence_status": "UPSTREAM_REPORT_NOT_INDEPENDENTLY_REMEASURED_BY_M6",
        "m6_treatment_version": "P3-X6-V2",
    },
}


# ---------------------------------------------------------------------------
# P2-M5 · simplify tolerance units
# ---------------------------------------------------------------------------

M6_SIMPLIFY_VERSION = "P2-M5-V2"


@dataclass(frozen=True)
class SimplifyPlan:
    version: str
    tolerance_deg: float
    declared_unit: str
    declared_value: float
    conversion: dict[str, Any]
    latitude_deg: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "tolerance_deg": self.tolerance_deg,
            "declared_unit": self.declared_unit,
            "declared_value": self.declared_value,
            "latitude_deg": self.latitude_deg,
            "conversion": self.conversion,
        }


def validate_simplify_request(arguments: Mapping[str, Any]) -> tuple[SimplifyPlan | None, Verdict | None]:
    """Refuse ambiguous input at the interface, then convert explicitly.

    A bare ``tolerance`` with no unit is rejected. ``units="metric"`` is a unit
    *system*, not a unit, and is rejected too. Metres are converted at the stated
    latitude through the WGS84 numerical inverse, never by a fixed ratio.
    """
    if "tolerance" not in arguments:
        return None, verdict(EVIDENCE_MISSING, "SIMPLIFY_TOLERANCE_MISSING")
    raw_value = arguments.get("tolerance")
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)) or not math.isfinite(float(raw_value)):
        return None, verdict(INVALID_ARGUMENT, "SIMPLIFY_TOLERANCE_NOT_FINITE", tolerance=raw_value)
    value = float(raw_value)
    if value < 0:
        return None, verdict(INVALID_ARGUMENT, "SIMPLIFY_TOLERANCE_NEGATIVE", tolerance=value)

    raw_unit = arguments.get("tolerance_unit")
    if raw_unit is None:
        return None, verdict(
            INVALID_ARGUMENT, "SIMPLIFY_TOLERANCE_UNIT_MISSING",
            hint="a bare tolerance number has no unit; P2-M5 is retained as the negative case",
            tolerance=value, legacy_case="P2-M5", m6_version=M6_SIMPLIFY_VERSION,
        )
    unit, reason = geo.parse_length_unit(raw_unit)
    if unit is None:
        return None, verdict(
            INVALID_ARGUMENT, reason,
            hint="explicit tolerance_unit required; a bare number is not a length",
            tolerance=value, tolerance_unit=raw_unit,
            legacy_case="P2-M5", m6_version=M6_SIMPLIFY_VERSION,
        )
    if unit is geo.LengthUnit.DEGREE and value > 0.1:
        return None, verdict(
            INVALID_ARGUMENT, "DEGREE_TOLERANCE_IMPLAUSIBLE_FOR_LOCAL_GEOMETRY",
            hint="a degree-valued simplification tolerance above 0.1 deg is almost always a metre/degree mix-up",
            tolerance=value, legacy_case="P2-M5", m6_version=M6_SIMPLIFY_VERSION,
        )
    if unit is geo.LengthUnit.DEGREE:
        return SimplifyPlan(
            M6_SIMPLIFY_VERSION, value, unit.value, value,
            {"model": "declared_degrees_no_conversion", "applicable": True},
            None,
        ), None
    if unit is geo.LengthUnit.RADIAN:
        return None, verdict(INVALID_ARGUMENT, "SIMPLIFY_RADIAN_TOLERANCE_NOT_ACCEPTED",
                             hint="convert to degrees before calling the tool")
    metres = geo.to_metres(value, unit)
    if metres is None:
        return None, verdict(INVALID_ARGUMENT, "SIMPLIFY_UNIT_NOT_CONVERTIBLE", unit=unit.value)
    latitude = arguments.get("latitude_deg")
    if isinstance(latitude, bool) or not isinstance(latitude, (int, float)) or not -90 <= float(latitude) <= 90:
        return None, verdict(
            SAFE_ABSTENTION, "LATITUDE_REQUIRED_FOR_METRE_TO_DEGREE_CONVERSION",
            hint="a metre tolerance cannot be converted without a stated latitude",
            distance_m=metres,
        )
    axis = str(arguments.get("tolerance_axis") or "meridian")
    conversion = geo.degrees_for_distance(metres, float(latitude), axis=axis)
    if not conversion.applicable:
        return None, conversion.verdict.with_evidence(
            distance_m=metres, latitude_deg=float(latitude), legacy_case="P2-M5",
        )
    return SimplifyPlan(
        M6_SIMPLIFY_VERSION, conversion.degrees, unit.value, value,
        conversion.to_dict(), float(latitude),
    ), None


@dataclass(frozen=True)
class SimplifyAssessment:
    version: str
    original_area_m2: float | None
    simplified_area_m2: float | None
    relative_area_change: float | None
    original_problems: list[str]
    simplified_problems: list[str]
    max_vertex_displacement_m: float | None
    tolerance_deg: float
    rel_tolerance: float
    verdict: Verdict

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "original_area_m2": self.original_area_m2,
            "simplified_area_m2": self.simplified_area_m2,
            "relative_area_change": self.relative_area_change,
            "original_problems": self.original_problems,
            "simplified_problems": self.simplified_problems,
            "max_vertex_displacement_m": self.max_vertex_displacement_m,
            "tolerance_deg": self.tolerance_deg,
            "rel_tolerance": self.rel_tolerance,
            "verdict": self.verdict.to_dict(),
        }


def assess_simplification(
    original: Mapping[str, Any],
    simplified: Mapping[str, Any],
    plan: SimplifyPlan,
    *,
    rel_tolerance: float = 0.1,
) -> SimplifyAssessment:
    """Area change, topology and shape deviation measured locally, not assumed."""
    original_problems = geo.geometry_problems(original)
    simplified_problems = geo.geometry_problems(simplified)
    area1, area1_problem = geo.polygon_area_m2(original)
    area2, area2_problem = geo.polygon_area_m2(simplified)
    displacement, displacement_problem = geo.max_vertex_displacement_m(original, simplified)

    def result(v: Verdict) -> SimplifyAssessment:
        relative = None
        if area1 is not None and area2 is not None and area1 > 0:
            relative = abs(area2 - area1) / area1
        return SimplifyAssessment(
            M6_SIMPLIFY_VERSION, area1, area2, relative,
            original_problems, simplified_problems, displacement,
            plan.tolerance_deg, rel_tolerance, v,
        )

    if original_problems or simplified_problems:
        return result(verdict(INVALID_ARGUMENT, "SIMPLIFY_GEOMETRY_TOPOLOGY_INVALID",
                              original_problems=original_problems, simplified_problems=simplified_problems))
    if area1_problem or area2_problem or area1 is None or area2 is None:
        return result(verdict(EVIDENCE_MISSING, "SIMPLIFY_AREA_UNREADABLE"))
    if displacement_problem or displacement is None:
        return result(verdict(EVIDENCE_MISSING, "SIMPLIFY_DISPLACEMENT_UNREADABLE"))
    relative = abs(area2 - area1) / area1 if area1 > 0 else 1.0
    origin = geo.geometry_origin(original)
    scale_lat = plan.latitude_deg if plan.latitude_deg is not None else (origin[0] if origin else 52.5)
    tolerance_m = plan.tolerance_deg * min(
        geo.metres_per_degree_lat(scale_lat), geo.metres_per_degree_lon(scale_lat)
    )
    if relative > rel_tolerance:
        return result(verdict(SEMANTIC_CONFLICT, "SIMPLIFY_AREA_CHANGE_EXCEEDS_LIMIT",
                              relative_area_change=relative, rel_tolerance=rel_tolerance))
    if displacement > max(tolerance_m, 1e-6):
        return result(verdict(SEMANTIC_CONFLICT, "SIMPLIFY_SHAPE_DEVIATION_EXCEEDS_TOLERANCE",
                              max_vertex_displacement_m=displacement, tolerance_m=tolerance_m))
    return result(ok("SIMPLIFY_SEMANTICS_ACCEPTED",
                     relative_area_change=relative, max_vertex_displacement_m=displacement,
                     conversion=plan.conversion))


def legacy_p2_m5_arguments() -> dict[str, Any]:
    """The untouched original request shape, retained as a negative fixture."""
    return {"operation": "simplify", "tolerance": 5, "high_quality": False}


# ---------------------------------------------------------------------------
# P2-S4 · cross-tool point/line disagreement
# ---------------------------------------------------------------------------

M6_POINT_LINE_VERSION = "P2-S4-V2"


@dataclass(frozen=True)
class PointLineAssessment:
    version: str
    distance_residual_m: float | None
    tolerance_m: float
    serialisation_loss_m: float | None
    float_roundtrip_delta_m: float | None
    endpoint_hit: bool | None
    degenerate_segments: int | None
    predicate_value: Any
    evidence_sufficiency: dict[str, Any]
    provider_bug_claimed: bool
    verdict: Verdict

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "distance_residual_m": self.distance_residual_m,
            "tolerance_m": self.tolerance_m,
            "serialisation_loss_m": self.serialisation_loss_m,
            "float_roundtrip_delta_m": self.float_roundtrip_delta_m,
            "endpoint_hit": self.endpoint_hit,
            "degenerate_segments": self.degenerate_segments,
            "predicate_value": self.predicate_value,
            "evidence_sufficiency": self.evidence_sufficiency,
            "provider_bug_claimed": self.provider_bug_claimed,
            "verdict": self.verdict.to_dict(),
        }


def investigate_point_line(
    nearest_point: Any,
    line: Mapping[str, Any],
    predicate_value: Any,
    *,
    tolerance_m: float = 1.0,
    serialisation_digits: int = 7,
    latitude_deg: float = 52.5,
    documented_tolerance_contract: bool = False,
    provider_documentation_ref: str | None = None,
    independent_samples: int = 0,
    provider_semantics_documented: bool = False,
) -> PointLineAssessment:
    """Local residual + point/line relation checker.

    A disagreement between two provider tools is NEVER sufficient on its own to
    assert a provider bug. Escalation to PROVIDER_INCONSISTENCY requires an
    explicit tolerance contract, provider documentation, documented semantics
    and at least three independent samples. Otherwise the case stays
    SEMANTIC_CONFLICT_UNRESOLVED.
    """
    residual = geo.point_line_residual(nearest_point, line)
    sufficiency = {
        "documented_tolerance_contract": documented_tolerance_contract,
        "provider_documentation_ref": provider_documentation_ref,
        "provider_semantics_documented": provider_semantics_documented,
        "independent_samples": independent_samples,
        "residual_model": "wgs84_local_plane_point_to_segment",
    }

    def result(v: Verdict, *, bug: bool = False) -> PointLineAssessment:
        serial_loss = None
        roundtrip = None
        pair = nearest_point if isinstance(nearest_point, (list, tuple)) else (
            nearest_point.get("coordinates") if isinstance(nearest_point, Mapping) else None
        )
        if isinstance(pair, (list, tuple)) and len(pair) >= 2:
            serial_loss = geo.serialisation_loss_m(pair, serialisation_digits, latitude_deg)
            if all(isinstance(x, (int, float)) for x in pair[:2]):
                roundtrip = geo.haversine_m(
                    float(pair[1]), float(pair[0]),
                    float(json.loads(json.dumps(float(pair[1])))),
                    float(json.loads(json.dumps(float(pair[0])))),
                )
        return PointLineAssessment(
            M6_POINT_LINE_VERSION,
            residual.distance_m if residual else None,
            tolerance_m, serial_loss, roundtrip,
            residual.endpoint_hit if residual else None,
            residual.degenerate_segments if residual else None,
            predicate_value, sufficiency, bug, v,
        )

    if residual is None:
        return result(verdict(SAFE_ABSTENTION, "POINT_LINE_RESIDUAL_UNCOMPUTABLE",
                              hint="line or point geometry unreadable; no provider bug claimed"))
    if residual.degenerate_segments and not residual.endpoint_hit:
        sufficiency["degenerate_segments_present"] = True
    if residual.distance_m > tolerance_m:
        if predicate_value is False:
            return result(ok("POINT_OFF_LINE_CONSISTENT_WITH_PREDICATE",
                             distance_residual_m=residual.distance_m))
        return result(verdict(SEMANTIC_CONFLICT, "POINT_OFF_LINE_BUT_PREDICATE_TRUE",
                              distance_residual_m=residual.distance_m))
    if predicate_value is True:
        return result(ok("POINT_ON_LINE_CONSISTENT_WITH_PREDICATE",
                         distance_residual_m=residual.distance_m))

    evidence_complete = (
        documented_tolerance_contract
        and provider_documentation_ref
        and provider_semantics_documented
        and independent_samples >= 3
    )
    if evidence_complete:
        return result(
            verdict(SEMANTIC_CONFLICT, "PROVIDER_INCONSISTENCY",
                    detail="independent samples and documented tolerance contract available",
                    distance_residual_m=residual.distance_m, tolerance_m=tolerance_m),
            bug=True,
        )
    return result(
        verdict(SEMANTIC_CONFLICT, "SEMANTIC_CONFLICT_UNRESOLVED",
                detail="local residual is within tolerance while the relational tool returned false; "
                       "provider bug NOT claimed without documented tolerance contract, "
                       "provider semantics and >=3 independent samples",
                distance_residual_m=residual.distance_m, tolerance_m=tolerance_m,
                serialisation_loss_m=geo.serialisation_loss_m(
                    [13.39, 52.519], serialisation_digits, latitude_deg
                )),
        bug=False,
    )


# ---------------------------------------------------------------------------
# P3-X6 · routing failure classification and bounded recovery
# ---------------------------------------------------------------------------

M6_ROUTING_VERSION = "P3-X6-V2"

SUPPORTED_TRAVEL_MODES = frozenset({"drive", "walk", "bike", "transit", "truck", "bicycle"})

_OFF_NETWORK_MARKERS = ("no suitable edges near location", "no edges near", "no route found",
                        "cannot snap", "outside the road network", "unreachable")
_SERVICE_MARKERS = ("service unavailable", "temporarily unavailable", "internal server error",
                    "bad gateway", "upstream error", "timeout", "rate limit", "429", "5xx")
_MODE_MARKERS = ("unsupported mode", "mode not supported", "invalid mode", "travel mode")


@dataclass(frozen=True)
class RoutingAssessment:
    version: str
    classification: str
    message: str
    coordinate_check: str
    travel_mode: str | None
    snapping_plan: dict[str, Any]
    candidates: list[dict[str, Any]]
    final_answer_allowed: bool
    verdict: Verdict

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "classification": self.classification,
            "message": self.message,
            "coordinate_check": self.coordinate_check,
            "travel_mode": self.travel_mode,
            "snapping_plan": self.snapping_plan,
            "candidates": self.candidates,
            "final_answer_allowed": self.final_answer_allowed,
            "verdict": self.verdict.to_dict(),
        }


def classify_routing_failure(
    message: str,
    arguments: Mapping[str, Any],
    *,
    http_status: int | None = None,
) -> RoutingAssessment:
    """Distinguish coordinate errors, off-network points, unsupported modes and
    service failures. Never converts an unroutable request into a success."""
    lowered = str(message).lower()
    waypoints = arguments.get("waypoints")
    coordinate_check = "NO_COORDINATES_SUPPLIED"
    if isinstance(waypoints, (list, tuple)) and waypoints:
        problems = []
        for node in waypoints:
            _, problem = geo.coordinate_from(node, crs=geo.Crs.WGS84, order=geo.CoordOrder.LON_LAT)
            if problem is not None:
                problems.append(problem.reason_code)
        coordinate_check = "VALID" if not problems else ",".join(sorted(set(problems)))
    travel_mode = str(arguments.get("mode") or "").lower() or None

    classification = "UNKNOWN"
    if coordinate_check not in ("VALID", "NO_COORDINATES_SUPPLIED"):
        classification = "INVALID_COORDINATE"
    elif travel_mode and travel_mode not in SUPPORTED_TRAVEL_MODES:
        classification = "UNSUPPORTED_TRAVEL_MODE"
    elif any(marker in lowered for marker in _MODE_MARKERS):
        classification = "UNSUPPORTED_TRAVEL_MODE"
    elif any(marker in lowered for marker in _OFF_NETWORK_MARKERS):
        classification = "OFF_NETWORK_LOCATION"
    elif http_status is not None and (http_status == 429 or http_status >= 500):
        classification = "SERVICE_UNAVAILABLE"
    elif any(marker in lowered for marker in _SERVICE_MARKERS):
        classification = "SERVICE_UNAVAILABLE"

    plan = geo.snapping_plan()
    candidates: list[dict[str, Any]] = []
    if classification == "OFF_NETWORK_LOCATION":
        candidates = [
            {"id": "snap_bounded", "action": "retry_with_snapping_radius_m",
             "radii_m": list(plan.candidates_m), "max_attempts": plan.max_attempts,
             "reason": "finite, ordered snapping radii; no unbounded expansion", "cost": "requires_new_live_calls"},
            {"id": "nearest_verified_anchor", "action": "replace_endpoint_with_nearest_verified_anchor",
             "reason": "anchors already have measured coordinates", "cost": "changes_the_question"},
            {"id": "alternate_mode", "action": "retry_with_alternative_travel_mode",
             "modes": sorted(SUPPORTED_TRAVEL_MODES - {travel_mode or "drive"}),
             "reason": "mode-specific network availability", "cost": "requires_new_live_calls"},
        ]
    elif classification == "INVALID_COORDINATE":
        candidates = [{"id": "correct_arguments", "action": "reject_and_fix_coordinates",
                       "reason": "coordinate validation failed before any call", "cost": "none"}]
    elif classification == "UNSUPPORTED_TRAVEL_MODE":
        candidates = [{"id": "supported_mode", "action": "reissue_with_supported_mode",
                       "modes": sorted(SUPPORTED_TRAVEL_MODES), "cost": "requires_new_live_calls"}]
    elif classification == "SERVICE_UNAVAILABLE":
        candidates = [{"id": "stop", "action": "stop_without_retry",
                       "reason": "no automatic retry against provider service failures", "cost": "none"}]

    reason_map = {
        "INVALID_COORDINATE": (INVALID_ARGUMENT, "ROUTING_COORDINATE_INVALID"),
        "UNSUPPORTED_TRAVEL_MODE": (INVALID_ARGUMENT, "ROUTING_MODE_UNSUPPORTED"),
        "OFF_NETWORK_LOCATION": (SAFE_ABSTENTION, "ROUTING_OFF_NETWORK_SAFE_ABSTENTION"),
        "SERVICE_UNAVAILABLE": (PROVIDER_ERROR, "ROUTING_SERVICE_UNAVAILABLE"),
        "UNKNOWN": (SAFE_ABSTENTION, "ROUTING_FAILURE_UNCLASSIFIED_SAFE_ABSTENTION"),
    }
    outcome, reason = reason_map[classification]
    return RoutingAssessment(
        M6_ROUTING_VERSION, classification, str(message), coordinate_check, travel_mode,
        plan.to_dict(), candidates, False,
        verdict(outcome, reason, Responsibility.AGENT_DECISION,
                classification=classification, snapping_plan=plan.to_dict(),
                candidates=candidates, final_answer_allowed=False,
                unlimited_radius_retry_forbidden=True,
                unroutable_reported_as_success=False),
    )


def all_treatments() -> dict[str, Any]:
    return {
        "retained_failures": RETAINED_FAILURES,
        "new_versions": [M6_SIMPLIFY_VERSION, M6_POINT_LINE_VERSION, M6_ROUTING_VERSION],
        "historical_verdicts_untouched": True,
        "provider_bug_claims": 0,
    }
