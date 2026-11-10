"""Strict JSON loading helpers.

Duplicate object keys are rejected instead of silently keeping the last value.
This is important for task IDs and fixture step IDs, where a silent overwrite
would make an evaluation result look more complete than it is.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class JsonLoadError(ValueError):
    """Raised when a JSON file cannot be read or parsed."""


class DuplicateJsonKeyError(JsonLoadError):
    """Raised when a JSON object contains the same key twice."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise DuplicateJsonKeyError(f"duplicate JSON object key: {key!r}")
        output[key] = value
    return output


def load_json(path: str | Path) -> Any:
    """Load UTF-8 JSON, rejecting duplicate object keys and invalid syntax."""
    json_path = Path(path)
    try:
        text = json_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise JsonLoadError(f"cannot read JSON file {json_path}: {exc}") from exc

    try:
        return json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise JsonLoadError(
            f"invalid JSON in {json_path} at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
