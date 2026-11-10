"""Task registry loading and strict structural validation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from ._jsonio import JsonLoadError, load_json
from .errors import RegistryError

SCHEMA_VERSION = "1.0.0"

CATEGORY_COUNTS: dict[str, int] = {"G": 3, "P": 3, "R": 4, "S": 4, "M": 4}
CATEGORY_LABELS: dict[str, str] = {
    "G": "geocoding (forward, reverse, and chained)",
    "P": "place search",
    "R": "route planning and route distance matrix",
    "S": "spatial relation",
    "M": "geometric measurement",
}

ALLOWED_TOOLS: tuple[str, ...] = (
    "geocode.forward",
    "geocode.reverse",
    "places.search",
    "route.plan",
    "route.matrix",
    "spatial.relate",
    "geometry.measure",
)

ALLOWED_FAMILIES: tuple[str, ...] = (
    "geocoding",
    "place_search",
    "reverse_geocoding",
    "route_planning",
    "route_distance_matrix",
    "spatial_relation",
    "geometric_measurement",
)

REQUIRED_FAMILIES: tuple[str, ...] = ALLOWED_FAMILIES
REQUIRED_SUBCATEGORIES: tuple[str, ...] = (
    "reverse_geocoding",
    "route_distance_matrix",
    "spatial_relation",
    "geometric_measurement",
)

ALLOWED_ORACLE_TYPES: tuple[str, ...] = (
    "fixture_exact",
    "fixture_tolerance",
    "fixture_boolean",
    "fixture_set",
)

ALLOWED_OPERATORS: tuple[str, ...] = (
    "equals",
    "contains",
    "length_equals",
    "numeric_close",
    "set_equals",
    "truthy",
    "lte",
    "gte",
)

REQUIRED_TASK_FIELDS: tuple[str, ...] = (
    "id",
    "category",
    "subcategory",
    "capability_family",
    "title",
    "description",
    "user_prompt",
    "input_spec",
    "reference_tool_chain",
    "expected_tools",
    "success_criteria",
    "oracle_type",
    "assumptions",
    "dynamic_data_handling",
    "source",
    "tags",
)

TASK_ID_RE = re.compile(r"^(?P<category>[GPRSM])-(?P<number>\d{3})$")
STEP_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


@dataclass(frozen=True)
class ValidationResult:
    """Machine-readable outcome of registry validation."""

    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    category_counts: Mapping[str, int] = field(default_factory=dict)
    family_counts: Mapping[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class Registry:
    """A validated registry loaded from disk."""

    path: Path
    schema_version: str
    meta: Mapping[str, Any]
    tasks: tuple[Mapping[str, Any], ...]

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(str(task["id"]) for task in self.tasks)

    def by_id(self, task_id: str) -> Mapping[str, Any]:
        for task in self.tasks:
            if task["id"] == task_id:
                return task
        raise KeyError(task_id)

    def select(self, task_ids: list[str] | tuple[str, ...] | None) -> tuple[Mapping[str, Any], ...]:
        if not task_ids:
            return self.tasks
        selected: list[Mapping[str, Any]] = []
        known = set(self.ids)
        for task_id in task_ids:
            if task_id not in known:
                raise RegistryError(f"unknown task id: {task_id!r}")
            selected.append(self.by_id(task_id))
        return tuple(selected)


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_registry(data: Any) -> ValidationResult:
    """Validate a decoded registry object without loading fixtures.

    Validation intentionally fails closed: exactly 18 tasks, the requested
    category counts, unique IDs, complete fields, and the required capability
    families are all checked.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(data, dict):
        return ValidationResult(errors=("registry root must be a JSON object",))

    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION!r}")

    meta = data.get("meta")
    if not isinstance(meta, dict):
        errors.append("meta must be an object")
    else:
        if meta.get("synthetic_only") is not True:
            errors.append("meta.synthetic_only must be true")
        if meta.get("real_api_verified") is not False:
            errors.append("meta.real_api_verified must be false")
        expected_counts = meta.get("expected_category_counts")
        if expected_counts != CATEGORY_COUNTS:
            errors.append(f"meta.expected_category_counts must equal {CATEGORY_COUNTS!r}")

    tasks = data.get("tasks")
    if not isinstance(tasks, list):
        return ValidationResult(errors=tuple(errors + ["tasks must be an array"]))

    if len(tasks) != 18:
        errors.append(f"tasks must contain exactly 18 entries, found {len(tasks)}")

    id_list: list[str] = []
    category_counts: dict[str, int] = {key: 0 for key in CATEGORY_COUNTS}
    family_counts: dict[str, int] = {key: 0 for key in ALLOWED_FAMILIES}
    subcategories: set[str] = set()
    multi_step_count = 0

    for index, task in enumerate(tasks):
        label = f"tasks[{index}]"
        if not isinstance(task, dict):
            errors.append(f"{label} must be an object")
            continue

        raw_id = task.get("id")
        if _is_nonempty_str(raw_id):
            task_id = str(raw_id)
            id_list.append(task_id)
            label = task_id
            match = TASK_ID_RE.match(task_id)
            if not match:
                errors.append(f"{label}: id must match G-001 style pattern")
        else:
            errors.append(f"{label}: id must be a non-empty string")

        for field_name in REQUIRED_TASK_FIELDS:
            if field_name not in task:
                errors.append(f"{label}: missing required field {field_name!r}")

        category = task.get("category")
        if category not in CATEGORY_COUNTS:
            errors.append(f"{label}: category must be one of G, P, R, S, M")
        else:
            category_counts[str(category)] += 1
            if _is_nonempty_str(raw_id):
                match = TASK_ID_RE.match(str(raw_id))
                if match and match.group("category") != category:
                    errors.append(f"{label}: id prefix does not match category {category!r}")

        if not _is_nonempty_str(task.get("subcategory")):
            errors.append(f"{label}: subcategory must be a non-empty string")
        else:
            subcategories.add(str(task["subcategory"]))

        family = task.get("capability_family")
        if family not in ALLOWED_FAMILIES:
            errors.append(f"{label}: capability_family must be one of {', '.join(ALLOWED_FAMILIES)}")
        else:
            family_counts[str(family)] += 1

        for text_field in ("title", "description", "user_prompt"):
            if not _is_nonempty_str(task.get(text_field)):
                errors.append(f"{label}: {text_field} must be a non-empty string")

        input_spec = task.get("input_spec")
        if not isinstance(input_spec, dict):
            errors.append(f"{label}: input_spec must be an object")
        else:
            if input_spec.get("type") != "object":
                errors.append(f"{label}: input_spec.type must be 'object'")
            required_inputs = input_spec.get("required")
            sample = input_spec.get("sample")
            if not isinstance(required_inputs, list) or not all(
                isinstance(item, str) for item in required_inputs
            ):
                errors.append(f"{label}: input_spec.required must be an array of strings")
            if not isinstance(sample, dict):
                errors.append(f"{label}: input_spec.sample must be an object")
            elif isinstance(required_inputs, list):
                for key in required_inputs:
                    if isinstance(key, str) and key not in sample:
                        errors.append(f"{label}: input_spec.sample is missing required key {key!r}")
            if not isinstance(input_spec.get("properties"), dict):
                errors.append(f"{label}: input_spec.properties must be an object")

        chain = task.get("reference_tool_chain")
        chain_tools: list[str] = []
        if not isinstance(chain, list) or not chain:
            errors.append(f"{label}: reference_tool_chain must be a non-empty array")
        else:
            seen_steps: set[str] = set()
            for step_index, step in enumerate(chain):
                step_label = f"{label}.reference_tool_chain[{step_index}]"
                if not isinstance(step, dict):
                    errors.append(f"{step_label}: must be an object")
                    continue
                step_id = step.get("step_id")
                if not _is_nonempty_str(step_id) or not STEP_ID_RE.match(str(step_id)):
                    errors.append(f"{step_label}: step_id must match lowercase_snake_case")
                elif str(step_id) in seen_steps:
                    errors.append(f"{step_label}: duplicate step_id {step_id!r}")
                else:
                    seen_steps.add(str(step_id))
                tool = step.get("tool")
                if tool not in ALLOWED_TOOLS:
                    errors.append(f"{step_label}: unknown abstract tool {tool!r}")
                else:
                    chain_tools.append(str(tool))
                if not isinstance(step.get("arguments"), dict):
                    errors.append(f"{step_label}: arguments must be an object")
                if not _is_nonempty_str(step.get("purpose")):
                    errors.append(f"{step_label}: purpose must be a non-empty string")

        expected_tools = task.get("expected_tools")
        if not isinstance(expected_tools, list) or not expected_tools:
            errors.append(f"{label}: expected_tools must be a non-empty array")
        else:
            if len(set(map(str, expected_tools))) != len(expected_tools):
                errors.append(f"{label}: expected_tools contains duplicates")
            for tool in expected_tools:
                if tool not in ALLOWED_TOOLS:
                    errors.append(f"{label}: expected_tools contains unknown tool {tool!r}")
            if set(map(str, expected_tools)) != set(chain_tools):
                errors.append(f"{label}: expected_tools must equal the tools used in reference_tool_chain")

        criteria = task.get("success_criteria")
        if not isinstance(criteria, list) or not criteria:
            errors.append(f"{label}: success_criteria must be a non-empty array")
        else:
            criterion_ids: set[str] = set()
            for criterion_index, criterion in enumerate(criteria):
                criterion_label = f"{label}.success_criteria[{criterion_index}]"
                if not isinstance(criterion, dict):
                    errors.append(f"{criterion_label}: must be an object")
                    continue
                criterion_id = criterion.get("id")
                if not _is_nonempty_str(criterion_id):
                    errors.append(f"{criterion_label}: id must be a non-empty string")
                elif str(criterion_id) in criterion_ids:
                    errors.append(f"{criterion_label}: duplicate criterion id {criterion_id!r}")
                else:
                    criterion_ids.add(str(criterion_id))
                target = criterion.get("target")
                if not _is_nonempty_str(target) or not str(target).startswith("$."):
                    errors.append(f"{criterion_label}: target must start with '$.'")
                operator = criterion.get("operator")
                if operator not in ALLOWED_OPERATORS:
                    errors.append(f"{criterion_label}: unsupported operator {operator!r}")
                elif operator == "numeric_close":
                    if not isinstance(criterion.get("tolerance"), (int, float)):
                        errors.append(f"{criterion_label}: numeric_close needs a numeric tolerance")
                elif operator in {"equals", "contains", "length_equals", "set_equals", "lte", "gte"}:
                    if "expected" not in criterion:
                        errors.append(f"{criterion_label}: {operator} needs expected")

        if task.get("oracle_type") not in ALLOWED_ORACLE_TYPES:
            errors.append(f"{label}: oracle_type must be one of {', '.join(ALLOWED_ORACLE_TYPES)}")

        assumptions = task.get("assumptions")
        if not isinstance(assumptions, list) or not assumptions or not all(
            _is_nonempty_str(item) for item in assumptions
        ):
            errors.append(f"{label}: assumptions must be a non-empty array of strings")

        dynamic = task.get("dynamic_data_handling")
        if not isinstance(dynamic, dict):
            errors.append(f"{label}: dynamic_data_handling must be an object")
        else:
            if not _is_nonempty_str(dynamic.get("strategy")):
                errors.append(f"{label}: dynamic_data_handling.strategy must be a string")
            if not _is_nonempty_str(dynamic.get("note")):
                errors.append(f"{label}: dynamic_data_handling.note must be a string")

        source = task.get("source")
        if not isinstance(source, dict):
            errors.append(f"{label}: source must be an object")
        else:
            if source.get("kind") != "synthetic":
                errors.append(f"{label}: source.kind must be 'synthetic'")
            if source.get("synthetic") is not True:
                errors.append(f"{label}: source.synthetic must be true")
            if not _is_nonempty_str(source.get("fixture_id")):
                errors.append(f"{label}: source.fixture_id must be a non-empty string")

        tags = task.get("tags")
        if not isinstance(tags, list) or not tags or not all(_is_nonempty_str(tag) for tag in tags):
            errors.append(f"{label}: tags must be a non-empty array of strings")
        elif len(set(map(str, tags))) != len(tags):
            errors.append(f"{label}: tags contains duplicates")
        elif "multi_step_tool_chain" in tags:
            multi_step_count += 1
            if not isinstance(chain, list) or len(chain) < 2:
                errors.append(f"{label}: multi_step_tool_chain tag needs at least 2 tool calls")

    duplicate_ids = sorted({task_id for task_id in id_list if id_list.count(task_id) > 1})
    for task_id in duplicate_ids:
        errors.append(f"duplicate task id: {task_id}")

    for category, expected in CATEGORY_COUNTS.items():
        actual = category_counts.get(category, 0)
        if actual != expected:
            errors.append(f"category {category} must contain {expected} tasks, found {actual}")

    missing_families = sorted(set(REQUIRED_FAMILIES) - {key for key, value in family_counts.items() if value})
    for family in missing_families:
        errors.append(f"missing required capability family: {family}")

    missing_subcategories = sorted(set(REQUIRED_SUBCATEGORIES) - subcategories)
    for subcategory in missing_subcategories:
        errors.append(f"missing required subcategory: {subcategory}")

    if multi_step_count < 4:
        errors.append(f"at least 4 tasks must be tagged multi_step_tool_chain, found {multi_step_count}")

    if not errors:
        warnings.append("Registry is synthetic-only; no real API behavior or response is verified.")

    return ValidationResult(
        errors=tuple(errors),
        warnings=tuple(warnings),
        category_counts=category_counts,
        family_counts=family_counts,
    )


def load_registry(path: str | Path) -> Registry:
    """Load and validate a registry, raising ``RegistryError`` on any issue."""
    registry_path = Path(path)
    try:
        data = load_json(registry_path)
    except JsonLoadError as exc:
        raise RegistryError(str(exc)) from exc

    result = validate_registry(data)
    if not result.ok:
        details = "\n".join(f"- {error}" for error in result.errors)
        raise RegistryError(f"Registry validation failed ({len(result.errors)} issue(s)):\n{details}")

    assert isinstance(data, dict)
    return Registry(
        path=registry_path,
        schema_version=str(data["schema_version"]),
        meta=dict(data["meta"]),
        tasks=tuple(data["tasks"]),
    )
