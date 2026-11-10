"""Four-field cost ledger and a gate that must run BEFORE a tool call.

``credits_reserved`` is a pre-spend ceiling, never a measurement.
``credits_observed`` stays ``null`` unless the provider actually reports it.
``credits_estimated`` is an explicitly labelled estimate.
``credits_unknown`` records that no observation exists.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from .outcomes import SAFE_ABSTENTION, Verdict, ok, verdict

CREDIT_FIELDS = ("credits_reserved", "credits_observed", "credits_estimated", "credits_unknown")


@dataclass(frozen=True)
class CostEntry:
    step_id: str
    tool: str
    credits_reserved: float
    credits_observed: float | None = None
    credits_estimated: float | None = None
    credits_unknown: bool = True
    gate_checked_before_call: bool = False
    gate_permit_sha256: str | None = None
    observation_note: str = "NOT_OBSERVABLE_PROVIDER_REPORTED_NOTHING"

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "tool": self.tool,
            "credits_reserved": self.credits_reserved,
            "credits_observed": self.credits_observed,
            "credits_estimated": self.credits_estimated,
            "credits_unknown": self.credits_unknown,
            "gate_checked_before_call": self.gate_checked_before_call,
            "gate_permit_sha256": self.gate_permit_sha256,
            "observation_note": self.observation_note,
        }


@dataclass(frozen=True)
class GatePermit:
    token: str
    step_id: str
    tool: str
    reservation: float
    sha256: str


def _digest(value: Any) -> str:
    blob = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class CostLedger:
    """Holds a pre-call gate and an append-only list of cost entries."""

    def __init__(self, *, cap_reserved: float, run_id: str = "m6-run") -> None:
        self.cap_reserved = float(cap_reserved)
        self.run_id = run_id
        self.entries: list[CostEntry] = []
        self._reserved_total = 0.0
        self._permits: dict[str, GatePermit] = {}
        self._used: set[str] = set()

    def check_before_call(self, *, step_id: str, tool: str, reservation: float,
                          arguments: Mapping[str, Any] | None = None) -> tuple[GatePermit | None, Verdict]:
        """Must be called before any tool call. Returns a single-use permit."""
        if reservation < 0:
            return None, verdict(SAFE_ABSTENTION, "NEGATIVE_RESERVATION_REFUSED", step_id=step_id)
        if self._reserved_total + reservation > self.cap_reserved:
            return None, verdict(
                SAFE_ABSTENTION, "BUDGET_GATE_BLOCKED_BEFORE_CALL",
                reserved_total=self._reserved_total, requested=reservation, cap=self.cap_reserved,
            )
        token = _digest({
            "run_id": self.run_id, "step_id": step_id, "tool": tool,
            "reservation": reservation, "seq": len(self._permits),
            "arguments_sha256": _digest(arguments or {}),
        })
        permit = GatePermit(token, step_id, tool, reservation, _digest({"token": token}))
        self._permits[token] = permit
        return permit, ok("GATE_CHECKED_BEFORE_CALL", step_id=step_id, reservation=reservation)

    def commit_call(self, *, permit: GatePermit | None, step_id: str, tool: str,
                    reservation: float, credits_observed: float | None = None,
                    credits_estimated: float | None = None) -> tuple[CostEntry | None, Verdict]:
        """Record a call. Refuses to proceed if the gate was not run first."""
        stored = self._permits.get(permit.token) if permit is not None else None
        if stored is None or permit.sha256 != stored.sha256:
            return None, verdict(SAFE_ABSTENTION, "GATE_NOT_RUN_BEFORE_CALL",
                                 hint="no call may be recorded without a prior pre-call gate")
        if permit.token in self._used:
            return None, verdict(SAFE_ABSTENTION, "GATE_PERMIT_REUSED", step_id=step_id)
        if stored.step_id != step_id or stored.tool != tool or abs(stored.reservation - reservation) > 1e-9:
            return None, verdict(SAFE_ABSTENTION, "GATE_PERMIT_MISMATCH", step_id=step_id)
        self._used.add(permit.token)
        self._reserved_total += reservation
        entry = CostEntry(
            step_id=step_id, tool=tool, credits_reserved=reservation,
            credits_observed=credits_observed, credits_estimated=credits_estimated,
            credits_unknown=credits_observed is None,
            gate_checked_before_call=True, gate_permit_sha256=permit.sha256,
            observation_note=("PROVIDER_REPORTED" if credits_observed is not None
                              else "NOT_OBSERVABLE_PROVIDER_REPORTED_NOTHING"),
        )
        self.entries.append(entry)
        return entry, ok("COST_ENTRY_COMMITTED", step_id=step_id)

    def summary(self) -> dict[str, Any]:
        observed = [e.credits_observed for e in self.entries]
        estimated = [e.credits_estimated for e in self.entries if e.credits_estimated is not None]
        any_unknown = any(e.credits_unknown for e in self.entries)
        return {
            "run_id": self.run_id,
            "calls": len(self.entries),
            "credits_reserved": round(sum(e.credits_reserved for e in self.entries), 6),
            "credits_observed": None if any_unknown else round(sum(x for x in observed if x is not None), 6),
            "credits_estimated": round(sum(estimated), 6) if estimated else None,
            "credits_unknown": any_unknown,
            "cap_reserved": self.cap_reserved,
            "all_gates_checked_before_call": all(e.gate_checked_before_call for e in self.entries),
            "reserved_is_not_consumption": True,
            "note": "The historical 514 credits is a reservation ceiling, not observed spend.",
        }

    def to_dict(self) -> dict[str, Any]:
        return {"summary": self.summary(), "entries": [e.to_dict() for e in self.entries]}
