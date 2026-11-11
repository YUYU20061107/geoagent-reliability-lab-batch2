import unittest

from geoagent_m6 import adapter
from geoagent_m6.outcomes import Outcome


def envelope(data):
    return {"jsonrpc": "2.0", "id": 1, "result": {"structuredContent": data}}


class TestTimezoneAdapter(unittest.TestCase):
    def test_known_timezones(self):
        cases = [
            ("Europe/Berlin", 3600),
            ("America/New_York", -18000),
            ("Asia/Tokyo", 32400),
        ]
        for city, offset in cases:
            with self.subTest(city=city):
                result = adapter.adapt(
                    envelope({
                        "tzdb_version": "2026e",
                        "timezones": [{"name": city, "offset_seconds": offset}],
                    }),
                    capability="timezone.lookup",
                    arguments={"lat": 52.51, "lon": 13.39},
                )
                self.assertEqual(result.step.verdict.outcome, Outcome.SUCCESS)
                self.assertEqual(result.step.read["timezone_name"], city)
                self.assertEqual(result.step.read["utc_offset_seconds"], offset)
                self.assertTrue(any("timezones[0]" in x["path"] for x in result.step.consumed))

    def test_missing_timezone_list_refused(self):
        result = adapter.adapt(envelope({"tzdb_version": "2026e"}), capability="timezone.lookup")
        self.assertEqual(result.step.verdict.outcome, Outcome.EVIDENCE_MISSING)
        self.assertEqual(result.step.verdict.reason_code, "TIMEZONE_NAME_OR_OFFSET_MISSING")

    def test_wrong_offset_type_refused(self):
        result = adapter.adapt(
            envelope({"timezones": [{"name": "Asia/Tokyo", "offset_seconds": "32400"}]}),
            capability="timezone.lookup",
        )
        self.assertEqual(result.step.verdict.outcome, Outcome.EVIDENCE_MISSING)

    def test_out_of_range_offset_refused(self):
        result = adapter.adapt(
            envelope({"timezones": [{"name": "Asia/Tokyo", "offset_seconds": 999999}]}),
            capability="timezone.lookup",
        )
        self.assertEqual(result.step.verdict.outcome, Outcome.EVIDENCE_MISSING)


if __name__ == "__main__":
    unittest.main()
