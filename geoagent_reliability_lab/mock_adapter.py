"""Deterministic mock adapter, completely separate from any future live adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .argument_contract import arguments_match, find_coordinate_violation
from .errors import ArgumentContractError, FixtureError, ToolExecutionError
from .fixtures import FixtureStore

SUPPORTED_FAILURE_MODES: tuple[str, ...] = ("tool_error",)


@dataclass(frozen=True)
class MockInvocation:
    """One successful fixture lookup."""

    result: Mapping[str, Any]
    fixture_ref: str
    source_path: str


@dataclass(frozen=True)
class MockAdapter:
    """Replay synthetic fixture responses; never touches the network.

    ``failure_mode='tool_error'`` is an explicit fault-injection hook used to
    prove that failures are recorded. It is not a claim about Geoapify behavior.

    ``argument_contract`` (G0.1-B) makes the adapter refuse invocations whose
    arguments differ from the arguments derived from the task reference chain.
    It is optional so library callers keep the historical replay behavior, while
    the CLI enables it by default (fail closed).
    """

    fixtures: FixtureStore
    failure_mode: str | None = None
    failure_task: str | None = None
    argument_contract: Mapping[str, Mapping[str, Mapping[str, Any]]] | None = None

    def __post_init__(self) -> None:
        if self.failure_mode is not None and self.failure_mode not in SUPPORTED_FAILURE_MODES:
            raise ValueError(f"unsupported mock failure mode: {self.failure_mode!r}")

    @property
    def source_path(self) -> str:
        return str(self.fixtures.path)

    def invoke(
        self,
        task_id: str,
        step: Mapping[str, Any],
        arguments: Mapping[str, Any],
    ) -> MockInvocation:
        """Return a frozen fixture response or raise an explicit injected error."""
        step_id = str(step["step_id"])
        if self.failure_mode == "tool_error" and self.failure_task in (None, task_id):
            raise ToolExecutionError(
                "INJECTED_TOOL_ERROR",
                f"Injected synthetic tool error at {task_id}.{step_id}",
            )

        if self.argument_contract is not None:
            expected = (self.argument_contract.get(task_id) or {}).get(step_id)
            if expected is None:
                raise FixtureError(f"no derived argument contract for {task_id}.{step_id}")
            violation = find_coordinate_violation(arguments)
            if violation is not None:
                raise ArgumentContractError(
                    "MOCK_ARGUMENT_COORDINATE_RANGE",
                    f"{task_id}.{step_id}: argument {violation} is out of range or non-finite",
                )
            matched, difference = arguments_match(arguments, expected)
            if not matched:
                raise ArgumentContractError(
                    "MOCK_ARGUMENT_CONTRACT_MISMATCH",
                    f"{task_id}.{step_id}: argument {difference} does not match the derived contract",
                )
        else:
            # Historical replay behavior: arguments are recorded by the runner.
            del arguments

        response = self.fixtures.get(task_id, step_id, str(step["tool"]))
        return MockInvocation(
            result=response.result,
            fixture_ref=response.fixture_ref,
            source_path=str(response.path),
        )
