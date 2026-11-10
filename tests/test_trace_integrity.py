"""Negative and positive tests for the independent trace-integrity checker.

These tests tamper with traces in memory or in temp files only. They never
modify repository fixtures, tasks, or recorded evidence.

The point of this suite is that a *result* evaluation can still pass after a
trace's provenance was tampered with; the integrity checker must catch exactly
that class of evidence forgery.
"""

from __future__ import annotations

import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from geoagent_reliability_lab.cli import main
from geoagent_reliability_lab.evaluator import evaluate_trace
from geoagent_reliability_lab.fixtures import FixtureStore
from geoagent_reliability_lab.mock_adapter import MockAdapter
from geoagent_reliability_lab.registry import load_registry
from geoagent_reliability_lab.runner import RunConfig, run_suite, run_task
from geoagent_reliability_lab.trace_integrity import (
    check_trace_file_integrity,
    check_trace_integrity,
)

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "tasks" / "tasks.json"
FIXTURE_PATH = ROOT / "fixtures" / "mock_responses.json"


def _reject_codes(report) -> set[str]:
    return {issue.code for issue in report.rejects}


class TraceIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = load_registry(REGISTRY_PATH)
        cls.store = FixtureStore.load(FIXTURE_PATH)

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.dir = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    # ---- helpers -------------------------------------------------------

    @staticmethod
    def persisted(trace: dict) -> dict:
        """Round-trip through JSON: this is the representation a trace has on disk.

        ``run_task`` builds traces in memory where ``steps`` and
        ``tool_calls[*].response`` may share objects; stored evidence never does.
        """
        return json.loads(json.dumps(trace, ensure_ascii=False))

    def pass_trace(self, task_id: str = "G-001") -> dict:
        return self.persisted(run_task(self.registry.by_id(task_id), MockAdapter(self.store), RunConfig()))

    def injected_trace(self) -> dict:
        adapter = MockAdapter(self.store, failure_mode="tool_error", failure_task="G-003")
        return self.persisted(run_task(self.registry.by_id("G-003"), adapter, RunConfig()))

    def budget_trace(self) -> dict:
        adapter = MockAdapter(self.store)
        return self.persisted(run_task(self.registry.by_id("G-003"), adapter, RunConfig(max_tool_calls=1)))

    def task(self, task_id: str = "G-001") -> dict:
        return dict(self.registry.by_id(task_id))

    def invoke_cli(self, argv: list[str]) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    # ---- positive regression: real runner output must never be rejected

    def test_integrity_accepts_all_real_runner_traces(self) -> None:
        """T13: every genuine trace passes; task failure is not evidence failure."""
        summary = run_suite(self.registry.tasks, MockAdapter(self.store), RunConfig(), self.dir / "all18.jsonl")
        self.assertEqual(summary.passed, 18)
        for task, trace in zip(self.registry.tasks, summary.traces, strict=True):
            report = check_trace_integrity(task, trace)
            self.assertTrue(report.ok, f"{task['id']}: {report.issues}")
            self.assertEqual(report.rejects, ())

        failure_traces = [self.injected_trace(), self.budget_trace()]
        for task, trace in zip(
            [self.registry.by_id("G-003"), self.registry.by_id("G-003")],
            failure_traces,
            strict=True,
        ):
            report = check_trace_integrity(task, trace)
            self.assertTrue(report.ok, f"failure trace rejected: {report.issues}")
            self.assertEqual(report.rejects, ())

    # ---- A-1 / A-2: identity, mode and provenance -----------------------

    def test_integrity_rejects_cleared_tool_calls(self) -> None:
        """T1: P0-1's exact tamper (metadata stripped, steps kept) must be rejected."""
        task = self.task()
        trace = copy.deepcopy(self.pass_trace())
        trace["tool_calls"] = []
        report = check_trace_integrity(task, trace)
        self.assertFalse(report.ok)
        self.assertIn("TRACE_STEPS_WITHOUT_CALLS", _reject_codes(report))
        self.assertIn("TRACE_BUDGET_CALL_COUNT_MISMATCH", _reject_codes(report))
        # Independence: the pure result re-scorer still passes, which is why the
        # separate integrity layer is required.
        self.assertTrue(evaluate_trace(task, trace).passed)

    def test_integrity_rejects_live_mode_and_network_source(self) -> None:
        """T2: a mock trace claiming live mode or network use is not admissible."""
        task = self.task()
        trace = copy.deepcopy(self.pass_trace())
        trace["mode"] = "live"
        trace["source"]["network"] = True
        trace["source"]["adapter"] = "LiveAdapter"
        report = check_trace_integrity(task, trace)
        codes = _reject_codes(report)
        self.assertIn("TRACE_MODE_UNKNOWN", codes)
        self.assertIn("TRACE_SOURCE_INCONSISTENT", codes)

    def test_integrity_rejects_identity_metadata_and_param_drift(self) -> None:
        """T8: trace id, timestamps, versions and echoed params must be consistent."""
        task = self.task()
        trace = copy.deepcopy(self.pass_trace())
        trace["trace_id"] = "tampered"
        trace["finished_at"] = "2000-01-01T00:00:00.000Z"
        trace["timestamp"] = "2001-01-01T00:00:00.000Z"
        trace["trace_schema_version"] = "9.9.9"
        trace["params"]["query"] = "Other place"
        trace["category"] = "X"
        codes = _reject_codes(check_trace_integrity(task, trace))
        for code in (
            "TRACE_ID_INVALID",
            "TRACE_TIMESTAMP_ORDER",
            "TRACE_TIMESTAMP_INCONSISTENT",
            "TRACE_SCHEMA_VERSION_UNSUPPORTED",
            "TRACE_PARAMS_MISMATCH",
            "TRACE_TASK_METADATA_MISMATCH",
        ):
            self.assertIn(code, codes)

    # ---- A-3: status / error coherence ----------------------------------

    def test_integrity_rejects_inconsistent_status_and_error(self) -> None:
        """T3: passed/status/error must agree with each other."""
        task = self.task()
        cases: list[tuple[str, dict, str]] = []

        trace = copy.deepcopy(self.pass_trace())
        trace["status"] = "fail"  # passed stays True
        cases.append(("status/passed", trace, "TRACE_STATUS_TAMPERED"))

        trace = copy.deepcopy(self.pass_trace())
        trace["error"] = {"code": "BAD", "kind": "tool", "message": "x", "step_id": None}
        trace["error_reason"] = "x"
        cases.append(("pass with error", trace, "TRACE_PASS_WITH_ERROR"))

        trace = copy.deepcopy(self.pass_trace())
        trace["status"], trace["passed"], trace["error"] = "fail", False, None
        cases.append(("fail without error", trace, "TRACE_FAIL_WITHOUT_ERROR"))

        for label, trace, code in cases:
            with self.subTest(label):
                self.assertIn(code, _reject_codes(check_trace_integrity(task, trace)))

    def test_integrity_rejects_pass_with_failed_recorded_check(self) -> None:
        """T4: a passing record cannot contain a failed recorded criterion."""
        task = self.task()
        trace = copy.deepcopy(self.pass_trace())
        trace["checks"][0]["passed"] = False
        self.assertIn("TRACE_PASS_WITH_FAILED_CHECK", _reject_codes(check_trace_integrity(task, trace)))

    def test_integrity_rejects_oracle_error_without_failed_checks(self) -> None:
        """T11: an ORACLE_MISMATCH must name the criteria that actually failed."""
        task = self.task()
        trace = copy.deepcopy(self.pass_trace())
        trace["status"], trace["passed"] = "fail", False
        trace["error"] = {
            "code": "ORACLE_MISMATCH",
            "kind": "evaluation",
            "message": "forged",
            "step_id": None,
            "failed_check_ids": [],
        }
        trace["error_reason"] = "forged"
        self.assertIn("TRACE_ORACLE_ERROR_INCONSISTENT", _reject_codes(check_trace_integrity(task, trace)))

    # ---- A-5: tool_calls <-> steps one-to-one ---------------------------

    def test_integrity_rejects_call_response_drift(self) -> None:
        """T5: recorded call responses and the steps used by the oracle must match."""
        task = self.task()
        trace = copy.deepcopy(self.pass_trace())
        trace["tool_calls"][0]["response"]["results"][0]["place_id"] = "drifted"
        report = check_trace_integrity(task, trace)
        self.assertIn("TRACE_MISSING_STEP_FOR_CALL", _reject_codes(report))
        self.assertTrue(evaluate_trace(task, trace).passed)

    def test_integrity_rejects_orphan_or_missing_steps(self) -> None:
        """T6: no step without a successful call, no successful call without a step."""
        task = self.task()

        trace = copy.deepcopy(self.pass_trace())
        trace["steps"]["ghost"] = {"synthetic": True}
        self.assertIn("TRACE_STEPS_WITHOUT_CALLS", _reject_codes(check_trace_integrity(task, trace)))

        trace = copy.deepcopy(self.pass_trace())
        del trace["steps"]["geocode"]
        self.assertIn("TRACE_MISSING_STEP_FOR_CALL", _reject_codes(check_trace_integrity(task, trace)))

    def test_integrity_rejects_foreign_fixture_and_unmarked_result(self) -> None:
        """T9: fixture refs must belong to the task step and results stay synthetic."""
        task = self.task()

        trace = copy.deepcopy(self.pass_trace())
        trace["tool_calls"][0]["fixture_ref"] = "G-002.reverse"
        self.assertIn("TRACE_OK_CALL_INCONSISTENT", _reject_codes(check_trace_integrity(task, trace)))

        trace = copy.deepcopy(self.pass_trace())
        trace["tool_calls"][0]["response"]["synthetic"] = False
        self.assertIn("TRACE_UNMARKED_SYNTHETIC", _reject_codes(check_trace_integrity(task, trace)))

        trace = copy.deepcopy(self.pass_trace())
        trace["source"]["credential_used"] = True
        self.assertIn("TRACE_SOURCE_INCONSISTENT", _reject_codes(check_trace_integrity(task, trace)))

    def test_integrity_rejects_malformed_calls(self) -> None:
        """T12: call shape, index order, sequence and length are all enforced."""
        task = self.task()

        trace = copy.deepcopy(self.pass_trace())
        del trace["tool_calls"][0]["arguments"]
        self.assertIn("TRACE_CALL_SHAPE_INVALID", _reject_codes(check_trace_integrity(task, trace)))

        chain_task = self.task("G-003")
        trace = copy.deepcopy(self.injected_trace())
        trace["tool_calls"][0]["index"] = 2
        self.assertIn("TRACE_CALL_INDEX_INVALID", _reject_codes(check_trace_integrity(chain_task, trace)))

        trace = copy.deepcopy(self.budget_trace())
        trace["tool_calls"][0]["step_id"] = "reverse"
        trace["tool_calls"][0]["tool"] = "geocode.reverse"
        self.assertIn("TRACE_CALL_SEQUENCE_MISMATCH", _reject_codes(check_trace_integrity(chain_task, trace)))

    # ---- A-6: budget arithmetic ------------------------------------------

    def test_integrity_rejects_budget_arithmetic_drift(self) -> None:
        """T7: budget counters must be recomputable from the recorded calls."""
        task = self.task()

        trace = copy.deepcopy(self.pass_trace())
        trace["budget"]["tool_calls_used"] = 0
        self.assertIn("TRACE_BUDGET_CALL_COUNT_MISMATCH", _reject_codes(check_trace_integrity(task, trace)))

        trace = copy.deepcopy(self.pass_trace())
        trace["budget"]["budget_units_spent"] = 5.0
        self.assertIn("TRACE_BUDGET_SPEND_MISMATCH", _reject_codes(check_trace_integrity(task, trace)))

        trace = copy.deepcopy(self.pass_trace())
        trace["budget"]["tool_calls_used"] = 9
        trace["budget"]["max_tool_calls"] = 1
        self.assertIn("TRACE_BUDGET_LIMIT_VIOLATED", _reject_codes(check_trace_integrity(task, trace)))

        chain_task = self.task("G-003")
        trace = copy.deepcopy(self.budget_trace())
        trace["budget"]["max_tool_calls"] = 8
        self.assertIn("TRACE_BUDGET_STOP_UNJUSTIFIED", _reject_codes(check_trace_integrity(chain_task, trace)))

    # ---- A-8: failure-path coherence -------------------------------------

    def test_integrity_rejects_failure_trace_without_error_step(self) -> None:
        """T10: a tool failure must point at the failing recorded call."""
        task = self.task("G-003")

        trace = copy.deepcopy(self.injected_trace())
        trace["tool_calls"] = []
        self.assertIn("TRACE_ERROR_STEP_MISMATCH", _reject_codes(check_trace_integrity(task, trace)))

        trace = copy.deepcopy(self.injected_trace())
        trace["error"]["step_id"] = "reverse"
        self.assertIn("TRACE_ERROR_STEP_MISMATCH", _reject_codes(check_trace_integrity(task, trace)))

    # ---- A-10: file-level evidence accounting ---------------------------

    def test_file_level_integrity_rejects_duplicate_trace_id(self) -> None:
        """T14: duplicated evidence must not be counted twice."""
        trace = self.pass_trace()
        issues = check_trace_file_integrity([trace, copy.deepcopy(trace)])
        self.assertIn("TRACE_ID_DUPLICATE", {issue.code for issue in issues if issue.level == "reject"})

    def test_cli_evaluate_rejects_duplicate_trace_id(self) -> None:
        """T14 (CLI): exit code reflects file-level rejection."""
        trace = self.pass_trace()
        path = self.dir / "duplicate.jsonl"
        path.write_text(
            json.dumps(trace, ensure_ascii=False) + "\n" + json.dumps(trace, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        code, output, error = self.invoke_cli(
            ["evaluate", "--trace", str(path), "--registry", str(REGISTRY_PATH), "--fixtures", str(FIXTURE_PATH)]
        )
        self.assertEqual(code, 1)
        self.assertIn("TRACE_ID_DUPLICATE", output + error)

    def test_cli_evaluate_rejects_tampered_metadata_trace(self) -> None:
        """P0-1 end to end: CLI must not count a forged trace as passed."""
        trace = copy.deepcopy(self.pass_trace())
        trace["mode"] = "live"
        trace["source"]["network"] = True
        path = self.dir / "forged.jsonl"
        path.write_text(json.dumps(trace, ensure_ascii=False) + "\n", encoding="utf-8")
        code, output, error = self.invoke_cli(
            ["evaluate", "--trace", str(path), "--registry", str(REGISTRY_PATH), "--fixtures", str(FIXTURE_PATH)]
        )
        self.assertEqual(code, 1)
        self.assertIn("TRACE_MODE_UNKNOWN", output + error)


if __name__ == "__main__":
    unittest.main()
