"""Built-in example data generation."""

from __future__ import annotations

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


def quickstart_records(*, improved: bool) -> list[dict[str, Any]]:
    action_grades = {action: "acceptable" for action in ACTION_CLASSES}
    action_grades["emit_claim"] = "blocked"
    action_grades["promote_workflow"] = "blocked"
    if improved:
        action_grades["pure_read"] = "surplus"
    dimensions = {dimension: "acceptable" for dimension in REQUIRED_DIMENSIONS}
    payload: dict[str, Any] = {
        "dimensions": dimensions,
        "action_grades": action_grades,
        "protected_debt": {dimension: "acceptable" for dimension in REQUIRED_DIMENSIONS},
        "positive_evidence": [],
        "policy": {
            "effect_classes": ["pure"],
            "semantic_scope": "none",
            "claim_emitting": False,
            "taint_level": "public",
            "boundary_status": "valid",
            "trusted_base_status": "valid",
            "workflow_promotion_authorized": False,
        },
    }
    if improved:
        evidence_hash = domain_hash("OASG:v1.0:demo_evidence", "pure_read_surplus")
        payload["proof_obligation_receipts"] = [
            {"coordinate": "KLB_2.pure_read", "status": "receipt_valid"}
        ]
        payload["positive_evidence"].append(
            {
                "coordinate": "KLB_2.pure_read",
                "evidence_hash": evidence_hash,
            }
        )
    return [
        {
            "event_id": "evt_observe_state",
            "event_time": "2026-05-08T00:00:00Z",
            "collector_id": "demo",
            "workflow_id": "quickstart",
            "component_id": "demo_component",
            "event_type": "observation",
            "payload": payload,
        }
    ]


def write_quickstart(output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    baseline = output_dir / "baseline.jsonl"
    candidate = output_dir / "candidate.jsonl"
    contract = output_dir / "comparison_contract.json"
    workload = output_dir / "workload_manifest.json"
    witnesses = output_dir / "positive_evidence_witnesses.json"
    baseline_snapshot_path = output_dir / "baseline_snapshot.json"
    candidate_snapshot_path = output_dir / "candidate_snapshot.json"
    baseline_klb_path = output_dir / "baseline_klb_receipt.json"
    candidate_klb_path = output_dir / "candidate_klb_receipt.json"
    baseline_ledger_receipt = output_dir / "baseline_ledger_receipt.json"
    gate_receipt = output_dir / "gate_receipt.json"
    baseline_records = seal_records(quickstart_records(improved=False))
    candidate_records = seal_records(quickstart_records(improved=True))
    write_jsonl(baseline, baseline_records)
    write_jsonl(candidate, candidate_records)
    baseline_snapshot = reduce_records(baseline_records)
    candidate_snapshot = reduce_records(candidate_records)
    baseline_klb = calculate_klb(baseline_snapshot)
    candidate_klb = calculate_klb(candidate_snapshot)
    contract_data = {
        "comparison_contract_id": "quickstart_contract",
        "workload_manifest_id": "quickstart_workload",
        "baseline_workflow_id": "quickstart_baseline",
        "candidate_mutation_id": "quickstart_candidate",
        "promotion_requested": False,
        "allow_workflow_promotion": False,
    }
    workload_data = {
        "workload_id": "quickstart_workload",
        "canonical_input_order": ["demo_input"],
        "input_hashes": [domain_hash("OASG:v1.0:demo_input", "demo_input")],
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
    contract_model = ComparisonContract.model_validate(contract_data)
    workload_model = WorkloadManifest.model_validate(workload_data)
    candidate_klb_hash = receipt_hash(candidate_klb.to_dict())
    pure_read_evidence_hash = candidate_snapshot.positive_evidence["KLB_2.pure_read"][0]
    witness_data = [
        {
            "receipt_type": "positive_evidence_witness",
            "witness_id": "quickstart_pure_read_witness",
            "coordinate_id": "KLB_2.pure_read",
            "evidence_hashes": [
                candidate_klb_hash,
                pure_read_evidence_hash,
            ],
            "required_receipt_types": [
                "klb_receipt",
                "comparison_contract",
                "workload_manifest",
            ],
            "status": "witness_valid",
            "ledger_prefix_hash": candidate_snapshot.ledger_prefix_hash,
            "comparison_contract_hash": receipt_hash(contract_model.model_dump(mode="json")),
            "workload_manifest_hash": receipt_hash(workload_model.model_dump(mode="json")),
            "klb_receipt_hash": candidate_klb_hash,
        }
    ]
    write_json(contract, contract_model.model_dump(mode="json"))
    write_json(workload, workload_model.model_dump(mode="json"))
    write_json(witnesses, witness_data)
    write_json(baseline_snapshot_path, baseline_snapshot.to_dict())
    write_json(candidate_snapshot_path, candidate_snapshot.to_dict())
    write_json(baseline_klb_path, baseline_klb.to_dict())
    write_json(candidate_klb_path, candidate_klb.to_dict())
    write_json(baseline_ledger_receipt, verify_records(baseline_records).to_dict())
    gate = evaluate_gate(
        baseline_snapshot,
        candidate_snapshot,
        baseline_klb,
        candidate_klb,
        contract_model,
        workload_model,
        [PositiveEvidenceWitness.model_validate(item) for item in witness_data],
    )
    write_json(gate_receipt, gate.to_dict())
    return {
        "baseline": baseline,
        "candidate": candidate,
        "contract": contract,
        "workload": workload,
        "witnesses": witnesses,
        "baseline_snapshot": baseline_snapshot_path,
        "candidate_snapshot": candidate_snapshot_path,
        "baseline_klb": baseline_klb_path,
        "candidate_klb": candidate_klb_path,
        "baseline_ledger_receipt": baseline_ledger_receipt,
        "gate_receipt": gate_receipt,
    }
