"""Independent structural integrity checking for recorded traces.

This module answers a different question than the result evaluator:

* ``evaluator.evaluate_trace`` asks: *do the recorded step results satisfy the
  task's success criteria?*
* ``trace_integrity.check_trace_integrity`` asks: *is this record a coherent,
  honestly labelled piece of evidence at all?*

Keeping the two separate is deliberate.  A forged trace can satisfy the oracle
(``evaluate_trace`` returns ``True``) while its provenance is false; only the
integrity layer can reject it.  This module therefore:

* never imports the evaluator,
* never trusts the recorded ``status``/``passed``/``checks`` as *results*,
  it only checks that they are mutually consistent,
* reports every finding instead of raising, so callers can aggregate.

It does not prove reality: a fully self-consistent forgery is still possible
(no signatures or external attestation are involved).  See the G0.1 work order
risk R1.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Mapping, Sequence

from . import MODE, VALIDATOR_VERSION

PASS_LEVELS: tuple[str, ...] = ("reject", "warn")
ALLOWED_MODES: tuple[str, ...] = (MODE,)
SUPPORTED_TRACE_SCHEMA_VERSION = "1.0.0"
#: Exact provenance a ``synthetic_mock`` trace must declare.
SOURCE_FOR_MOCK: Mapping[str, Any] = {
    "label": "synthetic/illustrative",
    "adapter": "MockAdapter",
    "api": "none",
    "network": False,
    "credential_used": False,
}
FIXTURE_LABEL = "synthetic/illustrative"
FIXTURE_KIND = "synthetic_fixture"

_TRACE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_CRITERIA_STEP_RE = re.compile(r"^\$\.steps\.([a-z][a-z0-9_]*)")
_REQUIRED_CALL_KEYS = (
    "index",
    "step_id",
    "tool",
    "arguments",
    "status",
    "response",
    "error",
    "duration_ms",
    "source",
    "fixture_ref",
)
_CHECK_GROUPS = ("A-1", "A-2", "A-3", "A-4", "A-5", "A-6", "A-7", "A-8", "A-9")


@dataclass(frozen=True)
class IntegrityIssue:
    """One machine-checkable finding about a trace's evidence quality."""

    code: str
    level: str
    location: str
    message: str

    def __post_init__(self) -> None:
        if self.level not in PASS_LEVELS:
            raise ValueError(f"unknown integrity level: {self.level!r}")


@dataclass(frozen=True)
class IntegrityReport:
    """Result of the full integrity pass for one trace record."""

    task_id: str | None
    checks_run: tuple[str, ...]
    issues: tuple[IntegrityIssue, ...]

    @property
    def rejects(self) -> tuple[IntegrityIssue, ...]:
        return tuple(issue for issue in self.issues if issue.level == "reject")

    @property
    def warnings(self) -> tuple[IntegrityIssue, ...]:
        return tuple(issue for issue in self.issues if issue.level == "warn")

    @property
    def ok(self) -> bool:
        """True when no ``reject`` finding was raised.

        This means "the record is admissible as evidence", not "the task
        succeeded"; success is decided by the independent oracle re-evaluation.
        """
        return not self.rejects


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_finite_number(value: Any) -> bool:
    return _is_number(value) and math.isfinite(float(value))


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _ok_call_step_ids(calls: Sequence[Any]) -> set[str]:
    return {
        str(call["step_id"])
        for call in calls
        if isinstance(call, Mapping) and call.get("status") == "ok" and "step_id" in call
    }


def check_trace_integrity(task: Mapping[str, Any], trace: Mapping[str, Any]) -> IntegrityReport:
    """Run every A-block consistency check for one trace record."""
    task_id = task.get("id") if isinstance(task, Mapping) else None
    issues: list[IntegrityIssue] = []

    def add(code: str, level: str, location: str, message: str) -> None:
        issues.append(IntegrityIssue(code=code, level=level, location=location, message=message))

    if not isinstance(trace, Mapping):
        add("TRACE_NOT_OBJECT", "reject", "$", "trace record must be a JSON object")
        return IntegrityReport(
            task_id=str(task_id) if task_id is not None else None,
            checks_run=(),
            issues=tuple(issues),
        )

    calls = trace.get("tool_calls")
    calls = calls if isinstance(calls, list) else []

    _check_identity(task, trace, add)          # A-1
    _check_mode_and_source(trace, add)         # A-2
    _check_status(trace, add)                  # A-3
    _check_recorded_checks(task, trace, add)   # A-4
    _check_calls(task, trace, calls, add)      # A-5
    _check_budget(task, trace, calls, add)     # A-6
    _check_criteria_steps(task, trace, calls, add)  # A-7
    _check_failure_path(trace, calls, add)     # A-8
    _check_time_and_ids(trace, add)            # A-9

    return IntegrityReport(
        task_id=str(task_id) if task_id is not None else None,
        checks_run=_CHECK_GROUPS,
        issues=tuple(issues),
    )


# ---------------------------------------------------------------------------
# A-1 identity / version / echoed input
# ---------------------------------------------------------------------------


def _check_identity(task: Mapping[str, Any], trace: Mapping[str, Any], add: Callable[..., None]) -> None:
    task_id = task.get("id")
    if trace.get("task_id") != task_id:
        add("TRACE_TASK_ID_MISMATCH", "reject", "$.task_id", f"expected task_id {task_id!r}, got {trace.get('task_id')!r}")

    for trace_key, task_key in (
        ("category", "category"),
        ("capability_family", "capability_family"),
        ("task_title", "title"),
    ):
        if trace.get(trace_key) != task.get(task_key):
            add(
                "TRACE_TASK_METADATA_MISMATCH",
                "reject",
                f"$.{trace_key}",
                f"expected {trace_key} {task.get(task_key)!r}, got {trace.get(trace_key)!r}",
            )

    if trace.get("trace_schema_version") != SUPPORTED_TRACE_SCHEMA_VERSION:
        add(
            "TRACE_SCHEMA_VERSION_UNSUPPORTED",
            "reject",
            "$.trace_schema_version",
            f"expected {SUPPORTED_TRACE_SCHEMA_VERSION!r}, got {trace.get('trace_schema_version')!r}",
        )
    if trace.get("validator_version") != VALIDATOR_VERSION:
        add(
            "TRACE_VALIDATOR_VERSION_DRIFT",
            "warn",
            "$.validator_version",
            f"trace was produced by {trace.get('validator_version')!r}, current is {VALIDATOR_VERSION!r}",
        )

    spec = task.get("input_spec")
    sample = spec.get("sample") if isinstance(spec, Mapping) else None
    if trace.get("params") != sample:
        add("TRACE_PARAMS_MISMATCH", "reject", "$.params", "recorded params differ from the task input sample")


# ---------------------------------------------------------------------------
# A-2 execution mode and provenance
# ---------------------------------------------------------------------------


def _check_mode_and_source(trace: Mapping[str, Any], add: Callable[..., None]) -> None:
    mode = trace.get("mode")
    if mode not in ALLOWED_MODES:
        add("TRACE_MODE_UNKNOWN", "reject", "$.mode", f"mode {mode!r} is not allowed; expected one of {list(ALLOWED_MODES)}")

    source = trace.get("source")
    if not isinstance(source, Mapping):
        add("TRACE_SOURCE_INCONSISTENT", "reject", "$.source", "source must be an object describing the adapter")
    else:
        for key, expected in SOURCE_FOR_MOCK.items():
            if source.get(key) != expected:
                add(
                    "TRACE_SOURCE_INCONSISTENT",
                    "reject",
                    f"$.source.{key}",
                    f"expected {key}={expected!r} for a synthetic mock trace, got {source.get(key)!r}",
                )

    fixture = trace.get("fixture")
    if not isinstance(fixture, Mapping):
        add("TRACE_FIXTURE_PROVENANCE_INCONSISTENT", "reject", "$.fixture", "fixture provenance must be an object")
        return
    if fixture.get("kind") != FIXTURE_KIND:
        add(
            "TRACE_FIXTURE_PROVENANCE_INCONSISTENT",
            "reject",
            "$.fixture.kind",
            f"expected fixture kind {FIXTURE_KIND!r}, got {fixture.get('kind')!r}",
        )
    if fixture.get("label") != FIXTURE_LABEL:
        add(
            "TRACE_FIXTURE_PROVENANCE_INCONSISTENT",
            "reject",
            "$.fixture.label",
            f"expected fixture label {FIXTURE_LABEL!r}, got {fixture.get('label')!r}",
        )
    if not _is_nonempty_str(fixture.get("path")):
        add("TRACE_FIXTURE_PROVENANCE_INCONSISTENT", "reject", "$.fixture.path", "fixture path must be a non-empty string")


# ---------------------------------------------------------------------------
# A-3 status / passed / error coherence
# ---------------------------------------------------------------------------


def _check_status(trace: Mapping[str, Any], add: Callable[..., None]) -> None:
    status = trace.get("status")
    passed = trace.get("passed")
    if status not in {"pass", "fail"} or not isinstance(passed, bool):
        add("TRACE_STATUS_INVALID", "reject", "$.status", "status must be 'pass'/'fail' and passed must be a boolean")
        return
    if passed != (status == "pass"):
        add("TRACE_STATUS_TAMPERED", "reject", "$.passed", f"passed={passed!r} contradicts status={status!r}")

    error = trace.get("error")
    reason = trace.get("error_reason")
    if passed:
        if error is not None or reason is not None:
            add("TRACE_PASS_WITH_ERROR", "reject", "$.error", "a passing record must have error=null and error_reason=null")
        return

    error_ok = (
        isinstance(error, Mapping)
        and _is_nonempty_str(error.get("code"))
        and _is_nonempty_str(error.get("kind"))
        and _is_nonempty_str(error.get("message"))
    )
    if not error_ok:
        add("TRACE_FAIL_WITHOUT_ERROR", "reject", "$.error", "a failing record must carry error code/kind/message")
    elif reason != error.get("message"):
        add("TRACE_FAIL_WITHOUT_ERROR", "reject", "$.error_reason", "error_reason must equal error.message")


# ---------------------------------------------------------------------------
# A-4 recorded checks self-consistency (never used as the result verdict)
# ---------------------------------------------------------------------------


def _check_recorded_checks(task: Mapping[str, Any], trace: Mapping[str, Any], add: Callable[..., None]) -> None:
    checks = trace.get("checks")
    if not isinstance(checks, list):
        add("TRACE_CHECKS_SHAPE_INVALID", "reject", "$.checks", "checks must be a list")
        return

    shape_ok = True
    for index, check in enumerate(checks):
        if not isinstance(check, Mapping):
            shape_ok = False
            add("TRACE_CHECKS_SHAPE_INVALID", "reject", f"$.checks[{index}]", "check must be an object")
            continue
        for key in ("id", "target", "operator", "detail"):
            if not isinstance(check.get(key), str):
                shape_ok = False
                add("TRACE_CHECKS_SHAPE_INVALID", "reject", f"$.checks[{index}].{key}", f"{key} must be a string")
        if not isinstance(check.get("passed"), bool):
            shape_ok = False
            add("TRACE_CHECKS_SHAPE_INVALID", "reject", f"$.checks[{index}].passed", "passed must be a boolean")

    criteria = task.get("success_criteria") or []
    criteria_ids = [criterion.get("id") for criterion in criteria if isinstance(criterion, Mapping)]
    recorded_ids = [check.get("id") for check in checks if isinstance(check, Mapping)]
    if shape_ok and recorded_ids and recorded_ids != criteria_ids:
        add(
            "TRACE_CHECKS_CRITERIA_MISMATCH",
            "reject",
            "$.checks",
            f"recorded check ids {recorded_ids!r} do not match criteria {criteria_ids!r}",
        )

    if trace.get("passed") is True and any(
        isinstance(check, Mapping) and check.get("passed") is False for check in checks
    ):
        add("TRACE_PASS_WITH_FAILED_CHECK", "reject", "$.checks", "a passing record cannot contain a failed recorded check")

    error = trace.get("error")
    if isinstance(error, Mapping) and error.get("code") == "ORACLE_MISMATCH":
        failed_ids = error.get("failed_check_ids")
        recorded_failed = {
            check.get("id") for check in checks if isinstance(check, Mapping) and check.get("passed") is False
        }
        if not isinstance(failed_ids, list) or not failed_ids:
            add("TRACE_ORACLE_ERROR_INCONSISTENT", "reject", "$.error.failed_check_ids", "ORACLE_MISMATCH must name failed checks")
        elif not set(map(str, failed_ids)) <= set(map(str, recorded_ids)) or not set(map(str, failed_ids)) <= recorded_failed:
            add(
                "TRACE_ORACLE_ERROR_INCONSISTENT",
                "reject",
                "$.error.failed_check_ids",
                "ORACLE_MISMATCH names checks that are absent or recorded as passed",
            )

    if isinstance(error, Mapping) and error.get("kind") not in (None, "evaluation") and checks:
        add(
            "TRACE_CHECKS_WITH_ROUTING_ERROR",
            "warn",
            "$.checks",
            f"a routing error (kind={error.get('kind')!r}) normally carries no recorded checks",
        )


# ---------------------------------------------------------------------------
# A-5 tool_calls <-> steps one-to-one correspondence
# ---------------------------------------------------------------------------


def _check_calls(
    task: Mapping[str, Any],
    trace: Mapping[str, Any],
    calls: Sequence[Any],
    add: Callable[..., None],
) -> None:
    task_id = str(task.get("id"))
    chain = task.get("reference_tool_chain") or []

    shape_ok = True
    for index, call in enumerate(calls):
        if not isinstance(call, Mapping):
            shape_ok = False
            add("TRACE_CALL_SHAPE_INVALID", "reject", f"$.tool_calls[{index}]", "call must be an object")
            continue
        for key in _REQUIRED_CALL_KEYS:
            if key not in call:
                shape_ok = False
                add("TRACE_CALL_SHAPE_INVALID", "reject", f"$.tool_calls[{index}].{key}", f"missing required key {key!r}")
        if not _is_int(call.get("index")):
            shape_ok = False
            add("TRACE_CALL_SHAPE_INVALID", "reject", f"$.tool_calls[{index}].index", "index must be an integer")
        if not _is_nonempty_str(call.get("step_id")):
            shape_ok = False
            add("TRACE_CALL_SHAPE_INVALID", "reject", f"$.tool_calls[{index}].step_id", "step_id must be a non-empty string")
        if not _is_nonempty_str(call.get("tool")):
            shape_ok = False
            add("TRACE_CALL_SHAPE_INVALID", "reject", f"$.tool_calls[{index}].tool", "tool must be a non-empty string")
        if not isinstance(call.get("arguments"), Mapping):
            shape_ok = False
            add("TRACE_CALL_SHAPE_INVALID", "reject", f"$.tool_calls[{index}].arguments", "arguments must be an object")
        if call.get("status") not in {"ok", "error"}:
            shape_ok = False
            add("TRACE_CALL_SHAPE_INVALID", "reject", f"$.tool_calls[{index}].status", "status must be 'ok' or 'error'")
        if not _is_finite_number(call.get("duration_ms")) or float(call.get("duration_ms")) < 0:
            shape_ok = False
            add("TRACE_CALL_SHAPE_INVALID", "reject", f"$.tool_calls[{index}].duration_ms", "duration_ms must be finite and >= 0")
        if not _is_nonempty_str(call.get("source")):
            shape_ok = False
            add("TRACE_CALL_SHAPE_INVALID", "reject", f"$.tool_calls[{index}].source", "source must be a non-empty string")
        if call.get("fixture_ref") is not None and not _is_nonempty_str(call.get("fixture_ref")):
            shape_ok = False
            add("TRACE_CALL_SHAPE_INVALID", "reject", f"$.tool_calls[{index}].fixture_ref", "fixture_ref must be null or a string")

    if not shape_ok:
        return

    seen_steps: set[str] = set()
    for position, call in enumerate(calls, start=1):
        step_id = str(call["step_id"])
        if call["index"] != position:
            add(
                "TRACE_CALL_INDEX_INVALID",
                "reject",
                f"$.tool_calls[{position - 1}].index",
                f"expected 1-based index {position}, got {call['index']!r}",
            )
        if step_id in seen_steps:
            add("TRACE_DUPLICATE_CALL_STEP", "reject", f"$.tool_calls[{position - 1}].step_id", f"duplicate step {step_id!r}")
        seen_steps.add(step_id)

    if len(calls) > len(chain):
        add(
            "TRACE_CALL_SEQUENCE_MISMATCH",
            "reject",
            "$.tool_calls",
            f"{len(calls)} calls recorded but the reference chain has {len(chain)} steps",
        )
    for position, call in enumerate(calls[: len(chain)]):
        expected_step = chain[position]
        if call["step_id"] != expected_step.get("step_id") or call["tool"] != expected_step.get("tool"):
            add(
                "TRACE_CALL_SEQUENCE_MISMATCH",
                "reject",
                f"$.tool_calls[{position}]",
                f"expected {expected_step.get('step_id')!r}/{expected_step.get('tool')!r}, "
                f"got {call['step_id']!r}/{call['tool']!r}",
            )

    steps = trace.get("steps")
    if not isinstance(steps, Mapping):
        add("TRACE_MISSING_STEP_FOR_CALL", "reject", "$.steps", "steps must be an object")
        return

    ok_step_ids: set[str] = set()
    for position, call in enumerate(calls):
        step_id = str(call["step_id"])
        if call["status"] == "ok":
            ok_step_ids.add(step_id)
            if call.get("error") is not None:
                add("TRACE_OK_CALL_INCONSISTENT", "reject", f"$.tool_calls[{position}].error", "a successful call must have error=null")
            response = call.get("response")
            if not isinstance(response, Mapping):
                add("TRACE_OK_CALL_INCONSISTENT", "reject", f"$.tool_calls[{position}].response", "a successful call must have an object response")
            if call.get("fixture_ref") != f"{task_id}.{step_id}":
                add(
                    "TRACE_OK_CALL_INCONSISTENT",
                    "reject",
                    f"$.tool_calls[{position}].fixture_ref",
                    f"expected fixture ref {task_id + '.' + step_id!r}, got {call.get('fixture_ref')!r}",
                )
            if isinstance(response, Mapping):
                if response.get("synthetic") is not True:
                    add(
                        "TRACE_UNMARKED_SYNTHETIC",
                        "reject",
                        f"$.tool_calls[{position}].response.synthetic",
                        "mock responses must be marked synthetic=true",
                    )
                if "source_label" in response and response.get("source_label") != FIXTURE_LABEL:
                    add(
                        "TRACE_UNMARKED_SYNTHETIC",
                        "reject",
                        f"$.tool_calls[{position}].response.source_label",
                        f"unexpected source_label {response.get('source_label')!r}",
                    )
        else:
            if call.get("response") is not None:
                add("TRACE_ERROR_CALL_INCONSISTENT", "reject", f"$.tool_calls[{position}].response", "an error call must have response=null")
            error = call.get("error")
            if not (
                isinstance(error, Mapping)
                and _is_nonempty_str(error.get("code"))
                and _is_nonempty_str(error.get("message"))
            ):
                add("TRACE_ERROR_CALL_INCONSISTENT", "reject", f"$.tool_calls[{position}].error", "an error call must carry code/message")

    orphan_steps = sorted(str(step) for step in steps if str(step) not in ok_step_ids)
    if orphan_steps:
        add(
            "TRACE_STEPS_WITHOUT_CALLS",
            "reject",
            "$.steps",
            f"steps {orphan_steps!r} have no successful tool call backing them",
        )

    for position, call in enumerate(calls):
        if call["status"] != "ok":
            continue
        step_id = str(call["step_id"])
        if step_id not in steps:
            add("TRACE_MISSING_STEP_FOR_CALL", "reject", f"$.steps.{step_id}", "successful call has no recorded step")
        elif steps[step_id] != call.get("response"):
            add(
                "TRACE_MISSING_STEP_FOR_CALL",
                "reject",
                f"$.steps.{step_id}",
                "recorded step differs from the response of the call that produced it",
            )


# ---------------------------------------------------------------------------
# A-6 budget arithmetic
# ---------------------------------------------------------------------------


def _check_budget(
    task: Mapping[str, Any],
    trace: Mapping[str, Any],
    calls: Sequence[Any],
    add: Callable[..., None],
) -> None:
    budget = trace.get("budget")
    if not isinstance(budget, Mapping):
        add("TRACE_BUDGET_SHAPE_INVALID", "reject", "$.budget", "budget must be an object")
        return
    max_calls = budget.get("max_tool_calls")
    max_units = budget.get("max_budget_units")
    cost = budget.get("call_cost_units")
    used = budget.get("tool_calls_used")
    spent = budget.get("budget_units_spent")
    if not (_is_int(max_calls) and max_calls > 0):
        add("TRACE_BUDGET_SHAPE_INVALID", "reject", "$.budget.max_tool_calls", "max_tool_calls must be a positive integer")
    if not (_is_finite_number(max_units) and float(max_units) > 0):
        add("TRACE_BUDGET_SHAPE_INVALID", "reject", "$.budget.max_budget_units", "max_budget_units must be finite and > 0")
    if not (_is_finite_number(cost) and float(cost) > 0):
        add("TRACE_BUDGET_SHAPE_INVALID", "reject", "$.budget.call_cost_units", "call_cost_units must be finite and > 0")
    if not (_is_int(used) and used >= 0):
        add("TRACE_BUDGET_SHAPE_INVALID", "reject", "$.budget.tool_calls_used", "tool_calls_used must be a non-negative integer")
    if not (_is_finite_number(spent) and float(spent) >= 0):
        add("TRACE_BUDGET_SHAPE_INVALID", "reject", "$.budget.budget_units_spent", "budget_units_spent must be finite and >= 0")
    if not (_is_int(max_calls) and _is_finite_number(max_units) and _is_finite_number(cost) and _is_int(used) and _is_finite_number(spent)):
        return

    if used != len(calls):
        add(
            "TRACE_BUDGET_CALL_COUNT_MISMATCH",
            "reject",
            "$.budget.tool_calls_used",
            f"tool_calls_used={used} but {len(calls)} calls were recorded",
        )
    expected_spend = len(calls) * float(cost)
    if not math.isclose(float(spent), expected_spend, rel_tol=1e-9, abs_tol=1e-9):
        add(
            "TRACE_BUDGET_SPEND_MISMATCH",
            "reject",
            "$.budget.budget_units_spent",
            f"budget_units_spent={spent} but {len(calls)} calls at {cost} units imply {expected_spend}",
        )
    if used > max_calls or float(spent) > float(max_units) + 1e-9:
        add(
            "TRACE_BUDGET_LIMIT_VIOLATED",
            "reject",
            "$.budget",
            "recorded spend exceeds the declared budget without stopping",
        )

    chain = task.get("reference_tool_chain") or []
    error = trace.get("error")
    code = error.get("code") if isinstance(error, Mapping) else None
    if code == "MAX_TOOL_CALLS_EXCEEDED":
        if len(calls) != max_calls or max_calls >= len(chain):
            add(
                "TRACE_BUDGET_STOP_UNJUSTIFIED",
                "reject",
                "$.error.code",
                "MAX_TOOL_CALLS_EXCEEDED is inconsistent with the call count and chain length",
            )
    elif code == "BUDGET_UNITS_EXCEEDED":
        justified = expected_spend + float(cost) > float(max_units) + 1e-9 and len(calls) < len(chain)
        if not justified:
            add(
                "TRACE_BUDGET_STOP_UNJUSTIFIED",
                "reject",
                "$.error.code",
                "BUDGET_UNITS_EXCEEDED is inconsistent with the recorded spend",
            )


# ---------------------------------------------------------------------------
# A-7 every oracle-referenced step must exist and be backed by a call
# ---------------------------------------------------------------------------


def _check_criteria_steps(
    task: Mapping[str, Any],
    trace: Mapping[str, Any],
    calls: Sequence[Any],
    add: Callable[..., None],
) -> None:
    checks = trace.get("checks")
    evaluated = bool(checks) or trace.get("passed") is True
    if not evaluated:
        return
    steps = trace.get("steps")
    if not isinstance(steps, Mapping):
        return
    backed = _ok_call_step_ids(calls)
    for criterion in task.get("success_criteria") or []:
        if not isinstance(criterion, Mapping):
            continue
        match = _CRITERIA_STEP_RE.match(str(criterion.get("target", "")))
        if not match:
            continue
        step_id = match.group(1)
        if step_id not in steps or step_id not in backed:
            add(
                "TRACE_ORACLE_STEP_MISSING",
                "reject",
                f"$.steps.{step_id}",
                f"criterion {criterion.get('id')!r} reads {step_id!r}, which has no successful recorded call",
            )


# ---------------------------------------------------------------------------
# A-8 failure path and failing step stay consistent
# ---------------------------------------------------------------------------


def _check_failure_path(trace: Mapping[str, Any], calls: Sequence[Any], add: Callable[..., None]) -> None:
    error = trace.get("error")
    if not isinstance(error, Mapping):
        return
    kind = error.get("kind")
    if kind in {"tool", "fixture"}:
        if not calls or not isinstance(calls[-1], Mapping):
            add("TRACE_ERROR_STEP_MISMATCH", "reject", "$.error.step_id", f"a {kind} error requires at least one recorded call")
            return
        last = calls[-1]
        if last.get("status") != "error" or error.get("step_id") != last.get("step_id"):
            add(
                "TRACE_ERROR_STEP_MISMATCH",
                "reject",
                "$.error.step_id",
                f"a {kind} error must point at the failing recorded call {last.get('step_id')!r}",
            )
    elif kind == "evaluation":
        if any(isinstance(call, Mapping) and call.get("status") != "ok" for call in calls):
            add(
                "TRACE_EVALUATION_WITH_FAILED_CALL",
                "reject",
                "$.error.kind",
                "evaluation errors only happen after every tool call succeeded",
            )
    elif kind == "argument":
        if error.get("step_id") is None:
            add(
                "TRACE_ARGUMENT_ERROR_STEP_MISSING",
                "warn",
                "$.error.step_id",
                "known P2 observability gap: argument errors do not record step_id (runner.py:201-202)",
            )
    elif kind == "budget":
        if error.get("step_id") is not None:
            add(
                "TRACE_BUDGET_ERROR_STEP_ANOMALY",
                "warn",
                "$.error.step_id",
                "budget stops are recorded with step_id=null by runner.py:200",
            )


# ---------------------------------------------------------------------------
# A-9 ids, timestamps and duration
# ---------------------------------------------------------------------------


def _check_time_and_ids(trace: Mapping[str, Any], add: Callable[..., None]) -> None:
    trace_id = trace.get("trace_id")
    if not (_is_nonempty_str(trace_id) and _TRACE_ID_RE.match(str(trace_id))):
        add("TRACE_ID_INVALID", "reject", "$.trace_id", "trace_id must be 32 lowercase hex characters")

    timestamp = _parse_timestamp(trace.get("timestamp"))
    started = _parse_timestamp(trace.get("started_at"))
    finished = _parse_timestamp(trace.get("finished_at"))
    if timestamp is None or started is None or finished is None:
        add("TRACE_TIMESTAMP_INVALID", "reject", "$.started_at", "timestamps must be ISO-8601 values with a timezone")
    else:
        if timestamp != started:
            add("TRACE_TIMESTAMP_INCONSISTENT", "reject", "$.timestamp", "timestamp must equal started_at")
        if started > finished:
            add("TRACE_TIMESTAMP_ORDER", "reject", "$.finished_at", "finished_at must not precede started_at")

    duration = trace.get("duration_ms")
    if not _is_finite_number(duration) or float(duration) < 0:
        add("TRACE_DURATION_INVALID", "reject", "$.duration_ms", "duration_ms must be finite and >= 0")


# ---------------------------------------------------------------------------
# A-10 file-level evidence accounting
# ---------------------------------------------------------------------------


def check_trace_file_integrity(records: Sequence[Mapping[str, Any]]) -> tuple[IntegrityIssue, ...]:
    """Check accounting invariants that only exist across a whole JSONL file."""
    issues: list[IntegrityIssue] = []
    seen_trace_ids: dict[str, int] = {}
    task_counts: dict[str, int] = {}
    previous_start: datetime | None = None
    previous_index = -1

    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            continue
        trace_id = record.get("trace_id")
        if isinstance(trace_id, str) and trace_id:
            if trace_id in seen_trace_ids:
                issues.append(
                    IntegrityIssue(
                        code="TRACE_ID_DUPLICATE",
                        level="reject",
                        location=f"$[{index}].trace_id",
                        message=f"trace_id {trace_id!r} already appeared at record {seen_trace_ids[trace_id]}",
                    )
                )
            else:
                seen_trace_ids[trace_id] = index

        task_id = record.get("task_id")
        if isinstance(task_id, str) and task_id:
            task_counts[task_id] = task_counts.get(task_id, 0) + 1
            if task_counts[task_id] == 2:
                issues.append(
                    IntegrityIssue(
                        code="TRACE_TASK_ID_REPEATED",
                        level="warn",
                        location=f"$[{index}].task_id",
                        message=f"task {task_id!r} appears more than once; confirm this is a deliberate re-run",
                    )
                )

        started = _parse_timestamp(record.get("started_at"))
        if started is not None and previous_start is not None and started < previous_start:
            issues.append(
                IntegrityIssue(
                    code="TRACE_TIMESTAMP_NONMONOTONIC",
                    level="warn",
                    location=f"$[{index}].started_at",
                    message=f"started_at goes backwards relative to record {previous_index}",
                )
            )
        if started is not None:
            previous_start = started
            previous_index = index

    return tuple(issues)
