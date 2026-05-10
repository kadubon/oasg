"""No-meta dominance gate for OASG v1.0."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from oasg.canonical import receipt_hash
from oasg.constants import (
    ALLOWED_EFFECT_CLASSES,
    REQUIRED_DIMENSIONS,
    REQUIRED_WITNESS_RECEIPTS,
    not_worse,
    strictly_better,
)
from oasg.klb import KLBResult
from oasg.models import ComparisonContract, PositiveEvidenceWitness, WorkloadManifest
from oasg.reducers.core import ReducerSnapshot


@dataclass(frozen=True)
class GateResult:
    status: str
    baseline_ledger_prefix_hash: str
    candidate_ledger_prefix_hash: str
    improved_coordinates: tuple[str, ...] = field(default_factory=tuple)
    missing_witness_coordinates: tuple[str, ...] = field(default_factory=tuple)
    rejected_reasons: tuple[str, ...] = field(default_factory=tuple)
    positive_evidence_witness_hashes: tuple[str, ...] = field(default_factory=tuple)
    receipt_type: str = "dominance_gate_receipt"

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt_type": self.receipt_type,
            "status": self.status,
            "baseline_ledger_prefix_hash": self.baseline_ledger_prefix_hash,
            "candidate_ledger_prefix_hash": self.candidate_ledger_prefix_hash,
            "improved_coordinates": list(self.improved_coordinates),
            "missing_witness_coordinates": list(self.missing_witness_coordinates),
            "rejected_reasons": list(self.rejected_reasons),
            "positive_evidence_witness_hashes": list(self.positive_evidence_witness_hashes),
        }


def evaluate_gate(
    baseline: ReducerSnapshot,
    candidate: ReducerSnapshot,
    baseline_klb: KLBResult,
    candidate_klb: KLBResult,
    contract: ComparisonContract,
    workload: WorkloadManifest,
    positive_witnesses: Sequence[PositiveEvidenceWitness] = (),
) -> GateResult:
    comparison_failures = _comparison_failures(baseline, candidate, contract, workload)
    if comparison_failures:
        return _reject(
            baseline,
            candidate,
            "rejected_contaminated_comparison",
            *comparison_failures,
        )
    if baseline.ledger_status != "ledger_prefix_valid":
        return _reject(baseline, candidate, "rejected_ledger_integrity", "baseline_ledger")
    if candidate.ledger_status != "ledger_prefix_valid":
        return _reject(baseline, candidate, "rejected_ledger_integrity", "candidate_ledger")
    if baseline_klb.status != "ok":
        return _reject(baseline, candidate, "inconclusive_klb_overflow", baseline_klb.status)
    if candidate_klb.status != "ok":
        return _reject(baseline, candidate, "inconclusive_klb_overflow", candidate_klb.status)
    policy_rejection = _policy_rejection(candidate, candidate_klb, contract)
    if policy_rejection is not None:
        status, reasons = policy_rejection
        return _reject(baseline, candidate, status, *reasons)

    baseline_vector = _dominance_vector(baseline, baseline_klb)
    candidate_vector = _dominance_vector(candidate, candidate_klb)
    regressions = [
        coordinate
        for coordinate, baseline_value in baseline_vector.items()
        if not not_worse(candidate_vector.get(coordinate, "blocked"), baseline_value)
    ]
    if regressions:
        status = "rejected_viability_regression" if any(r.startswith("KLB_2.") for r in regressions) else "rejected_floor_violation"
        return _reject(baseline, candidate, status, *regressions)

    improved = tuple(
        coordinate
        for coordinate, baseline_value in baseline_vector.items()
        if strictly_better(candidate_vector.get(coordinate, "blocked"), baseline_value)
    )
    if not improved:
        return GateResult(
            status="safe_non_regression",
            baseline_ledger_prefix_hash=baseline.ledger_prefix_hash,
            candidate_ledger_prefix_hash=candidate.ledger_prefix_hash,
        )

    valid_witness_hashes: list[str] = []
    missing: list[str] = []
    for coordinate in improved:
        witness_hash = _valid_witness_hash(
            coordinate,
            positive_witnesses,
            candidate,
            candidate_klb,
            contract,
            workload,
        )
        if witness_hash is None:
            missing.append(coordinate)
        else:
            valid_witness_hashes.append(witness_hash)
    if missing:
        return GateResult(
            status="rejected_no_concrete_positive_evidence",
            baseline_ledger_prefix_hash=baseline.ledger_prefix_hash,
            candidate_ledger_prefix_hash=candidate.ledger_prefix_hash,
            improved_coordinates=improved,
            missing_witness_coordinates=tuple(missing),
            rejected_reasons=("missing_positive_evidence_witness",),
        )

    return GateResult(
        status="safe_promotion",
        baseline_ledger_prefix_hash=baseline.ledger_prefix_hash,
        candidate_ledger_prefix_hash=candidate.ledger_prefix_hash,
        improved_coordinates=improved,
        positive_evidence_witness_hashes=tuple(valid_witness_hashes),
    )


def _dominance_vector(snapshot: ReducerSnapshot, klb: KLBResult) -> dict[str, str]:
    vector = {dimension: snapshot.dimensions.get(dimension, "blocked") for dimension in REQUIRED_DIMENSIONS}
    vector.update(
        {f"protected_debt.{key}": value for key, value in snapshot.protected_debt.items()}
    )
    vector.update({f"KLB_2.{action}": klb.klb.get(action, "blocked") for action in klb.action_order})
    return vector


def _reject(
    baseline: ReducerSnapshot,
    candidate: ReducerSnapshot,
    status: str,
    *reasons: str,
) -> GateResult:
    return GateResult(
        status=status,
        baseline_ledger_prefix_hash=baseline.ledger_prefix_hash,
        candidate_ledger_prefix_hash=candidate.ledger_prefix_hash,
        rejected_reasons=tuple(reasons),
    )


def _comparison_failures(
    baseline: ReducerSnapshot,
    candidate: ReducerSnapshot,
    contract: ComparisonContract,
    workload: WorkloadManifest,
) -> tuple[str, ...]:
    failures: list[str] = []
    if contract.workload_manifest_id != workload.workload_id:
        failures.append("workload_mismatch")
    if not workload.canonical_input_order or not workload.input_hashes:
        failures.append("workload_inputs_missing")
    if len(workload.canonical_input_order) != len(workload.input_hashes):
        failures.append("workload_pairing_mismatch")
    if workload.replay_pairing_rule != "same_input_hash":
        failures.append("unsupported_replay_pairing_rule")
    if workload.nondeterminism_seed_policy != "fixed":
        failures.append("unsupported_seed_policy")
    if workload.allowed_nondeterminism != "none":
        failures.append("unsupported_nondeterminism")
    if workload.contamination_policy != "reject":
        failures.append("unsupported_contamination_policy")
    if workload.mismatch_status_policy != "reject":
        failures.append("unsupported_mismatch_policy")
    if list(workload.ledger_prefix_hashes) != [
        baseline.ledger_prefix_hash,
        candidate.ledger_prefix_hash,
    ]:
        failures.append("ledger_prefix_pairing_mismatch")
    baseline_hash = receipt_hash(baseline.to_dict())
    candidate_hash = receipt_hash(candidate.to_dict())
    if workload.baseline_snapshot_hash != baseline_hash:
        failures.append("baseline_snapshot_hash_mismatch")
    if workload.candidate_snapshot_hash != candidate_hash:
        failures.append("candidate_snapshot_hash_mismatch")
    return tuple(failures)


def _policy_rejection(
    candidate: ReducerSnapshot,
    candidate_klb: KLBResult,
    contract: ComparisonContract,
) -> tuple[str, tuple[str, ...]] | None:
    unsupported_effects = tuple(
        effect
        for effect in candidate.effect_classes
        if effect not in ALLOWED_EFFECT_CLASSES and effect != "workflow_promotion"
    )
    if unsupported_effects:
        return "rejected_effect_policy", unsupported_effects
    if "workflow_promotion" in candidate.effect_classes and not candidate.workflow_promotion_authorized:
        return "rejected_effect_policy", ("workflow_promotion_without_authorization",)
    if candidate_klb.klb.get("emit_claim", "blocked") != "blocked" and candidate.semantic_scope in {
        "none",
        "operational_only",
    }:
        return "rejected_semantic_floor_missing", ("emit_claim_without_semantic_floor",)
    if candidate.claim_emitting and candidate.semantic_scope in {"none", "operational_only"}:
        return "rejected_semantic_floor_missing", ("claim_emitting_without_semantic_floor",)
    if candidate.taint_level in {"secret", "unknown_secret"}:
        return "rejected_secret_taint", (candidate.taint_level,)
    if candidate.boundary_status != "valid":
        return "rejected_boundary", (candidate.boundary_status,)
    if candidate.trusted_base_status != "valid":
        return "rejected_trusted_base", (candidate.trusted_base_status,)
    if contract.promotion_requested:
        return "rejected_effect_policy", ("active_promotion_requires_lifecycle_receipts",)
    return None


def _valid_witness_hash(
    coordinate: str,
    witnesses: Sequence[PositiveEvidenceWitness],
    candidate: ReducerSnapshot,
    candidate_klb: KLBResult,
    contract: ComparisonContract,
    workload: WorkloadManifest,
) -> str | None:
    for witness in witnesses:
        if witness.coordinate_id != coordinate or witness.status != "witness_valid":
            continue
        if witness.ledger_prefix_hash != candidate.ledger_prefix_hash:
            continue
        if witness.comparison_contract_hash != receipt_hash(contract.model_dump(mode="json")):
            continue
        if witness.workload_manifest_hash != receipt_hash(workload.model_dump(mode="json")):
            continue
        required_receipts = _required_receipts_for_coordinate(coordinate)
        if not set(required_receipts).issubset(set(witness.required_receipt_types)):
            continue
        observed_evidence = set(candidate.positive_evidence.get(coordinate, []))
        if not observed_evidence:
            continue
        if coordinate.startswith("KLB_2."):
            candidate_klb_hash = receipt_hash(candidate_klb.to_dict())
            if witness.klb_receipt_hash != candidate_klb_hash:
                continue
            if candidate_klb_hash not in witness.evidence_hashes:
                continue
            non_klb_evidence = set(witness.evidence_hashes) - {candidate_klb_hash}
            if not observed_evidence.intersection(non_klb_evidence):
                continue
        elif not observed_evidence.intersection(set(witness.evidence_hashes)):
            continue
        if not witness.evidence_hashes:
            continue
        return receipt_hash(witness.model_dump(mode="json"))
    return None


def _required_receipts_for_coordinate(coordinate: str) -> tuple[str, ...]:
    if coordinate.startswith("KLB_2."):
        return REQUIRED_WITNESS_RECEIPTS["KLB_2"]
    if coordinate.startswith("protected_debt."):
        return REQUIRED_WITNESS_RECEIPTS["protected_debt"]
    return REQUIRED_WITNESS_RECEIPTS["dimension"]
