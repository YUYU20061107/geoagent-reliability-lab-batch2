"""Synthetic fixture loading and replay.

Every response in the fixture store is invented for this repository and marked
``"synthetic": true``. It is never a captured Geoapify response.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ._jsonio import JsonLoadError, load_json
from .errors import FixtureError
from .registry import ALLOWED_TOOLS, Registry


@dataclass(frozen=True)
class FixtureResponse:
    """One deterministic fixture response for one tool-chain step."""

    task_id: str
    step_id: str
    capability: str
    result: Mapping[str, Any]
    path: Path

    @property
    def fixture_ref(self) -> str:
        return f"{self.task_id}.{self.step_id}"


@dataclass(frozen=True)
class FixtureStore:
    """A validated, offline-only response store."""

    path: Path
    meta: Mapping[str, Any]
    responses: Mapping[str, Mapping[str, Mapping[str, Any]]]

    @classmethod
    def load(cls, path: str | Path) -> "FixtureStore":
        fixture_path = Path(path)
        try:
            data = load_json(fixture_path)
        except JsonLoadError as exc:
            raise FixtureError(str(exc)) from exc

        errors = _validate_fixture_shape(data, fixture_path)
        if errors:
            details = "\n".join(f"- {error}" for error in errors)
            raise FixtureError(f"Fixture validation failed ({len(errors)} issue(s)):\n{details}")

        assert isinstance(data, dict)
        return cls(
            path=fixture_path,
            meta=dict(data["meta"]),
            responses=dict(data["responses"]),
        )

    def get(self, task_id: str, step_id: str, expected_capability: str) -> FixtureResponse:
        """Return a response, rejecting missing, unknown, or mismatched entries."""
        task_responses = self.responses.get(task_id)
        if not isinstance(task_responses, dict):
            raise FixtureError(f"no fixture responses for task {task_id!r} in {self.path}")
        entry = task_responses.get(step_id)
        if not isinstance(entry, dict):
            raise FixtureError(f"no fixture response for {task_id}.{step_id} in {self.path}")
        capability = entry.get("capability")
        if capability != expected_capability:
            raise FixtureError(
                f"fixture capability mismatch for {task_id}.{step_id}: "
                f"task expects {expected_capability!r}, fixture declares {capability!r}"
            )
        result = entry.get("result")
        if not isinstance(result, dict) or result.get("synthetic") is not True:
            raise FixtureError(f"fixture result for {task_id}.{step_id} must be an object with synthetic=true")
        return FixtureResponse(
            task_id=task_id,
            step_id=step_id,
            capability=str(capability),
            result=result,
            path=self.path,
        )

    def validate_for_tasks(self, registry: Registry) -> tuple[str, ...]:
        """Check that every registry step has exactly matching fixture coverage."""
        errors: list[str] = []
        expected_steps = 0
        for task in registry.tasks:
            task_id = str(task["id"])
            for step in task["reference_tool_chain"]:
                expected_steps += 1
                step_id = str(step["step_id"])
                try:
                    self.get(task_id, step_id, str(step["tool"]))
                except FixtureError as exc:
                    errors.append(str(exc))
        if not errors:
            return ()
        return tuple(errors + [f"expected {expected_steps} fixture entries across {len(registry.tasks)} tasks"])


def _validate_fixture_shape(data: Any, path: Path) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return [f"{path}: fixture root must be an object"]
    if data.get("schema_version") != "1.0.0":
        errors.append(f"{path}: schema_version must be '1.0.0'")
    meta = data.get("meta")
    if not isinstance(meta, dict):
        errors.append(f"{path}: meta must be an object")
    else:
        if meta.get("mode") != "synthetic_mock":
            errors.append(f"{path}: meta.mode must be 'synthetic_mock'")
        if meta.get("real_api") is not False:
            errors.append(f"{path}: meta.real_api must be false")
        if meta.get("network") is not False:
            errors.append(f"{path}: meta.network must be false")

    responses = data.get("responses")
    if not isinstance(responses, dict):
        return errors + [f"{path}: responses must be an object"]

    for task_id, task_responses in responses.items():
        if not isinstance(task_id, str) or not task_id:
            errors.append(f"{path}: response keys must be non-empty task IDs")
            continue
        if not isinstance(task_responses, dict):
            errors.append(f"{path}: responses[{task_id!r}] must be an object")
            continue
        for step_id, entry in task_responses.items():
            label = f"{path}: responses[{task_id!r}][{step_id!r}]"
            if not isinstance(step_id, str) or not step_id:
                errors.append(f"{label}: step ID must be a non-empty string")
                continue
            if not isinstance(entry, dict):
                errors.append(f"{label} must be an object")
                continue
            if entry.get("capability") not in ALLOWED_TOOLS:
                errors.append(f"{label}: unknown capability {entry.get('capability')!r}")
            result = entry.get("result")
            if not isinstance(result, dict):
                errors.append(f"{label}: result must be an object")
            elif result.get("synthetic") is not True:
                errors.append(f"{label}: result.synthetic must be true")

    return errors
