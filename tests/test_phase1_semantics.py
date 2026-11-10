"""Phase 1 regression: MCP adapter semantics, units/CRS/geometry, three live failures.

Runs entirely offline with synthetic fixtures. No credentials, no provider calls,
no dependency on private sealed evidence.
"""

from __future__ import annotations

import json
import math
import unittest

from geoagent_m6 import adapter, cases, semantics as geo
from geoagent_m6.outcomes import Outcome, from_legacy


def rpc(payload=None, *, is_error=False, text=None, status_code=None):
    body = {}
    if payload is not None:
        body["structuredContent"] = payload
    if text is not None:
        body["content"] = [{"type": "text", "text": text}]
    if status_code is not None:
        body["statusCode"] = status_code
    if is_error:
        body["isError"] = True
    return {"jsonrpc": "2.0", "id": 2, "result": body}


def geocode_payload(n=1, *, count=None, lat=52.5163, lon=13.3777):
    items = [{"lat": lat + i * 0.001, "lon": lon + i * 0.001, "place_id": f"p{i}"} for i in range(n)]
    return {"count": n if count is None else count, "results": items}


def square(lon=13.3777, lat=52.5163, half=0.001):
    return {"type": "Polygon", "coordinates": [[
        [lon - half, lat - half], [lon + half, lat - half],
        [lon + half, lat + half], [lon - half, lat + half],
        [lon - half, lat - half],
    ]]}


def bowtie():
    return {"type": "Polygon", "coordinates": [[
        [13.3770, 52.5160], [13.3790, 52.5180],
        [13.3770, 52.5180], [13.3790, 52.5160],
        [13.3770, 52.5160],
    ]]}


LINE = {"type": "LineString", "coordinates": [[13.380, 52.510], [13.400, 52.520]]}
BERLIN_BBOX = (52.30, 13.20, 52.70, 13.60)


class TestOutcomeTaxonomy(unittest.TestCase):
    def test_eight_terminal_states(self):
        self.assertEqual(len(list(Outcome)), 8)
        self.assertEqual(
            {o.value for o in Outcome},
            {"SUCCESS", "EMPTY_RESULT", "INVALID_ARGUMENT", "PROVIDER_ERROR",
             "CAPABILITY_UNAVAILABLE", "EVIDENCE_MISSING", "SEMANTIC_CONFLICT", "SAFE_ABSTENTION"},
        )

    def test_legacy_labels_map_into_single_taxonomy(self):
        expected = {
            "OK": "SUCCESS", "OK_EMPTY": "EMPTY_RESULT",
            "NORMALISATION_UNSUPPORTED": "EVIDENCE_MISSING",
            "TOOL_REPORTED_ERROR": "PROVIDER_ERROR",
            "UNSUPPORTED_CAPABILITY": "CAPABILITY_UNAVAILABLE",
            "INVARIANT_MISMATCH": "SEMANTIC_CONFLICT",
        }
        for legacy, outcome in expected.items():
            with self.subTest(legacy=legacy):
                self.assertEqual(from_legacy(legacy).outcome.value, outcome)

    def test_unknown_legacy_status_abstains(self):
        self.assertEqual(from_legacy("MADE_UP_STATUS").outcome, Outcome.SAFE_ABSTENTION)

    def test_empty_result_is_not_success(self):
        from geoagent_m6.outcomes import ok, verdict
        self.assertTrue(ok().succeeded)
        self.assertFalse(verdict(Outcome.EMPTY_RESULT, "NO_RESULTS").succeeded)


class TestAdapterContract(unittest.TestCase):
    def test_parameterised_envelope_classification(self):
        cases_table = [
            ("http200_iserror", rpc(geocode_payload(), is_error=True), {}, 200,
             "PROVIDER_ERROR", "MCP_TOOL_REPORTED_ERROR_HTTP200"),
            ("http500", rpc(geocode_payload()), {}, 500,
             "PROVIDER_ERROR", "HTTP_NON_SUCCESS"),
            ("business_status_400", rpc({"statusCode": 400, "count": 0, "results": []}), {}, 200,
             "PROVIDER_ERROR", "MCP_BUSINESS_STATUS_FAILURE"),
            ("jsonrpc_capability_missing",
             {"jsonrpc": "2.0", "id": 2, "error": {"code": -32601, "message": "Method not found"}}, {}, 200,
             "CAPABILITY_UNAVAILABLE", "MCP_RPC_CAPABILITY_MISSING"),
            ("jsonrpc_provider_error",
             {"jsonrpc": "2.0", "id": 2, "error": {"code": -32603, "message": "internal error"}}, {}, 200,
             "PROVIDER_ERROR", "MCP_RPC_ERROR"),
            ("iserror_capability_marker", rpc(text="tool not authorized", is_error=True), {}, 200,
             "CAPABILITY_UNAVAILABLE", "MCP_TOOL_CAPABILITY_MISSING"),
            ("missing_result_envelope", {"jsonrpc": "2.0", "id": 2}, {}, 200,
             "EVIDENCE_MISSING", "MCP_RESULT_ENVELOPE_MISSING"),
            ("missing_result_body", {"result": {}}, {}, 200,
             "EVIDENCE_MISSING", "MCP_RESULT_BODY_MISSING"),
            ("container_field_missing", rpc({"query": "Berlin"}), {}, 200,
             "EVIDENCE_MISSING", "RESULT_CONTAINER_FIELD_MISSING"),
            ("count_disagrees_with_array", rpc(geocode_payload(1, count=3)), {}, 200,
             "SEMANTIC_CONFLICT", "PROVIDER_COUNT_DISAGREES_WITH_ARRAY"),
            ("empty_legal_result", rpc(geocode_payload(0, count=0)), {}, 200,
             "EMPTY_RESULT", "NO_RESULTS_RETURNED"),
            ("coordinate_out_of_range", rpc(geocode_payload(1, lat=152.5)), {}, 200,
             "INVALID_ARGUMENT", "LATITUDE_OUT_OF_RANGE"),
            ("crs_request_response_conflict", rpc(dict(geocode_payload(), crs="EPSG:3857")),
             {"crs": "EPSG:4326"}, 200,
             "SEMANTIC_CONFLICT", "CRS_DISAGREES_BETWEEN_REQUEST_AND_RESPONSE"),
            ("simplify_without_unit", rpc(square()),
             {"operation": "simplify", "tolerance": 5}, 200,
             "INVALID_ARGUMENT", "SIMPLIFY_TOLERANCE_UNIT_MISSING"),
            ("simplify_ambiguous_unit_system", rpc(square()),
             {"operation": "simplify", "tolerance": 5, "tolerance_unit": "metric"}, 200,
             "INVALID_ARGUMENT", "AMBIGUOUS_UNIT_SYSTEM_REFUSED"),
            ("snapping_radius_over_policy", rpc(None, text='{"distance":1,"time":1}'),
             {"snapping_radius_m": 5000}, 200,
             "INVALID_ARGUMENT", "SNAPPING_RADIUS_OUTSIDE_POLICY"),
            ("unlimited_snapping", rpc(None, text='{"distance":1,"time":1}'),
             {"expand_until_found": True}, 200,
             "INVALID_ARGUMENT", "UNLIMITED_SNAPPING_FORBIDDEN"),
            ("geodesic_model_for_road_route", rpc(None, text='{"distance":1000,"time":60}'),
             {"distance_model": "haversine_sphere"}, 200,
             "SEMANTIC_CONFLICT", "GEODESIC_MODEL_DECLARED_FOR_ROAD_ROUTE"),
        ]
        for name, envelope, arguments, http_status, outcome, reason in cases_table:
            with self.subTest(case=name):
                if arguments.get("operation") == "simplify":
                    capability = "geometry.transform"
                elif any(k in arguments for k in ("snapping_radius_m", "expand_until_found", "distance_model")):
                    capability = "route.route"
                else:
                    capability = "geocode.forward"
                result = adapter.adapt(
                    envelope, capability=capability, arguments=arguments,
                    http_status=http_status, step_id=name,
                )
                self.assertEqual(result.step.verdict.outcome.value, outcome,
                                 f"{name}: {result.step.verdict.to_dict()}")
                self.assertEqual(result.step.verdict.reason_code, reason)

    def test_flattened_and_typed_and_geojson_shapes(self):
        good = adapter.adapt(rpc(geocode_payload(2)), capability="geocode.forward", step_id="g")
        self.assertEqual(good.step.verdict.outcome, Outcome.SUCCESS)
        self.assertEqual(good.step.read["result_count"], 2)
        self.assertEqual(good.step.read["source_shape"], "results")
        self.assertTrue(good.step.consumed)
        self.assertTrue(all("value_sha256" in c for c in good.step.consumed))

        typed_bool = adapter.adapt(rpc({"type": "boolean", "data": False}),
                                   capability="spatial.relate", step_id="rel")
        self.assertEqual(typed_bool.step.verdict.outcome, Outcome.SUCCESS)
        self.assertIs(typed_bool.step.read["value"], False)

        typed_num = adapter.adapt(rpc({"type": "number", "data": 275.15, "units": "meters"}),
                                  capability="geometry.measure", step_id="m")
        self.assertEqual(typed_num.step.verdict.outcome, Outcome.SUCCESS)
        self.assertEqual(typed_num.step.read["value"], 275.15)

        geojson = adapter.adapt(
            rpc({"type": "FeatureCollection", "features": [
                {"type": "Feature", "properties": {"place_id": "x"},
                 "geometry": {"type": "Point", "coordinates": [13.3777, 52.5163]}}
            ]}), capability="geocode.forward", step_id="gj",
        )
        self.assertEqual(geojson.step.verdict.outcome, Outcome.SUCCESS)
        self.assertEqual(geojson.step.read["results"][0]["place_id"], "x")
        self.assertAlmostEqual(geojson.step.read["results"][0]["lat"], 52.5163, places=6)

    def test_content_text_json_and_raw_byte_digest(self):
        result = adapter.adapt(
            rpc(text=json.dumps(geocode_payload(1))), capability="geocode.forward",
            raw_bytes=b'{"jsonrpc":"2.0"}', step_id="raw",
        )
        self.assertEqual(result.step.verdict.outcome, Outcome.SUCCESS)
        self.assertEqual(result.payload_kind, "content.text/json")
        self.assertEqual(result.transport_meta["capture_layer"], "MCP_CLIENT_OBSERVABLE")
        self.assertEqual(len(result.transport_meta["raw_message_sha256"]), 64)

    def test_category_catalogue_is_a_string_array(self):
        words = [f"catering.category_{i}" for i in range(833)]
        good = adapter.adapt(rpc({"count": 833, "categories": words}),
                             capability="places.categories", step_id="cats")
        self.assertEqual(good.step.verdict.outcome, Outcome.SUCCESS)
        self.assertEqual(good.step.read["result_count"], 833)
        self.assertEqual(good.step.read["category_count"], 833)
        self.assertTrue(good.step.read["count_matches_array"])

        mismatch = adapter.adapt(rpc({"count": 800, "categories": words}),
                                 capability="places.categories", step_id="cats_bad")
        self.assertEqual(mismatch.step.verdict.reason_code, "PROVIDER_COUNT_DISAGREES_WITH_ARRAY")

        missing = adapter.adapt(rpc({"count": 833}),
                                capability="places.categories", step_id="cats_missing")
        self.assertEqual(missing.step.verdict.outcome, Outcome.EVIDENCE_MISSING)

    def test_capability_resolution(self):
        tool, problem = adapter.resolve_tool("route.calculate")
        self.assertEqual(tool, "calculate_route")
        self.assertIsNone(problem)
        tool, problem = adapter.resolve_tool("not.a.capability")
        self.assertIsNone(tool)
        self.assertEqual(problem.outcome, Outcome.CAPABILITY_UNAVAILABLE)

    def test_lat_lon_swap_detection(self):
        swapped = adapter.adapt(
            rpc(geocode_payload(1, lat=13.3777, lon=52.5163)),
            capability="geocode.forward", expected_bbox=BERLIN_BBOX, step_id="swap",
        )
        self.assertEqual(swapped.step.verdict.reason_code, "LAT_LON_SWAP_SUSPECTED")

    def test_matrix_semantics(self):
        payload = {
            "sources": [{"lat": 52.51, "lon": 13.38}, {"lat": 52.52, "lon": 13.39}],
            "targets": [{"lat": 52.53, "lon": 13.40}],
            "sources_to_targets": [[1000], [1200]],
            "distance_units": "meters",
        }
        rectangular = adapter.adapt(rpc(payload), capability="route.matrix", step_id="mat")
        self.assertEqual(rectangular.step.verdict.outcome, Outcome.SUCCESS)
        self.assertTrue(rectangular.step.read["matrix_semantics"]["rectangular"])
        self.assertTrue(rectangular.step.read["matrix_semantics"]["direction_dependent"])

        asymmetric = {
            "sources_to_targets": [[0, 1000], [1200, 0]],
            "distance_units": "meters",
        }
        result = adapter.adapt(rpc(asymmetric), capability="route.matrix", step_id="asym")
        self.assertEqual(result.step.verdict.outcome, Outcome.SUCCESS)
        self.assertFalse(result.step.read["matrix_semantics"]["symmetric"])
        self.assertTrue(result.step.read["matrix_semantics"]["direction_dependent"])

        ragged = adapter.adapt(rpc({"sources_to_targets": [[1, 2], [3]]}),
                               capability="route.matrix", step_id="ragged")
        self.assertEqual(ragged.step.verdict.outcome, Outcome.SEMANTIC_CONFLICT)
        self.assertEqual(ragged.step.verdict.reason_code, "RAGGED_MATRIX")

    def test_route_distance_missing_and_null(self):
        for text, expected in (('{"time":60}', "EVIDENCE_MISSING"), ('{"distance":null,"time":60}', "EVIDENCE_MISSING")):
            with self.subTest(text=text):
                result = adapter.adapt(rpc(text=text), capability="route.route", step_id="r")
                self.assertEqual(result.step.verdict.outcome.value, expected)

    def test_adapter_contract_version_is_stamped(self):
        result = adapter.adapt(rpc(geocode_payload()), capability="geocode.forward")
        self.assertEqual(result.step.contract_version, adapter.ADAPTER_CONTRACT_VERSION)
        self.assertEqual(result.to_dict()["contract_version"], adapter.ADAPTER_CONTRACT_VERSION)


class TestUnitsAndGeometry(unittest.TestCase):
    def test_degree_conversion_is_latitude_dependent(self):
        self.assertNotAlmostEqual(
            geo.metres_per_degree_lat(0.0), geo.metres_per_degree_lat(78.0), delta=100.0
        )
        for lat in (0.0, 22.0, 52.5163, 78.0):
            with self.subTest(lat=lat):
                converted = geo.degrees_for_distance(800.0, lat)
                self.assertTrue(converted.applicable)
                back = geo.meridian_arc_m(lat, lat + converted.degrees)
                self.assertAlmostEqual(back, 800.0, delta=1e-3)
                self.assertEqual(converted.model, "wgs84_numerical")

    def test_conversion_refuses_unstable_or_out_of_envelope(self):
        self.assertEqual(
            geo.degrees_for_distance(10.0, 89.5, axis="parallel").verdict.outcome,
            Outcome.SAFE_ABSTENTION,
        )
        self.assertEqual(
            geo.degrees_for_distance(200_000.0, 52.5).verdict.outcome,
            Outcome.SAFE_ABSTENTION,
        )
        self.assertEqual(
            geo.degrees_for_distance(-1.0, 52.5).verdict.outcome,
            Outcome.INVALID_ARGUMENT,
        )

    def test_ambiguous_units_refused(self):
        for word in ("metric", "imperial", "si", "auto", "", None, 5):
            with self.subTest(word=word):
                unit, reason = geo.parse_length_unit(word)
                self.assertIsNone(unit)
                self.assertNotEqual(reason, "OK")

    def test_geometry_problems(self):
        self.assertEqual(geo.geometry_problems(square()), [])
        self.assertIn("SELF_INTERSECTION", " ".join(geo.geometry_problems(bowtie())))
        degenerate = {"type": "LineString", "coordinates": [[13.3, 52.5], [13.3, 52.5]]}
        self.assertIn("DEGENERATE_SEGMENT", geo.geometry_problems(degenerate))
        unclosed = {"type": "Polygon", "coordinates": [[
            [13.37, 52.51], [13.38, 52.51], [13.38, 52.52], [13.37, 52.52]
        ]]}
        self.assertTrue(any("RING_NOT_CLOSED" in p for p in geo.geometry_problems(unclosed)))
        self.assertEqual(geo.geometry_problems({"coordinates": []})[0], "UNSUPPORTED_GEOMETRY_TYPE")

    def test_polygon_area_local_plane(self):
        area, problem = geo.polygon_area_m2(square(half=0.001))
        self.assertIsNone(problem)
        width = 0.002 * geo.metres_per_degree_lon(52.5163)
        height = 0.002 * geo.metres_per_degree_lat(52.5163)
        self.assertAlmostEqual(area, width * height, delta=width * height * 0.001)

    def test_point_line_residual(self):
        on_line = [13.390, 52.515]
        residual = geo.point_line_residual(on_line, LINE)
        self.assertIsNotNone(residual)
        self.assertLess(residual.distance_m, 1.0)
        off_line = geo.point_line_residual([13.390, 52.530], LINE)
        self.assertGreater(off_line.distance_m, 100.0)
        endpoint = geo.point_line_residual([13.380, 52.510], LINE)
        self.assertTrue(endpoint.endpoint_hit)
        self.assertIsNone(geo.point_line_residual([13.39], LINE))

    def test_serialisation_loss(self):
        self.assertGreater(geo.serialisation_loss_m([13.3777, 52.5163], 7, 52.5), 0.0)
        self.assertGreater(
            geo.serialisation_loss_m([13.3777, 52.5163], 5, 52.5),
            geo.serialisation_loss_m([13.3777, 52.5163], 7, 52.5),
        )

    def test_snapping_policy_is_bounded(self):
        plan = geo.snapping_plan()
        self.assertEqual(plan.max_attempts, len(plan.candidates_m))
        self.assertEqual(max(plan.candidates_m), plan.max_radius_m)
        self.assertTrue(plan.unlimited_expansion_forbidden)


class TestP2M5(unittest.TestCase):
    def test_original_failure_is_retained_and_rejected_at_interface(self):
        plan, problem = cases.validate_simplify_request(cases.legacy_p2_m5_arguments())
        self.assertIsNone(plan)
        self.assertEqual(problem.outcome, Outcome.INVALID_ARGUMENT)
        self.assertEqual(problem.reason_code, "SIMPLIFY_TOLERANCE_UNIT_MISSING")
        self.assertEqual(problem.evidence["legacy_case"], "P2-M5")
        self.assertEqual(cases.RETAINED_FAILURES["P2-M5"]["m6_treatment_version"], "P2-M5-V2")

    def test_metres_convert_per_latitude_and_scale(self):
        seen = []
        for lat in (0.0, 22.0, 52.5163, 78.0):
            for metres in (1.0, 5.0, 50.0):
                with self.subTest(lat=lat, metres=metres):
                    plan, problem = cases.validate_simplify_request(
                        {"tolerance": metres, "tolerance_unit": "meters", "latitude_deg": lat}
                    )
                    self.assertIsNone(problem)
                    self.assertTrue(plan.conversion["applicable"])
                    back = geo.meridian_arc_m(lat, lat + plan.tolerance_deg)
                    self.assertAlmostEqual(back, metres, delta=1e-3)
                    seen.append(plan.tolerance_deg)
        self.assertGreater(len(set(seen)), 1)

    def test_degrees_need_no_conversion_and_missing_latitude_abstains(self):
        plan, problem = cases.validate_simplify_request(
            {"tolerance": 0.00005, "tolerance_unit": "degrees"}
        )
        self.assertIsNone(problem)
        self.assertEqual(plan.conversion["model"], "declared_degrees_no_conversion")
        self.assertEqual(plan.tolerance_deg, 0.00005)
        _, problem = cases.validate_simplify_request(
            {"tolerance": 5, "tolerance_unit": "meters"}
        )
        self.assertEqual(problem.outcome, Outcome.SAFE_ABSTENTION)

    def test_assessment_detects_area_loss_and_invalid_topology(self):
        plan, _ = cases.validate_simplify_request(
            {"tolerance": 0.00005, "tolerance_unit": "degrees"}
        )
        kept = cases.assess_simplification(square(), square(), plan)
        self.assertEqual(kept.verdict.outcome, Outcome.SUCCESS)
        self.assertAlmostEqual(kept.relative_area_change, 0.0, places=9)

        collapsed = {"type": "Polygon", "coordinates": [[
            [13.3770, 52.5160], [13.3780, 52.5160], [13.3775, 52.5165], [13.3770, 52.5160]
        ]]}
        lost = cases.assess_simplification(square(), collapsed, plan)
        self.assertGreater(lost.relative_area_change, 0.1)
        self.assertEqual(lost.verdict.outcome, Outcome.SEMANTIC_CONFLICT)

        bad = cases.assess_simplification(square(), bowtie(), plan)
        self.assertEqual(bad.verdict.outcome, Outcome.INVALID_ARGUMENT)

    def test_different_geometry_scales(self):
        plan, _ = cases.validate_simplify_request(
            {"tolerance": 0.00005, "tolerance_unit": "degrees"}
        )
        for half in (0.0001, 0.001, 0.005):
            with self.subTest(half=half):
                assessment = cases.assess_simplification(square(half=half), square(half=half), plan)
                self.assertEqual(assessment.verdict.outcome, Outcome.SUCCESS)
                self.assertGreater(assessment.original_area_m2, 0)
        self.assertGreater(
            cases.assess_simplification(square(half=0.005), square(half=0.005), plan).original_area_m2,
            cases.assess_simplification(square(half=0.0001), square(half=0.0001), plan).original_area_m2,
        )


class TestP2S4(unittest.TestCase):
    def test_conflict_stays_unresolved_without_sufficient_evidence(self):
        on_line = [13.390, 52.515]
        assessment = cases.investigate_point_line(on_line, LINE, False, tolerance_m=1.0)
        self.assertEqual(assessment.verdict.outcome, Outcome.SEMANTIC_CONFLICT)
        self.assertEqual(assessment.verdict.reason_code, "SEMANTIC_CONFLICT_UNRESOLVED")
        self.assertFalse(assessment.provider_bug_claimed)
        self.assertLess(assessment.distance_residual_m, 1.0)
        self.assertGreater(assessment.serialisation_loss_m, 0)

    def test_provider_inconsistency_requires_full_evidence(self):
        assessment = cases.investigate_point_line(
            [13.390, 52.515], LINE, False, tolerance_m=1.0,
            documented_tolerance_contract=True,
            provider_documentation_ref="PROVIDER_DOC#point_on_line/v1",
            provider_semantics_documented=True, independent_samples=3,
        )
        self.assertEqual(assessment.verdict.reason_code, "PROVIDER_INCONSISTENCY")
        self.assertTrue(assessment.provider_bug_claimed)

    def test_consistent_cases(self):
        off = cases.investigate_point_line([13.390, 52.530], LINE, False, tolerance_m=1.0)
        self.assertEqual(off.verdict.outcome, Outcome.SUCCESS)
        on = cases.investigate_point_line([13.390, 52.515], LINE, True, tolerance_m=1.0)
        self.assertEqual(on.verdict.outcome, Outcome.SUCCESS)

    def test_unreadable_geometry_abstains(self):
        assessment = cases.investigate_point_line([13.39], LINE, False)
        self.assertEqual(assessment.verdict.outcome, Outcome.SAFE_ABSTENTION)
        self.assertFalse(assessment.provider_bug_claimed)

    def test_historical_case_preserved(self):
        self.assertEqual(cases.RETAINED_FAILURES["P2-S4"]["m6_treatment_version"], "P2-S4-V2")
        self.assertEqual(cases.all_treatments()["provider_bug_claims"], 0)


class TestP3X6(unittest.TestCase):
    def test_off_network_abstains_with_bounded_candidates(self):
        result = cases.classify_routing_failure(
            "No suitable edges near location",
            {"waypoints": [{"lat": 52.5075, "lon": 13.3327}, {"lat": 52.473, "lon": 13.403}], "mode": "drive"},
        )
        self.assertEqual(result.classification, "OFF_NETWORK_LOCATION")
        self.assertEqual(result.verdict.outcome, Outcome.SAFE_ABSTENTION)
        self.assertFalse(result.final_answer_allowed)
        self.assertTrue(result.verdict.evidence["unlimited_radius_retry_forbidden"])
        self.assertFalse(result.verdict.evidence["unroutable_reported_as_success"])
        self.assertEqual(result.snapping_plan["max_attempts"], 3)
        self.assertGreaterEqual(len(result.candidates), 2)

    def test_failure_classification_matrix(self):
        table = [
            ("invalid coordinate", {"waypoints": [{"lat": 152.5, "lon": 13.4}]}, None, "INVALID_COORDINATE"),
            ("unsupported mode", {"mode": "teleport"}, None, "UNSUPPORTED_TRAVEL_MODE"),
            ("service unavailable", {"mode": "drive"}, 503, "SERVICE_UNAVAILABLE"),
            ("unknown", {"mode": "drive"}, None, "UNKNOWN"),
        ]
        for name, arguments, status, expected in table:
            with self.subTest(case=name):
                result = cases.classify_routing_failure("some failure", arguments, http_status=status)
                self.assertEqual(result.classification, expected)
                self.assertFalse(result.final_answer_allowed)

    def test_never_reports_unroutable_as_success(self):
        for message in ("No suitable edges near location", "", "Service Unavailable", "weird"):
            with self.subTest(message=message):
                result = cases.classify_routing_failure(message, {"mode": "drive"})
                self.assertNotEqual(result.verdict.outcome, Outcome.SUCCESS)

    def test_historical_case_preserved(self):
        self.assertEqual(cases.RETAINED_FAILURES["P3-X6"]["m6_treatment_version"], "P3-X6-V2")
        self.assertTrue(cases.all_treatments()["historical_verdicts_untouched"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
