"""Built-in conservative conformance scenarios."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from typing import Any

from oasg.canonical import domain_hash, receipt_hash
from oasg.examples import quickstart_records, write_quickstart
from oasg.gate import GateResult, evaluate_gate
from oasg.harness import write_harness_template
from oasg.io import read_json, read_jsonl, write_json
from oasg.klb import calculate_klb, enumerate_traces
from oasg.ledger import seal_records, verify_records
from oasg.library import (
    LibraryConflictError,
    load_library,
    quarantine_library_entry,
    rollback_library,
    write_library,
)
from oasg.models import ComparisonContract, PositiveEvidenceWitness, WorkloadManifest
from oasg.mutators import MutatorProfile, propose_mutations
from oasg.optimizer import run_optimizer, watch_optimizer
from oasg.operations import (
    write_observation_ledger,
    write_active_promotion,
    write_lease_receipt,
    write_mutation_candidate,
    write_shadow_receipt,
)
from oasg.policy import PolicyProfile, default_policy
from oasg.pressure import PressureResult
from oasg.reducers.core import ReducerSnapshot, reduce_ledger
from oasg.runners import default_runner
from oasg.scheduler import SchedulerResult, schedule_pressure


@dataclass(frozen=True)
class ConformanceResult:
    name: str
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


def run_conformance(_path: Path | None = None) -> list[ConformanceResult]:
    results: list[ConformanceResult] = []
    results.append(
        ConformanceResult(
            "klb_trace_count_73",
            len(enumerate_traces()) == 73,
            f"trace_count={len(enumerate_traces())}",
        )
    )
    with TemporaryDirectory() as tmp:
        paths = write_quickstart(Path(tmp))
        baseline = reduce_ledger(paths["baseline"])
        candidate = reduce_ledger(paths["candidate"])
        baseline_klb = calculate_klb(baseline)
        candidate_klb = calculate_klb(candidate)
        gate = evaluate_gate(
            baseline,
            candidate,
            baseline_klb,
            candidate_klb,
            ComparisonContract.model_validate(read_json(paths["contract"])),
            WorkloadManifest.model_validate(read_json(paths["workload"])),
            [
                PositiveEvidenceWitness.model_validate(item)
                for item in read_json(paths["witnesses"])
            ],
        )
        results.append(
            ConformanceResult(
                "witness_backed_safe_promotion",
                gate.status == "safe_promotion",
                gate.status,
            )
        )
        results.extend(_negative_gate_fixtures(paths))
        results.extend(_policy_negative_fixtures())
        results.append(_active_promotion_fixture(Path(tmp)))
        results.append(_active_promotion_negative_fixture(Path(tmp)))
        results.extend(_broad_cycle_negative_fixtures(Path(tmp)))
        results.extend(_optimizer_fixtures(Path(tmp)))
        results.extend(_v05_long_running_fixtures(Path(tmp)))
    return results


def _harness_command(tmp: Path) -> tuple[str, ...]:
    harness = write_harness_template(tmp / "oasg_harness.py")
    return (
        sys.executable,
        str(harness),
        "--mutation",
        "{mutation}",
        "--candidate",
        "{candidate}",
    )


def _negative_gate_fixtures(paths: dict[str, Path]) -> list[ConformanceResult]:
    baseline = reduce_ledger(paths["baseline"])
    candidate = reduce_ledger(paths["candidate"])
    baseline_klb = calculate_klb(baseline)
    candidate_klb = calculate_klb(candidate)
    contract = ComparisonContract.model_validate(read_json(paths["contract"]))
    workload = WorkloadManifest.model_validate(read_json(paths["workload"]))
    witnesses = [PositiveEvidenceWitness.model_validate(item) for item in read_json(paths["witnesses"])]
    no_witness = evaluate_gate(baseline, candidate, baseline_klb, candidate_klb, contract, workload, [])
    bad_workload = WorkloadManifest.model_validate(
        {**workload.model_dump(mode="json"), "workload_id": "bad"}
    )
    workload_gate = evaluate_gate(
        baseline,
        candidate,
        baseline_klb,
        candidate_klb,
        contract,
        bad_workload,
        witnesses,
    )
    tampered = read_jsonl(paths["candidate"])
    tampered[0]["payload"]["dimensions"]["budget"] = "surplus"
    payload_status = verify_records(tampered).status
    migration_status = verify_records(
        seal_records(
            [
                {
                    "record_type": "schema_migration_record",
                    "event_id": "schema_migration_bad",
                    "migration_id": "mig_bad",
                    "from_schema_epoch": "oasg.event_record.v0",
                    "to_schema_epoch": "oasg.event_record.v1",
                    "affected_record_types": ["event_record"],
                    "migration_map": {},
                    "fixture_results": [{"status": "failed"}],
                }
            ]
        )
    ).status
    bad_witness = PositiveEvidenceWitness.model_validate(
        {
            **witnesses[0].model_dump(mode="json"),
            "klb_receipt_hash": domain_hash("OASG:v1.0:bad_klb", "bad"),
        }
    )
    forged_witness_gate = evaluate_gate(
        baseline,
        candidate,
        baseline_klb,
        candidate_klb,
        contract,
        workload,
        [bad_witness],
    )
    overflow_policy = PolicyProfile(
        profile_id="overflow_fixture",
        horizon=2,
        max_trace_classes=1,
        actions=default_policy().actions,
    )
    overflow_gate = evaluate_gate(
        baseline,
        candidate,
        calculate_klb(baseline, overflow_policy),
        calculate_klb(candidate, overflow_policy),
        contract,
        workload,
        witnesses,
    )
    return [
        ConformanceResult(
            "forged_or_missing_witness_rejected",
            no_witness.status == "rejected_no_concrete_positive_evidence",
            no_witness.status,
        ),
        ConformanceResult(
            "workload_mismatch_rejected",
            workload_gate.status == "rejected_contaminated_comparison",
            workload_gate.status,
        ),
        ConformanceResult(
            "payload_hash_mismatch_rejected",
            payload_status == "rejected_payload_hash_mismatch",
            payload_status,
        ),
        ConformanceResult(
            "schema_migration_failure_rejected",
            migration_status == "rejected_schema_migration_invalid",
            migration_status,
        ),
        ConformanceResult(
            "forged_witness_hash_rejected",
            forged_witness_gate.status == "rejected_no_concrete_positive_evidence",
            forged_witness_gate.status,
        ),
        ConformanceResult(
            "klb_overflow_inconclusive",
            overflow_gate.status == "inconclusive_klb_overflow",
            overflow_gate.status,
        ),
    ]


def _policy_negative_fixtures() -> list[ConformanceResult]:
    cases = [
        (
            "stale_boundary_rejected",
            _candidate_with_policy({"boundary_status": "stale_boundary"}),
            "rejected_boundary",
        ),
        (
            "semantic_floor_omission_rejected",
            _candidate_with_policy({"claim_emitting": True}),
            "rejected_semantic_floor_missing",
        ),
        (
            "secret_taint_rejected",
            _candidate_with_policy({"taint_level": "secret"}),
            "rejected_secret_taint",
        ),
        (
            "disallowed_effect_rejected",
            _candidate_with_policy({"effect_classes": ["network"]}),
            "rejected_effect_policy",
        ),
        (
            "trusted_base_bridge_failure_rejected",
            _candidate_with_policy({"trusted_base_status": "unbridged"}),
            "rejected_trusted_base",
        ),
    ]
    results = []
    for name, records, expected in cases:
        gate = _gate_for_records(records)
        results.append(ConformanceResult(name, gate.status == expected, gate.status))

    debt_records = quickstart_records(improved=False)
    debt_records[0]["payload"]["protected_debt"]["evidence"] = "surplus"
    debt_gate = _gate_for_records(debt_records)
    results.append(
        ConformanceResult(
            "protected_debt_repair_without_receipt_rejected",
            debt_gate.status in {"safe_non_regression", "rejected_no_concrete_positive_evidence"},
            debt_gate.status,
        )
    )
    return results


def _candidate_with_policy(policy_updates: dict[str, object]) -> list[dict[str, Any]]:
    records = quickstart_records(improved=False)
    policy = records[0]["payload"]["policy"]
    policy.update(policy_updates)
    return records


def _gate_for_records(records: list[dict[str, Any]]) -> GateResult:
    baseline = reduce_ledger_from_records(quickstart_records(improved=False))
    candidate = reduce_ledger_from_records(records)
    contract = ComparisonContract(comparison_contract_id="contract", workload_manifest_id="workload")
    workload = WorkloadManifest(
        workload_id="workload",
        canonical_input_order=["input"],
        input_hashes=[domain_hash("OASG:v1.0:conformance_input", "input")],
        baseline_snapshot_hash=receipt_hash(baseline.to_dict()),
        candidate_snapshot_hash=receipt_hash(candidate.to_dict()),
        ledger_prefix_hashes=[baseline.ledger_prefix_hash, candidate.ledger_prefix_hash],
    )
    return evaluate_gate(
        baseline,
        candidate,
        calculate_klb(baseline),
        calculate_klb(candidate),
        contract,
        workload,
        [],
    )


def reduce_ledger_from_records(records: list[dict[str, Any]]) -> ReducerSnapshot:
    from oasg.reducers.core import reduce_records

    return reduce_records(seal_records(records))


def _active_promotion_fixture(tmp: Path) -> ConformanceResult:
    history = write_observation_ledger(
        tmp / "active_promotion_history.jsonl",
        workflow_id="active_agent",
        component_id="planner",
        event_id="evt_active_promotion_history",
        dimensions={"budget": "acceptable"},
        action_grades={"pure_read": "acceptable"},
        effect_classes=["pure"],
        semantic_scope="none",
        claim_emitting=False,
        taint_level="public",
        assume_complete=True,
    )
    result = run_optimizer(
        history=history,
        library_path=tmp / "active_promotion_library.json",
        out_dir=tmp / "active_promotion_run",
        max_candidates=4,
        runner_type="local-command",
        runner_command=_harness_command(tmp),
    )
    return ConformanceResult(
        "active_promotion_requires_shadow_and_lease",
        result.receipt["status"] == "active_promoted"
        and bool(result.receipt.get("runner_receipt_hashes")),
        str(result.receipt["status"]),
    )


def _active_promotion_negative_fixture(tmp: Path) -> ConformanceResult:
    mutation_dir = tmp / "mutation_negative"
    paths = write_mutation_candidate(
        mutation_dir,
        mutation_id="mut_negative",
        coordinate="KLB_2.pure_read",
        action_id="pure_read",
        to_grade="surplus",
    )
    quickstart = write_quickstart(tmp / "baseline_negative")
    comparison_dir = tmp / "comparison_negative"
    from oasg.operations import build_klb_witness, write_comparison_bundle

    comparison = write_comparison_bundle(
        comparison_dir,
        baseline=quickstart["baseline"],
        candidate=paths["candidate"],
    )
    witness_path = comparison_dir / "positive_evidence_witnesses.json"
    build_klb_witness(
        coordinate="KLB_2.pure_read",
        candidate_snapshot_path=comparison["candidate_snapshot"],
        candidate_klb_path=comparison["candidate_klb"],
        contract_path=comparison["contract"],
        workload_path=comparison["workload"],
        output=witness_path,
    )
    baseline = reduce_ledger(quickstart["baseline"])
    candidate = reduce_ledger(paths["candidate"])
    gate = evaluate_gate(
        baseline,
        candidate,
        calculate_klb(baseline),
        calculate_klb(candidate),
        ComparisonContract.model_validate(read_json(comparison["contract"])),
        WorkloadManifest.model_validate(read_json(comparison["workload"])),
        [PositiveEvidenceWitness.model_validate(item) for item in read_json(witness_path)],
    )
    gate_path = comparison_dir / "gate.json"
    shadow_path = comparison_dir / "shadow.json"
    lease_path = comparison_dir / "lease.json"
    active_path = comparison_dir / "active.json"
    write_json(gate_path, gate.to_dict())
    write_json(
        shadow_path,
        {
            "receipt_type": "shadow_receipt",
            "mutation_id": "mut_negative",
            "status": "shadow_rejected",
            "ledger_prefix_hash": gate.candidate_ledger_prefix_hash,
            "observed_coordinates": {},
        },
    )
    write_lease_receipt(paths["mutation"], paths["candidate"], lease_path, 1)
    write_active_promotion(
        safe_gate_receipt=read_json(gate_path),
        shadow_path=shadow_path,
        lease_path=lease_path,
        mutation_path=paths["mutation"],
        output=active_path,
    )
    active = read_json(active_path)
    return ConformanceResult(
        "active_promotion_without_shadow_rejected",
        active["status"] == "rejected_active_promotion",
        str(active["status"]),
    )


def _broad_cycle_negative_fixtures(tmp: Path) -> list[ConformanceResult]:
    return [
        _scheduler_starvation_fixture(),
        _shadow_rejects_invalid_candidate_fixture(tmp),
        _rollback_missing_fixture(tmp),
        _unsupported_mutator_fixture(),
    ]


def _scheduler_starvation_fixture() -> ConformanceResult:
    pressure = PressureResult(
        component_id="workflow_policy",
        coordinates={"KLB_2.pure_read": "critical", "KLB_2.local_reversible": "critical"},
    )
    previous = SchedulerResult(
        selected_component_id="workflow_policy",
        selected_coordinates=("KLB_2.pure_read",),
        pressure_age={"KLB_2.pure_read": 2, "KLB_2.local_reversible": 2},
    )
    scheduler = schedule_pressure(pressure, previous=previous, max_selected=1, deadline=1)
    return ConformanceResult(
        "scheduler_starvation_violation_detected",
        bool(scheduler.starvation_violation),
        ",".join(scheduler.starvation_violation),
    )


def _shadow_rejects_invalid_candidate_fixture(tmp: Path) -> ConformanceResult:
    paths = write_mutation_candidate(
        tmp / "shadow_invalid",
        mutation_id="mut_shadow_invalid",
        coordinate="KLB_2.pure_read",
        action_id="pure_read",
        to_grade="surplus",
    )
    records = read_jsonl(paths["candidate"])
    records[0]["payload"]["action_grades"]["pure_read"] = "blocked"
    from oasg.io import write_jsonl

    write_jsonl(paths["candidate"], records)
    shadow_path = tmp / "shadow_invalid.json"
    write_shadow_receipt(paths["mutation"], paths["candidate"], shadow_path)
    shadow = read_json(shadow_path)
    return ConformanceResult(
        "shadow_rejects_invalid_candidate_ledger",
        shadow["status"] == "shadow_rejected",
        str(shadow["status"]),
    )


def _rollback_missing_fixture(tmp: Path) -> ConformanceResult:
    mutation_dir = tmp / "rollback_missing"
    paths = write_mutation_candidate(
        mutation_dir,
        mutation_id="mut_rollback_missing",
        coordinate="KLB_2.pure_read",
        action_id="pure_read",
        to_grade="surplus",
    )
    quickstart = write_quickstart(tmp / "rollback_missing_baseline")
    comparison_dir = tmp / "rollback_missing_comparison"
    from oasg.operations import build_klb_witness, write_comparison_bundle

    comparison = write_comparison_bundle(
        comparison_dir,
        baseline=quickstart["baseline"],
        candidate=paths["candidate"],
    )
    witness_path = comparison_dir / "positive_evidence_witnesses.json"
    build_klb_witness(
        coordinate="KLB_2.pure_read",
        candidate_snapshot_path=comparison["candidate_snapshot"],
        candidate_klb_path=comparison["candidate_klb"],
        contract_path=comparison["contract"],
        workload_path=comparison["workload"],
        output=witness_path,
    )
    baseline = reduce_ledger(quickstart["baseline"])
    candidate = reduce_ledger(paths["candidate"])
    gate = evaluate_gate(
        baseline,
        candidate,
        calculate_klb(baseline),
        calculate_klb(candidate),
        ComparisonContract.model_validate(read_json(comparison["contract"])),
        WorkloadManifest.model_validate(read_json(comparison["workload"])),
        [PositiveEvidenceWitness.model_validate(item) for item in read_json(witness_path)],
    )
    shadow_path = comparison_dir / "shadow.json"
    lease_path = comparison_dir / "lease.json"
    active_path = comparison_dir / "active.json"
    write_shadow_receipt(paths["mutation"], paths["candidate"], shadow_path)
    lease = read_json(write_lease_receipt(paths["mutation"], paths["candidate"], lease_path, 1))
    lease["rollback_available"] = False
    write_json(lease_path, lease)
    write_active_promotion(
        safe_gate_receipt=gate.to_dict(),
        shadow_path=shadow_path,
        lease_path=lease_path,
        mutation_path=paths["mutation"],
        output=active_path,
    )
    active = read_json(active_path)
    return ConformanceResult(
        "rollback_missing_rejects_active_promotion",
        active["status"] == "rejected_active_promotion"
        and "rollback_missing" in active["rejected_reasons"],
        ",".join(active["rejected_reasons"]),
    )


def _unsupported_mutator_fixture() -> ConformanceResult:
    policy = default_policy()
    records = quickstart_records(improved=False)
    records[0]["payload"]["action_grades"] = {
        action: "surplus" if action != "emit_claim" else "blocked"
        for action in policy.action_ids
    }
    snapshot = reduce_ledger_from_records(records)
    klb = calculate_klb(snapshot, policy)
    scheduler = SchedulerResult(
        selected_component_id="workflow_policy",
        selected_coordinates=("KLB_2.emit_claim",),
    )
    batch = propose_mutations(snapshot, klb, scheduler, policy, max_candidates=4)
    proposed_actions = {proposal.action_id for proposal in batch.proposals}
    return ConformanceResult(
        "unsupported_semantic_mutator_not_proposed",
        "emit_claim" not in proposed_actions,
        ",".join(sorted(proposed_actions)),
    )


def _optimizer_fixtures(tmp: Path) -> list[ConformanceResult]:
    history = write_observation_ledger(
        tmp / "optimizer_history.jsonl",
        workflow_id="optimizer_agent",
        component_id="planner",
        event_id="evt_optimizer_history",
        dimensions={"budget": "acceptable"},
        action_grades={"pure_read": "acceptable"},
        effect_classes=["pure"],
        semantic_scope="none",
        claim_emitting=False,
        taint_level="public",
        assume_complete=True,
    )
    positive = run_optimizer(
        history=history,
        library_path=tmp / "optimizer_library.json",
        out_dir=tmp / "optimizer_run",
        max_candidates=4,
        runner_type="local-command",
        runner_command=_harness_command(tmp),
    )
    lease_blocked = run_optimizer(
        history=history,
        library_path=tmp / "optimizer_library_blocked.json",
        out_dir=tmp / "optimizer_run_blocked",
        max_candidates=1,
        max_events=0,
        runner_type="local-command",
        runner_command=_harness_command(tmp),
    )
    multi_cycle = run_optimizer(
        history=history,
        library_path=tmp / "optimizer_library_cycles.json",
        out_dir=tmp / "optimizer_run_cycles",
        max_candidates=4,
        cycles=2,
        runner_type="local-command",
        runner_command=_harness_command(tmp),
    )
    active_patch = positive.library.active_mutations[-1].get("patch", {})
    first_path_map = positive.receipt["candidate_paths"][0]
    seed_snapshot = reduce_ledger(Path(str(first_path_map["candidate"])))
    trial_snapshot = reduce_ledger(Path(str(first_path_map["trial_candidate"])))
    return [
        ConformanceResult(
            "optimizer_promotes_witness_backed_candidate",
            positive.receipt["status"] == "active_promoted",
            str(positive.receipt["status"]),
        ),
        ConformanceResult(
            "optimizer_rejects_lease_cap_overflow",
            lease_blocked.receipt["status"] == "no_valid_candidate",
            str(lease_blocked.receipt["status"]),
        ),
        ConformanceResult(
            "structured_mutation_patch_roundtrip",
            isinstance(active_patch, dict)
            and active_patch.get("record_type") == "mutation_patch"
            and active_patch.get("op") in {
                "adjust_charge",
                "set_retry_policy",
                "set_validator_policy",
                "set_routing_policy",
                "set_context_compression",
                "set_rollback_requirement",
            },
            str(active_patch),
        ),
        ConformanceResult(
            "policy_state_hash_matches_active_mutation",
            positive.library.active_mutations[-1].get("policy_state_hash")
            == receipt_hash(positive.library.policy_state.to_dict()),
            str(positive.library.active_mutations[-1].get("policy_state_hash")),
        ),
        ConformanceResult(
            "runner_receipts_recorded",
            bool(positive.receipt.get("runner_receipt_hashes")),
            str(positive.receipt.get("runner_receipt_hashes")),
        ),
        ConformanceResult(
            "trial_ledger_backed_promotion",
            bool(positive.receipt.get("trial_ledger_prefix_hashes"))
            and bool(trial_snapshot.positive_evidence)
            and seed_snapshot.positive_evidence == {},
            str(positive.receipt.get("trial_ledger_prefix_hashes")),
        ),
        ConformanceResult(
            "scheduler_state_persisted",
            positive.library.scheduler_state is not None,
            str(
                positive.library.scheduler_state.to_dict()
                if positive.library.scheduler_state is not None
                else None
            ),
        ),
        ConformanceResult(
            "multi_cycle_optimizer_run_records_cycles",
            multi_cycle.receipt["cycles_completed"] == 2,
            str(multi_cycle.receipt["cycles_completed"]),
        ),
    ]


def _v05_long_running_fixtures(tmp: Path) -> list[ConformanceResult]:
    history = write_observation_ledger(
        tmp / "watch_history.jsonl",
        workflow_id="watch_agent",
        component_id="planner",
        event_id="evt_watch_history",
        dimensions={"budget": "acceptable"},
        action_grades={"pure_read": "acceptable"},
        effect_classes=["pure"],
        semantic_scope="none",
        claim_emitting=False,
        taint_level="public",
        assume_complete=True,
    )
    library_path = tmp / "watch_library.json"
    state_path = tmp / "optimizer_state.json"
    first_watch = watch_optimizer(
        history=history,
        library_path=library_path,
        state_path=state_path,
        out_dir=tmp / "watch_run_1",
        max_iterations=1,
        runner_type="local-command",
        runner_command=_harness_command(tmp),
    )
    second_watch = watch_optimizer(
        history=history,
        library_path=library_path,
        state_path=state_path,
        out_dir=tmp / "watch_run_2",
        max_iterations=1,
        runner_type="local-command",
        runner_command=_harness_command(tmp),
    )
    append_history = write_observation_ledger(
        tmp / "watch_append_history.jsonl",
        workflow_id="watch_agent",
        component_id="planner",
        event_id="evt_watch_append_history",
        dimensions={"budget": "acceptable"},
        action_grades={"pure_read": "acceptable"},
        effect_classes=["pure"],
        semantic_scope="none",
        claim_emitting=False,
        taint_level="public",
        assume_complete=True,
    )
    append_watch = watch_optimizer(
        history=append_history,
        library_path=tmp / "watch_append_library.json",
        state_path=tmp / "watch_append_state.json",
        out_dir=tmp / "watch_append_run",
        max_iterations=1,
        append_lease_observations=True,
        runner_type="local-command",
        runner_command=_harness_command(tmp),
    )

    runner_rejected_shell = False
    try:
        default_runner("local-command", command=("echo hello",))
    except ValueError:
        runner_rejected_shell = True
    command_runner = default_runner(
        "local-command",
        command=(sys.executable, "-c", "print('oasg')"),
    )

    pressure_history = write_observation_ledger(
        tmp / "cooldown_history.jsonl",
        workflow_id="watch_agent",
        component_id="scheduler",
        event_id="evt_queue_pressure",
        dimensions={"queue": "critical"},
        action_grades={"close_obligation": "acceptable"},
        effect_classes=["pure"],
        semantic_scope="none",
        claim_emitting=False,
        taint_level="public",
        assume_complete=True,
    )
    profile = MutatorProfile(enabled_mutators=("retry_backoff_v1_0",))
    first_cooldown = run_optimizer(
        history=pressure_history,
        library_path=tmp / "cooldown_library.json",
        out_dir=tmp / "cooldown_run_1",
        mutator_profile=profile,
        runner_type="local-command",
        runner_command=_harness_command(tmp),
    )
    second_cooldown = run_optimizer(
        history=pressure_history,
        library_path=tmp / "cooldown_library.json",
        out_dir=tmp / "cooldown_run_2",
        mutator_profile=profile,
        runner_type="local-command",
        runner_command=_harness_command(tmp),
    )
    cooldown_proposals = read_json(second_cooldown.paths["mutation_batch"])["proposals"]

    library = load_library(None)
    conflict_path = tmp / "conflict_library.json"
    write_library(conflict_path, library)
    stale_hash = receipt_hash(library.to_dict())
    write_library(
        conflict_path,
        quarantine_library_entry(library, mutation_id="mut_conflict", reason="fixture"),
    )
    conflict_rejected = False
    try:
        write_library(conflict_path, library, expected_prior_hash=stale_hash)
    except LibraryConflictError:
        conflict_rejected = True

    rolled = rollback_library(load_library(library_path))
    return [
        ConformanceResult(
            "watch_checkpoint_and_no_new_work",
            first_watch["status"] == "active_promoted"
            and second_watch["status"] == "no_new_work",
            f"{first_watch['status']}->{second_watch['status']}",
        ),
        ConformanceResult(
            "watch_append_lease_observations",
            append_watch["status"] == "active_promoted"
            and len(read_jsonl(append_history)) == 2,
            f"{append_watch['status']}:{len(read_jsonl(append_history))}",
        ),
        ConformanceResult(
            "local_command_runner_rejects_shell_string",
            runner_rejected_shell and command_runner.runner_type == "local-command",
            command_runner.runner_type,
        ),
        ConformanceResult(
            "mutation_cooldown_skips_equivalent_failure",
            bool(first_cooldown.library.mutation_outcomes) and cooldown_proposals == [],
            str(cooldown_proposals),
        ),
        ConformanceResult(
            "library_conflict_rejects_stale_write",
            conflict_rejected,
            str(conflict_rejected),
        ),
        ConformanceResult(
            "rollback_restores_active_receipt_state",
            not rolled.active_mutations and not rolled.active_promotion_receipts,
            str(list(rolled.active_promotion_receipts)),
        ),
    ]
