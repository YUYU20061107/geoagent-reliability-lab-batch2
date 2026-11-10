"""Immutable preflight snapshots and run bindings.

Addresses the 19:22 same-name overwrite incident of the M5 pilot: a preflight
snapshot is never overwritten, every run gets its own snapshot identity, and a
complete before/after comparison is only claimable when a valid preflight
snapshot, run manifest, execution log and result summary are all bound to the
same run fingerprint and log version.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .outcomes import SEMANTIC_CONFLICT, Verdict, ok, verdict

SNAPSHOT_SCHEMA = "geoagent.m6.snapshot/1"


def digest(value: Any) -> str:
    blob = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Failure:
    reason: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"reason": self.reason, "detail": self.detail}


@dataclass(frozen=True)
class Snapshot:
    snapshot_id: str
    run_id: str
    created_at: str
    log_version: str
    harness_fingerprint: str
    payload_sha256: str
    file_path: str

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


@dataclass(frozen=True)
class Binding:
    binding_id: str
    snapshot_id: str
    run_id: str
    manifest_sha256: str
    execution_log_sha256: str
    result_summary_sha256: str
    log_version: str
    harness_fingerprint: str
    before_after_complete: bool
    note: str
    file_path: str

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


class SnapshotStore:
    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    def _path(self, name: str) -> Path:
        return self.directory / name

    def preflight(self, run_id: str, payload: Mapping[str, Any], *,
                  log_version: str, harness_fingerprint: str,
                  created_at: str | None = None) -> tuple[Snapshot | None, Failure | None]:
        stamp = created_at or datetime.now(timezone.utc).isoformat()
        payload_sha = digest(payload)
        snapshot_id = hashlib.sha256(
            f"{run_id}|{stamp}|{payload_sha}|{log_version}".encode("utf-8")
        ).hexdigest()[:20]
        target = self._path(f"PREFLIGHT__{snapshot_id}.json")
        for existing in self.directory.glob("PREFLIGHT__*.json") if self.directory.exists() else []:
            try:
                prior = json.loads(existing.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            if prior.get("run_id") == run_id:
                return None, Failure(
                    "PREFLIGHT_ALREADY_EXISTS_FOR_RUN",
                    f"run {run_id} already has {existing.name}; create a new run identity instead of overwriting",
                )
        if target.exists():
            return None, Failure("PREFLIGHT_TARGET_EXISTS", f"immutable target present: {target.name}")
        snapshot = Snapshot(snapshot_id, run_id, stamp, log_version, harness_fingerprint, payload_sha, str(target))
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            return None, Failure("PREFLIGHT_WRITE_FAILED", f"{type(exc).__name__}: {exc}")
        return snapshot, None

    def bind(self, snapshot_id: str, *, manifest: Mapping[str, Any],
             execution_log: Mapping[str, Any], result_summary: Mapping[str, Any],
             log_version: str, harness_fingerprint: str) -> tuple[Binding | None, Failure | None]:
        snapshot_path = self._path(f"PREFLIGHT__{snapshot_id}.json")
        if not snapshot_path.exists():
            return None, Failure(
                "PREFLIGHT_MISSING_BEFORE_AFTER_FORBIDDEN",
                "no valid pre-call snapshot; a complete before/after comparison cannot be claimed",
            )
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        if snapshot.get("log_version") != log_version or snapshot.get("harness_fingerprint") != harness_fingerprint:
            return None, Failure(
                "SNAPSHOT_LOG_VERSION_OR_FINGERPRINT_MISMATCH",
                "run fingerprint and log version must match the preflight snapshot exactly",
            )
        if not all(isinstance(x, Mapping) and x for x in (manifest, execution_log, result_summary)):
            return None, Failure("RUN_MANIFEST_INCOMPLETE",
                                 "manifest, execution log and result summary must all be non-empty")
        manifest_sha = digest(manifest)
        log_sha = digest(execution_log)
        summary_sha = digest(result_summary)
        binding_id = hashlib.sha256(
            f"{snapshot_id}|{manifest_sha}|{log_sha}|{summary_sha}".encode()
        ).hexdigest()[:20]
        target = self._path(f"BINDING__{binding_id}.json")
        if target.exists():
            return None, Failure("BINDING_TARGET_EXISTS", f"immutable target present: {target.name}")
        binding = Binding(
            binding_id, snapshot_id, snapshot["run_id"], manifest_sha, log_sha, summary_sha,
            log_version, harness_fingerprint, True,
            "preflight snapshot + run manifest + execution log + result summary bound to one run fingerprint",
            str(target),
        )
        try:
            target.write_text(json.dumps(binding.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            return None, Failure("BINDING_WRITE_FAILED", f"{type(exc).__name__}: {exc}")
        return binding, None

    def verify(self, binding: Binding | Mapping[str, Any]) -> Verdict:
        data = binding.to_dict() if isinstance(binding, Binding) else dict(binding)
        problems: list[str] = []
        snapshot_path = self._path(f"PREFLIGHT__{data.get('snapshot_id')}.json")
        if not snapshot_path.exists():
            problems.append("BOUND_PREFLIGHT_SNAPSHOT_MISSING")
        else:
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            if snapshot.get("log_version") != data.get("log_version"):
                problems.append("LOG_VERSION_NOT_BOUND")
            if snapshot.get("harness_fingerprint") != data.get("harness_fingerprint"):
                problems.append("HARNESS_FINGERPRINT_NOT_BOUND")
        if data.get("before_after_complete") and not snapshot_path.exists():
            problems.append("COMPLETE_BEFORE_AFTER_CLAIMED_WITHOUT_PREFLIGHT")
        for key in ("manifest_sha256", "execution_log_sha256", "result_summary_sha256"):
            if not isinstance(data.get(key), str) or len(data[key]) != 64:
                problems.append(f"{key}:INVALID")
        if problems:
            return verdict(SEMANTIC_CONFLICT, "SNAPSHOT_BINDING_INTEGRITY_FAILED", problems=problems)
        return ok("SNAPSHOT_BINDING_OK", binding_id=data.get("binding_id"))
