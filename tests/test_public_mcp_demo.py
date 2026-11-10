import importlib.util
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "examples" / "geoapify_mcp_two_step.py"
spec = importlib.util.spec_from_file_location("geoapify_mcp_two_step", SCRIPT)
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


class PublicDemoTests(unittest.TestCase):
    def test_synthetic_two_steps_and_verified_lineage(self):
        session = demo.McpSession()
        result = demo.run_chain(session)
        self.assertEqual(result["source"], "SYNTHETIC")
        self.assertEqual(result["network_tools_calls"], 0)
        self.assertEqual(result["simulated_tools_calls"], 2)
        self.assertTrue(result["lineage"]["arguments_equal_first_response"])
        self.assertEqual(result["dispatch_lineage"], "PASS")
        self.assertEqual(result["independent_geographic_oracle"], "UNKNOWN")
        self.assertEqual(result["credits_observed"], None)

    def test_request_hashes_are_present_and_individual(self):
        result = demo.run_chain(demo.McpSession())
        captured = result["request_response_hashes"]
        self.assertEqual(len(captured), 2)
        self.assertNotEqual(captured[0]["request_sha256"], captured[1]["request_sha256"])
        self.assertEqual(captured[0]["capture_layer"], "SYNTHETIC")

    def test_unsupported_tool_refused_without_booking(self):
        session = demo.McpSession()
        with self.assertRaisesRegex(demo.DemoError, "TOOL_NOT_WHITELISTED"):
            session.post("tools/call", {"name": "calculate_route", "arguments": {}})
        self.assertEqual(session.calls, 0)

    def test_live_requires_explicit_approval_before_key_access(self):
        cmd = [sys.executable, str(SCRIPT), "--live"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--authorize-two-calls", result.stderr)

    def test_live_key_missing_refused(self):
        env = dict(os.environ)
        env.pop("GEOAPIFY_API_KEY", None)
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--live", "--authorize-two-calls"],
            capture_output=True, text=True, env=env, timeout=15
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("GEOAPIFY_API_KEY_MISSING", result.stderr)

    def test_invalid_coordinates_refused(self):
        for point in [
            {"lat": 91, "lon": 13},
            {"lat": 52.5, "lon": 181},
            {"lat": "52.5", "lon": 13},
            {"lat": float("nan"), "lon": 13},
        ]:
            with self.subTest(point=point):
                with self.assertRaises(demo.DemoError):
                    demo.first_coordinates({"structuredContent": {"results": [point]}})

    def test_missing_source_field_no_fallback(self):
        with self.assertRaisesRegex(demo.DemoError, "INVALID_COORDINATE_TYPE"):
            demo.first_coordinates({"structuredContent": {"results": [{"lat": 52.5}]}})

    def test_hard_two_call_cap(self):
        session = demo.McpSession()
        demo.run_chain(session)
        with self.assertRaisesRegex(demo.DemoError, "CALL_OR_CREDIT_CEILING"):
            session.post("tools/call", {
                "name": "geocode_address",
                "arguments": {"query": "another"}
            })
        self.assertEqual(session.calls, 2)

    def test_existing_output_blocks_live_before_request(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder) / "already_exists.json"
            dest.write_text("keep", encoding="utf-8")
            env = dict(os.environ)
            env["GEOAPIFY_API_KEY"] = "NOT_A_REAL_KEY"
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--live", "--authorize-two-calls", "--out", str(dest)],
                capture_output=True, text=True, env=env, timeout=15,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("already exists", result.stderr)
            self.assertEqual(dest.read_text(encoding="utf-8"), "keep")

    def test_dry_run_cli_is_offline(self):
        env = dict(os.environ)
        env["GEOAPIFY_API_KEY"] = "NOT_A_REAL_KEY"
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            capture_output=True, text=True, env=env, timeout=15
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["source"], "SYNTHETIC")
        self.assertEqual(payload["network_tools_calls"], 0)
        self.assertNotIn("NOT_A_REAL_KEY", result.stdout)


if __name__ == "__main__":
    unittest.main()
