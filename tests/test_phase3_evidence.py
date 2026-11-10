"""Phase 3: provenance, capture, snapshots and cost gate. Offline only."""

from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path

from geoagent_m6 import capture, cost, provenance, snapshots


class TestProvenance(unittest.TestCase):
    def test_four_sources(self):
        self.assertEqual({s.value for s in provenance.Source},
                         {"LIVE", "REPLAY_FROM_LIVE", "SYNTHETIC", "UNKNOWN"})

    def test_classification_rules(self):
        table = [
            ("03_RUNS/P1/x/TRACE.json", "LIVE", {}, "LIVE"),
            ("04_REPLAY/F1/x/TRACE.json", "LIVE", {}, "REPLAY_FROM_LIVE"),
            ("04_REPLAY/F1/x/01_geo.json", "LIVE", {"origin_response_sha256": "a" * 64}, "REPLAY_FROM_LIVE"),
            ("06_EVIDENCE_INDEX/SYNTHETIC_18_BASELINE.jsonl", "SYNTHETIC", {}, "SYNTHETIC"),
            ("09_PUBLIC_MINIMAL/EXAMPLE_TRACE.json", "LIVE", {}, "REPLAY_FROM_LIVE"),
            ("07_REPORTS/COST_LEDGER.json", "LIVE", {}, "UNKNOWN"),
            ("07_REPORTS/COST_LEDGER.json", None, {}, "UNKNOWN"),
            ("04_REPLAY/REPLAY_SUMMARY.json", "REPLAY", {}, "REPLAY_FROM_LIVE"),
        ]
        for relpath, declared, doc, expected in table:
            with self.subTest(path=relpath, declared=declared):
                source, _ = provenance.classify(relpath, declared, doc)
                self.assertEqual(source.value, expected)

    def test_statistics_do_not_count_replay_as_live(self):
        entries = [
            provenance.ProvenanceEntry("03_RUNS/a/TRACE.json", "LIVE", provenance.Source.LIVE,
                                       "r", "a" * 64, "b" * 64, None, None, None, 10),
            provenance.ProvenanceEntry("04_REPLAY/F1/a/TRACE.json", "LIVE", provenance.Source.REPLAY_FROM_LIVE,
                                       "r", "c" * 64, "d" * 64, None, None, None, 10),
            provenance.ProvenanceEntry("04_REPLAY/F1/a/01_geo.json", "LIVE", provenance.Source.REPLAY_FROM_LIVE,
                                       "r", "e" * 64, "f" * 64, None, None, None, 10),
        ]
        stats = provenance.statistics(entries)
        self.assertEqual(stats["declared_live_total"], 3)
        self.assertEqual(stats["corrected_live_total"], 1)
        self.assertEqual(stats["relabelled_replay_traces"], 1)
        self.assertEqual(stats["relabelled_replay_step_files"], 1)
        self.assertEqual(stats["live_call_count_claimable_from_this_index"], 1)

    def test_verify_index_rejects_replay_left_as_live(self):
        index = {
            "entries": [
                {"relpath": "04_REPLAY/F1/x/TRACE.json", "corrected_source": "LIVE", "file_sha256": "a" * 64},
            ],
            "statistics": {"declared_live_total": 1, "corrected_live_total": 1,
                           "relabelled_away_from_live": 0},
        }
        result = provenance.verify_index(index)
        self.assertEqual(result.reason_code, "PROVENANCE_INDEX_INTEGRITY_FAILED")

    def test_build_index_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "04_REPLAY" / "F1").mkdir(parents=True)
            target = root / "04_REPLAY" / "F1" / "TRACE.json"
            payload = {"source": "LIVE", "workflow_id": "WF", "origin_response_sha256": "a" * 64}
            target.write_text(json.dumps(payload), encoding="utf-8")
            before = target.read_bytes()
            index = provenance.build_index(root)
            self.assertEqual(target.read_bytes(), before)
            self.assertEqual(index["entry_count"], 1)
            self.assertEqual(index["entries"][0]["corrected_source"], "REPLAY_FROM_LIVE")
            self.assertEqual(provenance.verify_index(index).reason_code, "PROVENANCE_INDEX_OK")


class TestCostGate(unittest.TestCase):
    def test_gate_must_precede_call(self):
        ledger = cost.CostLedger(cap_reserved=10.0)
        _, failure = ledger.commit_call(permit=None, step_id="s1", tool="geocode_address", reservation=1.0)
        self.assertEqual(failure.reason_code, "GATE_NOT_RUN_BEFORE_CALL")
        self.assertEqual(len(ledger.entries), 0)

    def test_permit_is_single_use_and_bound_to_arguments(self):
        ledger = cost.CostLedger(cap_reserved=10.0)
        permit, verdict = ledger.check_before_call(step_id="s1", tool="geocode_address", reservation=2.0)
        self.assertEqual(verdict.reason_code, "GATE_CHECKED_BEFORE_CALL")
        entry, ok_result = ledger.commit_call(permit=permit, step_id="s1", tool="geocode_address", reservation=2.0)
        self.assertEqual(ok_result.reason_code, "COST_ENTRY_COMMITTED")
        self.assertTrue(entry.gate_checked_before_call)
        _, reuse = ledger.commit_call(permit=permit, step_id="s1", tool="geocode_address", reservation=2.0)
        self.assertEqual(reuse.reason_code, "GATE_PERMIT_REUSED")
        _, mismatch = ledger.commit_call(permit=permit, step_id="s2", tool="geocode_address", reservation=2.0)
        self.assertIn(mismatch.reason_code, ("GATE_PERMIT_REUSED", "GATE_PERMIT_MISMATCH"))

    def test_gate_blocks_before_crossing_cap(self):
        ledger = cost.CostLedger(cap_reserved=5.0)
        permit, _ = ledger.check_before_call(step_id="s1", tool="t", reservation=4.0)
        ledger.commit_call(permit=permit, step_id="s1", tool="t", reservation=4.0)
        _, blocked = ledger.check_before_call(step_id="s2", tool="t", reservation=2.0)
        self.assertEqual(blocked.reason_code, "BUDGET_GATE_BLOCKED_BEFORE_CALL")
        self.assertEqual(len(ledger.entries), 1)

    def test_four_fields_and_null_observation(self):
        ledger = cost.CostLedger(cap_reserved=1000.0)
        permit, _ = ledger.check_before_call(step_id="s1", tool="t", reservation=514.0)
        ledger.commit_call(permit=permit, step_id="s1", tool="t", reservation=514.0)
        summary = ledger.summary()
        self.assertEqual(set(cost.CREDIT_FIELDS), {
            "credits_reserved", "credits_observed", "credits_estimated", "credits_unknown"})
        self.assertEqual(summary["credits_reserved"], 514.0)
        self.assertIsNone(summary["credits_observed"])
        self.assertTrue(summary["credits_unknown"])
        self.assertTrue(summary["reserved_is_not_consumption"])
        self.assertTrue(summary["all_gates_checked_before_call"])

    def test_observed_value_is_explicit(self):
        ledger = cost.CostLedger(cap_reserved=10.0)
        permit, _ = ledger.check_before_call(step_id="s1", tool="t", reservation=1.0)
        entry, _ = ledger.commit_call(permit=permit, step_id="s1", tool="t",
                                      reservation=1.0, credits_observed=1.0, credits_estimated=1.2)
        self.assertEqual(entry.credits_observed, 1.0)
        self.assertFalse(entry.credits_unknown)
        self.assertEqual(ledger.summary()["credits_observed"], 1.0)


class TestCapture(unittest.TestCase):
    def _bytes(self):
        request = json.dumps({"jsonrpc": "2.0", "id": 9, "method": "tools/call"}).encode()
        response = json.dumps({"jsonrpc": "2.0", "id": 9, "result": {
            "api_key": "SECRET_32_HEX_SHOULD_BE_REDACTED_000000",
            "structuredContent": {"count": 1, "results": [{"lat": 52.5, "lon": 13.4}]},
        }}).encode()
        return request, response

    def test_capture_verify_and_immutability(self):
        with tempfile.TemporaryDirectory() as tmp:
            sink = capture.CaptureSink(Path(tmp))
            request, response = self._bytes()
            record, failure = sink.capture(
                request_bytes=request, response_bytes=response, run_id="R1", step_id="geo",
                tool="geocode_address", capability="geocode.forward", request_id="9",
            )
            self.assertIsNone(failure)
            self.assertEqual(capture.verify_capture(record).reason_code, "CAPTURE_INTEGRITY_OK")
            before = Path(record.file_path).read_bytes()
            _, duplicate = sink.capture(
                request_bytes=request, response_bytes=response, run_id="R1", step_id="geo",
                tool="geocode_address", capability="geocode.forward", request_id="9",
            )
            self.assertEqual(duplicate.reason, "CAPTURE_TARGET_EXISTS")
            self.assertEqual(Path(record.file_path).read_bytes(), before)
            self.assertEqual(record.capture_layer, "MCP_CLIENT_OBSERVABLE")
            self.assertIn("not the provider's raw HTTP response", record.boundary_note)

    def test_secret_is_redacted_with_independent_digest(self):
        request, response = self._bytes()
        redacted, sha = capture.redact(response)
        self.assertNotIn(b"SECRET_32_HEX_SHOULD_BE_REDACTED_000000", redacted)
        self.assertNotEqual(sha, capture.sha256_bytes(response))
        self.assertEqual(capture.sha256_bytes(redacted), sha)

    def test_tampering_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            sink = capture.CaptureSink(Path(tmp))
            request, response = self._bytes()
            record, _ = sink.capture(
                request_bytes=request, response_bytes=response, run_id="R2", step_id="geo",
                tool="t", capability="c", request_id="9")
            data = record.to_dict()
            for name, mutation in (
                ("digest", {"response_sha256": "0" * 64}),
                ("correlation", {"correlation_id": "0" * 64}),
                ("layer", {"capture_layer": "PROVIDER_HTTP_RAW"}),
                ("boundary", {"boundary_note": "this is the provider raw HTTP response"}),
                ("bytes", {"response_bytes_b64": base64.b64encode(b"{}").decode()}),
            ):
                with self.subTest(mutation=name):
                    tampered = dict(data, **mutation)
                    self.assertEqual(capture.verify_capture(tampered).reason_code,
                                     "CAPTURE_INTEGRITY_FAILED")

    def test_write_failure_is_structured(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocker = Path(tmp) / "file_not_dir"
            blocker.write_text("x", encoding="utf-8")
            sink = capture.CaptureSink(blocker)
            record, failure = sink.capture(
                request_bytes=b"{}", response_bytes=b"{}", run_id="R3", step_id="s",
                tool="t", capability="c", request_id="1")
            self.assertIsNone(record)
            self.assertEqual(failure.reason, "CAPTURE_WRITE_FAILED")
            self.assertTrue(failure.retryable)


class TestSnapshots(unittest.TestCase):
    def test_preflight_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = snapshots.SnapshotStore(Path(tmp))
            first, failure = store.preflight("RUN1", {"gate": "NO_GO"},
                                            log_version="log/v1", harness_fingerprint="fp-1")
            self.assertIsNone(failure)
            _, second = store.preflight("RUN1", {"gate": "CHANGED"},
                                        log_version="log/v1", harness_fingerprint="fp-1")
            self.assertEqual(second.reason, "PREFLIGHT_ALREADY_EXISTS_FOR_RUN")
            self.assertEqual(json.loads(Path(first.file_path).read_text())["payload_sha256"],
                             snapshots.digest({"gate": "NO_GO"}))

    def test_each_run_gets_own_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = snapshots.SnapshotStore(Path(tmp))
            a, _ = store.preflight("RUN-A", {"x": 1}, log_version="log/v1", harness_fingerprint="fp")
            b, _ = store.preflight("RUN-B", {"x": 1}, log_version="log/v1", harness_fingerprint="fp",
                                   created_at="2026-11-09T00:00:01+00:00")
            self.assertNotEqual(a.snapshot_id, b.snapshot_id)

    def test_binding_requires_matching_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = snapshots.SnapshotStore(Path(tmp))
            snap, _ = store.preflight("RUN1", {"x": 1}, log_version="log/v1", harness_fingerprint="fp-1")
            _, failure = store.bind(snap.snapshot_id, manifest={"a": 1}, execution_log={"b": 2},
                                    result_summary={"c": 3}, log_version="log/v2",
                                    harness_fingerprint="fp-1")
            self.assertEqual(failure.reason, "SNAPSHOT_LOG_VERSION_OR_FINGERPRINT_MISMATCH")
            binding, ok_failure = store.bind(snap.snapshot_id, manifest={"a": 1}, execution_log={"b": 2},
                                             result_summary={"c": 3}, log_version="log/v1",
                                             harness_fingerprint="fp-1")
            self.assertIsNone(ok_failure)
            self.assertTrue(binding.before_after_complete)
            self.assertEqual(store.verify(binding).reason_code, "SNAPSHOT_BINDING_OK")

    def test_no_preflight_means_no_complete_before_after(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = snapshots.SnapshotStore(Path(tmp))
            _, failure = store.bind("MISSING", manifest={"a": 1}, execution_log={"b": 2},
                                    result_summary={"c": 3}, log_version="log/v1",
                                    harness_fingerprint="fp-1")
            self.assertEqual(failure.reason, "PREFLIGHT_MISSING_BEFORE_AFTER_FORBIDDEN")

    def test_incomplete_manifest_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = snapshots.SnapshotStore(Path(tmp))
            snap, _ = store.preflight("RUN1", {"x": 1}, log_version="log/v1", harness_fingerprint="fp")
            _, failure = store.bind(snap.snapshot_id, manifest={}, execution_log={"b": 2},
                                    result_summary={"c": 3}, log_version="log/v1",
                                    harness_fingerprint="fp")
            self.assertEqual(failure.reason, "RUN_MANIFEST_INCOMPLETE")


if __name__ == "__main__":
    unittest.main(verbosity=2)
