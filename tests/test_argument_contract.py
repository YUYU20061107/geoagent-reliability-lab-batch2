"""Negative and positive tests for the mock tool-argument contract.

The contract proves that a mock invocation consumed the arguments it was given:
wrong, swapped, missing, mistyped or out-of-range arguments must fail instead of
silently returning a frozen fixture. Tests tamper in memory only.
"""

from __future__ import annotations

import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from geoagent_reliability_lab.argument_contract import (
    build_argument_contract,
    check_argument_contract,
    find_coordinate_violation,
)
from geoagent_reliability_lab.cli import main
from geoagent_reliability_lab.errors import ArgumentContractError, FixtureError
from geoagent_reliability_lab.evaluator import evaluate_trace
from geoagent_reliability_lab.fixtures import FixtureStore
from geoagent_reliability_lab.mock_adapter import MockAdapter
from geoagent_reliability_lab.registry import load_registry
from geoagent_reliability_lab.runner import RunConfig, run_suite, run_task

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "tasks" / "tasks.json"
FIXTURE_PATH = ROOT / "fixtures" / "mock_responses.json"

REVERSE_STEP_INDEX = 1  # G-003: 0=geocode.forward, 1=geocode.reverse


class ArgumentContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = load_registry(REGISTRY_PATH)
        cls.store = FixtureStore.load(FIXTURE_PATH)
        cls.contract = build_argument_contract(cls.registry.tasks, cls.store)

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.dir = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    # ---- helpers -------------------------------------------------------

    def reverse_step(self) -> dict:
        return copy.deepcopy(self.registry.by_id("G-003")["reference_tool_chain"][REVERSE_STEP_INDEX])

    def contract_adapter(self) -> MockAdapter:
        return MockAdapter(self.store, argument_contract=self.contract)

    def pass_trace(self, task_id: str = "G-001") -> dict:
        trace = run_task(self.registry.by_id(task_id), MockAdapter(self.store), RunConfig())
        return json.loads(json.dumps(trace, ensure_ascii=False))  # disk representation

    def invoke_cli(self, argv: list[str]) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    # ---- positive coverage ---------------------------------------------

    def test_contract_covers_exactly_all_task_steps(self) -> None:
        """T23: every declared step has a derivable contract; 25/25."""
        total = sum(len(task["reference_tool_chain"]) for task in self.registry.tasks)
        covered = sum(len(steps) for steps in self.contract.values())
        self.assertEqual(total, 25)
        self.assertEqual(covered, 25)
        for task in self.registry.tasks:
            expected_ids = [step["step_id"] for step in task["reference_tool_chain"]]
            self.assertEqual(sorted(self.contract[task["id"]]), sorted(expected_ids))

    def test_mock_run_with_contract_passes_all_18_tasks(self) -> None:
        """T24 (API): enabling the contract must not create false positives."""
        summary = run_suite(
            self.registry.tasks,
            self.contract_adapter(),
            RunConfig(),
            self.dir / "contracted18.jsonl",
        )
        self.assertEqual(summary.passed, 18)
        self.assertEqual(summary.failed, 0)

    def test_posthoc_contract_accepts_real_runner_traces(self) -> None:
        """Positive regression: real traces satisfy the post-hoc contract."""
        summary = run_suite(
            self.registry.tasks,
            self.contract_adapter(),
            RunConfig(),
            self.dir / "contracted18.jsonl",
        )
        for task, trace in zip(self.registry.tasks, summary.traces, strict=True):
            report = check_argument_contract(task, trace, self.store)
            self.assertTrue(report.ok, f"{task['id']}: {report.issues}")

    def test_legacy_adapter_without_contract_keeps_old_behaviour(self) -> None:
        """Compatibility: library callers may opt out of the contract."""
        legacy = MockAdapter(self.store)
        invocation = legacy.invoke("G-003", self.reverse_step(), {"lat": 99.0, "lon": 99.0})
        self.assertIn("results", invocation.result)

    # ---- runtime rejection ---------------------------------------------

    def test_mock_adapter_rejects_swapped_reverse_coordinates(self) -> None:
        """T15: swapping lat/lon must not silently replay the fixture."""
        adapter = self.contract_adapter()
        with self.assertRaises(ArgumentContractError) as caught:
            adapter.invoke("G-003", self.reverse_step(), {"lat": 0.015, "lon": 0.005})
        self.assertEqual(caught.exception.code, "MOCK_ARGUMENT_CONTRACT_MISMATCH")

    def test_contract_rejects_out_of_range_coordinates(self) -> None:
        """T17: lat/lon range invariants are independent of the golden values."""
        adapter = self.contract_adapter()
        for arguments in (
            {"lat": 99.0, "lon": 0.015},
            {"lat": -91.0, "lon": 0.015},
            {"lat": 0.005, "lon": 181.0},
            {"lat": float("nan"), "lon": 0.015},
        ):
            with self.subTest(arguments=arguments):
                with self.assertRaises(ArgumentContractError) as caught:
                    adapter.invoke("G-003", self.reverse_step(), arguments)
                self.assertEqual(caught.exception.code, "MOCK_ARGUMENT_COORDINATE_RANGE")

    def test_contract_rejects_missing_extra_and_wrong_type_arguments(self) -> None:
        """T18: key set, types and numeric semantics are enforced."""
        adapter = self.contract_adapter()
        cases = {
            "missing": {"lat": 0.005},
            "extra": {"lat": 0.005, "lon": 0.015, "radius": 10},
            "string number": {"lat": "0.005", "lon": 0.015},
            "bool as number": {"lat": True, "lon": 0.015},
        }
        for label, arguments in cases.items():
            with self.subTest(label):
                with self.assertRaises(ArgumentContractError) as caught:
                    adapter.invoke("G-003", self.reverse_step(), arguments)
                self.assertEqual(caught.exception.code, "MOCK_ARGUMENT_CONTRACT_MISMATCH")

    def test_contract_rejects_wrong_coordinates_end_to_end(self) -> None:
        """T16: P0-2's exact repro must now fail end to end inside the runner."""
        cloned = copy.deepcopy(dict(self.registry.by_id("G-003")))
        cloned["reference_tool_chain"][REVERSE_STEP_INDEX]["arguments"] = {"lat": 0.015, "lon": 0.005}

        # Legacy adapter still passes, documenting the pre-G0.1 behaviour.
        legacy_trace = run_task(cloned, MockAdapter(self.store), RunConfig())
        self.assertTrue(legacy_trace["passed"])

        trace = run_task(cloned, self.contract_adapter(), RunConfig())
        self.assertEqual(trace["status"], "fail")
        self.assertEqual(trace["error"]["code"], "MOCK_ARGUMENT_CONTRACT_MISMATCH")
        self.assertEqual(trace["tool_calls"][-1]["status"], "error")
        self.assertNotIn("reverse", trace["steps"])

    def test_contract_rejects_cross_step_wrong_reference(self) -> None:
        """T19: wrong cross-step values fail the contract; bad paths fail resolution."""
        cloned = copy.deepcopy(dict(self.registry.by_id("G-003")))
        cloned["reference_tool_chain"][REVERSE_STEP_INDEX]["arguments"] = {
            "lat": "$.steps.geocode.results[0].place_id",
            "lon": "$.steps.geocode.results[0].location.lon",
        }
        trace = run_task(cloned, self.contract_adapter(), RunConfig())
        self.assertEqual(trace["error"]["code"], "MOCK_ARGUMENT_CONTRACT_MISMATCH")

        out_of_range = copy.deepcopy(dict(self.registry.by_id("G-003")))
        out_of_range["reference_tool_chain"][REVERSE_STEP_INDEX]["arguments"] = {
            "lat": "$.steps.geocode.results[5].location.lat",
            "lon": "$.steps.geocode.results[0].location.lon",
        }
        trace = run_task(out_of_range, self.contract_adapter(), RunConfig())
        self.assertEqual(trace["error"]["code"], "ARGUMENT_REFERENCE_ERROR")
        self.assertNotIn("reverse", trace["steps"])

    def test_contract_build_fails_when_a_fixture_is_missing(self) -> None:
        """T20: a contract cannot be derived from an incomplete fixture store."""
        partial = FixtureStore(
            path=self.store.path,
            meta=self.store.meta,
            responses={key: value for key, value in self.store.responses.items() if key != "G-001"},
        )
        with self.assertRaises(FixtureError):
            build_argument_contract(self.registry.tasks, partial)

    # ---- post-hoc rejection --------------------------------------------

    def test_posthoc_contract_rejects_tampered_arguments(self) -> None:
        """T21: a trace whose call args were edited must be rejected even if oracle passes."""
        task = dict(self.registry.by_id("G-001"))
        trace = copy.deepcopy(self.pass_trace())
        trace["tool_calls"][0]["arguments"]["query"] = "Unrelated Place"
        report = check_argument_contract(task, trace, self.store)
        self.assertFalse(report.ok)
        self.assertIn("TRACE_ARGUMENTS_CONTRACT_MISMATCH", {issue.code for issue in report.rejects})
        self.assertTrue(evaluate_trace(task, trace).passed)

    def test_posthoc_provenance_rejects_inconsistent_steps(self) -> None:
        """T22: a cross-step argument must match the steps it was resolved from."""
        task = dict(self.registry.by_id("G-003"))
        trace = copy.deepcopy(self.pass_trace("G-003"))
        trace["steps"]["geocode"]["results"][0]["location"]["lat"] = 0.99
        report = check_argument_contract(task, trace, self.store)
        self.assertFalse(report.ok)
        self.assertIn("TRACE_ARGUMENT_PROVENANCE_MISMATCH", {issue.code for issue in report.rejects})
        self.assertTrue(evaluate_trace(task, trace).passed)

    # ---- CLI integration ------------------------------------------------

    def test_cli_mock_run_and_evaluate_with_contract(self) -> None:
        """T24 (CLI): contracted mock run passes, evaluate reports the three verdicts."""
        trace_path = self.dir / "cli18.jsonl"
        code, output, error = self.invoke_cli(
            [
                "mock",
                "run",
                "--registry",
                str(REGISTRY_PATH),
                "--fixtures",
                str(FIXTURE_PATH),
                "--trace-out",
                str(trace_path),
            ]
        )
        self.assertEqual(code, 0, error)
        self.assertIn("tasks=18 passed=18 failed=0", output)

        code, output, error = self.invoke_cli(
            [
                "evaluate",
                "--trace",
                str(trace_path),
                "--registry",
                str(REGISTRY_PATH),
                "--fixtures",
                str(FIXTURE_PATH),
                "--json",
            ]
        )
        self.assertEqual(code, 0, error)
        payload = json.loads(output)
        self.assertEqual(payload["passed"], 18)
        for record in payload["records"]:
            self.assertTrue(record["oracle_passed"], record)
            self.assertTrue(record["integrity_ok"], record)
            self.assertTrue(record["contract_ok"], record)


if __name__ == "__main__":
    unittest.main()
