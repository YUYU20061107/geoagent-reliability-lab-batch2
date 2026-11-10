"""CLI acceptance tests: 18 tasks, duplicate rejection, mock pass and fail."""

from __future__ import annotations

import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from geoagent_reliability_lab.cli import main

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "tasks" / "tasks.json"
FIXTURE_PATH = ROOT / "fixtures" / "mock_responses.json"


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.dir = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def invoke(self, argv: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                code = main(argv)
            except SystemExit as exc:
                code = int(exc.code) if isinstance(exc.code, int) else 2
        return code, stdout.getvalue(), stderr.getvalue()

    def test_validate_reports_exact_registry_and_fixture_coverage(self) -> None:
        code, output, error = self.invoke(
            [
                "validate",
                "--registry",
                str(REGISTRY_PATH),
                "--fixtures",
                str(FIXTURE_PATH),
            ]
        )
        self.assertEqual(code, 0, error)
        self.assertIn("OK registry: 18 tasks", output)
        self.assertIn("fixture coverage: 25/25", output)
        self.assertIn("mode: synthetic_mock", output)

    def test_mock_run_multiple_tasks_and_independent_evaluate(self) -> None:
        trace_path = self.dir / "two-tasks.jsonl"
        code, output, error = self.invoke(
            [
                "mock",
                "run",
                "--registry",
                str(REGISTRY_PATH),
                "--fixtures",
                str(FIXTURE_PATH),
                "--task",
                "G-001",
                "--task",
                "R-002",
                "--trace-out",
                str(trace_path),
            ]
        )
        self.assertEqual(code, 0, error)
        self.assertIn("tasks=2 passed=2 failed=0", output)
        lines = trace_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(all(json.loads(line)["passed"] for line in lines))

        code, output, error = self.invoke(
            [
                "evaluate",
                "--trace",
                str(trace_path),
                "--registry",
                str(REGISTRY_PATH),
            ]
        )
        self.assertEqual(code, 0, error)
        self.assertIn("2 passed, 0 failed", output)

    def test_injected_tool_error_returns_nonzero_and_is_logged(self) -> None:
        trace_path = self.dir / "failure.jsonl"
        code, output, error = self.invoke(
            [
                "mock",
                "run",
                "--registry",
                str(REGISTRY_PATH),
                "--fixtures",
                str(FIXTURE_PATH),
                "--task",
                "G-003",
                "--inject-failure",
                "tool_error",
                "--inject-failure-task",
                "G-003",
                "--trace-out",
                str(trace_path),
            ]
        )
        self.assertEqual(code, 1)
        self.assertIn("failed=1", output)
        self.assertIn("INJECTED_TOOL_ERROR", error)
        trace = json.loads(trace_path.read_text(encoding="utf-8").strip())
        self.assertEqual(trace["status"], "fail")
        self.assertEqual(trace["error"]["code"], "INJECTED_TOOL_ERROR")

    def test_duplicate_task_id_registry_is_rejected(self) -> None:
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        data["tasks"].append(copy.deepcopy(data["tasks"][0]))
        duplicate_path = self.dir / "duplicate-tasks.json"
        duplicate_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        code, output, error = self.invoke(
            [
                "validate",
                "--registry",
                str(duplicate_path),
                "--fixtures",
                str(FIXTURE_PATH),
            ]
        )
        self.assertEqual(code, 2)
        self.assertIn("duplicate task id", error)
        self.assertNotIn("OK registry", output)

    def test_list_json_contains_all_18_tasks(self) -> None:
        code, output, error = self.invoke(
            ["list", "--registry", str(REGISTRY_PATH), "--json"]
        )
        self.assertEqual(code, 0, error)
        tasks = json.loads(output)
        self.assertEqual(len(tasks), 18)
        self.assertEqual({task["category"] for task in tasks}, {"G", "P", "R", "S", "M"})


if __name__ == "__main__":
    unittest.main()
