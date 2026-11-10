"""Four-source provenance governance and non-destructive relabelling.

Historical sealed files are NEVER rewritten. A derived reconciliation index
records the declared label, the corrected classification, the file hash, the
execution time, the upstream task and the derivation link. Statistics built
from the index cannot silently count replays as live calls.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping

from .outcomes import Verdict, ok, verdict, SEMANTIC_CONFLICT


class Source(str, Enum):
    LIVE = "LIVE"
    REPLAY_FROM_LIVE = "REPLAY_FROM_LIVE"
    SYNTHETIC = "SYNTHETIC"
    UNKNOWN = "UNKNOWN"


DERIVED_INDEX_VERSION = "geoagent.m6.provenance-index/1"


@dataclass(frozen=True)
class ProvenanceEntry:
    relpath: str
    declared_source: str | None
    corrected_source: Source
    correction_reason: str
    file_sha256: str
    data_sha256: str
    execution_time: str | None
    upstream_task: str | None
    derived_from: str | None
    bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "relpath": self.relpath,
            "declared_source": self.declared_source,
            "corrected_source": self.corrected_source.value,
            "correction_reason": self.correction_reason,
            "file_sha256": self.file_sha256,
            "data_sha256": self.data_sha256,
            "execution_time": self.execution_time,
            "upstream_task": self.upstream_task,
            "derived_from": self.derived_from,
            "bytes": self.bytes,
        }


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def data_digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def classify(relpath: str, declared: str | None, document: Mapping[str, Any]) -> tuple[Source, str]:
    """Rule-based classification. Directory + declared label + derivation link."""
    normalised = relpath.replace("\\", "/")
    top = normalised.split("/")[0]
    label = (declared or "").upper()

    if top == "04_REPLAY":
        reason = "OFFLINE_FAULT_INJECTION_REPLAY_DIRECTORY"
        if document.get("origin_response_sha256"):
            reason += "+ORIGIN_RESPONSE_SHA256_LINK_PRESENT"
        return Source.REPLAY_FROM_LIVE, reason
    if top == "09_PUBLIC_MINIMAL" and normalised.endswith("EXAMPLE_TRACE.json"):
        return Source.REPLAY_FROM_LIVE, "SANITISED_EXCERPT_NOT_A_LIVE_CALL"
    if "SYNTHETIC" in normalised.upper() or label == "SYNTHETIC":
        return Source.SYNTHETIC, "SYNTHETIC_BASELINE_OR_DECLARED_SYNTHETIC"
    if top == "03_RUNS" and label == "LIVE":
        return Source.LIVE, "LIVE_RUN_DIRECTORY_WITH_LIVE_LABEL"
    if label in ("REPLAY", "REPLAY_FROM_LIVE"):
        return Source.REPLAY_FROM_LIVE, "LEGACY_REPLAY_LABEL_NORMALISED"
    if label == "LIVE":
        return Source.UNKNOWN, "LIVE_LABEL_OUTSIDE_LIVE_RUN_DIRECTORY_REQUIRES_MANUAL_REVIEW"
    return Source.UNKNOWN, "NO_CLASSIFICATION_EVIDENCE"


def _nested(document: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in document:
            return document[key]
    for key in ("source_block", "provenance", "meta"):
        node = document.get(key)
        if isinstance(node, Mapping) and keys[0] in node:
            return node[keys[0]]
    return None


def build_index(root: Path, *, paths: Iterable[Path] | None = None) -> dict[str, Any]:
    """Read-only scan. Produces a derived index, never writes into root."""
    root = Path(root)
    entries: list[ProvenanceEntry] = []
    scan = paths if paths is not None else sorted(root.rglob("*.json"))
    for path in sorted(scan):
        path = Path(path)
        try:
            relpath = str(path.relative_to(root)).replace("\\", "/")
        except ValueError:
            relpath = str(path)
        raw = path.read_bytes()
        file_sha = hashlib.sha256(raw).hexdigest()
        try:
            document = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            document = {}
        declared = document.get("source") if isinstance(document, Mapping) else None
        source, reason = classify(relpath, declared, document if isinstance(document, Mapping) else {})
        derived_from = _nested(document, "origin_response_sha256") if isinstance(document, Mapping) else None
        if derived_from is None and isinstance(document, Mapping):
            derived_from = document.get("response_sha256") or (document.get("response") or {}).get("response_sha256")
        execution_time = None
        if isinstance(document, Mapping):
            execution_time = (document.get("started_at") or document.get("finished_at")
                              or document.get("timestamp") or document.get("generated_utc"))
        upstream = None
        if isinstance(document, Mapping):
            upstream = document.get("workflow_id") or document.get("run_id") or document.get("injection_id")
        entries.append(ProvenanceEntry(
            relpath, declared, source, reason, file_sha,
            data_digest(document), execution_time, upstream,
            derived_from if isinstance(derived_from, str) else None, len(raw),
        ))
    return {
        "schema": DERIVED_INDEX_VERSION,
        "mode": "NON_DESTRUCTIVE_DERIVED_INDEX",
        "sealed_files_modified": 0,
        "root": str(root),
        "entry_count": len(entries),
        "statistics": statistics(entries),
        "entries": [e.to_dict() for e in entries],
    }


def statistics(entries: Iterable[ProvenanceEntry]) -> dict[str, Any]:
    rows = list(entries)
    by_source = {source.value: sum(1 for e in rows if e.corrected_source is source) for source in Source}
    relabelled = [e for e in rows if e.declared_source == "LIVE" and e.corrected_source is not Source.LIVE]
    replay = [e for e in relabelled if e.relpath.replace("\\", "/").startswith("04_REPLAY/")]
    traces = sum(1 for e in replay if e.relpath.endswith("TRACE.json"))
    return {
        "total_files": len(rows),
        "by_corrected_source": by_source,
        "declared_live_total": sum(1 for e in rows if e.declared_source == "LIVE"),
        "corrected_live_total": by_source[Source.LIVE.value],
        "relabelled_away_from_live": len(relabelled),
        "relabelled_replay_traces": traces,
        "relabelled_replay_step_files": len(replay) - traces,
        "relabelled_other_sanitised_excerpts": len(relabelled) - len(replay),
        "live_call_count_claimable_from_this_index": by_source[Source.LIVE.value],
        "replay_must_not_be_counted_as_live": True,
    }


def verify_index(index: Mapping[str, Any]) -> Verdict:
    """A replay entry must never remain classified as LIVE."""
    problems: list[str] = []
    for entry in index.get("entries") or []:
        relpath = entry.get("relpath", "")
        if relpath.replace("\\", "/").startswith("04_REPLAY/") and entry.get("corrected_source") == "LIVE":
            problems.append(relpath)
        if not entry.get("file_sha256") or len(entry["file_sha256"]) != 64:
            problems.append(f"{relpath}:BAD_FILE_DIGEST")
    stats = index.get("statistics") or {}
    if stats.get("declared_live_total") != (
        stats.get("corrected_live_total", 0) + stats.get("relabelled_away_from_live", 0)
    ):
        problems.append("STATISTICS_DO_NOT_RECONCILE")
    if problems:
        return verdict(SEMANTIC_CONFLICT, "PROVENANCE_INDEX_INTEGRITY_FAILED", problems=problems)
    return ok("PROVENANCE_INDEX_OK", files=index.get("entry_count"))
