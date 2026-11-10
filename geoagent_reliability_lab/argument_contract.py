"""Mock tool-argument contract: prove that arguments are actually consumed.

G0.1-B closes the P0-2 gap: the mock adapter used to ``del arguments`` and replay
a fixed fixture, so a wrong reverse-geocoding coordinate still "passed".

The contract has two layers:

1. **Runtime enforcement** (``MockAdapter(argument_contract=...)``): every
   invocation is compared with the arguments derived from the task's own
   reference chain replayed against the synthetic fixtures.
2. **Post-hoc verification** (``check_argument_contract``): independently
   recomputes the expected arguments from the current repository data and
   compares them with a recorded trace, including cross-step provenance.

The golden values are *derived*, never duplicated: ``tasks/tasks.json`` stays
the single source of truth for the reference chain.  This proves argument
passing inside the synthetic world only; it says nothing about real Geoapify
semantics, and a wrong reference chain would produce a wrong golden value
(work order risk R1).
"""

from __future__ import annotations

import json
import math
from typing import Any, Mapping, Sequence

from . import MODE
from .errors import FixtureError
from .evaluator import resolve_references
from .fixtures import FixtureStore
from .trace_integrity import IntegrityIssue, IntegrityReport

CONTRACT_CHECKS = ("B-1", "B-2", "B-3", "B-5")


# ---------------------------------------------------------------------------
# primitive comparisons
# ---------------------------------------------------------------------------


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _normalize(value: Any) -> Any:
    """Canonical form used for human-readable comparisons (0 == 0.0)."""
    if isinstance(value, bool):
        return value
    if _is_number(value):
        return float(value)
    if isinstance(value, Mapping):
        return {str(key): _normalize(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    return value


def canonical_arguments(value: Any) -> str:
    """A deterministic string form of an argument mapping."""
    return json.dumps(_normalize(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def arguments_match(actual: Any, expected: Any) -> tuple[bool, str]:
    """Compare recorded arguments with expected arguments.

    Returns ``(matches, first_difference_location)``.  Numeric ``int``/``float``
    compare by value (``0 == 0.0``); booleans never equal numbers.
    """
    return _compare(actual, expected, "$")


def _compare(actual: Any, expected: Any, path: str) -> tuple[bool, str]:
    if isinstance(expected, bool) or isinstance(actual, bool):
        if not (isinstance(actual, bool) and isinstance(expected, bool)):
            return False, path
        return actual == expected, path

    if _is_number(expected) and _is_number(actual):
        actual_float, expected_float = float(actual), float(expected)
        if not (math.isfinite(actual_float) and math.isfinite(expected_float)):
            return False, path
        return actual_float == expected_float, path

    if isinstance(expected, Mapping):
        if not isinstance(actual, Mapping):
            return False, path
        actual_keys = {str(key) for key in actual}
        expected_keys = {str(key) for key in expected}
        if actual_keys != expected_keys:
            extra = sorted(actual_keys - expected_keys)
            missing = sorted(expected_keys - actual_keys)
            detail = f"{path}"
            if missing:
                detail += f".{missing[0]} (missing)"
            elif extra:
                detail += f".{extra[0]} (unexpected)"
            return False, detail
        for key in sorted(expected_keys):
            match, where = _compare(actual.get(key), expected[key], f"{path}.{key}")
            if not match:
                return False, where
        return True, path

    if isinstance(expected, (list, tuple)):
        if not isinstance(actual, (list, tuple)):
            return False, path
        if len(actual) != len(expected):
            return False, f"{path}[{min(len(actual), len(expected))}] (length)"
        for index, item in enumerate(expected):
            match, where = _compare(actual[index], item, f"{path}[{index}]")
            if not match:
                return False, where
        return True, path

    if isinstance(expected, str):
        if not isinstance(actual, str) or actual != expected:
            return False, path
        return True, path

    if expected is None or actual is None:
        return actual is None and expected is None, path

    return type(actual) is type(expected) and actual == expected, path


def find_coordinate_violation(arguments: Any) -> str | None:
    """Return the first ``lat``/``lon`` path that is non-finite or out of range."""
    return _walk_coordinates(arguments, "$")


def _walk_coordinates(value: Any, path: str) -> str | None:
    if isinstance(value, Mapping):
        for key in ("lat", "lon"):
            if key in value:
                item = value[key]
                if _is_number(item):
                    number = float(item)
                    if not math.isfinite(number):
                        return f"{path}.{key}"
                    if key == "lat" and not -90.0 <= number <= 90.0:
                        return f"{path}.{key}"
                    if key == "lon" and not -180.0 <= number <= 180.0:
                        return f"{path}.{key}"
        for key, item in value.items():
            found = _walk_coordinates(item, f"{path}.{key}")
            if found is not None:
                return found
        return None
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found = _walk_coordinates(item, f"{path}[{index}]")
            if found is not None:
                return found
    return None


# ---------------------------------------------------------------------------
# golden argument derivation (single source of truth: tasks + fixtures)
# ---------------------------------------------------------------------------


def expected_step_arguments(task: Mapping[str, Any], store: FixtureStore) -> dict[str, dict[str, Any]]:
    """Derive the expected arguments of every reference-chain step.

    Replays the reference chain against the synthetic fixtures using the same
    reference resolver as the runner, so the contract and the runner agree by
    construction (and a contract build fails loudly if a fixture is missing or
    a golden coordinate is out of range).
    """
    task_id = str(task["id"])
    spec = task.get("input_spec") or {}
    context: dict[str, Any] = {"steps": {}, "input": dict(spec.get("sample") or {})}
    expected: dict[str, dict[str, Any]] = {}

    for step in task.get("reference_tool_chain") or []:
        step_id = str(step["step_id"])
        try:
            arguments = resolve_references(step["arguments"], context)
        except Exception as exc:  # ReferenceResolutionError and friends
            raise FixtureError(f"cannot derive argument contract for {task_id}.{step_id}: {exc}") from exc
        if not isinstance(arguments, Mapping):
            raise FixtureError(f"reference arguments for {task_id}.{step_id} must resolve to an object")
        violation = find_coordinate_violation(arguments)
        if violation is not None:
            raise FixtureError(
                f"golden arguments for {task_id}.{step_id} violate the coordinate invariant at {violation}"
            )
        response = store.get(task_id, step_id, str(step["tool"]))
        expected[step_id] = dict(arguments)
        context["steps"][step_id] = response.result

    return expected


def build_argument_contract(
    tasks: Sequence[Mapping[str, Any]], store: FixtureStore
) -> dict[str, dict[str, dict[str, Any]]]:
    """Build ``{task_id: {step_id: expected_arguments}}`` for every task."""
    return {str(task["id"]): expected_step_arguments(task, store) for task in tasks}


# ---------------------------------------------------------------------------
# post-hoc verification of a recorded trace
# ---------------------------------------------------------------------------


def _contains_reference(value: Any) -> bool:
    if isinstance(value, str):
        return value.startswith("$.")
    if isinstance(value, Mapping):
        return any(_contains_reference(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_reference(item) for item in value)
    return False


def check_argument_contract(
    task: Mapping[str, Any], trace: Mapping[str, Any], store: FixtureStore
) -> IntegrityReport:
    """Independently verify a trace's arguments against the derived contract."""
    task_id = task.get("id")
    issues: list[IntegrityIssue] = []

    def add(code: str, level: str, location: str, message: str) -> None:
        issues.append(IntegrityIssue(code=code, level=level, location=location, message=message))

    report_task_id = str(task_id) if task_id is not None else None
    if not isinstance(trace, Mapping):
        add("TRACE_CONTRACT_UNAVAILABLE", "reject", "$", "trace record must be an object")
        return IntegrityReport(report_task_id, CONTRACT_CHECKS, tuple(issues))

    if trace.get("mode") != MODE:
        add(
            "TRACE_CONTRACT_SKIPPED_NON_MOCK",
            "warn",
            "$.mode",
            "the synthetic fixture contract does not apply to non-mock traces",
        )
        return IntegrityReport(report_task_id, CONTRACT_CHECKS, tuple(issues))

    try:
        expected = expected_step_arguments(task, store)
    except FixtureError as exc:
        add("TRACE_CONTRACT_UNAVAILABLE", "reject", "$", f"cannot re-derive the contract: {exc}")
        return IntegrityReport(report_task_id, CONTRACT_CHECKS, tuple(issues))

    calls = trace.get("tool_calls")
    if not isinstance(calls, list):
        # A-block owns call shape; the contract simply has nothing to check.
        return IntegrityReport(report_task_id, CONTRACT_CHECKS, ())

    for index, call in enumerate(calls):
        if not isinstance(call, Mapping):
            continue
        step_id = call.get("step_id")
        golden = expected.get(str(step_id)) if step_id is not None else None
        if golden is None:
            add(
                "TRACE_CONTRACT_UNAVAILABLE",
                "reject",
                f"$.tool_calls[{index}].step_id",
                f"no derivable expected arguments for step {step_id!r}",
            )
            continue
        recorded = call.get("arguments")
        violation = find_coordinate_violation(recorded)
        if violation is not None:
            add(
                "TRACE_ARGUMENT_COORDINATE_RANGE",
                "reject",
                f"$.tool_calls[{index}].arguments{violation[1:]}",
                f"recorded coordinate at {violation} is out of range or non-finite",
            )
        matches, difference = arguments_match(recorded, golden)
        if not matches:
            add(
                "TRACE_ARGUMENTS_CONTRACT_MISMATCH",
                "reject",
                f"$.tool_calls[{index}].arguments{difference[1:]}",
                f"recorded arguments differ from the derived contract at {difference}",
            )

    _check_provenance(task, trace, calls, add)
    return IntegrityReport(report_task_id, CONTRACT_CHECKS, tuple(issues))


def _check_provenance(
    task: Mapping[str, Any],
    trace: Mapping[str, Any],
    calls: Sequence[Any],
    add: Any,
) -> None:
    """A resolved cross-step argument must match the steps it was resolved from."""
    steps = trace.get("steps")
    if not isinstance(steps, Mapping):
        return
    params = trace.get("params")
    context = {"steps": steps, "input": params if isinstance(params, Mapping) else {}}
    chain = task.get("reference_tool_chain") or []
    by_step = {str(step.get("step_id")): step for step in chain if isinstance(step, Mapping)}

    for index, call in enumerate(calls):
        if not isinstance(call, Mapping):
            continue
        step_id = call.get("step_id")
        if step_id is None:
            continue
        step = by_step.get(str(step_id))
        if step is None or not _contains_reference(step.get("arguments")):
            continue
        try:
            resolved = resolve_references(step.get("arguments"), context)
        except Exception as exc:
            add(
                "TRACE_ARGUMENT_PROVENANCE_UNRESOLVABLE",
                "reject",
                f"$.tool_calls[{index}].arguments",
                f"cannot resolve the recorded step references: {exc}",
            )
            continue
        matches, difference = arguments_match(call.get("arguments"), resolved)
        if not matches:
            add(
                "TRACE_ARGUMENT_PROVENANCE_MISMATCH",
                "reject",
                f"$.tool_calls[{index}].arguments{difference[1:]}",
                f"recorded arguments disagree with the steps they were resolved from at {difference}",
            )
