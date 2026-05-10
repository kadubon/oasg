"""Conservative deterministic reducers for the v1.0 profile."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from oasg.constants import ACTION_CLASSES, REQUIRED_DIMENSIONS, TAINT_LEVELS, require_grade, strictly_better
from oasg.ledger import VALID_STATUS, LedgerVerification, verify_jsonl, verify_records
from oasg.io import read_jsonl


@dataclass(frozen=True)
class ReducerSnapshot:
    ledger_status: str
    ledger_prefix_hash: str
    dimensions: dict[str, str]
    action_grades: dict[str, str]
    protected_debt: dict[str, str]
    positive_evidence: dict[str, list[str]]
    records_seen: int
    effect_classes: tuple[str, ...] = ()
    semantic_scope: str = "none"
    claim_emitting: bool = False
    taint_level: str = "public"
    boundary_status: str = "valid"
    trusted_base_status: str = "valid"
    workflow_promotion_authorized: bool = False
    artifact_type: str = "reducer_snapshot"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": self.artifact_type,
            "ledger_status": self.ledger_status,
            "ledger_prefix_hash": self.ledger_prefix_hash,
            "dimensions": self.dimensions,
            "action_grades": self.action_grades,
            "protected_debt": self.protected_debt,
            "positive_evidence": self.positive_evidence,
            "records_seen": self.records_seen,
            "effect_classes": list(self.effect_classes),
            "semantic_scope": self.semantic_scope,
            "claim_emitting": self.claim_emitting,
            "taint_level": self.taint_level,
            "boundary_status": self.boundary_status,
            "trusted_base_status": self.trusted_base_status,
            "workflow_promotion_authorized": self.workflow_promotion_authorized,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ReducerSnapshot":
        return cls(
            ledger_status=str(value["ledger_status"]),
            ledger_prefix_hash=str(value["ledger_prefix_hash"]),
            dimensions={str(k): require_grade(str(v)) for k, v in value["dimensions"].items()},
            action_grades={str(k): require_grade(str(v)) for k, v in value["action_grades"].items()},
            protected_debt={
                str(k): require_grade(str(v)) for k, v in value.get("protected_debt", {}).items()
            },
            positive_evidence={
                str(k): [str(item) for item in items]
                for k, items in value.get("positive_evidence", {}).items()
            },
            records_seen=int(value["records_seen"]),
            effect_classes=tuple(str(item) for item in value.get("effect_classes", [])),
            semantic_scope=str(value.get("semantic_scope", "none")),
            claim_emitting=bool(value.get("claim_emitting", False)),
            taint_level=str(value.get("taint_level", "public")),
            boundary_status=str(value.get("boundary_status", "valid")),
            trusted_base_status=str(value.get("trusted_base_status", "valid")),
            workflow_promotion_authorized=bool(value.get("workflow_promotion_authorized", False)),
        )


def _initial_dimensions() -> dict[str, str]:
    return {dimension: "blocked" for dimension in REQUIRED_DIMENSIONS}


def _initial_action_grades() -> dict[str, str]:
    return {action_class: "blocked" for action_class in ACTION_CLASSES}


def reduce_records(
    records: list[dict[str, Any]],
    verification: LedgerVerification | None = None,
) -> ReducerSnapshot:
    verification = verification or verify_records(records)
    dimensions: dict[str, str] = {}
    action_grades: dict[str, str] = {}
    protected_debt: dict[str, str] = {}
    positive_evidence: dict[str, list[str]] = {}
    effect_classes: set[str] = set()
    semantic_scope = "none"
    claim_emitting = False
    taint_level = "public"
    boundary_status = "valid"
    trusted_base_status = "valid"
    workflow_promotion_authorized = False
    state = _ReducerState(
        dimensions=dimensions,
        action_grades=action_grades,
        protected_debt=protected_debt,
        positive_evidence=positive_evidence,
        effect_classes=effect_classes,
        semantic_scope=semantic_scope,
        claim_emitting=claim_emitting,
        taint_level=taint_level,
        boundary_status=boundary_status,
        trusted_base_status=trusted_base_status,
        workflow_promotion_authorized=workflow_promotion_authorized,
    )

    if verification.status != VALID_STATUS:
        return ReducerSnapshot(
            ledger_status=verification.status,
            ledger_prefix_hash=verification.ledger_prefix_hash,
            dimensions=_initial_dimensions(),
            action_grades=_initial_action_grades(),
            protected_debt={dimension: "blocked" for dimension in REQUIRED_DIMENSIONS},
            positive_evidence=positive_evidence,
            records_seen=verification.records_seen,
        )

    rejected_lines = {
        line.append_index
        for line in verification.line_statuses
        if line.status not in {VALID_STATUS, "ledger_prefix_valid"}
    }
    for record in records:
        if int(record.get("append_index", 0)) in rejected_lines:
            continue
        payload = record.get("payload", {})
        if not isinstance(payload, dict):
            continue
        _dispatch_record(state, str(record.get("event_type", "observation")), payload)

    return ReducerSnapshot(
        ledger_status=verification.status,
        ledger_prefix_hash=verification.ledger_prefix_hash,
        dimensions=_fill_required(dimensions, REQUIRED_DIMENSIONS),
        action_grades=_fill_required(action_grades, ACTION_CLASSES),
        protected_debt=_fill_required(protected_debt, REQUIRED_DIMENSIONS),
        positive_evidence=positive_evidence,
        records_seen=verification.records_seen,
        effect_classes=tuple(sorted(effect_classes)),
        semantic_scope=state.semantic_scope,
        claim_emitting=state.claim_emitting,
        taint_level=state.taint_level,
        boundary_status=state.boundary_status,
        trusted_base_status=state.trusted_base_status,
        workflow_promotion_authorized=state.workflow_promotion_authorized,
    )


@dataclass
class _ReducerState:
    dimensions: dict[str, str]
    action_grades: dict[str, str]
    protected_debt: dict[str, str]
    positive_evidence: dict[str, list[str]]
    effect_classes: set[str]
    semantic_scope: str
    claim_emitting: bool
    taint_level: str
    boundary_status: str
    trusted_base_status: str
    workflow_promotion_authorized: bool


def _dispatch_record(state: _ReducerState, event_type: str, payload: dict[str, Any]) -> None:
    handlers: dict[str, Callable[[_ReducerState, dict[str, Any]], None]] = {
        "observation": _handle_observation,
        "coverage": _handle_coverage,
        "proof_obligation": _handle_observation,
        "repair": _handle_observation,
        "policy": _handle_policy_event,
        "mutation": _handle_policy_event,
        "shadow": _handle_lifecycle_event,
        "lease": _handle_lifecycle_event,
        "boundary": _handle_boundary_event,
        "taint": _handle_taint_event,
        "semantic": _handle_policy_event,
        "trusted_base_bridge": _handle_trusted_base_event,
    }
    handlers.get(event_type, _handle_observation)(state, payload)


def _handle_observation(state: _ReducerState, payload: dict[str, Any]) -> None:
    proof_coordinates = _coordinate_set(payload.get("proof_obligation_receipts", []))
    repair_coordinates = _coordinate_set(payload.get("repair_receipts", []))
    _merge_grade_map(state.dimensions, payload.get("dimensions", {}), proof_coordinates)
    _merge_grade_map(state.action_grades, payload.get("action_grades", {}), proof_coordinates)
    _merge_grade_map(state.protected_debt, payload.get("protected_debt", {}), repair_coordinates)
    _merge_positive_evidence(
        state.positive_evidence,
        payload.get("positive_evidence", []),
        proof_coordinates | repair_coordinates,
    )
    _handle_policy_event(state, payload)


def _handle_coverage(state: _ReducerState, payload: dict[str, Any]) -> None:
    if payload.get("missingness_policy") in {"hard_negative", "protected_negative"}:
        state.dimensions["evidence"] = "critical"


def _handle_policy_event(state: _ReducerState, payload: dict[str, Any]) -> None:
    policy = payload.get("policy", payload)
    if not isinstance(policy, dict):
        return
    state.effect_classes.update(str(item) for item in policy.get("effect_classes", []))
    if str(policy.get("semantic_scope", "none")) != "none":
        state.semantic_scope = str(policy["semantic_scope"])
    state.claim_emitting = state.claim_emitting or bool(policy.get("claim_emitting", False))
    state.taint_level = _max_taint(state.taint_level, str(policy.get("taint_level", "public")))
    state.boundary_status = str(policy.get("boundary_status", state.boundary_status))
    state.trusted_base_status = str(policy.get("trusted_base_status", state.trusted_base_status))
    state.workflow_promotion_authorized = state.workflow_promotion_authorized or bool(
        policy.get("workflow_promotion_authorized", False)
    )


def _handle_lifecycle_event(state: _ReducerState, payload: dict[str, Any]) -> None:
    status = str(payload.get("status", ""))
    if status.endswith("passed"):
        state.dimensions["comparison"] = "acceptable"
    elif status:
        state.dimensions["comparison"] = "critical"


def _handle_boundary_event(state: _ReducerState, payload: dict[str, Any]) -> None:
    state.boundary_status = str(payload.get("status", "stale_boundary"))


def _handle_taint_event(state: _ReducerState, payload: dict[str, Any]) -> None:
    state.taint_level = _max_taint(state.taint_level, str(payload.get("taint_level", "unknown_secret")))


def _handle_trusted_base_event(state: _ReducerState, payload: dict[str, Any]) -> None:
    state.trusted_base_status = str(payload.get("status", "unbridged"))


def _fill_required(values: dict[str, str], required: tuple[str, ...]) -> dict[str, str]:
    output = {item: values.get(item, "blocked") for item in required}
    for key, value in values.items():
        output.setdefault(key, value)
    return output


def _merge_grade_map(target: dict[str, str], raw: Any, proof_coordinates: set[str]) -> None:
    if not isinstance(raw, dict):
        return
    for key, value in raw.items():
        coordinate = str(key)
        grade = require_grade(str(value))
        current = target.get(coordinate)
        if current is not None and strictly_better(grade, current) and coordinate not in proof_coordinates:
            continue
        target[coordinate] = grade


def _merge_positive_evidence(
    target: dict[str, list[str]],
    raw: Any,
    proof_coordinates: set[str],
) -> None:
    if not isinstance(raw, list):
        return
    for item in raw:
        if not isinstance(item, dict):
            continue
        coordinate = str(item.get("coordinate", ""))
        evidence_hash = str(item.get("evidence_hash", ""))
        if coordinate and evidence_hash and coordinate in proof_coordinates:
            target.setdefault(coordinate, []).append(evidence_hash)


def _coordinate_set(raw: Any) -> set[str]:
    coordinates: set[str] = set()
    if not isinstance(raw, list):
        return coordinates
    for item in raw:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status", ""))
        if status not in {"receipt_valid", "repair_valid", "witness_valid"}:
            continue
        coordinate = item.get("coordinate") or item.get("coordinate_id") or item.get("dimension_id")
        if coordinate:
            coordinates.add(str(coordinate))
    return coordinates


def _max_taint(left: str, right: str) -> str:
    left_index = TAINT_LEVELS.index(left) if left in TAINT_LEVELS else len(TAINT_LEVELS) - 1
    right_index = TAINT_LEVELS.index(right) if right in TAINT_LEVELS else len(TAINT_LEVELS) - 1
    return TAINT_LEVELS[max(left_index, right_index)]


def reduce_ledger(path: Path) -> ReducerSnapshot:
    records = read_jsonl(path)
    return reduce_records(records, verify_jsonl(path))
