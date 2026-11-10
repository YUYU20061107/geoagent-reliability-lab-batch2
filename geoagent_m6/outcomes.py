"""One outcome state machine for GeoAgent M6.

The M5 live pilot used two overlapping vocabularies (transport reasons and
normalisation statuses). M6 keeps a single terminal taxonomy. Legacy labels are
accepted only as *inputs* through ``from_legacy``; they never become a second
set of states.

An outcome describes a tool/step result, not a task verdict. In particular
``EMPTY_RESULT`` is a legitimate observation and is NOT success, and
``SAFE_ABSTENTION`` is a deliberate decision not to answer.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class Outcome(str, Enum):
    SUCCESS = "SUCCESS"
    EMPTY_RESULT = "EMPTY_RESULT"
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    CAPABILITY_UNAVAILABLE = "CAPABILITY_UNAVAILABLE"
    EVIDENCE_MISSING = "EVIDENCE_MISSING"
    SEMANTIC_CONFLICT = "SEMANTIC_CONFLICT"
    SAFE_ABSTENTION = "SAFE_ABSTENTION"


class Responsibility(str, Enum):
    """Who owns a statement. Kept distinct to prevent circular self-proof."""

    AGENT_DECISION = "AGENT_DECISION"
    TOOL_EXECUTOR = "TOOL_EXECUTOR"
    ORACLE = "ORACLE"
    EVALUATOR = "EVALUATOR"


SUCCESS = Outcome.SUCCESS
EMPTY_RESULT = Outcome.EMPTY_RESULT
INVALID_ARGUMENT = Outcome.INVALID_ARGUMENT
PROVIDER_ERROR = Outcome.PROVIDER_ERROR
CAPABILITY_UNAVAILABLE = Outcome.CAPABILITY_UNAVAILABLE
EVIDENCE_MISSING = Outcome.EVIDENCE_MISSING
SEMANTIC_CONFLICT = Outcome.SEMANTIC_CONFLICT
SAFE_ABSTENTION = Outcome.SAFE_ABSTENTION


LEGACY_STATUS_MAP: dict[str, Outcome] = {
    "OK": SUCCESS,
    "OK_EMPTY": EMPTY_RESULT,
    "OK_GEOMETRY_ONLY": EMPTY_RESULT,
    "NORMALISATION_UNSUPPORTED": EVIDENCE_MISSING,
    "NORMALISATION_PARTIAL": EVIDENCE_MISSING,
    "TOOL_REPORTED_ERROR": PROVIDER_ERROR,
    "TOOL_CALL_FAILED": PROVIDER_ERROR,
    "MCP_RESULT_UNRECOGNISED": EVIDENCE_MISSING,
    "MOCK_ARGUMENT_MISMATCH": INVALID_ARGUMENT,
    "INVARIANT_MISMATCH": SEMANTIC_CONFLICT,
    "UNSUPPORTED_CAPABILITY": CAPABILITY_UNAVAILABLE,
    "CAPABILITY_UNAVAILABLE": CAPABILITY_UNAVAILABLE,
    "BUDGET_GATE_CLOSED": SAFE_ABSTENTION,
    "PROVIDER_INCONSISTENCY": SEMANTIC_CONFLICT,
    "SEMANTIC_CONFLICT_UNRESOLVED": SEMANTIC_CONFLICT,
}

# Outcomes that must never be reported as a successful task completion.
NON_SUCCESS = frozenset(o for o in Outcome if o is not SUCCESS)

# Outcomes that abort a chain unless the executor has an explicit recovery rule.
TERMINAL_WITHOUT_RECOVERY = frozenset(
    {
        Outcome.INVALID_ARGUMENT,
        Outcome.PROVIDER_ERROR,
        Outcome.CAPABILITY_UNAVAILABLE,
        Outcome.EVIDENCE_MISSING,
        Outcome.SEMANTIC_CONFLICT,
        Outcome.SAFE_ABSTENTION,
    }
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _to_plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(k): _to_plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_plain(v) for v in value]
    return value


@dataclass(frozen=True)
class Verdict:
    """A terminal, attributable statement about one step or one decision."""

    outcome: Outcome
    reason_code: str
    layer: Responsibility
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return self.outcome is Outcome.SUCCESS

    @property
    def abstains(self) -> bool:
        return self.outcome is Outcome.SAFE_ABSTENTION

    @property
    def terminates_chain(self) -> bool:
        return self.outcome in TERMINAL_WITHOUT_RECOVERY

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "reason_code": self.reason_code,
            "layer": self.layer.value,
            "detail": self.detail,
            "evidence": _to_plain(self.evidence),
        }

    def with_evidence(self, **extra: Any) -> "Verdict":
        merged = dict(self.evidence)
        merged.update(extra)
        return Verdict(self.outcome, self.reason_code, self.layer, self.detail, merged)


def verdict(
    outcome: Outcome,
    reason_code: str,
    layer: Responsibility = Responsibility.TOOL_EXECUTOR,
    detail: str = "",
    **evidence: Any,
) -> Verdict:
    return Verdict(outcome, reason_code, layer, detail, _to_plain(evidence))


def ok(reason_code: str = "OK", **evidence: Any) -> Verdict:
    return verdict(Outcome.SUCCESS, reason_code, **evidence)


def from_legacy(status: str, *, detail: str = "", **evidence: Any) -> Verdict:
    """Map an M5 status label into the single M6 taxonomy. Unknown -> abstain."""
    outcome = LEGACY_STATUS_MAP.get(status)
    if outcome is None:
        return verdict(
            Outcome.SAFE_ABSTENTION,
            "LEGACY_STATUS_UNMAPPED",
            detail=f"unmapped legacy status {status!r}; {detail}",
            legacy_status=status,
            **evidence,
        )
    return verdict(outcome, f"LEGACY_{status}", detail=detail, legacy_status=status, **evidence)


@dataclass
class StepResult:
    """The observable product of one tool step."""

    step_id: str
    capability: str
    tool: str
    verdict: Verdict
    read: dict[str, Any] = field(default_factory=dict)
    payload: Any = None
    contract_version: str = ""
    consumed: list[dict[str, Any]] = field(default_factory=list)

    @property
    def read_digest(self) -> str:
        return digest(self.read)

    @property
    def payload_digest(self) -> str:
        return digest(self.payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "capability": self.capability,
            "tool": self.tool,
            "verdict": self.verdict.to_dict(),
            "read": _to_plain(self.read),
            "read_digest": self.read_digest,
            "payload_digest": self.payload_digest,
            "contract_version": self.contract_version,
            "consumed": _to_plain(self.consumed),
        }


def combine(verdicts: list[Verdict], *, reason_code: str = "CHAIN_EVALUATION") -> Verdict:
    """Worst-case chain verdict. Any non-success dominates; abstention outranks errors
    only when evidence is missing, otherwise the first blocking verdict wins."""
    if not verdicts:
        return verdict(Outcome.EVIDENCE_MISSING, "NO_STEP_VERDICTS", Responsibility.EVALUATOR)
    for item in verdicts:
        if item.outcome is Outcome.EVIDENCE_MISSING:
            return item.with_evidence(combined_reason=reason_code)
    for item in verdicts:
        if item.outcome is Outcome.CAPABILITY_UNAVAILABLE:
            return item.with_evidence(combined_reason=reason_code)
    priority = (
        Outcome.INVALID_ARGUMENT,
        Outcome.PROVIDER_ERROR,
        Outcome.SEMANTIC_CONFLICT,
        Outcome.SAFE_ABSTENTION,
        Outcome.EMPTY_RESULT,
    )
    for outcome in priority:
        for item in verdicts:
            if item.outcome is outcome:
                return item.with_evidence(combined_reason=reason_code)
    return verdict(
        Outcome.SUCCESS,
        reason_code,
        Responsibility.EVALUATOR,
        steps=len(verdicts),
    )
