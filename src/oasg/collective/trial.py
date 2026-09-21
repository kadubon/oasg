"""Host-controlled bounded execution and the unchanged OASG gate/lifecycle."""

from __future__ import annotations

import base64
import subprocess
import sys
import time
from typing import Any

from oasg.canonical import receipt_hash
from oasg.collective.check import check_projection
from oasg.collective.evidence import reference
from oasg.collective.projection import project
from oasg.collective.wire import Contract, Execution, Measurement, Source, TaskBinding, digest, encoded, loads, sha
from oasg.collective.worker import implementation_digest
from oasg.constants import REQUIRED_WITNESS_RECEIPTS
from oasg.gate import evaluate_gate
from oasg.klb import calculate_klb
from oasg.lifecycle import LeaseResult, MutationPlan, ShadowResult, active_promotion_receipt
from oasg.models import ComparisonContract, PositiveEvidenceWitness, WorkloadManifest
from oasg.policy_state import MutationPatch
from oasg.reducers.core import reduce_records


def run_worker(contract: Contract, binding: TaskBinding, *, split: str,
               key: Any, now: int) -> Source:
    if contract.implementation != implementation_digest() or not contract.execute:
        raise ValueError("host worker not registered")
    if not binding.lease_start <= now < min(binding.lease_end, contract.expires_at):
        raise ValueError("current lease or authority expired")
    inputs = contract.training if split == "training" else contract.confirmation
    variant = contract.baseline if binding.arm == "baseline" else contract.candidate
    if binding.policy_digest != digest({"variant": variant}) or binding.input_digest != digest(inputs):
        raise ValueError("task input or policy not registered")
    completed = subprocess.run([sys.executable, "-m", "oasg.collective.worker"],
        input=encoded({"inputs": inputs, "variant": variant}), capture_output=True,
        timeout=10, check=True, shell=False)
    # Output is bounded by the fixed worker and the registered 8 x 4096 domain.
    raw = loads(completed.stdout)
    if raw["implementation"] != contract.implementation or implementation_digest() != contract.implementation:
        raise ValueError("worker changed during execution")
    measurements = [Measurement.model_validate(m) for m in raw["rows"]]
    correct = all(m.output == reference(m.input) for m in measurements)
    payload = dict(schema_id="oasg.collective.execution.v1", contract=digest(contract),
        binding=binding.model_dump(), variant=variant, implementation=contract.implementation,
        evidence_class=contract.evidence_class, split=split, observed_at=now,
        received_at=max(now, int(time.time())), measurements=[m.model_dump() for m in measurements],
        external_effects=0, verification="positive" if correct else "negative", complete=True,
        cost_id="cost:" + binding.attempt, work=sum(m.probes for m in measurements) + contract.overhead)
    signature = base64.b64encode(key.sign(encoded(payload))).decode()
    result = Execution.model_validate({**payload, "signature": signature})
    original = encoded(result).decode()
    return Source(original=original, sha256=sha(original.encode()), producer_digest=digest(result))


def compare(contract: Contract, baseline: Source, candidate: Source, public_key: bytes) -> dict[str, Any]:
    reports = [project(contract, source, public_key) for source in (baseline, candidate)]
    for report in reports:
        check_projection(contract, report, public_key)
    before, after = [source.execution() for source in (baseline, candidate)]
    if (before.binding.arm != "baseline" or after.binding.arm != "candidate"
            or before.split != after.split or before.binding.run != after.binding.run
            or before.binding.input_digest != after.binding.input_digest
            or before.binding.attempt == after.binding.attempt):
        raise ValueError("unpaired trial")
    snapshots = [reduce_records(r["records"]) for r in reports]
    bl, ca = snapshots
    bk, ck = [calculate_klb(snapshot) for snapshot in snapshots]
    cc = ComparisonContract(comparison_contract_id=digest(contract),
        workload_manifest_id=contract.scope.study, candidate_mutation_id="collective-routing")
    workload = WorkloadManifest(workload_id=contract.scope.study,
        canonical_input_order=[str(i) for i in range(len(before.measurements))],
        input_hashes=[receipt_hash({"input":m.input}) for m in before.measurements],
        baseline_snapshot_hash=receipt_hash(bl.to_dict()),
        candidate_snapshot_hash=receipt_hash(ca.to_dict()),
        ledger_prefix_hashes=[bl.ledger_prefix_hash, ca.ledger_prefix_hash])
    witnesses = []
    for coordinate in ca.positive_evidence:
        is_klb = coordinate.startswith("KLB_2.")
        witnesses.append(PositiveEvidenceWitness(witness_id=coordinate,
            coordinate_id=coordinate, evidence_hashes=[receipt_hash(candidate.model_dump())] +
            ([receipt_hash(ck.to_dict())] if is_klb else []),
            required_receipt_types=list(REQUIRED_WITNESS_RECEIPTS["KLB_2" if is_klb else "dimension"]),
            ledger_prefix_hash=ca.ledger_prefix_hash,
            comparison_contract_hash=receipt_hash(cc.model_dump(mode="json")),
            workload_manifest_hash=receipt_hash(workload.model_dump(mode="json")),
            klb_receipt_hash=receipt_hash(ck.to_dict()) if is_klb else None))
    gate = evaluate_gate(bl, ca, bk, ck, cc, workload, witnesses)
    patch = MutationPatch(mutation_id="collective-routing", op="set_routing_policy",
        target_action_id="local_reversible", coordinate_id="budget", value=contract.candidate,
        mutator_id="registered-finite-routing", precondition_policy_hash=contract.library_digest)
    mutation = MutationPlan(mutation_id=patch.mutation_id, target_component_id=contract.scope.worker,
        coordinate_id="budget", action_id="local_reversible", from_grade=bl.dimensions["budget"],
        to_grade=ca.dimensions["budget"], patch=patch.to_dict()).to_dict()
    supported = all(r["dimensions"]["runner_execution_support"] for r in reports)
    common: dict[str, Any] = dict(mutation_id=patch.mutation_id, ledger_prefix_hash=ca.ledger_prefix_hash,
        runner_type="oasg-registered-finite-worker" if supported else "synthetic",
        workload_id=workload.workload_id, input_hashes=tuple(workload.input_hashes),
        execution_receipt_hash=receipt_hash(candidate.model_dump()), trial_ledger_prefix_hash=ca.ledger_prefix_hash,
        trial_reducer_snapshot_hash=receipt_hash(ca.to_dict()))
    shadow = ShadowResult(status="shadow_passed" if supported else "shadow_rejected",
        observed_coordinates=ca.dimensions, replayed_event_count=1, **common)
    lease = LeaseResult(status="lease_passed" if supported else "lease_rejected_cap_exceeded",
        max_events=1, executed_event_count=1, effect_counts={"external": 0},
        resources={"work": after.work}, rollback_available=True, **common)
    active = active_promotion_receipt(gate, shadow, lease, mutation)
    return {"schema_id": "oasg.collective.trial.v1", "contract": digest(contract),
        "projections": reports, "gate": gate.to_dict(), "mutation": mutation,
        "shadow": shadow.to_dict(), "lease": lease.to_dict(), "active": active,
        "comparison": cc.model_dump(mode="json"), "workload": workload.model_dump(mode="json"),
        "witnesses": [w.model_dump(mode="json") for w in witnesses],
        "work": {"baseline": before.work, "candidate": after.work},
        "execution_authorization": False, "collective_benefit": None}
