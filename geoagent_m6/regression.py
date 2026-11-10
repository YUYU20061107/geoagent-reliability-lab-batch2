"""Parameterised offline fault-attribution matrix (M6 Phase 4).

Four families, each case carrying an EXPECTED verdict. "The program did not
crash" is never an acceptance criterion. Real response shapes from the M5 pilot
(sanitised, REPLAY_FROM_LIVE) are used as the mutation substrate where possible;
the public core remains runnable with synthetic shapes if that file is absent.

Historical failure IDs P2-M5 / P2-S4 / P3-X6 are retained, not overwritten.
"""

from __future__ import annotations

import copy
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import adapter, cases, executor, snapshots
from .outcomes import Outcome, Verdict

REGRESSION_VERSION = "geoagent.m6.regression-matrix/1"
FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "mcp_response_shapes.json"

CATEGORIES = {
    "A": "PARAMETER_SEMANTICS",
    "B": "RESPONSE_STRUCTURE",
    "C": "EXECUTION_EVIDENCE",
    "D": "MULTISTEP_CHAIN",
    "X": "COMBINED",
}


def env(payload):
    return {"jsonrpc": "2.0", "id": 1, "result": {"structuredContent": payload}}


def geocode(n=1, *, place_ids=None, lat=52.5163, lon=13.3777):
    ids = place_ids or [f"p{i}" for i in range(n)]
    return {"count": n, "results": [
        {"lat": lat + i * 0.001, "lon": lon + i * 0.001, "place_id": ids[i],
         "formatted": f"Place {i}", "country_code": "de"} for i in range(n)
    ]}


def route(distance=1500.0):
    return {"distance": distance, "time": 600.0,
            "geometry": {"type": "LineString", "coordinates": [[13.3777, 52.5163], [13.4000, 52.5200]]}}


def matrix_payload(rows=2, cols=2):
    return {
        "sources": [{"lat": 52.51 + i * 0.001, "lon": 13.38} for i in range(rows)],
        "targets": [{"lat": 52.52 + j * 0.001, "lon": 13.39} for j in range(cols)],
        "sources_to_targets": [[0 if i == j else 1000 + 100 * i + 10 * j for j in range(cols)]
                               for i in range(rows)],
        "distance_units": "meters",
    }


def square(half=0.001):
    return {"type": "Polygon", "coordinates": [[
        [13.3777 - half, 52.5163 - half], [13.3777 + half, 52.5163 - half],
        [13.3777 + half, 52.5163 + half], [13.3777 - half, 52.5163 + half],
        [13.3777 - half, 52.5163 - half],
    ]]}


def wf(chain, *, cross_checks=None, wid="RG"):
    return {"id": wid, "chain": chain, "invariants": [], "cross_checks": cross_checks or []}


def as_result(v: Verdict, **extra: Any) -> dict[str, Any]:
    return {"outcome": v.outcome.value, "reason": v.reason_code,
            "evidence": {"detail": v.detail, **extra}}


class Matrix:
    def __init__(self) -> None:
        self.real_shapes: dict[str, Any] = {}
        self.fixture_origin = "SYNTHETIC_FALLBACK"
        if FIXTURE_PATH.exists():
            data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
            for sample in data.get("samples") or []:
                self.real_shapes.setdefault(sample["tool"], sample["structuredContent"])
            self.fixture_origin = data.get("source", "REPLAY_FROM_LIVE_SANITISED")

    def real(self, tool: str) -> Any:
        return copy.deepcopy(self.real_shapes.get(tool, geocode()))

    def adapt(self, envelope, capability, **kwargs) -> dict[str, Any]:
        result = adapter.adapt(envelope, capability=capability, **kwargs)
        return as_result(result.step.verdict, consumed=len(result.step.consumed))

    def chain(self, workflow, responses, **kwargs) -> dict[str, Any]:
        record = executor.Executor(responses, run_id="M6-REGRESSION", **kwargs).run(workflow)
        return {
            "outcome": record.evaluator["outcome"],
            "reason": record.evaluator["reason_code"],
            "evidence": {"failure_layer": record.failure_layer,
                         "final_answer": record.final_answer is not None,
                         "nodes": len(record.nodes)},
        }

    def simplify(self, arguments) -> dict[str, Any]:
        _, problem = cases.validate_simplify_request(arguments)
        return as_result(problem) if problem else {"outcome": "SUCCESS", "reason": "NO_ERROR", "evidence": {}}

    def assess(self, original, simplified, arguments) -> dict[str, Any]:
        plan, problem = cases.validate_simplify_request(arguments)
        if problem:
            return as_result(problem)
        return as_result(cases.assess_simplification(original, simplified, plan).verdict)

    def point_line(self, point, line, predicate, **kwargs) -> dict[str, Any]:
        return as_result(cases.investigate_point_line(point, line, predicate, **kwargs).verdict)

    def routing(self, message, arguments, **kwargs) -> dict[str, Any]:
        return as_result(cases.classify_routing_failure(message, arguments, **kwargs).verdict)

    def good_record(self):
        workflow = wf([
            {"step_id": "geo", "tool": "geocode.forward", "arguments": {"query": "Berlin"}},
            {"step_id": "rev", "tool": "geocode.reverse", "arguments": {
                "lat": "$.steps.geo.read.top.lat"}},
        ])
        return executor.Executor(
            {"geo": env(geocode()), "rev": env(geocode())}, run_id="M6-REG",
            oracle_expectations={"geo.result_count": 1},
        ).run(workflow)

    def integrity(self, mutate: Callable[[dict], None], *, anchor: bool = False,
                  expected: str = "SEMANTIC_CONFLICT") -> dict[str, Any]:
        record = self.good_record()
        data = copy.deepcopy(record.to_dict())
        mutate(data)
        v = executor.verify_execution_record(data, external_anchor=record.digest if anchor else None)
        return as_result(v, expected_detection=expected)

    def snapshot_reuse(self) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as tmp:
            store = snapshots.SnapshotStore(Path(tmp))
            store.preflight("SAME-RUN", {"x": 1}, log_version="log/v1", harness_fingerprint="fp")
            _, failure = store.preflight("SAME-RUN", {"x": 2}, log_version="log/v1", harness_fingerprint="fp")
        return {"outcome": "INVALID_ARGUMENT", "reason": failure.reason if failure else "NO_FAILURE",
                "evidence": {"detail": failure.detail if failure else ""}}


@dataclass(frozen=True)
class Case:
    case_id: str
    category: str
    name: str
    expected_outcome: Outcome
    expected_reason: str | None
    origin: str
    run: Callable[[Matrix], dict[str, Any]]


def build_cases() -> list[Case]:
    A, B, C, D, X = ("A", "B", "C", "D", "X")
    return [
        # ---------------- A · parameter semantics ----------------
        Case("A01", A, "unit_missing_simplify_bare_number", Outcome.INVALID_ARGUMENT,
             "SIMPLIFY_TOLERANCE_UNIT_MISSING", "P2-M5",
             lambda m: m.simplify(cases.legacy_p2_m5_arguments())),
        Case("A02", A, "lat_lon_swapped", Outcome.SEMANTIC_CONFLICT,
             "LAT_LON_SWAP_SUSPECTED", "M5-live-shape",
             lambda m: m.adapt(env(geocode(lat=13.3777, lon=52.5163)), "geocode.forward",
                               expected_bbox=(52.30, 13.20, 52.70, 13.60))),
        Case("A03", A, "crs_request_response_conflict", Outcome.SEMANTIC_CONFLICT,
             "CRS_DISAGREES_BETWEEN_REQUEST_AND_RESPONSE", "synthetic",
             lambda m: m.adapt(env(dict(geocode(), crs="EPSG:3857")), "geocode.forward",
                               arguments={"crs": "EPSG:4326"})),
        Case("A04", A, "degree_used_as_metre", Outcome.INVALID_ARGUMENT,
             "DEGREE_TOLERANCE_IMPLAUSIBLE_FOR_LOCAL_GEOMETRY", "P2-M5",
             lambda m: m.simplify({"tolerance": 5, "tolerance_unit": "degrees"})),
        Case("A05", A, "empty_geometry", Outcome.EMPTY_RESULT, None, "synthetic",
             lambda m: m.adapt(env({"operation": "simplify", "geometry": None}),
                               "geometry.transform", arguments={"operation": "simplify",
                                                               "tolerance": 0.00005,
                                                               "tolerance_unit": "degrees"},
                               require_nonempty=True)),
        Case("A06", A, "degenerate_line_segment", Outcome.SAFE_ABSTENTION,
             "POINT_LINE_RESIDUAL_UNCOMPUTABLE", "P2-S4",
             lambda m: m.point_line([13.39, 52.52],
                                    {"type": "LineString", "coordinates": [[13.39, 52.52], [13.39, 52.52]]},
                                    False)),
        Case("A07", A, "self_intersecting_polygon", Outcome.INVALID_ARGUMENT,
             "SIMPLIFY_GEOMETRY_TOPOLOGY_INVALID", "synthetic",
             lambda m: m.assess(square(), {"type": "Polygon", "coordinates": [[
                 [13.3770, 52.5160], [13.3790, 52.5180], [13.3770, 52.5180],
                 [13.3790, 52.5160], [13.3770, 52.5160]]]},
                 {"tolerance": 0.00005, "tolerance_unit": "degrees"})),
        Case("A08", A, "coordinate_out_of_bounds", Outcome.INVALID_ARGUMENT,
             "LATITUDE_OUT_OF_RANGE", "synthetic",
             lambda m: m.adapt(env(geocode(lat=152.5)), "geocode.forward")),
        Case("A09", A, "matrix_dimension_mismatch", Outcome.INVALID_ARGUMENT,
             "MATRIX_SHAPE_DISAGREES_WITH_SOURCES_TARGETS", "M5-live-shape",
             lambda m: m.adapt(env({"sources": [{"lat": 1, "lon": 1}], "targets": [{"lat": 2, "lon": 2}],
                                    "sources_to_targets": [[1, 2], [3, 4]]}), "route.matrix")),

        # ---------------- B · response structure ----------------
        Case("B01", B, "count_disagrees_with_results", Outcome.SEMANTIC_CONFLICT,
             "PROVIDER_COUNT_DISAGREES_WITH_ARRAY", "REPLAY_FROM_LIVE_SANITISED",
             lambda m: m.adapt(
                 env({"count": 3, "results": m.real("geocode_address")["results"][:1]}),
                 "geocode.forward")),
        Case("B02", B, "http200_with_iserror", Outcome.PROVIDER_ERROR,
             "MCP_TOOL_REPORTED_ERROR_HTTP200", "M5-live-shape",
             lambda m: m.adapt({"result": {"isError": True,
                                           "content": [{"type": "text", "text": "provider error"}]}},
                               "geocode.forward")),
        Case("B03", B, "required_field_missing", Outcome.EVIDENCE_MISSING,
             "RESULT_CONTAINER_FIELD_MISSING", "REPLAY_FROM_LIVE_SANITISED",
             lambda m: m.adapt(env({"query": "Berlin"}), "geocode.forward")),
        Case("B04", B, "legal_empty_result", Outcome.EMPTY_RESULT,
             "NO_RESULTS_RETURNED", "synthetic",
             lambda m: m.adapt(env({"count": 0, "results": []}), "geocode.forward")),
        Case("B05", B, "multi_candidate_identity_ambiguous", Outcome.SEMANTIC_CONFLICT,
             "CROSS_TOOL_CONFLICT_DETECTED", "synthetic",
             lambda m: m.chain(wf([
                 {"step_id": "geo", "tool": "geocode.forward", "arguments": {}},
                 {"step_id": "rev", "tool": "geocode.reverse", "arguments": {}},
             ], cross_checks=[{"kind": "identity_preserved", "from_step": "geo", "to_step": "rev"}]),
                 {"geo": env(geocode(2, place_ids=["A", "B"])), "rev": env(geocode(place_ids=["B"]))},
                 oracle_expectations={"geo.result_count": 2})),
        Case("B06", B, "json_type_changed_results_object", Outcome.EVIDENCE_MISSING,
             "RESULT_CONTAINER_FIELD_MISSING", "REPLAY_FROM_LIVE_SANITISED",
             lambda m: m.adapt(env({"count": 1, "results": {"lat": 52.5, "lon": 13.4}}),
                               "geocode.forward")),
        Case("B07", B, "null_and_non_finite_numbers", Outcome.EVIDENCE_MISSING,
             "ROUTE_DISTANCE_FIELD_MISSING", "synthetic",
             lambda m: m.adapt(env({"distance": float("nan"), "time": None}), "route.route")),
        Case("B08", B, "return_order_change_is_not_a_failure", Outcome.SUCCESS,
             "ADAPTER_SUCCESS", "REPLAY_FROM_LIVE_SANITISED",
             lambda m: m.adapt(env(geocode(2, place_ids=["B", "A"])), "geocode.forward")),

        # ---------------- C · execution evidence ----------------
        Case("C01", C, "response_deleted", Outcome.EVIDENCE_MISSING,
             "RESPONSE_MISSING_FOR_STEP", "synthetic",
             lambda m: m.chain(wf([{"step_id": "geo", "tool": "geocode.forward", "arguments": {}}]),
                               {}, oracle_expectations={"geo.result_count": 1})),
        Case("C02", C, "response_replaced_with_conflicting_value", Outcome.SEMANTIC_CONFLICT,
             "CROSS_TOOL_CONFLICT_DETECTED", "synthetic",
             lambda m: m.chain(wf([
                 {"step_id": "mat", "tool": "route.matrix", "arguments": {}},
                 {"step_id": "route", "tool": "route.route", "arguments": {}},
             ], cross_checks=[{"kind": "matrix_cell_equals_route", "matrix_step": "mat",
                               "route_step": "route", "row": 0, "col": 1, "tolerance_m": 0}]),
                 {"mat": env(matrix_payload()), "route": env(route(9999.0))},
                 oracle_expectations={"route.distance_m": 9999.0})),
        Case("C03", C, "response_digest_modified", Outcome.SEMANTIC_CONFLICT,
             "EXECUTION_RECORD_INTEGRITY_FAILED", "synthetic",
             lambda m: m.integrity(lambda d: d["nodes"][0].update({"response_sha256": "0" * 64}))),
        Case("C04", C, "consumption_record_modified", Outcome.SEMANTIC_CONFLICT,
             "EXECUTION_RECORD_INTEGRITY_FAILED", "synthetic",
             lambda m: m.integrity(lambda d: d["consumption_proof"][0].update({"consumed_paths": []}))),
        Case("C05", C, "trace_evidence_deleted", Outcome.SEMANTIC_CONFLICT,
             "EXECUTION_RECORD_INTEGRITY_FAILED", "synthetic",
             lambda m: m.integrity(lambda d: d.update({"final_answer_evidence": []}))),
        Case("C06", C, "consistent_repackaging_detected_by_anchor", Outcome.SEMANTIC_CONFLICT,
             "EXECUTION_RECORD_INTEGRITY_FAILED", "synthetic",
             lambda m: m.integrity(
                 lambda d: d["nodes"][0]["verdict"].update({"reason_code": "FORGED_CONSISTENT_REPACK"}),
                 anchor=True)),
        Case("C07", C, "forged_internal_consistency_no_independent_oracle", Outcome.SEMANTIC_CONFLICT,
             "EXECUTION_RECORD_INTEGRITY_FAILED", "synthetic",
             lambda m: m.integrity(lambda d: d["oracle"].update({"status": "UNKNOWN"}))),
        Case("C08", C, "reused_run_identity", Outcome.INVALID_ARGUMENT,
             "PREFLIGHT_ALREADY_EXISTS_FOR_RUN", "M5-19:22-incident",
             lambda m: m.snapshot_reuse()),

        # ---------------- D · multi-step chains ----------------
        Case("D01", D, "upstream_error_propagates", Outcome.PROVIDER_ERROR,
             "MCP_TOOL_REPORTED_ERROR_HTTP200", "synthetic",
             lambda m: m.chain(wf([
                 {"step_id": "geo", "tool": "geocode.forward", "arguments": {}},
                 {"step_id": "rev", "tool": "geocode.reverse", "arguments": {
                     "lat": "$.steps.geo.read.top.lat"}},
             ]), {"geo": {"result": {"isError": True,
                                    "content": [{"type": "text", "text": "boom"}]}},
                  "rev": env(geocode())}, oracle_expectations={"geo.result_count": 1})),
        Case("D02", D, "coordinate_order_swapped_between_steps", Outcome.SEMANTIC_CONFLICT,
             "LAT_LON_SWAP_SUSPECTED", "synthetic",
             lambda m: m.adapt(env(geocode(lat=13.3777, lon=52.5163)),
                               "geocode.forward", expected_bbox=(52.30, 13.20, 52.70, 13.60))),
        Case("D03", D, "place_id_mismatch", Outcome.SEMANTIC_CONFLICT,
             "CROSS_TOOL_CONFLICT_DETECTED", "synthetic",
             lambda m: m.chain(wf([
                 {"step_id": "geo", "tool": "geocode.forward", "arguments": {}},
                 {"step_id": "rev", "tool": "geocode.reverse", "arguments": {}},
             ], cross_checks=[{"kind": "identity_preserved", "from_step": "geo", "to_step": "rev"}]),
                 {"geo": env(geocode(place_ids=["A"])), "rev": env(geocode(place_ids=["Z"]))},
                 oracle_expectations={"geo.result_count": 1})),
        Case("D04", D, "matrix_transposed", Outcome.SEMANTIC_CONFLICT,
             "CROSS_TOOL_CONFLICT_DETECTED", "synthetic",
             lambda m: m.chain(wf([
                 {"step_id": "mat", "tool": "route.matrix", "arguments": {}},
             ], cross_checks=[{"kind": "matrix_direction", "matrix_step": "mat",
                               "expected_index": [0, 1], "actual_index": [1, 0]}]),
                 {"mat": env({"sources_to_targets": [[0, 1000], [1200, 0]],
                              "distance_units": "meters"})},
                 oracle_expectations={"mat.matrix_key": "sources_to_targets"})),
        Case("D05", D, "route_direction_reversed_on_asymmetric_matrix", Outcome.SEMANTIC_CONFLICT,
             "CROSS_TOOL_CONFLICT_DETECTED", "synthetic",
             lambda m: m.chain(wf([
                 {"step_id": "mat", "tool": "route.matrix", "arguments": {}},
             ], cross_checks=[{"kind": "matrix_direction", "matrix_step": "mat",
                               "expected_index": [1, 0], "actual_index": [0, 1]}]),
                 {"mat": env({"sources_to_targets": [[0, 900], [1500, 0]],
                              "distance_units": "meters"})},
                 oracle_expectations={"mat.matrix_key": "sources_to_targets"})),
        Case("D06", D, "missing_intermediate_node", Outcome.EVIDENCE_MISSING,
             "UPSTREAM_REFERENCE_MISSING", "synthetic",
             lambda m: m.chain(wf([
                 {"step_id": "geo", "tool": "geocode.forward", "arguments": {}},
                 {"step_id": "rev", "tool": "geocode.reverse", "arguments": {
                     "lat": "$.steps.absent.read.top.lat"}},
             ]), {"geo": env(geocode()), "rev": env(geocode())},
                 oracle_expectations={"geo.result_count": 1})),
        Case("D07", D, "illegal_recovery_attempt", Outcome.PROVIDER_ERROR,
             "MCP_TOOL_REPORTED_ERROR_HTTP200", "synthetic",
             lambda m: m.chain(wf([{"step_id": "geo", "tool": "geocode.forward", "arguments": {}}]),
                               {"geo": {"result": {"isError": True,
                                                  "content": [{"type": "text", "text": "boom"}]}}},
                               oracle_expectations={"geo.result_count": 1},
                               recovery_policy={"allow": "undeclared_recovery",
                                                "on_reasons": ["MCP_TOOL_REPORTED_ERROR_HTTP200"]})),
        Case("D08", D, "answer_without_sufficient_evidence", Outcome.SAFE_ABSTENTION,
             "EVIDENCE_INSUFFICIENT_SAFE_ABSTENTION", "synthetic",
             lambda m: m.chain(wf([{"step_id": "geo", "tool": "geocode.forward", "arguments": {}}]),
                               {"geo": env(geocode())})),

        # ---------------- X · combinations ----------------
        Case("X01", X, "unit_error_plus_count_conflict", Outcome.INVALID_ARGUMENT,
             "SIMPLIFY_TOLERANCE_UNIT_MISSING", "combined:A01+B01",
             lambda m: m.adapt(env({"count": 9, "results": []}), "geometry.transform",
                               arguments={"operation": "simplify", "tolerance": 5})),
        Case("X02", X, "structure_mutation_plus_evidence_tamper", Outcome.SEMANTIC_CONFLICT,
             "EXECUTION_RECORD_INTEGRITY_FAILED", "combined:B03+C03",
             lambda m: m.integrity(lambda d: d["nodes"][0].update({"response_sha256": "0" * 64}))),
        Case("X03", X, "swap_plus_multistep_reference", Outcome.EVIDENCE_MISSING,
             "UPSTREAM_REFERENCE_MISSING", "combined:A02+D06",
             lambda m: m.chain(wf([
                 {"step_id": "geo", "tool": "geocode.forward", "arguments": {}},
                 {"step_id": "rev", "tool": "geocode.reverse", "arguments": {
                     "lat": "$.steps.gone.read.top.lat"}},
             ]), {"geo": env(geocode(lat=13.3777, lon=52.5163)), "rev": env(geocode())},
                 oracle_expectations={"geo.result_count": 1})),
        Case("X04", X, "deleted_response_in_multistep_chain", Outcome.EVIDENCE_MISSING,
             "RESPONSE_MISSING_FOR_STEP", "combined:C01+D06",
             lambda m: m.chain(wf([
                 {"step_id": "geo", "tool": "geocode.forward", "arguments": {}},
                 {"step_id": "rev", "tool": "geocode.reverse", "arguments": {
                     "lat": "$.steps.geo.read.top.lat"}},
             ]), {"geo": env(geocode())}, oracle_expectations={"geo.result_count": 1})),
        Case("X05", X, "iserror_with_failed_recovery", Outcome.PROVIDER_ERROR,
             "MCP_TOOL_REPORTED_ERROR_HTTP200", "combined:B02+D07",
             lambda m: m.chain(wf([{"step_id": "geo", "tool": "geocode.forward", "arguments": {}}]),
                               {"geo": {"result": {"isError": True,
                                                  "content": [{"type": "text", "text": "boom"}]}}},
                               oracle_expectations={"geo.result_count": 1},
                               recovery_policy={"allow": "retry", "on_reasons": ["MCP_TOOL_REPORTED_ERROR_HTTP200"],
                                                "retry_responses": {"geo": env({"query": "x"})}})),
        Case("X06", X, "routing_off_network_safe_abstention", Outcome.SAFE_ABSTENTION,
             "ROUTING_OFF_NETWORK_SAFE_ABSTENTION", "combined:P3-X6",
             lambda m: m.routing("No suitable edges near location",
                                 {"waypoints": [{"lat": 52.5075, "lon": 13.3327},
                                                {"lat": 52.473, "lon": 13.403}], "mode": "drive"})),
    ]


def run_matrix() -> dict[str, Any]:
    matrix = Matrix()
    results = []
    for case in build_cases():
        try:
            observed = case.run(matrix)
        except Exception as exc:  # a matrix driver must report, not crash the whole run
            observed = {"outcome": "INTERNAL_ERROR", "reason": type(exc).__name__,
                        "evidence": {"detail": str(exc)[:300]}}
        outcome_ok = observed["outcome"] == case.expected_outcome.value
        reason_ok = case.expected_reason is None or observed["reason"] == case.expected_reason
        results.append({
            "case_id": case.case_id,
            "category": case.category,
            "category_name": CATEGORIES[case.category],
            "name": case.name,
            "origin": case.origin,
            "expected_outcome": case.expected_outcome.value,
            "expected_reason": case.expected_reason,
            "observed_outcome": observed["outcome"],
            "observed_reason": observed["reason"],
            "passed": outcome_ok and reason_ok,
            "evidence": observed.get("evidence", {}),
        })
    by_category: dict[str, dict[str, int]] = {}
    for key, name in CATEGORIES.items():
        rows = [r for r in results if r["category"] == key]
        by_category[f"{key}_{name}"] = {
            "total": len(rows),
            "passed": sum(1 for r in rows if r["passed"]),
            "failed": sum(1 for r in rows if not r["passed"]),
        }
    attribution = [
        {
            "case_id": r["case_id"], "category": r["category_name"],
            "fault": r["name"], "observed_outcome": r["observed_outcome"],
            "observed_reason": r["observed_reason"],
            "layer": "TOOL_EXECUTOR" if r["category"] in ("A", "B") else
                     "EVALUATOR" if r["category"] == "C" else "AGENT_DECISION",
            "reproducible": True,
        }
        for r in results
    ]
    return {
        "schema": "geoagent.m6.regression-results/1",
        "version": REGRESSION_VERSION,
        "network": False,
        "provider_calls": 0,
        "fixture_origin": matrix.fixture_origin,
        "real_shape_tools_available": sorted(matrix.real_shapes),
        "total_cases": len(results),
        "passed": sum(1 for r in results if r["passed"]),
        "failed": sum(1 for r in results if not r["passed"]),
        "by_category": by_category,
        "expected_verdict_required_for_every_case": True,
        "retained_historical_failure_ids": ["P2-M5", "P2-S4", "P3-X6"],
        "historical_failures_rewritten": False,
        "results": results,
        "failure_attribution_matrix": attribution,
    }
