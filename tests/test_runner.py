"""Tests for the offline mock runner and independent evaluation."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from geoagent_reliability_lab.evaluator import evaluate_trace
from geoagent_reliability_lab.fixtures import FixtureStore
from geoagent_reliability_lab.mock_adapter import MockAdapter, MockInvocation
from geoagent_reliability_lab.registry import load_registry
from geoagent_reliability_lab.runner import RunConfig, load_traces, run_suite

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "tasks" / "tasks.json"
FIXTURE_PATH = ROOT / "fixtures" / "mock_responses.json"


class RunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = load_registry(REGISTRY_PATH)
        cls.store = FixtureStore.load(FIXTURE_PATH)

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.trace_path = Path(self.tempdir.name) / "trace.jsonl"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_full_mock_suite_passes_and_writes_evidence(self) -> None:
        summary = run_suite(
            self.registry.tasks,
            MockAdapter(self.store),
            RunConfig(max_tool_calls=8, max_budget_units=8.0),
            self.trace_path,
        )
        self.assertEqual(summary.total, 18)
        self.assertEqual(summary.passed, 18)
        self.assertEqual(summary.failed, 0)
        self.assertTrue(summary.ok)

        lines = self.trace_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 18)
        trace = json.loads(lines[0])
        self.assertEqual(trace["mode"], "synthetic_mock")
        self.assertEqual(trace["validator_version"], "geoagent-validator/0.1.0")
        self.assertTrue(trace["passed"])
        self.assertEqual(trace["status"], "pass")
        self.assertIsNone(trace["error_reason"])
        self.assertIn("params", trace)
        self.assertIn("tool_calls", trace)
        self.assertEqual(trace["source"]["label"], "synthetic/illustrative")
        self.assertFalse(trace["source"]["network"])
        self.assertTrue(trace["tool_calls"][0]["response"]["synthetic"])

    def test_tool_error_is_recorded_in_trace(self) -> None:
        adapter = MockAdapter(self.store, failure_mode="tool_error", failure_task="G-003")
        task = self.registry.by_id("G-003")
        summary = run_suite([task], adapter, RunConfig(), self.trace_path)
        self.assertEqual(summary.failed, 1)
        trace = load_traces(self.trace_path)[0]
        self.assertEqual(trace["status"], "fail")
        self.assertEqual(trace["error"]["code"], "INJECTED_TOOL_ERROR")
        self.assertIn("G-003.geocode", trace["error_reason"])
        self.assertEqual(len(trace["tool_calls"]), 1)
        self.assertEqual(trace["tool_calls"][0]["status"], "error")
        self.assertIsNone(trace["tool_calls"][0]["response"])

    def test_max_tool_calls_circuit_breaker(self) -> None:
        task = self.registry.by_id("G-003")
        summary = run_suite(
            [task],
            MockAdapter(self.store),
            RunConfig(max_tool_calls=1, max_budget_units=8.0),
            self.trace_path,
        )
        self.assertEqual(summary.failed, 1)
        trace = load_traces(self.trace_path)[0]
        self.assertEqual(trace["error"]["code"], "MAX_TOOL_CALLS_EXCEEDED")
        self.assertEqual(len(trace["tool_calls"]), 1)
        self.assertEqual(trace["budget"]["tool_calls_used"], 1)
        self.assertIn("geocode", trace["steps"])
        self.assertNotIn("reverse", trace["steps"])

    def test_budget_units_circuit_breaker(self) -> None:
        summary = run_suite(
            [self.registry.by_id("G-001")],
            MockAdapter(self.store),
            RunConfig(max_tool_calls=8, max_budget_units=0.5, call_cost_units=1.0),
            self.trace_path,
        )
        self.assertEqual(summary.failed, 1)
        trace = load_traces(self.trace_path)[0]
        self.assertEqual(trace["error"]["code"], "BUDGET_UNITS_EXCEEDED")
        self.assertEqual(trace["tool_calls"], [])
        self.assertEqual(trace["budget"]["budget_units_spent"], 0.0)

    def test_mock_runs_without_an_api_key(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GEOAPIFY_API_KEY", None)
            summary = run_suite(
                [self.registry.by_id("G-001")],
                MockAdapter(self.store),
                RunConfig(),
                self.trace_path,
            )
        self.assertTrue(summary.ok)
        trace = load_traces(self.trace_path)[0]
        self.assertFalse(trace["source"]["credential_used"])

    def test_oracle_mismatch_is_a_complete_failure_record(self) -> None:
        class WrongPlaceAdapter:
            source_path = "in-memory-wrong-fixture"

            def invoke(self, task_id, step, arguments):
                del task_id, step, arguments
                return MockInvocation(
                    result={
                        "synthetic": True,
                        "result_count": 1,
                        "results": [
                            {
                                "place_id": "wrong_place",
                                "location": {"lat": 0.01, "lon": 0.02},
                            }
                        ],
                    },
                    fixture_ref="wrong.G-001.geocode",
                    source_path=self.source_path,
                )

        task = self.registry.by_id("G-001")
        summary = run_suite([task], WrongPlaceAdapter(), RunConfig(), self.trace_path)
        self.assertEqual(summary.failed, 1)
        trace = load_traces(self.trace_path)[0]
        self.assertEqual(trace["status"], "fail")
        self.assertEqual(trace["error"]["code"], "ORACLE_MISMATCH")
        self.assertIn("top_place_id", trace["error_reason"])
        self.assertEqual(len(trace["checks"]), 4)
        self.assertTrue(any(check["id"] == "top_place_id" and not check["passed"] for check in trace["checks"]))

    def test_independent_evaluation_does_not_trust_recorded_status(self) -> None:
        task = self.registry.by_id("G-001")
        run_suite([task], MockAdapter(self.store), RunConfig(), self.trace_path)
        trace = copy.deepcopy(load_traces(self.trace_path)[0])
        self.assertTrue(trace["passed"])
        trace["steps"]["geocode"]["results"][0]["place_id"] = "tampered"
        evaluation = evaluate_trace(task, trace)
        self.assertFalse(evaluation.passed)
        self.assertTrue(any(check["id"] == "top_place_id" for check in evaluation.failed_checks))


if __name__ == "__main__":
    unittest.main()
