"""Minimal OASG integration for an existing agent.

This script is intentionally dependency-free beyond the local OASG package. It simulates an agent
that emits observable ledgers, then shows one unsupported candidate rejected and one trial-backed
candidate accepted as `safe_promotion`.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from oasg.canonical import domain_hash, receipt_hash
from oasg.constants import ACTION_CLASSES, REQUIRED_DIMENSIONS
from oasg.gate import evaluate_gate
from oasg.io import write_json, write_jsonl
from oasg.klb import calculate_klb
from oasg.ledger import seal_records, verify_records
from oasg.models import ComparisonContract, PositiveEvidenceWitness, WorkloadManifest
from oasg.reducers.core import reduce_records


def _action_grades(*, improved: bool) -> dict[str, str]:
    grades = {action: "acceptable" for action in ACTION_CLASSES}
    grades["emit_claim"] = "blocked"
    grades["promote_workflow"] = "blocked"
    if improved:
        grades["pure_read"] = "surplus"
    return grades


def _observation_payload(*, improved: bool, evidence_hash: str | None) -> dict[str, Any]:
    positive_evidence = []
    proof_receipts = []
    if evidence_hash is not None:
        positive_evidence.append(
            {
                "coordinate": "KLB_2.pure_read",
                "evidence_hash": evidence_hash,
            }
        )
        proof_receipts.append(
            {
                "coordinate": "KLB_2.pure_read",
                "status": "receipt_valid",
            }
        )
    return {
        "payload_type": "observation",
        "dimensions": {dimension: "acceptable" for dimension in REQUIRED_DIMENSIONS},
        "action_grades": _action_grades(improved=improved),
        "protected_debt": {dimension: "acceptable" for dimension in REQUIRED_DIMENSIONS},
        "proof_obligation_receipts": proof_receipts,
        "repair_receipts": [],
        "positive_evidence": positive_evidence,
        "policy": {
            "effect_classes": ["pure"],
            "semantic_scope": "none",
            "claim_emitting": False,
            "taint_level": "public",
            "boundary_status": "valid",
            "trusted_base_status": "valid",
            "workflow_promotion_authorized": False,
        },
        "model_event": None,
    }


def _agent_event(*, event_id: str, improved: bool, evidence_hash: str | None) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "event_time": "2026-05-08T00:00:00Z",
        "collector_id": "minimal_agent",
        "workflow_id": "minimal_agent",
        "component_id": "reader_policy",
        "event_type": "observation",
        "payload": _observation_payload(improved=improved, evidence_hash=evidence_hash),
    }


def _workload(
    *,
    workload_id: str,
    baseline_snapshot: Any,
    candidate_snapshot: Any,
) -> WorkloadManifest:
    data = {
        "workload_id": workload_id,
        "canonical_input_order": ["read_local_state"],
        "input_hashes": [domain_hash("OASG:v1.0:minimal_input", "read_local_state")],
        "baseline_snapshot_hash": receipt_hash(baseline_snapshot.to_dict()),
        "candidate_snapshot_hash": receipt_hash(candidate_snapshot.to_dict()),
        "replay_pairing_rule": "same_input_hash",
        "nondeterminism_seed_policy": "fixed",
        "allowed_nondeterminism": "none",
        "contamination_policy": "reject",
        "mismatch_status_policy": "reject",
        "ledger_prefix_hashes": [
            baseline_snapshot.ledger_prefix_hash,
            candidate_snapshot.ledger_prefix_hash,
        ],
    }
    return WorkloadManifest.model_validate(data)


def _contract(*, contract_id: str, workload_id: str, mutation_id: str) -> ComparisonContract:
    return ComparisonContract.model_validate(
        {
            "comparison_contract_id": contract_id,
            "workload_manifest_id": workload_id,
            "baseline_workflow_id": "minimal_agent_baseline",
            "candidate_mutation_id": mutation_id,
            "promotion_requested": False,
            "allow_workflow_promotion": False,
        }
    )


def _write_gate_bundle(
    *,
    out_dir: Path,
    name: str,
    baseline_records: list[dict[str, Any]],
    candidate_records: list[dict[str, Any]],
    evidence_hash: str | None,
) -> None:
    baseline_path = out_dir / "baseline.jsonl"
    candidate_path = out_dir / f"candidate_{name}.jsonl"
    contract_path = out_dir / f"comparison_contract_{name}.json"
    workload_path = out_dir / f"workload_manifest_{name}.json"
    witnesses_path = out_dir / f"positive_evidence_witnesses_{name}.json"
    gate_path = out_dir / f"gate_{name}.json"

    write_jsonl(baseline_path, baseline_records)
    write_jsonl(candidate_path, candidate_records)

    baseline_snapshot = reduce_records(baseline_records)
    candidate_snapshot = reduce_records(candidate_records)
    baseline_klb = calculate_klb(baseline_snapshot)
    candidate_klb = calculate_klb(candidate_snapshot)
    contract = _contract(
        contract_id=f"minimal_contract_{name}",
        workload_id=f"minimal_workload_{name}",
        mutation_id=f"minimal_mutation_{name}",
    )
    workload = _workload(
        workload_id=f"minimal_workload_{name}",
        baseline_snapshot=baseline_snapshot,
        candidate_snapshot=candidate_snapshot,
    )

    witnesses: list[PositiveEvidenceWitness] = []
    if evidence_hash is not None:
        candidate_klb_hash = receipt_hash(candidate_klb.to_dict())
        witness = PositiveEvidenceWitness.model_validate(
            {
                "receipt_type": "positive_evidence_witness",
                "witness_id": f"minimal_witness_{name}",
                "coordinate_id": "KLB_2.pure_read",
                "evidence_hashes": [candidate_klb_hash, evidence_hash],
                "required_receipt_types": [
                    "klb_receipt",
                    "comparison_contract",
                    "workload_manifest",
                    "minimal_trial_receipt",
                ],
                "status": "witness_valid",
                "ledger_prefix_hash": candidate_snapshot.ledger_prefix_hash,
                "comparison_contract_hash": receipt_hash(contract.model_dump(mode="json")),
                "workload_manifest_hash": receipt_hash(workload.model_dump(mode="json")),
                "klb_receipt_hash": candidate_klb_hash,
            }
        )
        witnesses.append(witness)

    gate = evaluate_gate(
        baseline_snapshot,
        candidate_snapshot,
        baseline_klb,
        candidate_klb,
        contract,
        workload,
        witnesses,
    )
    write_json(contract_path, contract.model_dump(mode="json"))
    write_json(workload_path, workload.model_dump(mode="json"))
    write_json(
        witnesses_path,
        [witness.model_dump(mode="json") for witness in witnesses],
    )
    write_json(gate_path, gate.to_dict())
    write_json(out_dir / f"baseline_snapshot_{name}.json", baseline_snapshot.to_dict())
    write_json(out_dir / f"candidate_snapshot_{name}.json", candidate_snapshot.to_dict())
    write_json(out_dir / f"baseline_klb_{name}.json", baseline_klb.to_dict())
    write_json(out_dir / f"candidate_klb_{name}.json", candidate_klb.to_dict())


def write_minimal_example(out_dir: Path) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    trial_receipt = {
        "receipt_type": "minimal_trial_receipt",
        "status": "trial_observed",
        "coordinate_id": "KLB_2.pure_read",
        "runner": "plain_python_minimal_agent",
        "workload_id": "minimal_workload_trial_backed",
        "observed_delta": "pure_read_available_without_protected_regression",
    }
    trial_hash = receipt_hash(trial_receipt)
    write_json(out_dir / "trial_receipt.json", trial_receipt | {"receipt_hash": trial_hash})

    baseline_records = seal_records(
        [_agent_event(event_id="evt_baseline", improved=False, evidence_hash=None)]
    )
    missing_witness_records = seal_records(
        [_agent_event(event_id="evt_candidate_missing_witness", improved=True, evidence_hash=None)]
    )
    trial_backed_records = seal_records(
        [
            _agent_event(
                event_id="evt_candidate_trial_backed",
                improved=True,
                evidence_hash=trial_hash,
            )
        ]
    )

    _write_gate_bundle(
        out_dir=out_dir,
        name="missing_witness",
        baseline_records=baseline_records,
        candidate_records=missing_witness_records,
        evidence_hash=None,
    )
    _write_gate_bundle(
        out_dir=out_dir,
        name="trial_backed",
        baseline_records=baseline_records,
        candidate_records=trial_backed_records,
        evidence_hash=trial_hash,
    )
    baseline_receipt = verify_records(baseline_records).to_dict()
    write_json(out_dir / "baseline_ledger_receipt.json", baseline_receipt)
    return {
        "baseline": str(out_dir / "baseline.jsonl"),
        "candidate_missing_witness": str(out_dir / "candidate_missing_witness.jsonl"),
        "candidate_trial_backed": str(out_dir / "candidate_trial_backed.jsonl"),
        "gate_missing_witness": str(out_dir / "gate_missing_witness.json"),
        "gate_trial_backed": str(out_dir / "gate_trial_backed.json"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the minimal OASG agent integration.")
    parser.add_argument("--out-dir", type=Path, default=Path("examples/minimal_agent_integration/out"))
    args = parser.parse_args()
    paths = write_minimal_example(args.out_dir)
    for key, value in paths.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
