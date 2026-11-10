"""Capture pipeline for FUTURE authorised live calls (offline-verified only).

IMPORTANT BOUNDARY
    This captures the raw *messages observable by the MCP client*: the JSON-RPC
    request bytes it sent and the JSON-RPC response bytes it received. It is NOT
    the provider's raw HTTP response (status line, headers, chunk framing, TLS
    record bytes), which an MCP client normally cannot observe. Nothing here may
    be described as "provider HTTP raw response bytes".

New captures never retroactively fill the historical gap: the M5 evidence pack
contains only parsed payloads plus digests, and that remains a declared gap.

Immutable naming, no overwrite, structured write-failure feedback, redacted
copies with independent digests, and a link to the executor's consumption record
are all built in. Verified offline with fixtures and a local controllable stub
service; no network egress is performed by this module.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .outcomes import EVIDENCE_MISSING, SEMANTIC_CONFLICT, Verdict, ok, verdict

CAPTURE_LAYER = "MCP_CLIENT_OBSERVABLE"
CAPTURE_SCHEMA = "geoagent.m6.mcp-message-capture/1"
NOT_PROVIDER_HTTP_RAW = (
    "This record is the MCP client-observable JSON-RPC message bytes, not the "
    "provider's raw HTTP response bytes."
)

_HEX32 = re.compile(r"^[a-fA-F0-9]{32}$")
_HEX64 = re.compile(r"^[a-fA-F0-9]{64}$")
_PRIVATE_PATH = re.compile(r"[A-Za-z]:\\(?:Users|geoapify|ds)|/home/", re.I)
_DROP_KEYS = frozenset({
    "api_key", "apikey", "x-api-key", "authorization", "cookie", "set-cookie",
    "credential", "credentials", "secret", "token", "mcp-session-id", "session_id",
})
_KEEP_HASH_KEY = re.compile(r"(^|_)(sha256|digest|fingerprint)($|_)", re.I)


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def redact(raw: bytes) -> tuple[bytes, str]:
    """Return (redacted_bytes, digest). Hash fields survive; secrets do not."""
    try:
        document = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return b'{"__redacted__":"NON_JSON_BYTES"}', sha256_bytes(b"NON_JSON_BYTES")

    def walk(node: Any, key: str | None = None) -> Any:
        if isinstance(node, dict):
            return {k: (v if _KEEP_HASH_KEY.search(str(k)) and isinstance(v, str) else walk(v, str(k)))
                    for k, v in node.items() if str(k).lower() not in _DROP_KEYS}
        if isinstance(node, list):
            return [walk(v, key) for v in node]
        if isinstance(node, str):
            if _HEX32.match(node) or _HEX64.match(node) or _PRIVATE_PATH.search(node):
                return "[REDACTED]"
            return node
        return node

    cleaned = canonical(walk(document))
    return cleaned, sha256_bytes(cleaned)


@dataclass(frozen=True)
class CaptureFailure:
    reason: str
    detail: str
    retryable: bool

    def to_dict(self) -> dict[str, Any]:
        return {"reason": self.reason, "detail": self.detail, "retryable": self.retryable}


@dataclass(frozen=True)
class CaptureRecord:
    capture_id: str
    correlation_id: str
    run_id: str
    step_id: str
    tool: str
    capability: str
    request_id: str
    request_bytes_b64: str
    response_bytes_b64: str
    request_sha256: str
    response_sha256: str
    redacted_bytes_b64: str
    redacted_sha256: str
    capture_layer: str
    boundary_note: str
    captured_at: str
    consumed: dict[str, Any] | None
    derived_from_record_sha256: str | None
    file_path: str

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


class CaptureSink:
    """Append-only capture store. A target that already exists is never overwritten."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    def capture(
        self,
        *,
        request_bytes: bytes,
        response_bytes: bytes,
        run_id: str,
        step_id: str,
        tool: str,
        capability: str,
        request_id: str,
        consumed: Mapping[str, Any] | None = None,
        derived_from_record_sha256: str | None = None,
        captured_at: str | None = None,
    ) -> tuple[CaptureRecord | None, CaptureFailure | None]:
        if not request_bytes or not response_bytes:
            return None, CaptureFailure("EMPTY_MESSAGE_BYTES", "request and response bytes must be non-empty", False)
        request_sha = sha256_bytes(request_bytes)
        response_sha = sha256_bytes(response_bytes)
        correlation = hashlib.sha256(request_sha.encode() + response_sha.encode()).hexdigest()
        capture_id = f"{run_id}__{step_id}__{request_id}__{response_sha[:16]}"
        redacted, redacted_sha = redact(response_bytes)
        target = self.directory / f"{capture_id}.json"
        if target.exists():
            return None, CaptureFailure(
                "CAPTURE_TARGET_EXISTS", f"immutable target already present: {target.name}", False
            )
        stamp = captured_at or datetime.now(timezone.utc).isoformat()
        record = CaptureRecord(
            capture_id, correlation, run_id, step_id, tool, capability, request_id,
            base64.b64encode(request_bytes).decode("ascii"),
            base64.b64encode(response_bytes).decode("ascii"),
            request_sha, response_sha,
            base64.b64encode(redacted).decode("ascii"), redacted_sha,
            CAPTURE_LAYER, NOT_PROVIDER_HTTP_RAW, stamp,
            dict(consumed) if consumed else None,
            derived_from_record_sha256, str(target),
        )
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(record.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            return None, CaptureFailure("CAPTURE_WRITE_FAILED", f"{type(exc).__name__}: {exc}", True)
        return record, None


def verify_capture(record: CaptureRecord | Mapping[str, Any]) -> Verdict:
    """Recompute all digests and check the declared capture-layer boundary."""
    data = record.to_dict() if isinstance(record, CaptureRecord) else dict(record)
    problems: list[str] = []
    try:
        request_raw = base64.b64decode(data["request_bytes_b64"], validate=True)
        response_raw = base64.b64decode(data["response_bytes_b64"], validate=True)
        redacted_raw = base64.b64decode(data["redacted_bytes_b64"], validate=True)
    except (KeyError, ValueError) as exc:
        return verdict(EVIDENCE_MISSING, "CAPTURE_BYTES_UNREADABLE", detail=str(exc))
    if sha256_bytes(request_raw) != data.get("request_sha256"):
        problems.append("REQUEST_SHA256_MISMATCH")
    if sha256_bytes(response_raw) != data.get("response_sha256"):
        problems.append("RESPONSE_SHA256_MISMATCH")
    if sha256_bytes(redacted_raw) != data.get("redacted_sha256"):
        problems.append("REDACTED_SHA256_MISMATCH")
    expected_correlation = hashlib.sha256(
        (data.get("request_sha256", "") + data.get("response_sha256", "")).encode()
    ).hexdigest()
    if expected_correlation != data.get("correlation_id"):
        problems.append("CORRELATION_ID_MISMATCH")
    if data.get("capture_layer") != CAPTURE_LAYER:
        problems.append("CAPTURE_LAYER_MISDECLARED")
    if "not the provider's raw HTTP response" not in str(data.get("boundary_note", "")):
        problems.append("BOUNDARY_NOTE_MISSING")
    if redacted_raw == response_raw and b"api_key" in response_raw:
        problems.append("REDACTION_DID_NOT_REMOVE_SECRET")
    path = Path(data.get("file_path", ""))
    if path.exists():
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        if on_disk.get("response_sha256") != data.get("response_sha256"):
            problems.append("ON_DISK_RECORD_DISAGREES")
    if problems:
        return verdict(SEMANTIC_CONFLICT, "CAPTURE_INTEGRITY_FAILED", problems=problems)
    return ok("CAPTURE_INTEGRITY_OK", capture_id=data.get("capture_id"))
