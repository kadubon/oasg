"""Read-only independent projection check; no projecting or executing routine."""

from __future__ import annotations

from typing import Any

from oasg.canonical import receipt_hash
from oasg.collective.evidence import checked_execution
from oasg.collective.wire import Contract, Source, digest
from oasg.constants import ACTION_CLASSES, REQUIRED_DIMENSIONS, LEDGER_PROFILE, LEDGER_PROFILE_EPOCH
from oasg.ledger import verify_records
from oasg.reducers.core import reduce_records


def check_projection(contract: Contract, report: dict[str, Any], public_key: bytes) -> dict[str, Any]:
    if set(report) != {"schema_id", "contract", "source", "records", "field_map", "dimensions"}:
        raise ValueError("unknown projection fields")
    if report["schema_id"] != "oasg.collective.projection.v1" or report["contract"] != digest(contract):
        raise ValueError("projection contract binding")
    source = Source.model_validate(report["source"])
    result = checked_execution(contract, source, public_key)
    records = report["records"]
    if len(records) != 1 or verify_records(records).status != "ledger_prefix_valid":
        raise ValueError("incomplete or invalid projected ledger")
    record = records[0]
    if set(record) != {"event_id", "collector_id", "workflow_id", "component_id", "event_type",
                       "payload", "coverage_scope", "authority_scope", "record_type", "append_index",
                       "ledger_profile", "ledger_profile_epoch", "schema_epoch", "policy_epoch",
                       "parent_event_ids", "payload_hash", "payload_pointer", "rejection_status",
                       "supersedes_event_ids", "duplicate_policy", "prev_integrity_hash",
                       "canonical_record_hash", "integrity_hash", "ledger_prefix_hash"}:
        raise ValueError("unknown projected record fields")
    if (record["collector_id"], record["coverage_scope"], record["authority_scope"]) != ("local", "default", "local"):
        raise ValueError("projected authority or coverage changed")
    metadata = {"record_type": "event_record", "append_index": 1, "ledger_profile": LEDGER_PROFILE,
        "ledger_profile_epoch": LEDGER_PROFILE_EPOCH, "schema_epoch": "oasg.event_record.v1",
        "policy_epoch": "oasg.policy.v1.0", "parent_event_ids": [], "payload_pointer": None,
        "rejection_status": None, "supersedes_event_ids": [], "duplicate_policy": "reject_duplicate"}
    if any(record[k] != v for k, v in metadata.items()):
        raise ValueError("unregistered ledger metadata")
    if (record["event_id"], record["workflow_id"], record["component_id"], record["event_type"]) != (
            result.binding.attempt, contract.scope.study, contract.scope.worker, "observation"):
        raise ValueError("projected event substitution")
    supported = (result.evidence_class == contract.evidence_class == "executed_finite_software"
                 and result.complete and result.verification == "positive"
                 and result.work <= contract.max_work)
    expected_floor = "acceptable" if supported else "blocked"
    budget = ("surplus" if result.work <= contract.efficient_work else "acceptable") if supported else "blocked"
    snapshot = reduce_records(records)
    expected_dimensions = {x: budget if x == "budget" else expected_floor for x in REQUIRED_DIMENSIONS}
    expected_actions = {x: "blocked" if x in {"emit_claim", "promote_workflow"} else expected_floor for x in ACTION_CLASSES}
    if (snapshot.dimensions != expected_dimensions or snapshot.action_grades != expected_actions
            or snapshot.protected_debt != dict.fromkeys(REQUIRED_DIMENSIONS, expected_floor)):
        raise ValueError("forged protected grade projection")
    payload = record["payload"]
    if set(payload) != {"payload_type", "dimensions", "action_grades", "protected_debt",
                        "proof_obligation_receipts", "repair_receipts", "positive_evidence", "policy", "model_event"}:
        raise ValueError("unknown projected payload fields")
    coordinates = ["budget", *["KLB_2." + a for a in ACTION_CLASSES]]
    obligations = [{"coordinate": x, "status": "receipt_valid"} for x in coordinates] if supported else []
    witnesses = [{"coordinate": x, "evidence_hash": receipt_hash(source.model_dump())} for x in coordinates] if supported else []
    if (payload["payload_type"] != "observation" or payload["repair_receipts"]
            or payload["proof_obligation_receipts"] != obligations or payload["positive_evidence"] != witnesses
            or payload["dimensions"] != expected_dimensions or payload["action_grades"] != expected_actions
            or payload["protected_debt"] != dict.fromkeys(REQUIRED_DIMENSIONS, expected_floor)):
        raise ValueError("unregistered observation or witness fields")
    if payload["policy"] != {"effect_classes": ["pure"], "semantic_scope": "none",
        "claim_emitting": False, "taint_level": "public", "boundary_status": "valid",
        "trusted_base_status": "valid", "workflow_promotion_authorized": False}:
        raise ValueError("forged policy/effect projection")
    expected_evidence = {x: [receipt_hash(source.model_dump())] for x in ["budget", *["KLB_2." + a for a in ACTION_CLASSES]]} if supported else {}
    if snapshot.positive_evidence != expected_evidence:
        raise ValueError("unbound positive witness")
    if payload["model_event"] != {"source": source.sha256, "contract": digest(contract),
        "cost_id": result.cost_id, "work": result.work, "variant": result.variant,
        "evidence_class": result.evidence_class}:
        raise ValueError("counter or source projection altered")
    expected_map = {
        "dimensions.budget": "execution.work,contract.efficient_work,contract.max_work",
        "protected_floors": "contract.scope,execution.binding,execution.measurements,execution.verification",
        "policy": "contract.effects,execution.external_effects",
        "positive_evidence": "original_source.sha256",
        "model_event": "execution.work,execution.variant,execution.cost_id"}
    if report["field_map"] != expected_map:
        raise ValueError("incomplete field provenance")
    if report["dimensions"] != {"runner_execution_support": supported,
        "evidence_class": result.evidence_class, "source_authentication": "scoped_host_attestation",
        "verification_work_status": result.verification, "execution_authorization": False,
        "statistical_support": None}:
        raise ValueError("unsupported evidence claim")
    return {"ok": True, "source": source.sha256, "projection_completeness": True,
            "execution_authorization": False, "ccr_reward": 0}


def check_trial(contract: Contract, trial: dict[str, Any], public_key: bytes) -> dict[str, Any]:
    from oasg.gate import evaluate_gate
    from oasg.klb import calculate_klb
    from oasg.models import ComparisonContract, PositiveEvidenceWitness, WorkloadManifest

    if set(trial) != {"schema_id", "contract", "projections", "gate", "mutation", "shadow", "lease",
                     "active", "comparison", "workload", "witnesses", "work", "execution_authorization", "collective_benefit"}:
        raise ValueError("unknown trial fields")
    if (trial["schema_id"] != "oasg.collective.trial.v1" or trial["execution_authorization"] is not False
            or trial["collective_benefit"] is not None):
        raise ValueError("unsupported trial authority or benefit claim")
    if trial["contract"] != digest(contract) or len(trial["projections"]) != 2:
        raise ValueError("trial binding or paired source count")
    for report in trial["projections"]:
        check_projection(contract, report, public_key)
    left, right = [Source.model_validate(r["source"]).execution() for r in trial["projections"]]
    if (left.binding.arm, right.binding.arm) != ("baseline", "candidate") or (
        left.binding.run != right.binding.run or left.split != right.split
        or left.binding.input_digest != right.binding.input_digest
        or left.binding.task != right.binding.task or left.binding.trial != right.binding.trial
        or left.binding.reservation != right.binding.reservation
        or left.binding.fencing_token != right.binding.fencing_token
        or left.binding.attempt == right.binding.attempt):
        raise ValueError("unpaired native trial")
    before, after = [reduce_records(r["records"]) for r in trial["projections"]]
    workload = WorkloadManifest.model_validate(trial["workload"])
    comparison = ComparisonContract(comparison_contract_id=digest(contract),
        workload_manifest_id=contract.scope.study, candidate_mutation_id="collective-routing")
    if trial["comparison"] != comparison.model_dump(mode="json") or workload.workload_id != contract.scope.study:
        raise ValueError("unregistered comparison protocol")
    expected_inputs = [receipt_hash({"input":m.input}) for m in left.measurements]
    if workload.input_hashes != expected_inputs or workload.canonical_input_order != [str(i) for i in range(len(expected_inputs))]:
        raise ValueError("trial inclusion changed")
    gate = evaluate_gate(before, after, calculate_klb(before), calculate_klb(after),
        ComparisonContract.model_validate(trial["comparison"]), workload,
        [PositiveEvidenceWitness.model_validate(w) for w in trial["witnesses"]])
    if gate.to_dict() != trial["gate"] or trial["work"] != {"baseline":left.work,"candidate":right.work}:
        raise ValueError("gate or measured work substitution")
    from oasg.lifecycle import LeaseResult, MutationPlan, ShadowResult, active_promotion_receipt
    from oasg.policy_state import MutationPatch

    patch = MutationPatch(mutation_id="collective-routing",op="set_routing_policy",
        target_action_id="local_reversible",coordinate_id="budget",value=contract.candidate,
        mutator_id="registered-finite-routing",precondition_policy_hash=contract.library_digest)
    mutation = MutationPlan(mutation_id=patch.mutation_id,target_component_id=contract.scope.worker,
        coordinate_id="budget",action_id="local_reversible",from_grade=before.dimensions["budget"],
        to_grade=after.dimensions["budget"],patch=patch.to_dict()).to_dict()
    if mutation != trial["mutation"]:
        raise ValueError("candidate changed the registered operational patch")
    supported = all(p["dimensions"]["runner_execution_support"] for p in trial["projections"])
    common: dict[str,Any] = dict(mutation_id=patch.mutation_id,ledger_prefix_hash=after.ledger_prefix_hash,
        runner_type="oasg-registered-finite-worker" if supported else "synthetic",
        workload_id=workload.workload_id,input_hashes=tuple(workload.input_hashes),
        execution_receipt_hash=receipt_hash(trial["projections"][1]["source"]),
        trial_ledger_prefix_hash=after.ledger_prefix_hash,
        trial_reducer_snapshot_hash=receipt_hash(after.to_dict()))
    shadow = ShadowResult(status="shadow_passed" if supported else "shadow_rejected",
        observed_coordinates=after.dimensions,replayed_event_count=1,**common)
    lease = LeaseResult(status="lease_passed" if supported else "lease_rejected_cap_exceeded",
        max_events=1,executed_event_count=1,effect_counts={"external":0},resources={"work":right.work},
        rollback_available=True,**common)
    if (trial["shadow"] != shadow.to_dict() or trial["lease"] != lease.to_dict()
            or trial["active"] != active_promotion_receipt(gate,shadow,lease,mutation)):
        raise ValueError("lifecycle receipts do not reconstruct from source execution")
    return {"ok":True, "local_gate_status":gate.status,"execution_authorization":False}
