"""Shared exception types."""

from __future__ import annotations


class LabError(Exception):
    """Base class for expected, user-facing lab errors."""


class RegistryError(LabError):
    """The task registry is missing, malformed, or fails validation."""


class FixtureError(LabError):
    """A synthetic fixture is missing or inconsistent with the registry."""


class EvaluationError(LabError):
    """A success criterion cannot be resolved."""


class ReferenceResolutionError(EvaluationError):
    """A tool argument reference such as ``$steps.search.results[0]`` is invalid."""


class ToolExecutionError(LabError):
    """A mock tool call failed explicitly."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ArgumentContractError(ToolExecutionError):
    """A mock invocation violated the declared tool-argument contract."""


class BudgetExceeded(LabError):
    """A run stopped before crossing a configured budget boundary."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class TraceFormatError(LabError):
    """A JSONL trace file cannot be read or has an invalid record shape."""
