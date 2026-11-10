"""Independent, JSON-only evaluation of a recorded tool chain.

The evaluator deliberately knows nothing about the mock adapter or the live
transport. It receives a task definition and the recorded step responses, then
applies the task's machine-verifiable success criteria from scratch.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .errors import EvaluationError, ReferenceResolutionError

OPERATORS = frozenset(
    {"equals", "contains", "length_equals", "numeric_close", "set_equals", "truthy", "lte", "gte"}
)


@dataclass(frozen=True)
class Evaluation:
    """Result of applying all success criteria for one task."""

    passed: bool
    checks: tuple[dict[str, Any], ...]

    @property
    def failed_checks(self) -> tuple[dict[str, Any], ...]:
        return tuple(check for check in self.checks if not check["passed"])


def _parse_path(path: str) -> list[tuple[str, str | int]]:
    if path == "$":
        return []
    if not isinstance(path, str) or not path.startswith("$."):
        raise EvaluationError(f"invalid JSON path {path!r}; expected a path beginning with '$.'")

    body = path[2:]
    if not body:
        raise EvaluationError(f"invalid JSON path {path!r}")

    tokens: list[tuple[str, str | int]] = []
    index = 0
    while index < len(body):
        char = body[index]
        if char == ".":
            index += 1
            if index >= len(body) or body[index] in ".[":
                raise EvaluationError(f"invalid JSON path {path!r}: empty key")
            continue
        if char == "[":
            close = body.find("]", index + 1)
            if close == -1:
                raise EvaluationError(f"invalid JSON path {path!r}: missing ']'")
            number = body[index + 1 : close]
            if not number.isdigit():
                raise EvaluationError(f"invalid JSON path {path!r}: array index must be an integer")
            tokens.append(("index", int(number)))
            index = close + 1
            continue

        start = index
        while index < len(body) and body[index] not in ".[":
            index += 1
        key = body[start:index]
        if not key:
            raise EvaluationError(f"invalid JSON path {path!r}: empty key")
        tokens.append(("key", key))

    return tokens


def resolve_path(context: Any, path: str) -> Any:
    """Resolve a small JSON path subset: dotted keys and numeric array indexes."""
    current = context
    for kind, token in _parse_path(path):
        if kind == "key":
            if not isinstance(current, Mapping) or token not in current:
                raise EvaluationError(f"path {path!r} does not exist at key {token!r}")
            current = current[token]
        else:
            assert isinstance(token, int)
            if not isinstance(current, list) or token >= len(current):
                raise EvaluationError(f"path {path!r} does not exist at index {token}")
            current = current[token]
    return current


def resolve_references(value: Any, context: Mapping[str, Any]) -> Any:
    """Recursively resolve string template references used by tool arguments.

    A string is a reference only when it starts with ``$.``. Other strings,
    including ordinary text and empty strings, are left untouched.
    """
    if isinstance(value, str) and value.startswith("$."):
        try:
            return resolve_path(context, value)
        except EvaluationError as exc:
            raise ReferenceResolutionError(str(exc)) from exc
    if isinstance(value, dict):
        return {key: resolve_references(item, context) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_references(item, context) for item in value]
    return value


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _finite_number(value: Any) -> bool:
    """JSON number, excluding booleans and IEEE NaN/infinities."""
    return type(value) is int or (type(value) is float and math.isfinite(value))


def _semantic_equal(left: Any, right: Any) -> bool:
    """Strict JSON value equality, allowing int/float comparison but not bool/int."""
    if (type(left) is float and not math.isfinite(left)) or (
        type(right) is float and not math.isfinite(right)
    ):
        return False
    if _finite_number(left) and _finite_number(right):
        return left == right
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is bool and type(right) is bool and left is right
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return left.keys() == right.keys() and all(
            _semantic_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _semantic_equal(x, y) for x, y in zip(left, right)
        )
    if left is None or right is None:
        return left is right
    return type(left) is type(right) and left == right


def _apply_operator(criterion: Mapping[str, Any], actual: Any) -> tuple[bool, str]:
    """Evaluate without Python truthiness or lossy numeric coercion.

    Type mismatches must fail closed. Result is not an oracle unless the
    criterion itself is grounded in an independent reference.
    """
    operator = criterion.get("operator")
    expected = criterion.get("expected")

    if operator == "truthy":
        passed = actual is True
        return passed, "" if passed else "expected literal JSON boolean true"

    if operator == "equals":
        passed = _semantic_equal(actual, expected)
        return passed, "" if passed else "values or JSON types are not equal"

    if operator == "contains":
        if isinstance(actual, str):
            passed = isinstance(expected, str) and expected in actual
        elif isinstance(actual, Mapping):
            passed = isinstance(expected, str) and expected in actual
        elif isinstance(actual, (list, tuple)):
            passed = any(_semantic_equal(item, expected) for item in actual)
        else:
            passed = False
        return passed, "" if passed else "actual value does not contain typed expected value"

    if operator == "length_equals":
        passed = (
            type(expected) is int and expected >= 0
            and isinstance(actual, (str, list, tuple, Mapping))
            and len(actual) == expected
        )
        return passed, "" if passed else "actual length or expected length type is invalid"

    if operator == "numeric_close":
        tolerance = criterion.get("tolerance")
        if not (
            _finite_number(actual) and _finite_number(expected)
            and _finite_number(tolerance) and tolerance >= 0
        ):
            return False, "value, reference, or tolerance is not a finite JSON number"
        try:
            passed = math.isclose(actual, expected, rel_tol=0.0, abs_tol=tolerance)
        except (OverflowError, TypeError, ValueError):
            passed = False
        return passed, "" if passed else "numeric value is outside tolerance"

    if operator == "set_equals":
        if not isinstance(actual, (list, tuple)) or not isinstance(expected, (list, tuple)):
            return False, "set equality requires JSON arrays"
        try:
            passed = sorted(_canonical(item) for item in actual) == sorted(
                _canonical(item) for item in expected
            )
        except (TypeError, ValueError, OverflowError):
            passed = False
        return passed, "" if passed else "collections are not equal as sets"

    if operator in {"lte", "gte"}:
        if not (_finite_number(actual) and _finite_number(expected)):
            return False, "numeric comparison requires finite JSON numbers"
        passed = actual <= expected if operator == "lte" else actual >= expected
        return passed, "" if passed else f"numeric comparison {operator} failed"

    raise EvaluationError(f"unsupported operator: {operator!r}")


def evaluate(task: Mapping[str, Any], context: Mapping[str, Any]) -> Evaluation:
    """Apply every machine-verifiable criterion in ``task`` to ``context``."""
    criteria = task.get("success_criteria")
    if not isinstance(criteria, (list, tuple)) or not criteria:
        return Evaluation(
            passed=False,
            checks=({"id": "__criteria_present__", "target": None, "operator": None,
                     "passed": False, "actual": None, "expected": "nonempty criteria",
                     "detail": "task has no valid success criteria"},),
        )
    checks: list[dict[str, Any]] = []
    for criterion in criteria:
        if not isinstance(criterion, Mapping):
            checks.append({
                "id": "__criterion_type__", "target": None, "operator": None,
                "passed": False, "actual": None, "expected": "criterion object",
                "detail": "criterion must be a JSON object",
            })
            continue
        criterion_id = criterion.get("id")
        target = criterion.get("target")
        entry: dict[str, Any] = {
            "id": criterion_id,
            "target": target,
            "operator": criterion.get("operator"),
            "passed": False,
            "actual": None,
            "expected": criterion.get("expected"),
            "detail": "",
        }
        try:
            actual = resolve_path(context, str(target))
            entry["actual"] = actual
            passed, detail = _apply_operator(criterion, actual)
            entry["passed"] = passed
            entry["detail"] = detail
        except EvaluationError as exc:
            entry["detail"] = str(exc)
        except (KeyError, TypeError, ValueError) as exc:
            entry["detail"] = f"criterion could not be evaluated: {type(exc).__name__}: {exc}"
        checks.append(entry)

    return Evaluation(passed=all(check["passed"] for check in checks), checks=tuple(checks))


def evaluate_trace(task: Mapping[str, Any], trace: Mapping[str, Any]) -> Evaluation:
    """Re-evaluate a saved trace without trusting its recorded pass/fail fields."""
    steps = trace.get("steps")
    if not isinstance(steps, dict):
        raise EvaluationError("trace has no object field 'steps'; cannot independently evaluate")
    context = {
        "steps": steps,
        "input": trace.get("params", {}),
    }
    return evaluate(task, context)
