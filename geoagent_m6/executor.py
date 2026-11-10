"""M6 offline executor with an explicit dependency graph and consumption proof.

Four responsibilities are kept separate and every statement carries its layer:

  AGENT_DECISION  - choosing to continue, stop, recover or abstain
  TOOL_EXECUTOR   - what the adapter actually read from a response
  ORACLE          - an independent truth criterion (external spec / mathematical
                    identity), never derived from the tool's own answer
  EVALUATOR       - the final chain verdict

A successful tool call is NEVER a successful task. The executor refuses to emit
a final answer when the Oracle is UNKNOWN or the evidence chain is incomplete.

Historical L3 verdicts (0 PASS / 7 UNKNOWN in M5-S0) are not retroactively
upgraded: this is a *new* mechanism for *new* runs only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from . import adapter, semantics as geo
from .outcomes import (
    EVIDENCE_MISSING,
    SAFE_ABSTENTION,
    SEMANTIC_CONFLICT,
    SUCCESS,
    Responsibility,
    StepResult,
    Verdict,
    combine,
    digest,
    ok,
    verdict,
)

EXECUTOR_VERSION = "geoagent.m6.executor/1.0.0"


@dataclass(frozen=True)
class Reference:
    source_step: str
    to_step: str
    argument_field: str
    source_path: str
    value_sha256: str
    identity_sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_step": self.source_step,
            "to_step": self.to_step,
            "argument_field": self.argument_field,
            "source_path": self.source_path,
            "value_sha256": self.value_sha256,
            "identity_sha256": self.identity_sha256,
        }


@dataclass(frozen=True)
class OracleJudgement:
    status: str
    source: str
    basis: str
    checks: list[dict[str, Any]]
    verdict: Verdict

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "source": self.source,
            "basis": self.basis,
            "checks": self.checks,
            "verdict": self.verdict.to_dict(),
        }


def _lookup(context: Mapping[str, Any], path: str) -> tuple[Any, bool]:
    parts = path.split(".")
    if parts[0] == "$":
        parts = parts[1:]
    node: Any = context
    for part in parts:
        if isinstance(node, Mapping) and part in node:
            node = node[part]
        elif isinstance(node, Sequence) and not isinstance(node, (str, bytes)) and part.isdigit():
            index = int(part)
            if index >= len(node):
                return None, False
            node = node[index]
        else:
            return None, False
    return node, True


def resolve_references(
    value: Any,
    context: Mapping[str, Any],
    *,
    to_step: str,
    argument_field: str = "",
) -> tuple[Any, list[Reference], Verdict | None]:
    """Resolve ``$.steps.<id>.read.<path>`` and record every dependency."""
    references: list[Reference] = []
    if isinstance(value, str) and value.startswith("$."):
        found, present = _lookup(context, value)
        if not present:
            return None, [], verdict(
                EVIDENCE_MISSING, "UPSTREAM_REFERENCE_MISSING",
                Responsibility.AGENT_DECISION,
                source_path=value, to_step=to_step, argument_field=argument_field,
            )
        identity = None
        if isinstance(found, Mapping) and found.get("place_id"):
            identity = digest(found["place_id"])
        parts = value.split(".")
        references.append(Reference(
            parts[2] if len(parts) > 2 else "unknown",
            to_step, argument_field, value, digest(found), identity,
        ))
        return found, references, None
    if isinstance(value, Mapping):
        resolved: dict[str, Any] = {}
        for key, item in value.items():
            got, refs, problem = resolve_references(
                item, context, to_step=to_step,
                argument_field=f"{argument_field}.{key}" if argument_field else str(key),
            )
            if problem is not None:
                return None, references, problem
            resolved[str(key)] = got
            references.extend(refs)
        return resolved, references, None
    if isinstance(value, (list, tuple)):
        resolved_list: list[Any] = []
        for index, item in enumerate(value):
            got, refs, problem = resolve_references(
                item, context, to_step=to_step, argument_field=f"{argument_field}[{index}]"
            )
            if problem is not None:
                return None, references, problem
            resolved_list.append(got)
            references.extend(refs)
        return resolved_list, references, None
    return value, [], None


def _read_value(steps: Mapping[str, Mapping[str, Any]], step_id: str, key: str) -> Any:
    read = (steps.get(step_id) or {}).get("read") or {}
    return read.get(key)


def judge_oracle(
    workflow: Mapping[str, Any],
    steps: Mapping[str, Mapping[str, Any]],
    *,
    expectations: Mapping[str, Any] | None = None,
) -> OracleJudgement:
    """Independent truth criteria. Never uses a tool's own verdict as truth."""
    checks: list[dict[str, Any]] = []
    passed = 0

    def add(name: str, condition: bool, basis: str, observed: Any, expected: Any) -> None:
        nonlocal passed
        checks.append({"id": name, "passed": bool(condition), "basis": basis,
                       "observed": observed, "expected": expected})
        if condition:
            passed += 1

    specs = dict(expectations or {})
    for name, expected in specs.items():
        observed = _read_value(steps, str(name.split(".")[0]), name.split(".")[-1])
        add(f"spec:{name}", observed == expected, "EXTERNAL_SPEC", observed, expected)

    for invariant in workflow.get("invariants") or []:
        kind = invariant.get("invariant")
        if kind == "route_at_least_geodesic":
            distance = _read_value(steps, invariant["step"], "distance_m")
            a = (float(invariant["from"]["lat"]), float(invariant["from"]["lon"]))
            b = (float(invariant["to"]["lat"]), float(invariant["to"]["lon"]))
            straight = geo.haversine_m(a[0], a[1], b[0], b[1])
            add(kind, isinstance(distance, (int, float)) and distance > 0 and distance + 1.0 >= straight,
                "INDEPENDENT_MATHEMATICAL_IDENTITY:ROUTE_GEODESIC_LOWER_BOUND",
                distance, f">= {round(straight - 1.0, 3)}")
        elif kind == "matrix_diagonal_zero":
            read = (steps.get(invariant["step"]) or {}).get("read") or {}
            matrix = read.get("matrix")
            diagonal = [matrix[i][i] for i in range(min(len(matrix), len(matrix[0])))] if matrix else None
            add(kind, diagonal is not None and all(v == 0 for v in diagonal),
                "INDEPENDENT_MATHEMATICAL_IDENTITY:ZERO_SELF_DISTANCE", diagonal, [0] * (len(diagonal or [])))
        elif kind == "nonnegative_measure":
            value = _read_value(steps, invariant["step"], "value")
            add(kind, isinstance(value, (int, float)) and value >= 0,
                "INDEPENDENT_MATHEMATICAL_IDENTITY:NONNEGATIVE_MEASURE", value, ">= 0")

    if not checks:
        return OracleJudgement(
            "UNKNOWN", "NONE", "NO_INDEPENDENT_CRITERION_DECLARED", [],
            verdict(SAFE_ABSTENTION, "ORACLE_UNKNOWN_EVIDENCE_INSUFFICIENT",
                    Responsibility.ORACLE,
                    hint="a chain without an independent criterion must not produce a final answer"),
        )
    all_passed = passed == len(checks)
    return OracleJudgement(
        "PASS" if all_passed else "FAIL",
        "EXTERNAL_SPEC_AND_MATHEMATICAL_IDENTITIES",
        "criteria declared independently of tool verdicts",
        checks,
        verdict(SUCCESS if all_passed else SEMANTIC_CONFLICT,
                "ORACLE_PASS" if all_passed else "ORACLE_CRITERION_FAILED",
                Responsibility.ORACLE, checks_passed=passed, checks_total=len(checks)),
    )


@dataclass
class ExecutionRecord:
    schema: str
    executor_version: str
    run_id: str
    workflow_id: str
    source: str
    network: bool
    provider_calls: int
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    consumption_proof: list[dict[str, Any]]
    cross_checks: list[dict[str, Any]]
    oracle: dict[str, Any]
    evaluator: dict[str, Any]
    final_answer: Any
    final_answer_evidence: list[str]
    failure_layer: str | None
    recovery: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}

    @property
    def digest(self) -> str:
        return digest(self.to_dict())


def _cross_checks(workflow: Mapping[str, Any], steps: Mapping[str, Mapping[str, Any]],
                  references: Mapping[str, list[Reference]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for rule in workflow.get("cross_checks") or []:
        kind = rule["kind"]
        if kind == "matrix_cell_equals_route":
            matrix = _read_value(steps, rule["matrix_step"], "matrix")
            route = _read_value(steps, rule["route_step"], "distance_m")
            row, col = rule["row"], rule["col"]
            cell = matrix[row][col] if matrix and row < len(matrix) and col < len(matrix[row]) else None
            findings.append({
                "kind": kind, "consistent": cell is not None and route is not None and abs(cell - route) <= rule.get("tolerance_m", 1.0),
                "matrix_cell": cell, "route_distance_m": route,
            })
        elif kind == "identity_preserved":
            upstream = _read_value(steps, rule["from_step"], "top") or {}
            downstream = _read_value(steps, rule["to_step"], "top") or {}
            findings.append({
                "kind": kind,
                "consistent": bool(upstream.get("place_id")) and upstream.get("place_id") == downstream.get("place_id"),
                "upstream_place_id": upstream.get("place_id"), "downstream_place_id": downstream.get("place_id"),
            })
        elif kind == "matrix_direction":
            read = (steps.get(rule["matrix_step"]) or {}).get("read") or {}
            semantics = read.get("matrix_semantics") or {}
            expected_index = rule.get("expected_index")
            actual_index = rule.get("actual_index")
            transposed = expected_index != actual_index
            direction_dependent = semantics.get("direction_dependent") is True
            findings.append({
                "kind": kind,
                "consistent": not (transposed and direction_dependent),
                "note": "an asymmetric matrix must not be transposed for a reversed direction",
                "direction_dependent": direction_dependent,
                "transposed": transposed,
                "expected_index": expected_index, "actual_index": actual_index,
            })
    for step_id, refs in references.items():
        for ref in refs:
            if ref.identity_sha256 and rule_exists(workflow, "identity_preserved"):
                findings.append({"kind": "reference_identity", "to_step": step_id,
                                 "source_path": ref.source_path, "identity_sha256": ref.identity_sha256})
    return findings


def rule_exists(workflow: Mapping[str, Any], kind: str) -> bool:
    return any(r.get("kind") == kind for r in (workflow.get("cross_checks") or []))


class Executor:
    """Offline, deterministic multi-step executor over pre-supplied MCP envelopes.

    ``responses`` maps step_id to either a deserialised MCP envelope, a callable
    returning one, or ``None`` (simulating a missing response / missing executor).
    """

    def __init__(
        self,
        responses: Mapping[str, Any] | None,
        *,
        run_id: str = "m6-offline-run",
        oracle_expectations: Mapping[str, Any] | None = None,
        recovery_policy: Mapping[str, Any] | None = None,
        external_anchor: str | None = None,
    ) -> None:
        self.responses = responses
        self.run_id = run_id
        self.oracle_expectations = oracle_expectations
        self.recovery_policy = dict(recovery_policy or {})
        self.external_anchor = external_anchor

    def run(self, workflow: Mapping[str, Any]) -> ExecutionRecord:
        workflow_id = str(workflow.get("id", "unnamed"))
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        proof: list[dict[str, Any]] = []
        all_references: dict[str, list[Reference]] = {}
        steps: dict[str, dict[str, Any]] = {}
        context: dict[str, Any] = {"steps": {}, "input": dict(workflow.get("inputs") or {})}
        step_verdicts: list[Verdict] = []
        failure_layer: str | None = None
        recovery: dict[str, Any] = {"attempted": False, "authorised": False, "kind": None}

        not_evaluated = {
            "status": "NOT_EVALUATED", "source": "NONE",
            "basis": "CHAIN_DID_NOT_REACH_ORACLE", "checks": [],
            "verdict": verdict(SAFE_ABSTENTION, "ORACLE_NOT_EVALUATED",
                               Responsibility.ORACLE).to_dict(),
        }

        def build(final: Verdict, *, answer: Any = None, evidence: list[str] | None = None,
                  last_layer: str | None = None,
                  oracle_data: dict[str, Any] | None = None) -> ExecutionRecord:
            return ExecutionRecord(
                "geoagent.m6.execution-record/1", EXECUTOR_VERSION, self.run_id,
                workflow_id, "REPLAY_OR_SYNTHETIC", False, 0,
                nodes, edges, proof, _cross_checks(workflow, steps, all_references),
                oracle_data or not_evaluated, final.to_dict(), answer, evidence or [],
                last_layer or failure_layer, recovery,
            )

        if self.responses is None:
            v = verdict(EVIDENCE_MISSING, "EXECUTOR_MISSING", Responsibility.TOOL_EXECUTOR,
                        hint="no response source supplied; execution blocked before any step")
            failure_layer = Responsibility.TOOL_EXECUTOR.value
            blocked = dict(not_evaluated, basis="EXECUTOR_BLOCKED", verdict=v.to_dict())
            return build(v, last_layer=failure_layer, oracle_data=blocked)

        for index, step in enumerate(workflow.get("chain") or [], start=1):
            step_id = str(step["step_id"])
            capability = str(step["tool"])
            arguments, references, ref_problem = resolve_references(
                step.get("arguments") or {}, context, to_step=step_id
            )
            all_references[step_id] = references
            edges.extend(ref.to_dict() for ref in references)
            if ref_problem is not None:
                failure_layer = Responsibility.AGENT_DECISION.value
                step_verdicts.append(ref_problem)
                nodes.append({"index": index, "step_id": step_id, "capability": capability,
                              "verdict": ref_problem.to_dict(), "failure_layer": failure_layer})
                return build(ref_problem, last_layer=failure_layer)

            envelope = self.responses.get(step_id)
            if envelope is None:
                v = verdict(EVIDENCE_MISSING, "RESPONSE_MISSING_FOR_STEP",
                            Responsibility.TOOL_EXECUTOR, step_id=step_id)
                failure_layer = Responsibility.TOOL_EXECUTOR.value
                step_verdicts.append(v)
                nodes.append({"index": index, "step_id": step_id, "capability": capability,
                              "verdict": v.to_dict(), "failure_layer": failure_layer})
                return build(v, last_layer=failure_layer)
            if callable(envelope):
                envelope = envelope(step_id, arguments)

            adapt_result = adapter.adapt(
                envelope, capability=capability, arguments=arguments, step_id=step_id,
                require_square_matrix=bool(step.get("require_square_matrix")),
                expected_bbox=step.get("expected_bbox"),
            )
            step_result: StepResult = adapt_result.step
            step_verdicts.append(step_result.verdict)
            layer = Responsibility.TOOL_EXECUTOR.value
            node = {
                "index": index, "step_id": step_id, "capability": capability,
                "tool": step_result.tool,
                "arguments": arguments,
                "input_fields": sorted(_argument_fields(arguments)),
                "input_sources": [ref.source_path for ref in references],
                "response_sha256": step_result.payload_digest,
                "read_sha256": step_result.read_digest,
                "consumed_paths": [c["path"] for c in step_result.consumed],
                "verdict": step_result.verdict.to_dict(),
                "failure_layer": layer if step_result.verdict.outcome is not SUCCESS else None,
                "normalisation": step_result.verdict.reason_code,
            }
            nodes.append(node)
            proof.append({
                "step_id": step_id,
                "tool": step_result.tool,
                "response_payload_sha256": step_result.payload_digest,
                "response_read_sha256": step_result.read_digest,
                "consumed_paths": [c["path"] for c in step_result.consumed],
                "consumed_count": len(step_result.consumed),
                "executor_context_sha256": digest(step_result.read),
                "downstream_references": [],
                "proof": "EXECUTOR_READ_PAYLOAD" if step_result.consumed else "NO_CONSUMED_FIELDS",
            })

            if step_result.verdict.outcome is not SUCCESS:
                failure_layer = Responsibility.TOOL_EXECUTOR.value
                replacement = (self.recovery_policy.get("retry_responses") or {}).get(step_id)
                if not (self._may_recover(step_result.verdict) and replacement is not None):
                    combined = combine(step_verdicts, reason_code="CHAIN_STOPPED_AT_STEP")
                    return build(combined, last_layer=failure_layer)
                recovery = {
                    "attempted": True, "authorised": True,
                    "kind": self.recovery_policy.get("allow"), "step_id": step_id,
                    "failed_attempt": {
                        "reason_code": step_result.verdict.reason_code,
                        "verdict_sha256": digest(step_result.verdict.to_dict()),
                    },
                    "note": "failed attempt retained; a declared replacement response was consumed",
                }
                retry = adapter.adapt(
                    replacement, capability=capability, arguments=arguments, step_id=step_id,
                    require_square_matrix=bool(step.get("require_square_matrix")),
                    expected_bbox=step.get("expected_bbox"),
                )
                if retry.step.verdict.outcome is not SUCCESS:
                    recovery["retry_outcome"] = retry.step.verdict.outcome.value
                    return build(combine(step_verdicts, reason_code="RECOVERY_FAILED"),
                                 last_layer=failure_layer)
                recovery["retry_outcome"] = "SUCCESS"
                step_result = retry.step
                step_verdicts[-1] = step_result.verdict
                node.update({
                    "response_sha256": step_result.payload_digest,
                    "read_sha256": step_result.read_digest,
                    "consumed_paths": [c["path"] for c in step_result.consumed],
                    "verdict": step_result.verdict.to_dict(),
                    "failure_layer": None,
                    "recovered": True,
                })
                proof[-1].update({
                    "response_payload_sha256": step_result.payload_digest,
                    "response_read_sha256": step_result.read_digest,
                    "consumed_paths": [c["path"] for c in step_result.consumed],
                    "consumed_count": len(step_result.consumed),
                    "executor_context_sha256": digest(step_result.read),
                    "proof": "EXECUTOR_READ_PAYLOAD",
                })

            steps[step_id] = {
                "read": step_result.read,
                "payload": step_result.payload,
                "verdict": step_result.verdict,
            }
            context["steps"][step_id] = {"read": step_result.read, "payload": step_result.payload}

        for item in proof:
            item["downstream_references"] = [
                ref.to_dict() for refs in all_references.values() for ref in refs
                if ref.source_path.split(".")[2] == item["step_id"]
            ]

        cross = _cross_checks(workflow, steps, all_references)
        conflicts = [c for c in cross if c.get("consistent") is False]
        if conflicts:
            v = verdict(SEMANTIC_CONFLICT, "CROSS_TOOL_CONFLICT_DETECTED",
                        Responsibility.EVALUATOR, conflicts=conflicts)
            failure_layer = Responsibility.EVALUATOR.value
            return build(v, last_layer=failure_layer)

        oracle = judge_oracle(workflow, steps, expectations=self.oracle_expectations)
        if oracle.status == "UNKNOWN":
            failure_layer = Responsibility.ORACLE.value
            return build(
                verdict(SAFE_ABSTENTION, "EVIDENCE_INSUFFICIENT_SAFE_ABSTENTION",
                        Responsibility.EVALUATOR, oracle_status="UNKNOWN"),
                last_layer=failure_layer, oracle_data=oracle.to_dict(),
            )
        if oracle.status == "FAIL":
            failure_layer = Responsibility.EVALUATOR.value
            return build(
                verdict(SEMANTIC_CONFLICT, "ORACLE_CRITERION_FAILED",
                        Responsibility.EVALUATOR, oracle_checks=oracle.checks),
                last_layer=failure_layer, oracle_data=oracle.to_dict(),
            )

        chain = combine(step_verdicts, reason_code="ALL_STEPS_SUCCESS")
        if chain.outcome is not SUCCESS:
            failure_layer = Responsibility.EVALUATOR.value
            return build(chain, last_layer=failure_layer)

        evidence = [n["response_sha256"] for n in nodes] + [r["source_path"] for r in edges]
        final = verdict(SUCCESS, "TASK_VERDICT_WITH_INDEPENDENT_ORACLE",
                        Responsibility.EVALUATOR,
                        oracle_source=oracle.source, oracle_status=oracle.status,
                        steps=len(nodes), evidence_refs=evidence)
        return build(final, answer={
            "workflow_id": workflow_id,
            "status": "PASS_WITH_DECLARED_INDEPENDENT_CRITERIA",
            "oracle_status": oracle.status,
            "not_provider_accuracy": True,
        }, evidence=evidence, oracle_data=oracle.to_dict())

    def _may_recover(self, v: Verdict) -> bool:
        allowed = self.recovery_policy.get("allow")
        if allowed is None:
            return False
        return v.reason_code in set(self.recovery_policy.get("on_reasons") or [])


def _argument_fields(value: Any, prefix: str = "") -> list[str]:
    if isinstance(value, Mapping):
        out: list[str] = []
        for key, item in value.items():
            field = f"{prefix}.{key}" if prefix else str(key)
            out.append(field)
            out.extend(_argument_fields(item, field))
        return out
    return []


def verify_execution_record(record: ExecutionRecord | Mapping[str, Any], *,
                            external_anchor: str | None = None) -> Verdict:
    """Recompute every digest in a record; detect tampering and repackaging."""
    data = record.to_dict() if isinstance(record, ExecutionRecord) else dict(record)
    problems: list[str] = []
    proof_by_step = {p.get("step_id"): p for p in (data.get("consumption_proof") or [])}
    for node in data.get("nodes") or []:
        step_id = node.get("step_id")
        if not node.get("response_sha256") or len(node["response_sha256"]) != 64:
            problems.append(f"node:{step_id}:BAD_RESPONSE_DIGEST")
        proof = proof_by_step.get(step_id)
        if proof is None:
            problems.append(f"node:{step_id}:NO_CONSUMPTION_PROOF")
            continue
        if node.get("response_sha256") != proof.get("response_payload_sha256"):
            problems.append(f"node:{step_id}:RESPONSE_DIGEST_DISAGREES_WITH_CONSUMPTION_PROOF")
        if node.get("read_sha256") != proof.get("response_read_sha256"):
            problems.append(f"node:{step_id}:READ_DIGEST_DISAGREES_WITH_CONSUMPTION_PROOF")
    for item in data.get("consumption_proof") or []:
        if item.get("proof") == "NO_CONSUMED_FIELDS":
            problems.append(f"consumption:{item.get('step_id')}:NO_EVIDENCE_OF_READ")
        if not item.get("consumed_paths"):
            problems.append(f"consumption:{item.get('step_id')}:EMPTY_CONSUMED_PATHS")
    for edge in data.get("edges") or []:
        if not edge.get("value_sha256") or len(edge["value_sha256"]) != 64:
            problems.append("edge:BAD_VALUE_DIGEST")
    if data.get("final_answer") and not data.get("final_answer_evidence"):
        problems.append("FINAL_ANSWER_WITHOUT_EVIDENCE")
    evaluator = data.get("evaluator") or {}
    if evaluator.get("outcome") != "SUCCESS" and data.get("final_answer"):
        problems.append("FINAL_ANSWER_ON_NON_SUCCESS_VERDICT")
    oracle = data.get("oracle") or {}
    if data.get("final_answer") and oracle.get("status") in ("UNKNOWN", "NOT_EVALUATED"):
        problems.append("FINAL_ANSWER_WITHOUT_INDEPENDENT_ORACLE")
    if data.get("final_answer") and "TOOL" in str(oracle.get("source", "")).upper():
        problems.append("ORACLE_SOURCE_NOT_INDEPENDENT")
    if external_anchor is not None:
        if digest(data) != external_anchor:
            problems.append("EXTERNAL_ANCHOR_DISAGREES_WITH_REPACKAGED_RECORD")
    if problems:
        return verdict(SEMANTIC_CONFLICT, "EXECUTION_RECORD_INTEGRITY_FAILED",
                       Responsibility.EVALUATOR, problems=problems)
    return ok("EXECUTION_RECORD_INTEGRITY_OK", nodes=len(data.get("nodes") or []))


def dependency_graph(record: ExecutionRecord | Mapping[str, Any]) -> dict[str, Any]:
    """Machine-readable answer to: which node called which tool, with which
    input fields, which response was read, which output fed the next node,
    where failure occurred, and which evidence the final answer depends on."""
    data = record.to_dict() if isinstance(record, ExecutionRecord) else dict(record)
    return {
        "workflow_id": data.get("workflow_id"),
        "nodes": [
            {
                "step_id": n.get("step_id"), "tool": n.get("tool"),
                "capability": n.get("capability"),
                "input_fields": n.get("input_fields"),
                "input_sources": n.get("input_sources"),
                "response_sha256": n.get("response_sha256"),
                "read_sha256": n.get("read_sha256"),
                "consumed_paths": n.get("consumed_paths"),
                "failure_layer": n.get("failure_layer"),
            }
            for n in (data.get("nodes") or [])
        ],
        "edges": data.get("edges") or [],
        "consumption_proof": data.get("consumption_proof") or [],
        "cross_checks": data.get("cross_checks") or [],
        "final_answer_evidence": data.get("final_answer_evidence") or [],
        "failure_layer": data.get("failure_layer"),
    }
