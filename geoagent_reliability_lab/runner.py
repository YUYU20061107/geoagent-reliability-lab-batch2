"""Offline mock runner and JSONL evidence writer.

The runner only orchestrates the abstract tool chain, a mock adapter, budgets,
and independent evaluation. It has no HTTP client and no credential handling.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import MODE, VALIDATOR_VERSION
from .errors import (
    BudgetExceeded,
    EvaluationError,
    FixtureError,
    LabError,
    ReferenceResolutionError,
    ToolExecutionError,
    TraceFormatError,
)
from .evaluator import Evaluation, evaluate, resolve_references
from .mock_adapter import MockAdapter


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _duration_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000.0, 3)


def _error_payload(
    code: str,
    kind: str,
    message: str,
    *,
    step_id: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "code": code,
        "kind": kind,
        "message": message,
        "step_id": step_id,
    }
    if extra:
        payload.update(dict(extra))
    return payload


@dataclass(frozen=True)
class RunConfig:
    """Budget hooks; both limits are intentionally testable with the mock."""

    max_tool_calls: int = 8
    max_budget_units: float = 8.0
    call_cost_units: float = 1.0

    def __post_init__(self) -> None:
        if self.max_tool_calls < 1:
            raise ValueError("max_tool_calls must be at least 1")
        if self.max_budget_units <= 0:
            raise ValueError("max_budget_units must be greater than 0")
        if self.call_cost_units <= 0:
            raise ValueError("call_cost_units must be greater than 0")


@dataclass(frozen=True)
class SuiteSummary:
    path: Path
    total: int
    passed: int
    failed: int
    traces: tuple[Mapping[str, Any], ...]

    @property
    def ok(self) -> bool:
        return self.failed == 0 and self.total > 0


class JsonlTraceWriter:
    """Write one JSON object per line, replacing an existing trace file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("w", encoding="utf-8", newline="\n")

    def write(self, trace: Mapping[str, Any]) -> None:
        self._handle.write(json.dumps(trace, ensure_ascii=False, separators=(",", ":")) + "\n")
        self._handle.flush()

    def close(self) -> None:
        self._handle.close()

    def __enter__(self) -> "JsonlTraceWriter":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()


def run_task(
    task: Mapping[str, Any],
    adapter: MockAdapter,
    config: RunConfig,
) -> dict[str, Any]:
    """Run one task, always returning a serializable trace with explicit errors."""
    task_id = str(task["id"])
    params = dict(task["input_spec"]["sample"])
    context: dict[str, Any] = {"steps": {}, "input": params}
    steps: dict[str, Any] = {}
    calls: list[dict[str, Any]] = []
    spent_units = 0.0
    evaluation: Evaluation | None = None
    error: dict[str, Any] | None = None
    started_at = utc_now()
    trace_started = time.perf_counter()

    try:
        for index, step in enumerate(task["reference_tool_chain"], start=1):
            step_id = str(step["step_id"])
            if len(calls) >= config.max_tool_calls:
                raise BudgetExceeded(
                    "MAX_TOOL_CALLS_EXCEEDED",
                    f"stopped before step {index} ({step_id}): max_tool_calls={config.max_tool_calls}",
                )
            if spent_units + config.call_cost_units > config.max_budget_units + 1e-9:
                raise BudgetExceeded(
                    "BUDGET_UNITS_EXCEEDED",
                    (
                        f"stopped before step {index} ({step_id}): "
                        f"max_budget_units={config.max_budget_units}, "
                        f"requested={spent_units + config.call_cost_units}"
                    ),
                )

            arguments = resolve_references(step["arguments"], context)
            spent_units += config.call_cost_units
            call_started = time.perf_counter()
            try:
                invocation = adapter.invoke(task_id, step, arguments)
            except Exception as exc:  # Logged explicitly before re-raising for classification.
                calls.append(
                    {
                        "index": index,
                        "step_id": step_id,
                        "tool": step["tool"],
                        "arguments": dict(arguments),
                        "status": "error",
                        "fixture_ref": None,
                        "response": None,
                        "error": {
                            "code": type(exc).__name__,
                            "message": str(exc),
                        },
                        "duration_ms": _duration_ms(call_started),
                        "source": "synthetic_mock",
                    }
                )
                raise

            calls.append(
                {
                    "index": index,
                    "step_id": step_id,
                    "tool": step["tool"],
                    "arguments": dict(arguments),
                    "status": "ok",
                    "fixture_ref": invocation.fixture_ref,
                    "response": invocation.result,
                    "error": None,
                    "duration_ms": _duration_ms(call_started),
                    "source": "synthetic_mock",
                }
            )
            steps[step_id] = invocation.result
            context["steps"][step_id] = invocation.result

        evaluation = evaluate(task, context)
        if not evaluation.passed:
            failed_ids = [str(check["id"]) for check in evaluation.failed_checks]
            error = _error_payload(
                "ORACLE_MISMATCH",
                "evaluation",
                f"{len(failed_ids)} of {len(evaluation.checks)} success criteria failed: {', '.join(failed_ids)}",
                extra={"failed_check_ids": failed_ids},
            )

    except ToolExecutionError as exc:
        error = _error_payload(exc.code, "tool", exc.message, step_id=_last_step_id(calls))
    except BudgetExceeded as exc:
        error = _error_payload(exc.code, "budget", exc.message)
    except ReferenceResolutionError as exc:
        error = _error_payload("ARGUMENT_REFERENCE_ERROR", "argument", str(exc))
    except FixtureError as exc:
        error = _error_payload("FIXTURE_ERROR", "fixture", str(exc), step_id=_last_step_id(calls))
    except EvaluationError as exc:
        error = _error_payload("EVALUATION_ERROR", "evaluation", str(exc))
    except LabError as exc:
        error = _error_payload("LAB_ERROR", "internal", str(exc))
    except Exception as exc:  # The trace must retain unexpected failures instead of crashing the suite.
        error = _error_payload(
            "INTERNAL_ERROR",
            "internal",
            f"{type(exc).__name__}: {exc}",
            step_id=_last_step_id(calls),
        )

    finished_at = utc_now()
    passed = bool(error is None and evaluation is not None and evaluation.passed)
    return {
        "trace_schema_version": "1.0.0",
        "trace_id": uuid.uuid4().hex,
        "task_id": task_id,
        "task_title": task["title"],
        "category": task["category"],
        "capability_family": task["capability_family"],
        "mode": MODE,
        "timestamp": started_at,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": round((time.perf_counter() - trace_started) * 1000.0, 3),
        "validator_version": VALIDATOR_VERSION,
        "params": params,
        "budget": {
            "max_tool_calls": config.max_tool_calls,
            "max_budget_units": config.max_budget_units,
            "call_cost_units": config.call_cost_units,
            "tool_calls_used": len(calls),
            "budget_units_spent": spent_units,
        },
        "tool_calls": calls,
        "steps": steps,
        "checks": list(evaluation.checks) if evaluation else [],
        "status": "pass" if passed else "fail",
        "passed": passed,
        "error_reason": error["message"] if error else None,
        "error": error,
        "fixture": {
            "kind": "synthetic_fixture",
            "path": adapter.source_path,
            "label": "synthetic/illustrative",
        },
        "source": {
            "label": "synthetic/illustrative",
            "adapter": "MockAdapter",
            "api": "none",
            "network": False,
            "credential_used": False,
        },
    }


def _last_step_id(calls: Sequence[Mapping[str, Any]]) -> str | None:
    if not calls:
        return None
    return str(calls[-1]["step_id"])


def run_suite(
    tasks: Sequence[Mapping[str, Any]],
    adapter: MockAdapter,
    config: RunConfig,
    trace_path: str | Path,
    *,
    fail_fast: bool = False,
) -> SuiteSummary:
    """Run selected tasks and write one trace line per task as work proceeds."""
    if not tasks:
        raise ValueError("run_suite requires at least one task")

    traces: list[Mapping[str, Any]] = []
    target = Path(trace_path)
    with JsonlTraceWriter(target) as writer:
        for task in tasks:
            trace = run_task(task, adapter, config)
            writer.write(trace)
            traces.append(trace)
            if fail_fast and not trace["passed"]:
                break

    passed = sum(1 for trace in traces if trace["passed"])
    return SuiteSummary(
        path=target,
        total=len(traces),
        passed=passed,
        failed=len(traces) - passed,
        traces=tuple(traces),
    )


def load_traces(path: str | Path) -> tuple[dict[str, Any], ...]:
    """Load a JSONL trace file for independent re-evaluation."""
    trace_path = Path(path)
    try:
        lines = trace_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise TraceFormatError(f"cannot read trace file {trace_path}: {exc}") from exc

    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise TraceFormatError(
                f"{trace_path}:{line_number}: invalid JSON: {exc.msg}"
            ) from exc
        if not isinstance(record, dict):
            raise TraceFormatError(f"{trace_path}:{line_number}: trace line must be a JSON object")
        records.append(record)
    return tuple(records)
