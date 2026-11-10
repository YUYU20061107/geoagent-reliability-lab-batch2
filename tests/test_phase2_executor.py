"""Phase 2: twelve multi-step chains, four responsibility layers, consumption proof.

All responses are synthetic offline fixtures. No provider call, no credentials,
no dependency on private sealed evidence.
"""

from __future__ import annotations

import copy
import json
import unittest

from geoagent_m6 import executor
from geoagent_m6.outcomes import Outcome


def env(payload):
    return {"jsonrpc": "2.0", "id": 1, "result": {"structuredContent": payload}}


def geocode(n=1, *, place_ids=None):
    items = []
    for i in range(n):
        items.append({
            "lat": 52.5163 + i * 0.001, "lon": 13.3777 + i * 0.001,
            "place_id": (place_ids or [f"p{i}" for i in range(n)])[i],
            "formatted": f"Place {i}", "country_code": "de",
        })
    return {"count": n, "results": items}


def route(distance=1500.0, time_s=600.0):
    return {
        "distance": distance, "time": time_s,
        "geometry": {"type": "LineString", "coordinates": [[13.3777, 52.5163], [13.4000, 52.5200]]},
    }


def matrix(rows=2, cols=2):
    return {
        "sources": [{"lat": 52.51 + i * 0.001, "lon": 13.38 + i * 0.001} for i in range(rows)],
        "targets": [{"lat": 52.52 + j * 0.001, "lon": 13.39 + j * 0.001} for j in range(cols)],
        "sources_to_targets": [[0 if i == j else 1000 + 100 * i + 10 * j for j in range(cols)] for i in range(rows)],
        "distance_units": "meters",
    }


def workflow(chain, *, invariants=None, cross_checks=None, wid="WF"):
    return {
        "id": wid, "chain": chain,
        "invariants": invariants or [], "cross_checks": cross_checks or [],
    }


ANCHOR_A = {"lat": 52.5163, "lon": 13.3777}
ANCHOR_B = {"lat": 52.5219, "lon": 13.4132}


class TestTwelveChains(unittest.TestCase):
    def _run(self, wf, responses, **kwargs):
        return executor.Executor(responses, run_id="m6-test", **kwargs).run(wf)

    def test_01_forward_then_reverse_geocoding(self):
        wf = workflow([
            {"step_id": "geo", "tool": "geocode.forward", "arguments": {"query": "Berlin"}},
            {"step_id": "rev", "tool": "geocode.reverse", "arguments": {
                "lat": "$.steps.geo.read.top.lat", "lon": "$.steps.geo.read.top.lon"}},
        ])
        record = self._run(wf, {"geo": env(geocode()), "rev": env(geocode())},
                           oracle_expectations={"geo.result_count": 1, "rev.result_count": 1})
        self.assertEqual(record.evaluator["outcome"], "SUCCESS")
        self.assertIsNotNone(record.final_answer)
        self.assertEqual(len(record.edges), 2)
        self.assertTrue(record.final_answer_evidence)
        self.assertTrue(all(p["consumed_count"] > 0 for p in record.consumption_proof))
        graph = executor.dependency_graph(record)
        self.assertEqual(graph["nodes"][1]["capability"], "geocode.reverse")
        self.assertIn("$.steps.geo.read.top.lat", [e["source_path"] for e in graph["edges"]])

    def test_02_place_search_then_routing(self):
        wf = workflow([
            {"step_id": "search", "tool": "places.search", "arguments": {"query": "cafe", "limit": 1}},
            {"step_id": "route", "tool": "route.route", "arguments": {
                "waypoints": [ANCHOR_A, "$.steps.search.read.top"], "mode": "drive"}},
        ], invariants=[{"invariant": "route_at_least_geodesic", "step": "route",
                        "from": ANCHOR_A, "to": {"lat": 52.5173, "lon": 13.3787}}])
        record = self._run(wf, {"search": env(geocode()), "route": env(route())},
                           oracle_expectations={"route.distance_m": 1500.0})
        self.assertEqual(record.evaluator["outcome"], "SUCCESS")
        self.assertEqual(record.oracle["status"], "PASS")
        self.assertEqual(len(record.oracle["checks"]), 2)

    def test_03_matrix_then_route_selection(self):
        wf = workflow([
            {"step_id": "mat", "tool": "route.matrix", "arguments": {"mode": "drive"}},
            {"step_id": "route", "tool": "route.route", "arguments": {
                "waypoints": [ANCHOR_A, ANCHOR_B], "mode": "drive",
                "selected_cell": "$.steps.mat.read.matrix.0.1"}},
        ], cross_checks=[{"kind": "matrix_cell_equals_route", "matrix_step": "mat",
                          "route_step": "route", "row": 0, "col": 1, "tolerance_m": 0.0}])
        payload = matrix()
        record = self._run(wf, {"mat": env(payload), "route": env(route(1010.0))},
                           oracle_expectations={"route.distance_m": 1010.0})
        self.assertEqual(record.evaluator["outcome"], "SUCCESS")
        self.assertTrue(record.cross_checks[0]["consistent"])

    def test_04_route_output_vs_distance_and_geometry(self):
        wf = workflow([
            {"step_id": "route", "tool": "route.route", "arguments": {"waypoints": [ANCHOR_A, ANCHOR_B], "mode": "drive"}},
            {"step_id": "measure", "tool": "geometry.measure", "arguments": {
                "geometry": "$.steps.route.read.geometry", "operation": "length"}},
        ])
        record = self._run(wf, {"route": env(route()), "measure": env({"type": "number", "data": 1500.0})},
                           oracle_expectations={"route.distance_m": 1500.0, "measure.value": 1500.0})
        self.assertEqual(record.evaluator["outcome"], "SUCCESS")
        self.assertTrue(record.edges)

    def test_05_spatial_relation_then_measurement(self):
        wf = workflow([
            {"step_id": "rel", "tool": "spatial.relate", "arguments": {"operation": "within"}},
            {"step_id": "measure", "tool": "geometry.measure", "arguments": {"operation": "area"}},
        ])
        record = self._run(wf, {"rel": env({"type": "boolean", "data": True}),
                                "measure": env({"type": "number", "data": 275.15})},
                           oracle_expectations={"rel.value": True, "measure.value": 275.15})
        self.assertEqual(record.evaluator["outcome"], "SUCCESS")

    def test_06_multi_candidate_identity_preserved(self):
        wf = workflow([
            {"step_id": "geo", "tool": "geocode.forward", "arguments": {"query": "Berlin", "limit": 2}},
            {"step_id": "rev", "tool": "geocode.reverse", "arguments": {
                "place_id": "$.steps.geo.read.top.place_id"}},
        ], cross_checks=[{"kind": "identity_preserved", "from_step": "geo", "to_step": "rev"}])
        record = self._run(wf, {"geo": env(geocode(2, place_ids=["id-A", "id-B"])),
                                "rev": env(geocode(place_ids=["id-A"]))},
                           oracle_expectations={"geo.result_count": 2})
        self.assertEqual(record.evaluator["outcome"], "SUCCESS")
        self.assertTrue(record.cross_checks[0]["consistent"])

        broken = self._run(wf, {"geo": env(geocode(2, place_ids=["id-A", "id-B"])),
                                "rev": env(geocode(place_ids=["id-B"]))},
                           oracle_expectations={"geo.result_count": 2})
        self.assertEqual(broken.evaluator["outcome"], "SEMANTIC_CONFLICT")

    def test_07_no_results_stops_safely(self):
        wf = workflow([
            {"step_id": "geo", "tool": "geocode.forward", "arguments": {"query": "nowhere"}},
            {"step_id": "rev", "tool": "geocode.reverse", "arguments": {"lat": "$.steps.geo.read.top.lat"}},
        ])
        record = self._run(wf, {"geo": env({"count": 0, "results": []}), "rev": env(geocode())},
                           oracle_expectations={"rev.result_count": 1})
        self.assertNotEqual(record.evaluator["outcome"], "SUCCESS")
        self.assertIsNone(record.final_answer)
        self.assertEqual(record.evaluator["reason_code"], "NO_RESULTS_RETURNED")

    def test_08_conflicting_tool_answers_are_rejected(self):
        wf = workflow([
            {"step_id": "mat", "tool": "route.matrix", "arguments": {}},
            {"step_id": "route", "tool": "route.route", "arguments": {"waypoints": [ANCHOR_A, ANCHOR_B]}},
        ], cross_checks=[{"kind": "matrix_cell_equals_route", "matrix_step": "mat",
                          "route_step": "route", "row": 0, "col": 1, "tolerance_m": 0.0}])
        record = self._run(wf, {"mat": env(matrix()), "route": env(route(9999.0))},
                           oracle_expectations={"route.distance_m": 9999.0})
        self.assertEqual(record.evaluator["outcome"], "SEMANTIC_CONFLICT")
        self.assertEqual(record.evaluator["reason_code"], "CROSS_TOOL_CONFLICT_DETECTED")
        self.assertIsNone(record.final_answer)

    def test_09_asymmetric_matrix_direction_dependency(self):
        asymmetric = {"sources_to_targets": [[0, 1000], [1200, 0]], "distance_units": "meters"}
        wf = workflow([
            {"step_id": "mat", "tool": "route.matrix", "arguments": {}},
        ], cross_checks=[{"kind": "matrix_direction", "matrix_step": "mat",
                          "expected_index": [0, 1], "actual_index": [1, 0]}])
        record = self._run(wf, {"mat": env(asymmetric)},
                           oracle_expectations={"mat.matrix_key": "sources_to_targets"})
        self.assertEqual(record.evaluator["outcome"], "SEMANTIC_CONFLICT")
        self.assertTrue(record.cross_checks[0]["direction_dependent"])
        self.assertTrue(record.cross_checks[0]["transposed"])

    def test_10_missing_evidence_abstains(self):
        wf = workflow([
            {"step_id": "geo", "tool": "geocode.forward", "arguments": {}},
            {"step_id": "rev", "tool": "geocode.reverse", "arguments": {
                "lat": "$.steps.geo.read.top.lat"}},
        ])
        missing_response = self._run(wf, {"geo": env(geocode())},
                                     oracle_expectations={"geo.result_count": 1})
        self.assertEqual(missing_response.evaluator["outcome"], "EVIDENCE_MISSING")
        self.assertIsNone(missing_response.final_answer)

        missing_reference = self._run(wf, {"geo": env(geocode()), "rev": env(geocode())},
                                      oracle_expectations={"geo.result_count": 1})
        del missing_reference  # reference exists here; the next case removes it
        wf2 = workflow([
            {"step_id": "geo", "tool": "geocode.forward", "arguments": {}},
            {"step_id": "rev", "tool": "geocode.reverse", "arguments": {
                "lat": "$.steps.absent.read.top.lat"}},
        ])
        bad_ref = self._run(wf2, {"geo": env(geocode()), "rev": env(geocode())},
                            oracle_expectations={"geo.result_count": 1})
        self.assertEqual(bad_ref.evaluator["reason_code"], "UPSTREAM_REFERENCE_MISSING")

    def test_11_executor_missing_blocks(self):
        wf = workflow([{"step_id": "geo", "tool": "geocode.forward", "arguments": {}}])
        record = executor.Executor(None, run_id="m6-test").run(wf)
        self.assertEqual(record.evaluator["outcome"], "EVIDENCE_MISSING")
        self.assertEqual(record.evaluator["reason_code"], "EXECUTOR_MISSING")
        self.assertIsNone(record.final_answer)
        self.assertEqual(record.nodes, [])

    def test_12_recovery_after_fault_injection(self):
        wf = workflow([{"step_id": "geo", "tool": "geocode.forward", "arguments": {"query": "Berlin"}}])
        failing = {"jsonrpc": "2.0", "id": 1,
                   "result": {"isError": True, "content": [{"type": "text", "text": "transient"}]}}
        replacement = env(geocode())
        record = self._run(
            wf, {"geo": failing},
            oracle_expectations={"geo.result_count": 1},
            recovery_policy={"allow": "retry_with_declared_replacement",
                             "on_reasons": ["MCP_TOOL_REPORTED_ERROR_HTTP200"],
                             "retry_responses": {"geo": replacement}},
        )
        self.assertEqual(record.evaluator["outcome"], "SUCCESS")
        self.assertTrue(record.recovery["attempted"])
        self.assertEqual(record.recovery["failed_attempt"]["reason_code"],
                         "MCP_TOOL_REPORTED_ERROR_HTTP200")
        self.assertTrue(record.nodes[0]["recovered"])

        illegal = self._run(
            wf, {"geo": failing}, oracle_expectations={"geo.result_count": 1},
            recovery_policy={"allow": "retry_with_declared_replacement",
                             "on_reasons": ["MCP_TOOL_REPORTED_ERROR_HTTP200"]},
        )
        self.assertNotEqual(illegal.evaluator["outcome"], "SUCCESS")
        self.assertFalse(illegal.recovery["attempted"])


class TestFourResponsibilities(unittest.TestCase):
    def test_tool_success_does_not_imply_task_success(self):
        wf = workflow([{"step_id": "geo", "tool": "geocode.forward", "arguments": {}}])
        record = executor.Executor({"geo": env(geocode())}, run_id="m6-test").run(wf)
        self.assertEqual(record.nodes[0]["verdict"]["outcome"], "SUCCESS")
        self.assertEqual(record.evaluator["outcome"], "SAFE_ABSTENTION")
        self.assertEqual(record.evaluator["reason_code"], "EVIDENCE_INSUFFICIENT_SAFE_ABSTENTION")
        self.assertIsNone(record.final_answer)
        self.assertEqual(record.oracle["status"], "UNKNOWN")

    def test_oracle_source_is_separate_from_tool_source(self):
        wf = workflow([{"step_id": "geo", "tool": "geocode.forward", "arguments": {}}])
        record = executor.Executor({"geo": env(geocode())}, run_id="m6-test",
                                   oracle_expectations={"geo.result_count": 1}).run(wf)
        self.assertEqual(record.nodes[0]["verdict"]["layer"], "TOOL_EXECUTOR")
        self.assertEqual(record.oracle["verdict"]["layer"], "ORACLE")
        self.assertEqual(record.evaluator["layer"], "EVALUATOR")
        self.assertIn("EXTERNAL_SPEC", record.oracle["source"])
        self.assertTrue(record.final_answer["not_provider_accuracy"])

    def test_dependency_graph_answers_six_questions(self):
        wf = workflow([
            {"step_id": "geo", "tool": "geocode.forward", "arguments": {"query": "Berlin", "limit": 1}},
            {"step_id": "rev", "tool": "geocode.reverse", "arguments": {
                "lat": "$.steps.geo.read.top.lat"}},
        ])
        record = executor.Executor({"geo": env(geocode()), "rev": env(geocode())},
                                   run_id="m6-test",
                                   oracle_expectations={"geo.result_count": 1}).run(wf)
        graph = executor.dependency_graph(record)
        self.assertEqual(graph["nodes"][0]["tool"], "geocode_address")
        self.assertIn("query", graph["nodes"][0]["input_fields"])
        self.assertEqual(len(graph["nodes"][0]["consumed_paths"]) > 0, True)
        self.assertEqual(graph["edges"][0]["source_step"], "geo")
        self.assertEqual(graph["edges"][0]["to_step"], "rev")
        self.assertIsNone(graph["failure_layer"])
        self.assertTrue(graph["final_answer_evidence"])

    def test_failure_layer_is_attributed(self):
        wf = workflow([{"step_id": "geo", "tool": "geocode.forward", "arguments": {}}])
        failing = {"result": {"isError": True, "content": [{"type": "text", "text": "boom"}]}}
        record = executor.Executor({"geo": failing}, run_id="m6-test").run(wf)
        self.assertEqual(record.failure_layer, "TOOL_EXECUTOR")
        self.assertEqual(record.nodes[0]["failure_layer"], "TOOL_EXECUTOR")


class TestConsumptionProofIntegrity(unittest.TestCase):
    def _good_record(self):
        wf = workflow([
            {"step_id": "geo", "tool": "geocode.forward", "arguments": {"query": "Berlin"}},
            {"step_id": "rev", "tool": "geocode.reverse", "arguments": {
                "lat": "$.steps.geo.read.top.lat"}},
        ])
        return executor.Executor({"geo": env(geocode()), "rev": env(geocode())},
                                 run_id="m6-test",
                                 oracle_expectations={"geo.result_count": 1}).run(wf)

    def test_clean_record_verifies(self):
        record = self._good_record()
        result = executor.verify_execution_record(record, external_anchor=record.digest)
        self.assertEqual(result.outcome, Outcome.SUCCESS)

    def test_tampering_is_detected(self):
        mutations = {
            "delete_response_digest": lambda d: d["nodes"][0].pop("response_sha256"),
            "alter_consumed_paths": lambda d: d["consumption_proof"][0].update({"consumed_paths": []}),
            "mark_no_consumption": lambda d: d["consumption_proof"][0].update({"proof": "NO_CONSUMED_FIELDS"}),
            "alter_edge_digest": lambda d: d["edges"][0].update({"value_sha256": "deadbeef"}),
            "remove_final_evidence": lambda d: d.update({"final_answer_evidence": []}),
            "inject_answer_on_failure": lambda d: d["evaluator"].update({"outcome": "SAFE_ABSTENTION"}),
        }
        for name, mutate in mutations.items():
            with self.subTest(mutation=name):
                data = copy.deepcopy(self._good_record().to_dict())
                mutate(data)
                result = executor.verify_execution_record(data)
                self.assertEqual(result.outcome, Outcome.SEMANTIC_CONFLICT,
                                 f"{name} was not detected")

    def test_repackaging_detected_by_external_anchor(self):
        record = self._good_record()
        anchor = record.digest
        data = copy.deepcopy(record.to_dict())
        data["nodes"][0]["verdict"]["reason_code"] = "FORGED_CONSISTENT_REPACK"
        result = executor.verify_execution_record(data, external_anchor=anchor)
        self.assertEqual(result.reason_code, "EXECUTION_RECORD_INTEGRITY_FAILED")
        self.assertIn("EXTERNAL_ANCHOR_DISAGREES_WITH_REPACKAGED_RECORD",
                      result.evidence["problems"])

    def test_record_serialisation_is_deterministic(self):
        a = self._good_record()
        b = self._good_record()
        self.assertEqual(a.digest, b.digest)


if __name__ == "__main__":
    unittest.main(verbosity=2)
