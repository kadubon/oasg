from __future__ import annotations

from oasg.canonical import domain_hash, receipt_hash
from oasg.examples import quickstart_records
from oasg.gate import evaluate_gate
from oasg.klb import calculate_klb, enumerate_traces
from oasg.ledger import seal_records
from oasg.models import ComparisonContract, PositiveEvidenceWitness, WorkloadManifest
from oasg.reducers.core import reduce_records


def _contract() -> ComparisonContract:
    return ComparisonContract(
        comparison_contract_id="contract",
        workload_manifest_id="workload",
    )


def _workload(baseline, candidate) -> WorkloadManifest:  # type: ignore[no-untyped-def]
    return WorkloadManifest(
        workload_id="workload",
        canonical_input_order=["input"],
        input_hashes=[domain_hash("OASG:v1.0:test_input", "input")],
        baseline_snapshot_hash=receipt_hash(baseline.to_dict()),
        candidate_snapshot_hash=receipt_hash(candidate.to_dict()),
        ledger_prefix_hashes=[baseline.ledger_prefix_hash, candidate.ledger_prefix_hash],
    )


def _witness(
    coordinate: str,
    candidate,
    candidate_klb,
    contract: ComparisonContract,
    workload: WorkloadManifest,
) -> PositiveEvidenceWitness:  # type: ignore[no-untyped-def]
    klb_hash = receipt_hash(candidate_klb.to_dict())
    observed = candidate.positive_evidence.get(
        coordinate,
        [domain_hash("OASG:v1.0:missing_test_evidence", coordinate)],
    )
    return PositiveEvidenceWitness(
        witness_id=f"wit_{coordinate}",
        coordinate_id=coordinate,
        evidence_hashes=[klb_hash, observed[0]],
        required_receipt_types=["klb_receipt", "comparison_contract", "workload_manifest"],
        ledger_prefix_hash=candidate.ledger_prefix_hash,
        comparison_contract_hash=receipt_hash(contract.model_dump(mode="json")),
        workload_manifest_hash=receipt_hash(workload.model_dump(mode="json")),
        klb_receipt_hash=klb_hash,
    )


def test_klb_trace_enumeration_is_v01_bounded_profile() -> None:
    traces = enumerate_traces()
    assert len(traces) == 73
    assert traces[0] == ()
    assert traces[1] == ("pure_read",)
    assert traces[-1] == ("promote_workflow", "promote_workflow")


def test_gate_accepts_quickstart_candidate_with_positive_witness() -> None:
    baseline = reduce_records(seal_records(quickstart_records(improved=False)))
    candidate = reduce_records(seal_records(quickstart_records(improved=True)))
    contract = _contract()
    workload = _workload(baseline, candidate)
    baseline_klb = calculate_klb(baseline)
    candidate_klb = calculate_klb(candidate)
    result = evaluate_gate(
        baseline,
        candidate,
        baseline_klb,
        candidate_klb,
        contract,
        workload,
        [_witness("KLB_2.pure_read", candidate, candidate_klb, contract, workload)],
    )
    assert result.status == "safe_promotion"
    assert "KLB_2.pure_read" in result.improved_coordinates
    assert result.positive_evidence_witness_hashes


def test_gate_rejects_improvement_without_sidecar_witness_even_if_payload_claims_evidence() -> None:
    records = quickstart_records(improved=True)
    records[0]["payload"]["positive_evidence"] = [
        {
            "coordinate": "KLB_2.pure_read",
            "evidence_hash": domain_hash("OASG:v1.0:forged", "claim"),
        }
    ]
    baseline = reduce_records(seal_records(quickstart_records(improved=False)))
    candidate = reduce_records(seal_records(records))
    contract = _contract()
    workload = _workload(baseline, candidate)
    result = evaluate_gate(
        baseline,
        candidate,
        calculate_klb(baseline),
        calculate_klb(candidate),
        contract,
        workload,
    )
    assert result.status == "rejected_no_concrete_positive_evidence"
    assert "KLB_2.pure_read" in result.missing_witness_coordinates


def test_gate_rejects_sidecar_witness_without_reducer_adopted_evidence() -> None:
    records = quickstart_records(improved=True)
    records[0]["payload"]["proof_obligation_receipts"] = []
    records[0]["payload"]["positive_evidence"] = [
        {
            "coordinate": "KLB_2.pure_read",
            "evidence_hash": domain_hash("OASG:v1.0:forged", "claim"),
        }
    ]
    baseline = reduce_records(seal_records(quickstart_records(improved=False)))
    candidate = reduce_records(seal_records(records))
    contract = _contract()
    workload = _workload(baseline, candidate)
    baseline_klb = calculate_klb(baseline)
    candidate_klb = calculate_klb(candidate)
    result = evaluate_gate(
        baseline,
        candidate,
        baseline_klb,
        candidate_klb,
        contract,
        workload,
        [_witness("KLB_2.pure_read", candidate, candidate_klb, contract, workload)],
    )
    assert result.status == "rejected_no_concrete_positive_evidence"


def test_gate_rejects_klb_regression() -> None:
    candidate_records = quickstart_records(improved=False)
    candidate_records[0]["payload"]["action_grades"]["pure_read"] = "blocked"
    baseline = reduce_records(seal_records(quickstart_records(improved=False)))
    candidate = reduce_records(seal_records(candidate_records))
    contract = _contract()
    workload = _workload(baseline, candidate)
    result = evaluate_gate(
        baseline,
        candidate,
        calculate_klb(baseline),
        calculate_klb(candidate),
        contract,
        workload,
    )
    assert result.status == "rejected_viability_regression"
    assert "KLB_2.pure_read" in result.rejected_reasons


def test_gate_rejects_workload_mismatch() -> None:
    baseline = reduce_records(seal_records(quickstart_records(improved=False)))
    candidate = reduce_records(seal_records(quickstart_records(improved=True)))
    contract = _contract()
    baseline_klb = calculate_klb(baseline)
    candidate_klb = calculate_klb(candidate)
    good_workload = _workload(baseline, candidate)
    bad_workload = WorkloadManifest.model_validate(
        {**good_workload.model_dump(mode="json"), "workload_id": "different"}
    )
    result = evaluate_gate(
        baseline,
        candidate,
        baseline_klb,
        candidate_klb,
        contract,
        bad_workload,
    )
    assert result.status == "rejected_contaminated_comparison"
    assert result.rejected_reasons == ("workload_mismatch",)


def test_gate_rejects_active_promotion_without_effect_receipt() -> None:
    baseline = reduce_records(seal_records(quickstart_records(improved=False)))
    candidate = reduce_records(seal_records(quickstart_records(improved=True)))
    contract = ComparisonContract(
        comparison_contract_id="contract",
        workload_manifest_id="workload",
        promotion_requested=True,
        allow_workflow_promotion=True,
    )
    workload = _workload(baseline, candidate)
    result = evaluate_gate(
        baseline,
        candidate,
        calculate_klb(baseline),
        calculate_klb(candidate),
        contract,
        workload,
    )
    assert result.status == "rejected_effect_policy"
    assert "active_promotion_requires_lifecycle_receipts" in result.rejected_reasons


def test_gate_rejects_claim_emitting_without_semantic_floor() -> None:
    candidate_records = quickstart_records(improved=False)
    candidate_records[0]["payload"]["policy"]["claim_emitting"] = True
    baseline = reduce_records(seal_records(quickstart_records(improved=False)))
    candidate = reduce_records(seal_records(candidate_records))
    result = evaluate_gate(
        baseline,
        candidate,
        calculate_klb(baseline),
        calculate_klb(candidate),
        _contract(),
        _workload(baseline, candidate),
    )
    assert result.status == "rejected_semantic_floor_missing"


def test_gate_rejects_disallowed_network_effect() -> None:
    candidate_records = quickstart_records(improved=False)
    candidate_records[0]["payload"]["policy"]["effect_classes"] = ["network"]
    baseline = reduce_records(seal_records(quickstart_records(improved=False)))
    candidate = reduce_records(seal_records(candidate_records))
    result = evaluate_gate(
        baseline,
        candidate,
        calculate_klb(baseline),
        calculate_klb(candidate),
        _contract(),
        _workload(baseline, candidate),
    )
    assert result.status == "rejected_effect_policy"
    assert "network" in result.rejected_reasons
