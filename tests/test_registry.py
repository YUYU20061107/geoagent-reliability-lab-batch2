"""Tests for the synthetic task registry."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from geoagent_reliability_lab.fixtures import FixtureStore
from geoagent_reliability_lab.registry import (
    CATEGORY_COUNTS,
    REQUIRED_FAMILIES,
    REQUIRED_SUBCATEGORIES,
    load_registry,
    validate_registry,
)

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "tasks" / "tasks.json"
FIXTURE_PATH = ROOT / "fixtures" / "mock_responses.json"


class RegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = load_registry(REGISTRY_PATH)

    def test_exactly_18_tasks_and_category_counts(self) -> None:
        self.assertEqual(len(self.registry.tasks), 18)
        self.assertEqual(len(set(self.registry.ids)), 18)
        counts = {"G": 0, "P": 0, "R": 0, "S": 0, "M": 0}
        for task in self.registry.tasks:
            counts[task["category"]] += 1
        self.assertEqual(counts, CATEGORY_COUNTS)
        self.assertEqual(counts, {"G": 3, "P": 3, "R": 4, "S": 4, "M": 4})

    def test_required_capability_and_subcategory_coverage(self) -> None:
        families = {task["capability_family"] for task in self.registry.tasks}
        subcategories = {task["subcategory"] for task in self.registry.tasks}
        self.assertEqual(families, set(REQUIRED_FAMILIES))
        self.assertTrue(set(REQUIRED_SUBCATEGORIES).issubset(subcategories))
        self.assertIn("reverse_geocoding", subcategories)
        self.assertIn("route_distance_matrix", subcategories)
        self.assertIn("spatial_relation", subcategories)
        self.assertIn("geometric_measurement", subcategories)
        multi_step = [task for task in self.registry.tasks if "multi_step_tool_chain" in task["tags"]]
        self.assertGreaterEqual(len(multi_step), 4)

    def test_duplicate_task_ids_are_rejected(self) -> None:
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        data["tasks"].append(copy.deepcopy(data["tasks"][0]))
        result = validate_registry(data)
        self.assertFalse(result.ok)
        self.assertTrue(any("duplicate task id" in error for error in result.errors))

    def test_every_registry_step_has_a_synthetic_fixture(self) -> None:
        store = FixtureStore.load(FIXTURE_PATH)
        self.assertEqual(store.validate_for_tasks(self.registry), ())
        total_steps = sum(len(task["reference_tool_chain"]) for task in self.registry.tasks)
        self.assertEqual(total_steps, 25)

    def test_all_reference_tool_chain_steps_are_abstract_and_declared(self) -> None:
        for task in self.registry.tasks:
            declared = set(task["expected_tools"])
            used = {step["tool"] for step in task["reference_tool_chain"]}
            self.assertEqual(declared, used, task["id"])
            self.assertTrue(all(tool.count(".") == 1 for tool in used), task["id"])


if __name__ == "__main__":
    unittest.main()
