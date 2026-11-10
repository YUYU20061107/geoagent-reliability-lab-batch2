"""Phase 4: the offline fault-attribution matrix is part of the test suite."""

from __future__ import annotations

import unittest

from geoagent_m6 import regression


class TestRegressionMatrix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = regression.run_matrix()

    def test_every_case_passes_its_expected_verdict(self):
        failures = [(r["case_id"], r["expected_outcome"], r["expected_reason"],
                     r["observed_outcome"], r["observed_reason"])
                    for r in self.report["results"] if not r["passed"]]
        self.assertEqual(failures, [], f"unexpected verdicts: {failures}")
        self.assertEqual(self.report["failed"], 0)

    def test_every_case_declares_an_expected_outcome(self):
        self.assertTrue(self.report["expected_verdict_required_for_every_case"])
        for row in self.report["results"]:
            with self.subTest(case=row["case_id"]):
                self.assertIn(row["expected_outcome"],
                              {"SUCCESS", "EMPTY_RESULT", "INVALID_ARGUMENT", "PROVIDER_ERROR",
                               "CAPABILITY_UNAVAILABLE", "EVIDENCE_MISSING", "SEMANTIC_CONFLICT",
                               "SAFE_ABSTENTION"})
                self.assertNotIn(row["observed_outcome"], ("INTERNAL_ERROR", "UNKNOWN"))

    def test_all_five_families_covered(self):
        for key in ("A_PARAMETER_SEMANTICS", "B_RESPONSE_STRUCTURE", "C_EXECUTION_EVIDENCE",
                    "D_MULTISTEP_CHAIN", "X_COMBINED"):
            with self.subTest(family=key):
                entry = self.report["by_category"][key]
                self.assertGreater(entry["total"], 0)
                self.assertEqual(entry["failed"], 0)

    def test_real_shapes_used_as_substrate(self):
        self.assertIn("geocode_address", self.report["real_shape_tools_available"])
        self.assertIn("REPLAY_FROM_LIVE", self.report["fixture_origin"])
        self.assertFalse(self.report["network"])
        self.assertEqual(self.report["provider_calls"], 0)

    def test_historical_failures_retained(self):
        self.assertEqual(self.report["retained_historical_failure_ids"],
                         ["P2-M5", "P2-S4", "P3-X6"])
        self.assertFalse(self.report["historical_failures_rewritten"])

    def test_attribution_matrix_is_complete(self):
        self.assertEqual(len(self.report["failure_attribution_matrix"]), self.report["total_cases"])
        for row in self.report["failure_attribution_matrix"]:
            self.assertTrue(row["reproducible"])
            self.assertTrue(row["observed_reason"])

    def test_matrix_is_deterministic(self):
        again = regression.run_matrix()
        self.assertEqual(
            [(r["case_id"], r["observed_outcome"], r["observed_reason"]) for r in self.report["results"]],
            [(r["case_id"], r["observed_outcome"], r["observed_reason"]) for r in again["results"]],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
