"""Mutation lifecycle receipts and active promotion checks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from oasg.gate import GateResult


@dataclass(frozen=True)
class MutationPlan:
    mutation_id: str
    target_component_id: str
    coordinate_id: str
    action_id: str
    from_grade: str
    to_grade: str
    effect_class: str = "workflow_promotion"
    patch: dict[str, Any] | None = None
    receipt_type: str = "mutation_record"

    def to_dict(self) -> dict[str, Any]:
        record = {
            "record_type": self.receipt_type,
            "mutation_id": self.mutation_id,
            "target_component_id": self.target_component_id,
            "state": "proposed",
            "declared_improvement_coordinates": [self.coordinate_id],
            "effect_class": self.effect_class,
            "action_id": self.action_id,
            "from_grade": self.from_grade,
            "to_grade": self.to_grade,
            "lease_caps": {"max_events": 20, "max_external_effects": 0},
        }
        if self.patch is not None:
            record["patch"] = self.patch
        return record


@dataclass(frozen=True)
class ShadowResult:
    mutation_id: str
    status: str
    ledger_prefix_hash: str
    observed_coordinates: dict[str, str] = field(default_factory=dict)
    replayed_event_count: int = 0
    runner_type: str = "ledger-replay"
    workload_id: str = "candidate_replay"
    input_hashes: tuple[str, ...] = ()
    execution_receipt_hash: str | None = None
    trial_ledger_path: str | None = None
    trial_ledger_prefix_hash: str | None = None
    trial_reducer_snapshot_hash: str | None = None
    receipt_type: str = "shadow_receipt"

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt_type": self.receipt_type,
            "mutation_id": self.mutation_id,
            "status": self.status,
            "ledger_prefix_hash": self.ledger_prefix_hash,
            "observed_coordinates": self.observed_coordinates,
            "replayed_event_count": self.replayed_event_count,
            "runner_type": self.runner_type,
            "workload_id": self.workload_id,
            "input_hashes": list(self.input_hashes),
            "execution_receipt_hash": self.execution_receipt_hash,
            "trial_ledger_path": self.trial_ledger_path,
            "trial_ledger_prefix_hash": self.trial_ledger_prefix_hash,
            "trial_reducer_snapshot_hash": self.trial_reducer_snapshot_hash,
        }


@dataclass(frozen=True)
class LeaseResult:
    mutation_id: str
    status: str
    ledger_prefix_hash: str
    max_events: int
    effect_counts: dict[str, int] = field(default_factory=dict)
    executed_event_count: int = 0
    rollback_available: bool = True
    resources: dict[str, int] = field(default_factory=dict)
    runner_type: str = "ledger-replay"
    workload_id: str = "candidate_replay"
    input_hashes: tuple[str, ...] = ()
    execution_receipt_hash: str | None = None
    trial_ledger_path: str | None = None
    trial_ledger_prefix_hash: str | None = None
    trial_reducer_snapshot_hash: str | None = None
    receipt_type: str = "lease_receipt"

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt_type": self.receipt_type,
            "mutation_id": self.mutation_id,
            "status": self.status,
            "ledger_prefix_hash": self.ledger_prefix_hash,
            "max_events": self.max_events,
            "effect_counts": self.effect_counts,
            "executed_event_count": self.executed_event_count,
            "rollback_available": self.rollback_available,
            "resources": self.resources,
            "runner_type": self.runner_type,
            "workload_id": self.workload_id,
            "input_hashes": list(self.input_hashes),
            "execution_receipt_hash": self.execution_receipt_hash,
            "trial_ledger_path": self.trial_ledger_path,
            "trial_ledger_prefix_hash": self.trial_ledger_prefix_hash,
            "trial_reducer_snapshot_hash": self.trial_reducer_snapshot_hash,
        }


def shadow_candidate(
    mutation: dict[str, Any],
    candidate_ledger_prefix_hash: str,
    *,
    candidate_records_seen: int = 1,
    candidate_ledger_status: str = "ledger_prefix_valid",
    candidate_positive_evidence: dict[str, list[str]] | None = None,
) -> ShadowResult:
    declared = tuple(str(item) for item in mutation.get("declared_improvement_coordinates", []))
    evidence = candidate_positive_evidence or {}
    missing = [coordinate for coordinate in declared if not evidence.get(coordinate)]
    status = (
        "shadow_passed"
        if declared
        and not missing
        and candidate_records_seen > 0
        and candidate_ledger_status == "ledger_prefix_valid"
        else "shadow_rejected"
    )
    return ShadowResult(
        mutation_id=str(mutation["mutation_id"]),
        status=status,
        ledger_prefix_hash=candidate_ledger_prefix_hash,
        observed_coordinates={
            coordinate: "acceptable"
            for coordinate in declared
            if coordinate not in missing
        },
        replayed_event_count=candidate_records_seen,
    )


def lease_candidate(
    mutation: dict[str, Any],
    candidate_ledger_prefix_hash: str,
    *,
    max_events: int,
    candidate_records_seen: int = 1,
    candidate_ledger_status: str = "ledger_prefix_valid",
) -> LeaseResult:
    caps = mutation.get("lease_caps", {})
    cap_events = int(caps.get("max_events", max_events))
    external_cap = int(caps.get("max_external_effects", 0))
    status = (
        "lease_passed"
        if max_events <= cap_events
        and candidate_records_seen <= max_events
        and external_cap == 0
        and candidate_ledger_status == "ledger_prefix_valid"
        else "lease_rejected_cap_exceeded"
    )
    return LeaseResult(
        mutation_id=str(mutation["mutation_id"]),
        status=status,
        ledger_prefix_hash=candidate_ledger_prefix_hash,
        max_events=max_events,
        effect_counts={"workflow_promotion": 1, "external": 0},
        executed_event_count=candidate_records_seen,
        rollback_available=True,
        resources={"events": candidate_records_seen},
    )


def active_promotion_receipt(
    safe_gate: GateResult,
    shadow: ShadowResult,
    lease: LeaseResult,
    mutation: dict[str, Any],
) -> dict[str, Any]:
    reasons: list[str] = []
    if safe_gate.status != "safe_promotion":
        reasons.append(f"gate_status:{safe_gate.status}")
    if shadow.status != "shadow_passed":
        reasons.append(f"shadow_status:{shadow.status}")
    if lease.status != "lease_passed":
        reasons.append(f"lease_status:{lease.status}")
    if shadow.ledger_prefix_hash != safe_gate.candidate_ledger_prefix_hash:
        reasons.append("shadow_prefix_mismatch")
    if lease.ledger_prefix_hash != safe_gate.candidate_ledger_prefix_hash:
        reasons.append("lease_prefix_mismatch")
    if shadow.runner_type == "synthetic" or lease.runner_type == "synthetic":
        reasons.append("synthetic_runner_receipt")
    if shadow.runner_type == "demo-replay" or lease.runner_type == "demo-replay":
        reasons.append("demo_replay_runner_not_active_promotable")
    if shadow.execution_receipt_hash is None:
        reasons.append("shadow_execution_receipt_missing")
    if lease.execution_receipt_hash is None:
        reasons.append("lease_execution_receipt_missing")
    if shadow.trial_ledger_prefix_hash is None:
        reasons.append("shadow_trial_ledger_missing")
    if lease.trial_ledger_prefix_hash is None:
        reasons.append("lease_trial_ledger_missing")
    if shadow.trial_ledger_prefix_hash != safe_gate.candidate_ledger_prefix_hash:
        reasons.append("shadow_trial_prefix_mismatch")
    if lease.trial_ledger_prefix_hash != safe_gate.candidate_ledger_prefix_hash:
        reasons.append("lease_trial_prefix_mismatch")
    if shadow.trial_reducer_snapshot_hash is None:
        reasons.append("shadow_trial_snapshot_missing")
    if lease.trial_reducer_snapshot_hash is None:
        reasons.append("lease_trial_snapshot_missing")
    if not shadow.workload_id or shadow.workload_id != lease.workload_id:
        reasons.append("workload_runner_mismatch")
    if shadow.mutation_id != mutation.get("mutation_id"):
        reasons.append("shadow_mutation_mismatch")
    if lease.mutation_id != mutation.get("mutation_id"):
        reasons.append("lease_mutation_mismatch")
    if mutation.get("effect_class") != "workflow_promotion":
        reasons.append("mutation_not_workflow_promotion")
    patch = mutation.get("patch")
    if not isinstance(patch, dict):
        reasons.append("missing_policy_patch")
    elif patch.get("op") == "set_action_grade":
        reasons.append("manual_action_grade_patch_not_active_promotable")
    declared = {str(item) for item in mutation.get("declared_improvement_coordinates", [])}
    if not declared.issubset(set(safe_gate.improved_coordinates)):
        reasons.append("declared_coordinate_not_safely_promoted")
    caps = mutation.get("lease_caps", {})
    if lease.max_events > int(caps.get("max_events", lease.max_events)):
        reasons.append("lease_max_events_exceeds_cap")
    if int(lease.effect_counts.get("external", 0)) != 0:
        reasons.append("external_effect_seen")
    if not lease.rollback_available:
        reasons.append("rollback_missing")
    status = "active_promoted" if not reasons else "rejected_active_promotion"
    return {
        "receipt_type": "active_promotion_receipt",
        "status": status,
        "baseline_ledger_prefix_hash": safe_gate.baseline_ledger_prefix_hash,
        "candidate_ledger_prefix_hash": safe_gate.candidate_ledger_prefix_hash,
        "improved_coordinates": list(safe_gate.improved_coordinates),
        "missing_witness_coordinates": list(safe_gate.missing_witness_coordinates),
        "rejected_reasons": reasons,
        "positive_evidence_witness_hashes": list(safe_gate.positive_evidence_witness_hashes),
        "mutation_id": mutation.get("mutation_id"),
        "shadow_status": shadow.status,
        "lease_status": lease.status,
        "shadow_runner_type": shadow.runner_type,
        "lease_runner_type": lease.runner_type,
        "shadow_execution_receipt_hash": shadow.execution_receipt_hash,
        "lease_execution_receipt_hash": lease.execution_receipt_hash,
        "shadow_trial_ledger_prefix_hash": shadow.trial_ledger_prefix_hash,
        "lease_trial_ledger_prefix_hash": lease.trial_ledger_prefix_hash,
        "shadow_trial_reducer_snapshot_hash": shadow.trial_reducer_snapshot_hash,
        "lease_trial_reducer_snapshot_hash": lease.trial_reducer_snapshot_hash,
    }
