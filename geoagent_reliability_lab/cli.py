"""Command-line interface for the offline GeoAgent Reliability Lab runner."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import VALIDATOR_VERSION, __version__
from .argument_contract import build_argument_contract, check_argument_contract
from .errors import EvaluationError, FixtureError, RegistryError, TraceFormatError
from .evaluator import evaluate_trace
from .fixtures import FixtureStore
from .mock_adapter import MockAdapter
from .registry import Registry, load_registry
from .runner import RunConfig, load_traces, run_suite
from .trace_integrity import check_trace_file_integrity, check_trace_integrity


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _data_path(relative: str) -> Path:
    for base in (Path.cwd(), _project_root()):
        candidate = base / relative
        if candidate.exists():
            return candidate
    return _project_root() / relative


def _default_registry() -> Path:
    return _data_path("tasks/tasks.json")


def _default_fixtures() -> Path:
    return _data_path("fixtures/mock_responses.json")


def _print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _print_validation(registry: Registry, store: FixtureStore) -> int:
    fixture_errors = store.validate_for_tasks(registry)
    steps = sum(len(task["reference_tool_chain"]) for task in registry.tasks)
    if fixture_errors:
        for error in fixture_errors:
            print(f"FIXTURE ERROR: {error}", file=sys.stderr)
        return 1

    print(f"OK registry: {len(registry.tasks)} tasks")
    print("categories: " + ", ".join(f"{key}={value}" for key, value in _category_counts(registry).items()))
    print("families: " + ", ".join(f"{key}={value}" for key, value in _family_counts(registry).items()))
    print(f"fixture coverage: {steps}/{steps} task steps, path={store.path}")
    try:
        contract = build_argument_contract(registry.tasks, store)
    except FixtureError as exc:
        print(f"ARGUMENT CONTRACT ERROR: {exc}", file=sys.stderr)
        return 1
    contract_steps = sum(len(step_arguments) for step_arguments in contract.values())
    print(f"argument contract: {contract_steps}/{steps} task steps derivable")
    print("mode: synthetic_mock; no API key read; no network request made")
    return 0


def _category_counts(registry: Registry) -> dict[str, int]:
    counts = {"G": 0, "P": 0, "R": 0, "S": 0, "M": 0}
    for task in registry.tasks:
        counts[str(task["category"])] += 1
    return counts


def _family_counts(registry: Registry) -> dict[str, int]:
    counts: dict[str, int] = {}
    for task in registry.tasks:
        family = str(task["capability_family"])
        counts[family] = counts.get(family, 0) + 1
    return counts


def _cmd_list(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry)
    tasks = list(registry.tasks)
    if args.category:
        category = args.category.upper()
        if category not in {"G", "P", "R", "S", "M"}:
            print(f"ERROR: unknown category {args.category!r}", file=sys.stderr)
            return 2
        tasks = [task for task in tasks if task["category"] == category]

    if args.json:
        _print_json(
            [
                {
                    "id": task["id"],
                    "category": task["category"],
                    "subcategory": task["subcategory"],
                    "capability_family": task["capability_family"],
                    "title": task["title"],
                }
                for task in tasks
            ]
        )
        return 0

    if not tasks:
        print("No matching tasks.", file=sys.stderr)
        return 1
    print(f"{'ID':<7} {'CAT':<4} {'FAMILY':<24} {'SUBCATEGORY':<28} TITLE")
    for task in tasks:
        print(
            f"{task['id']:<7} {task['category']:<4} "
            f"{task['capability_family']:<24} {task['subcategory']:<28} {task['title']}"
        )
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry)
    store = FixtureStore.load(args.fixtures)
    return _print_validation(registry, store)


def _selected_tasks(registry: Registry, task_ids: list[str] | None) -> tuple:
    return registry.select(task_ids)


def _trace_path(value: str | None) -> Path:
    if value:
        return Path(value)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path.cwd() / "artifacts" / "traces" / f"mock-{stamp}.jsonl"


def _cmd_mock_run(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry)
    store = FixtureStore.load(args.fixtures)
    fixture_errors = store.validate_for_tasks(registry)
    if fixture_errors:
        for error in fixture_errors:
            print(f"FIXTURE ERROR: {error}", file=sys.stderr)
        return 2

    tasks = _selected_tasks(registry, args.task)
    config = RunConfig(
        max_tool_calls=args.max_tool_calls,
        max_budget_units=args.max_budget_units,
        call_cost_units=args.call_cost_units,
    )
    try:
        contract = build_argument_contract(registry.tasks, store)
    except FixtureError as exc:
        print(f"ARGUMENT CONTRACT ERROR: {exc}", file=sys.stderr)
        return 2
    failure_mode = None if args.inject_failure == "none" else args.inject_failure
    adapter = MockAdapter(
        fixtures=store,
        failure_mode=failure_mode,
        failure_task=args.inject_failure_task,
        argument_contract=contract,
    )
    trace_path = _trace_path(args.trace_out)
    summary = run_suite(tasks, adapter, config, trace_path, fail_fast=args.fail_fast)

    print("mode=synthetic_mock")
    print(f"source={registry.meta.get('source_label', 'synthetic/illustrative')}")
    print(f"trace={summary.path}")
    print(f"tasks={summary.total} passed={summary.passed} failed={summary.failed}")
    if failure_mode:
        print(f"fault_injection={failure_mode} task={args.inject_failure_task or 'all'}")
    for trace in summary.traces:
        if not trace["passed"]:
            code = trace["error"]["code"] if trace["error"] else "UNKNOWN"
            print(f"FAIL {trace['task_id']} [{code}] {trace['error_reason']}", file=sys.stderr)
    return 0 if summary.ok else 1


def _issue_payload(issues: Sequence[Any]) -> list[dict[str, Any]]:
    return [
        {"code": issue.code, "level": issue.level, "location": issue.location, "message": issue.message}
        for issue in issues
    ]


def _cmd_evaluate(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry)
    store = FixtureStore.load(args.fixtures)
    records = load_traces(args.trace)
    if not records:
        print(f"ERROR: trace file contains no records: {args.trace}", file=sys.stderr)
        return 2

    results: list[dict[str, Any]] = []
    for record in records:
        record_task_id = record.get("task_id")
        entry: dict[str, Any] = {
            "task_id": record_task_id,
            "passed": False,
            "oracle_passed": False,
            "integrity_ok": False,
            "contract_ok": False,
            "failed_checks": [],
            "integrity_issues": [],
            "contract_issues": [],
        }
        task: Mapping[str, Any] | None = None
        if not isinstance(record_task_id, str):
            entry["error"] = "trace has no task_id"
        else:
            try:
                task = registry.by_id(record_task_id)
            except KeyError:
                entry["error"] = "unknown task id"

        if task is not None:
            try:
                evaluation = evaluate_trace(task, record)
                entry["oracle_passed"] = evaluation.passed
                entry["failed_checks"] = [
                    {"id": check["id"], "detail": check["detail"]} for check in evaluation.failed_checks
                ]
            except EvaluationError as exc:
                entry["oracle_error"] = str(exc)

            integrity = check_trace_integrity(task, record)
            entry["integrity_ok"] = integrity.ok
            entry["integrity_issues"] = _issue_payload(integrity.issues)

            contract = check_argument_contract(task, record, store)
            entry["contract_ok"] = contract.ok
            entry["contract_issues"] = _issue_payload(contract.issues)

            entry["passed"] = bool(entry["oracle_passed"] and entry["integrity_ok"] and entry["contract_ok"])
        results.append(entry)

    file_issues = check_trace_file_integrity(records)
    file_rejected = any(issue.level == "reject" for issue in file_issues)
    passed = sum(1 for result in results if result["passed"])
    failed = len(results) - passed
    integrity_ok = sum(1 for result in results if result["integrity_ok"])
    contract_ok = sum(1 for result in results if result["contract_ok"])
    payload = {
        "trace": str(args.trace),
        "validator_version": VALIDATOR_VERSION,
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "integrity_ok": integrity_ok,
        "integrity_rejected": len(results) - integrity_ok,
        "contract_ok": contract_ok,
        "contract_rejected": len(results) - contract_ok,
        "file_issues": _issue_payload(file_issues),
        "records": results,
    }
    if args.json:
        _print_json(payload)
    else:
        print(f"Re-evaluated {len(results)} trace records: {passed} passed, {failed} failed")
        print(
            f"integrity: {integrity_ok} ok / {len(results) - integrity_ok} rejected; "
            f"contract: {contract_ok} ok / {len(results) - contract_ok} rejected"
        )
        for issue in file_issues:
            print(
                f"TRACE FILE {issue.level.upper()} [{issue.code}] {issue.location}: {issue.message}",
                file=sys.stderr,
            )
        for result in results:
            if not result["passed"]:
                print(f"FAIL {result['task_id']}: {result}", file=sys.stderr)
    return 0 if failed == 0 and not file_rejected else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="geoagent-lab",
        description="Offline synthetic mock runner for geospatial agent tool chains.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List registry tasks.")
    list_parser.add_argument("--registry", default=str(_default_registry()), help="Path to tasks JSON.")
    list_parser.add_argument("--category", choices=list("GPRSM"), help="Filter by category.")
    list_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    list_parser.set_defaults(func=_cmd_list)

    validate_parser = subparsers.add_parser("validate", help="Validate registry and fixture coverage.")
    validate_parser.add_argument("--registry", default=str(_default_registry()), help="Path to tasks JSON.")
    validate_parser.add_argument("--fixtures", default=str(_default_fixtures()), help="Path to mock fixtures JSON.")
    validate_parser.set_defaults(func=_cmd_validate)

    mock_parser = subparsers.add_parser("mock", help="Run or replay the synthetic mock adapter.")
    mock_subparsers = mock_parser.add_subparsers(dest="mock_command", required=True)
    run_parser = mock_subparsers.add_parser("run", help="Run selected tasks and write JSONL traces.")
    run_parser.add_argument("--registry", default=str(_default_registry()), help="Path to tasks JSON.")
    run_parser.add_argument("--fixtures", default=str(_default_fixtures()), help="Path to mock fixtures JSON.")
    run_parser.add_argument(
        "--task",
        action="append",
        metavar="TASK_ID",
        help="Task ID to run; repeat for multiple tasks. Defaults to all 18.",
    )
    run_parser.add_argument("--trace-out", help="JSONL trace destination. Defaults to artifacts/traces/mock-<UTC>.jsonl.")
    run_parser.add_argument("--max-tool-calls", type=int, default=8, help="Maximum tool calls per task (default 8).")
    run_parser.add_argument("--max-budget-units", type=float, default=8.0, help="Maximum budget units per task (default 8.0).")
    run_parser.add_argument("--call-cost-units", type=float, default=1.0, help="Budget units charged per call (default 1.0).")
    run_parser.add_argument(
        "--inject-failure",
        choices=["none", "tool_error"],
        default="none",
        help="Explicit synthetic fault injection, for failure-path evidence.",
    )
    run_parser.add_argument("--inject-failure-task", metavar="TASK_ID", help="Limit injected failure to one task.")
    run_parser.add_argument("--fail-fast", action="store_true", help="Stop after the first failed task.")
    run_parser.set_defaults(func=_cmd_mock_run)

    evaluate_parser = subparsers.add_parser("evaluate", help="Independently re-evaluate a JSONL trace.")
    evaluate_parser.add_argument("--trace", required=True, help="JSONL trace file to re-evaluate.")
    evaluate_parser.add_argument("--registry", default=str(_default_registry()), help="Path to tasks JSON.")
    evaluate_parser.add_argument("--fixtures", default=str(_default_fixtures()), help="Path to mock fixtures JSON.")
    evaluate_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    evaluate_parser.set_defaults(func=_cmd_evaluate)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except RegistryError as exc:
        print(f"REGISTRY ERROR: {exc}", file=sys.stderr)
        return 2
    except FixtureError as exc:
        print(f"FIXTURE ERROR: {exc}", file=sys.stderr)
        return 2
    except TraceFormatError as exc:
        print(f"TRACE ERROR: {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
