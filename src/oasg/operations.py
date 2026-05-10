"""High-level local operations used by the CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from oasg.canonical import domain_hash, receipt_hash
from oasg.constants import REQUIRED_DIMENSIONS
from oasg.events import event_record, observation_payload
from oasg.io import read_json, read_jsonl, write_json, write_jsonl
from oasg.klb import calculate_klb
from oasg.ledger import seal_records
from oasg.lifecycle import MutationPlan
from oasg.lifecycle import ShadowResult, LeaseResult, active_promotion_receipt
from oasg.models import ComparisonContract, PositiveEvidenceWitness, WorkloadManifest
from oasg.policy_state import MutationPatch
from oasg.policy import PolicyProfile, default_policy
from oasg.reducers.core import ReducerSnapshot, reduce_ledger, reduce_records
from oasg.runners import TrialResult, default_runner


def write_observation_ledger(
    output: Path,
    *,
    workflow_id: str,
    component_id: str,
    event_id: str,
    dimensions: dict[str, str],
    action_grades: dict[str, str],
    effect_classes: list[str],
    semantic_scope: str,
    claim_emitting: bool,
    taint_level: str,
    policy: PolicyProfile | None = None,
    assume_complete: bool = False,
) -> Path:
    policy = policy or default_policy()
    fill_grade = "acceptable" if assume_complete else "blocked"
    merged_dimensions = {dimension: fill_grade for dimension in REQUIRED_DIMENSIONS}
    merged_dimensions.update(dimensions)
    merged_actions = {action: fill_grade for action in policy.action_ids}
    merged_actions.update(action_grades)
    merged_protected_debt = {dimension: fill_grade for dimension in REQUIRED_DIMENSIONS}
    payload = observation_payload(
        dimensions=merged_dimensions,
        action_grades=merged_actions,
        protected_debt=merged_protected_debt,
        policy={
            "effect_classes": effect_classes,
            "semantic_scope": semantic_scope,
            "claim_emitting": claim_emitting,
            "taint_level": taint_level,
            "boundary_status": "valid",
            "trusted_base_status": "valid",
            "workflow_promotion_authorized": False,
        },
    )
    write_jsonl(
        output,
        seal_records(
            [
                event_record(
                    event_id=event_id,
                    workflow_id=workflow_id,
                    component_id=component_id,
                    event_type="observation",
                    payload=payload,
                )
            ]
        ),
    )
    return output


def write_comparison_bundle(
    output_dir: Path,
    *,
    baseline: Path,
    candidate: Path,
    policy: PolicyProfile | None = None,
    baseline_policy: PolicyProfile | None = None,
    candidate_policy: PolicyProfile | None = None,
) -> dict[str, Path]:
    policy = policy or default_policy()
    baseline_policy = baseline_policy or policy
    candidate_policy = candidate_policy or policy
    output_dir.mkdir(parents=True, exist_ok=True)
    baseline_snapshot = reduce_ledger(baseline)
    candidate_snapshot = reduce_ledger(candidate)
    baseline_klb = calculate_klb(baseline_snapshot, baseline_policy)
    candidate_klb = calculate_klb(candidate_snapshot, candidate_policy)
    contract = ComparisonContract(
        comparison_contract_id="comparison_contract",
        workload_manifest_id="workload_manifest",
    )
    workload = WorkloadManifest(
        workload_id="workload_manifest",
        canonical_input_order=["ledger_pair"],
        input_hashes=[
            domain_hash(
                "OASG:v1.0:comparison_input",
                baseline_snapshot.ledger_prefix_hash,
                candidate_snapshot.ledger_prefix_hash,
            )
        ],
        baseline_snapshot_hash=receipt_hash(baseline_snapshot.to_dict()),
        candidate_snapshot_hash=receipt_hash(candidate_snapshot.to_dict()),
        ledger_prefix_hashes=[
            baseline_snapshot.ledger_prefix_hash,
            candidate_snapshot.ledger_prefix_hash,
        ],
    )
    paths = {
        "baseline_snapshot": output_dir / "baseline_snapshot.json",
        "candidate_snapshot": output_dir / "candidate_snapshot.json",
        "baseline_klb": output_dir / "baseline_klb_receipt.json",
        "candidate_klb": output_dir / "candidate_klb_receipt.json",
        "contract": output_dir / "comparison_contract.json",
        "workload": output_dir / "workload_manifest.json",
    }
    write_json(paths["baseline_snapshot"], baseline_snapshot.to_dict())
    write_json(paths["candidate_snapshot"], candidate_snapshot.to_dict())
    write_json(paths["baseline_klb"], baseline_klb.to_dict())
    write_json(paths["candidate_klb"], candidate_klb.to_dict())
    write_json(paths["contract"], contract.model_dump(mode="json"))
    write_json(paths["workload"], workload.model_dump(mode="json"))
    return paths


def write_mutation_candidate(
    output_dir: Path,
    *,
    mutation_id: str,
    coordinate: str,
    action_id: str,
    to_grade: str,
    policy: PolicyProfile | None = None,
    baseline_snapshot: ReducerSnapshot | None = None,
    patch: MutationPatch | None = None,
    allow_synthetic_evidence: bool = True,
) -> dict[str, Path]:
    policy = policy or default_policy()
    output_dir.mkdir(parents=True, exist_ok=True)
    if action_id not in policy.action_ids:
        raise ValueError(f"action_id {action_id!r} is not in policy profile {policy.profile_id!r}")
    patch = patch or MutationPatch(
        mutation_id=mutation_id,
        op="set_action_grade",
        target_action_id=action_id,
        coordinate_id=coordinate,
        value=to_grade,
        mutator_id="manual_action_grade_v1_0",
    )
    plan = MutationPlan(
        mutation_id=mutation_id,
        target_component_id="workflow_policy",
        coordinate_id=coordinate,
        action_id=action_id,
        from_grade="acceptable",
        to_grade=to_grade,
        patch=patch.to_dict() if patch is not None else None,
    )
    evidence_hash = domain_hash("OASG:v1.0:mutation_plan", mutation_id, coordinate, to_grade)
    if baseline_snapshot is None:
        dimensions = {dimension: "acceptable" for dimension in REQUIRED_DIMENSIONS}
        action_grades = {action: "acceptable" for action in policy.action_ids}
        protected_debt = {dimension: "acceptable" for dimension in REQUIRED_DIMENSIONS}
    else:
        dimensions = dict(baseline_snapshot.dimensions)
        action_grades = {
            action: baseline_snapshot.action_grades.get(action, "blocked")
            for action in policy.action_ids
        }
        protected_debt = dict(baseline_snapshot.protected_debt)
    proof_receipts: list[dict[str, str]] = []
    positive_evidence: list[dict[str, str]] = []
    if patch.op == "set_action_grade" and allow_synthetic_evidence:
        action_grades[action_id] = to_grade
        proof_receipts = [{"coordinate": coordinate, "status": "receipt_valid"}]
        positive_evidence = [{"coordinate": coordinate, "evidence_hash": evidence_hash}]
    payload = observation_payload(
        dimensions=dimensions,
        action_grades=action_grades,
        protected_debt=protected_debt,
        proof_obligation_receipts=proof_receipts,
        positive_evidence=positive_evidence,
        policy={
            "effect_classes": ["pure"],
            "semantic_scope": "none",
            "claim_emitting": False,
            "taint_level": "public",
            "boundary_status": "valid",
            "trusted_base_status": "valid",
            "workflow_promotion_authorized": False,
        },
    )
    candidate = output_dir / "candidate.jsonl"
    mutation = output_dir / "mutation_record.json"
    write_jsonl(
        candidate,
        seal_records(
            [
                event_record(
                    event_id=f"evt_{mutation_id}",
                    workflow_id="mutation_candidate",
                    component_id="workflow_policy",
                    event_type="observation",
                    payload=payload,
                )
            ]
        ),
    )
    write_json(mutation, plan.to_dict())
    return {"candidate": candidate, "mutation": mutation}


def write_trial_ledger(
    mutation_path: Path,
    candidate: Path,
    output: Path,
    workload_path: Path | None = None,
    *,
    runner_type: str = "ledger-replay",
    runner_command: tuple[str, ...] | None = None,
    runner_timeout_seconds: int = 30,
    policy: PolicyProfile | None = None,
) -> TrialResult:
    mutation = read_json(mutation_path)
    candidate_records = read_jsonl(candidate)
    candidate_snapshot = reduce_records(candidate_records)
    workload = (
        _candidate_workload(candidate_snapshot)
        if workload_path is None
        else WorkloadManifest.model_validate(read_json(workload_path))
    )
    runner = default_runner(
        runner_type,
        command=_expand_runner_command(
            runner_command,
            mutation_path=mutation_path,
            candidate=candidate,
            trial_ledger_out=output,
            workload_path=workload_path,
        ),
        timeout_seconds=runner_timeout_seconds,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    return runner.run_trial(
        mutation=mutation,
        candidate_seed=candidate_snapshot,
        workload=workload,
        trial_ledger_path=output,
        policy=policy,
    )


def _expand_runner_command(
    command: tuple[str, ...] | None,
    *,
    mutation_path: Path,
    candidate: Path,
    trial_ledger_out: Path,
    workload_path: Path | None,
) -> tuple[str, ...] | None:
    if command is None:
        return None
    replacements = {
        "{mutation}": str(mutation_path),
        "{candidate}": str(candidate),
        "{trial_ledger_out}": str(trial_ledger_out),
        "{workload}": str(workload_path) if workload_path is not None else "",
    }
    return tuple(replacements.get(item, item) for item in command)


def write_trial_bundle(
    mutation_path: Path,
    candidate: Path,
    output_dir: Path,
    workload_path: Path | None = None,
    *,
    runner_type: str = "ledger-replay",
    runner_command: tuple[str, ...] | None = None,
    runner_timeout_seconds: int = 30,
    max_events: int = 1,
    trial_ledger_out: Path | None = None,
    policy: PolicyProfile | None = None,
) -> dict[str, Path]:
    """Run or verify one trial ledger, then derive shadow and lease receipts from it."""

    output_dir.mkdir(parents=True, exist_ok=True)
    mutation = read_json(mutation_path)
    candidate_snapshot = reduce_records(read_jsonl(candidate))
    workload = (
        _candidate_workload(candidate_snapshot)
        if workload_path is None
        else WorkloadManifest.model_validate(read_json(workload_path))
    )
    trial_path = trial_ledger_out or output_dir / "trial.jsonl"
    trial = write_trial_ledger(
        mutation_path,
        candidate,
        trial_path,
        workload_path,
        runner_type=runner_type,
        runner_command=runner_command,
        runner_timeout_seconds=runner_timeout_seconds,
        policy=policy,
    )
    trial_records = read_jsonl(trial.trial_ledger_path)
    support = _trial_supports_patch(
        mutation=mutation,
        trial=trial,
        trial_records=trial_records,
    )
    trial_workload = _with_trial_prefix(workload, trial.trial_snapshot)
    shadow = _shadow_from_trial(mutation, trial, trial_workload, support)
    lease = _lease_from_trial(mutation, trial, trial_workload, max_events, support)
    shadow_path = output_dir / "shadow.json"
    lease_path = output_dir / "lease.json"
    trial_receipt_path = output_dir / "trial_ledger_receipt.json"
    execution_path = output_dir / "workload_execution_receipt.json"
    bundle_path = output_dir / "trial_bundle.json"
    write_json(shadow_path, shadow.to_dict())
    write_json(lease_path, lease.to_dict())
    write_json(trial_receipt_path, trial.to_trial_receipt())
    write_json(execution_path, trial.to_execution_receipt())
    _write_trial_session(
        bundle_path,
        mutation=mutation,
        shadow=shadow.to_dict(),
        lease=lease.to_dict(),
        workload=trial_workload.model_dump(mode="json"),
    )
    return {
        "trial": trial.trial_ledger_path,
        "trial_receipt": trial_receipt_path,
        "execution": execution_path,
        "shadow": shadow_path,
        "lease": lease_path,
        "trial_session": bundle_path,
    }


def write_shadow_receipt(
    mutation_path: Path,
    candidate: Path,
    output: Path,
    workload_path: Path | None = None,
    *,
    runner_type: str = "ledger-replay",
    runner_command: tuple[str, ...] | None = None,
    runner_timeout_seconds: int = 30,
    trial_ledger_out: Path | None = None,
    policy: PolicyProfile | None = None,
) -> Path:
    mutation = read_json(mutation_path)
    candidate_snapshot = reduce_records(read_jsonl(candidate))
    workload = _candidate_workload(candidate_snapshot) if workload_path is None else WorkloadManifest.model_validate(read_json(workload_path))
    trial = write_trial_ledger(
        mutation_path,
        candidate,
        trial_ledger_out or output.with_name(f"{output.stem}_trial.jsonl"),
        workload_path,
        runner_type=runner_type,
        runner_command=runner_command,
        runner_timeout_seconds=runner_timeout_seconds,
        policy=policy,
    )
    trial_workload = _with_trial_prefix(workload, trial.trial_snapshot)
    receipt = default_runner(
        runner_type,
        command=runner_command,
        timeout_seconds=runner_timeout_seconds,
    ).run_shadow(
        mutation=mutation,
        candidate=trial.trial_snapshot,
        workload=trial_workload,
    )
    enriched = ShadowResult(
        mutation_id=receipt.mutation_id,
        status=receipt.status if trial.status == "trial_observed" else "shadow_rejected",
        ledger_prefix_hash=trial.trial_ledger_prefix_hash,
        observed_coordinates=receipt.observed_coordinates,
        replayed_event_count=receipt.replayed_event_count,
        runner_type=receipt.runner_type,
        workload_id=receipt.workload_id,
        input_hashes=receipt.input_hashes,
        execution_receipt_hash=receipt_hash(trial.to_execution_receipt()),
        trial_ledger_path=str(trial.trial_ledger_path),
        trial_ledger_prefix_hash=trial.trial_ledger_prefix_hash,
        trial_reducer_snapshot_hash=trial.trial_reducer_snapshot_hash,
    )
    write_json(output, enriched.to_dict())
    write_json(output.with_name(f"{output.stem}_execution.json"), trial.to_execution_receipt())
    write_json(output.with_name(f"{output.stem}_trial_receipt.json"), trial.to_trial_receipt())
    return output


def write_lease_receipt(
    mutation_path: Path,
    candidate: Path,
    output: Path,
    max_events: int,
    workload_path: Path | None = None,
    *,
    runner_type: str = "ledger-replay",
    runner_command: tuple[str, ...] | None = None,
    runner_timeout_seconds: int = 30,
    trial_ledger_out: Path | None = None,
    policy: PolicyProfile | None = None,
) -> Path:
    mutation = read_json(mutation_path)
    candidate_snapshot = reduce_records(read_jsonl(candidate))
    workload = _candidate_workload(candidate_snapshot) if workload_path is None else WorkloadManifest.model_validate(read_json(workload_path))
    trial = write_trial_ledger(
        mutation_path,
        candidate,
        trial_ledger_out or output.with_name(f"{output.stem}_trial.jsonl"),
        workload_path,
        runner_type=runner_type,
        runner_command=runner_command,
        runner_timeout_seconds=runner_timeout_seconds,
        policy=policy,
    )
    trial_workload = _with_trial_prefix(workload, trial.trial_snapshot)
    receipt = default_runner(
        runner_type,
        command=runner_command,
        timeout_seconds=runner_timeout_seconds,
    ).run_lease(
        mutation=mutation,
        candidate=trial.trial_snapshot,
        workload=trial_workload,
        max_events=max_events,
    )
    enriched = LeaseResult(
        mutation_id=receipt.mutation_id,
        status=receipt.status if trial.status == "trial_observed" else "lease_rejected_cap_exceeded",
        ledger_prefix_hash=trial.trial_ledger_prefix_hash,
        max_events=receipt.max_events,
        effect_counts=receipt.effect_counts,
        executed_event_count=receipt.executed_event_count,
        rollback_available=receipt.rollback_available and trial.effect_counts.get("external", 0) == 0,
        resources={**receipt.resources, **trial.resources},
        runner_type=receipt.runner_type,
        workload_id=receipt.workload_id,
        input_hashes=receipt.input_hashes,
        execution_receipt_hash=receipt_hash(trial.to_execution_receipt()),
        trial_ledger_path=str(trial.trial_ledger_path),
        trial_ledger_prefix_hash=trial.trial_ledger_prefix_hash,
        trial_reducer_snapshot_hash=trial.trial_reducer_snapshot_hash,
    )
    write_json(output, enriched.to_dict())
    write_json(output.with_name(f"{output.stem}_execution.json"), trial.to_execution_receipt())
    write_json(output.with_name(f"{output.stem}_trial_receipt.json"), trial.to_trial_receipt())
    return output


def build_klb_witness(
    *,
    coordinate: str,
    candidate_snapshot_path: Path,
    candidate_klb_path: Path,
    contract_path: Path,
    workload_path: Path,
    output: Path,
) -> Path:
    candidate_snapshot = read_json(candidate_snapshot_path)
    candidate_klb = read_json(candidate_klb_path)
    contract = ComparisonContract.model_validate(read_json(contract_path))
    workload = WorkloadManifest.model_validate(read_json(workload_path))
    klb_hash = receipt_hash(candidate_klb)
    observed = candidate_snapshot.get("positive_evidence", {})
    coordinates = sorted({coordinate, *(str(item) for item in observed)})
    witnesses: list[dict[str, Any]] = []
    required_receipts = [
        "klb_receipt",
        "comparison_contract",
        "workload_manifest",
        "proof_obligation_receipt",
        "protected_debt_record",
    ]
    for coordinate_id in coordinates:
        evidence = observed.get(coordinate_id, [])
        if not evidence:
            continue
        witness = PositiveEvidenceWitness(
            witness_id=f"witness_{coordinate_id.replace('.', '_')}",
            coordinate_id=coordinate_id,
            evidence_hashes=[klb_hash, *evidence],
            required_receipt_types=required_receipts,
            ledger_prefix_hash=str(candidate_snapshot["ledger_prefix_hash"]),
            comparison_contract_hash=receipt_hash(contract.model_dump(mode="json")),
            workload_manifest_hash=receipt_hash(workload.model_dump(mode="json")),
            klb_receipt_hash=klb_hash,
        )
        witnesses.append(witness.model_dump(mode="json"))
    write_json(output, witnesses)
    return output


def write_active_promotion(
    *,
    safe_gate_receipt: dict[str, Any],
    shadow_path: Path,
    lease_path: Path,
    mutation_path: Path,
    output: Path,
) -> Path:
    shadow_raw = read_json(shadow_path)
    lease_raw = read_json(lease_path)
    mutation = read_json(mutation_path)
    safe_gate = _gate_from_dict(safe_gate_receipt)
    shadow = ShadowResult(
        mutation_id=str(shadow_raw["mutation_id"]),
        status=str(shadow_raw["status"]),
        ledger_prefix_hash=str(shadow_raw["ledger_prefix_hash"]),
        observed_coordinates={
            str(k): str(v) for k, v in shadow_raw.get("observed_coordinates", {}).items()
        },
        replayed_event_count=int(shadow_raw.get("replayed_event_count", 0)),
        runner_type=str(shadow_raw.get("runner_type", "synthetic")),
        workload_id=str(shadow_raw.get("workload_id", "")),
        input_hashes=tuple(str(item) for item in shadow_raw.get("input_hashes", [])),
        execution_receipt_hash=(
            str(shadow_raw["execution_receipt_hash"])
            if shadow_raw.get("execution_receipt_hash") is not None
            else None
        ),
        trial_ledger_path=(
            str(shadow_raw["trial_ledger_path"])
            if shadow_raw.get("trial_ledger_path") is not None
            else None
        ),
        trial_ledger_prefix_hash=(
            str(shadow_raw["trial_ledger_prefix_hash"])
            if shadow_raw.get("trial_ledger_prefix_hash") is not None
            else None
        ),
        trial_reducer_snapshot_hash=(
            str(shadow_raw["trial_reducer_snapshot_hash"])
            if shadow_raw.get("trial_reducer_snapshot_hash") is not None
            else None
        ),
    )
    lease = LeaseResult(
        mutation_id=str(lease_raw["mutation_id"]),
        status=str(lease_raw["status"]),
        ledger_prefix_hash=str(lease_raw["ledger_prefix_hash"]),
        max_events=int(lease_raw["max_events"]),
        effect_counts={str(k): int(v) for k, v in lease_raw.get("effect_counts", {}).items()},
        executed_event_count=int(lease_raw.get("executed_event_count", 0)),
        rollback_available=bool(lease_raw.get("rollback_available", False)),
        resources={str(k): int(v) for k, v in lease_raw.get("resources", {}).items()},
        runner_type=str(lease_raw.get("runner_type", "synthetic")),
        workload_id=str(lease_raw.get("workload_id", "")),
        input_hashes=tuple(str(item) for item in lease_raw.get("input_hashes", [])),
        execution_receipt_hash=(
            str(lease_raw["execution_receipt_hash"])
            if lease_raw.get("execution_receipt_hash") is not None
            else None
        ),
        trial_ledger_path=(
            str(lease_raw["trial_ledger_path"])
            if lease_raw.get("trial_ledger_path") is not None
            else None
        ),
        trial_ledger_prefix_hash=(
            str(lease_raw["trial_ledger_prefix_hash"])
            if lease_raw.get("trial_ledger_prefix_hash") is not None
            else None
        ),
        trial_reducer_snapshot_hash=(
            str(lease_raw["trial_reducer_snapshot_hash"])
            if lease_raw.get("trial_reducer_snapshot_hash") is not None
            else None
        ),
    )
    write_json(output, active_promotion_receipt(safe_gate, shadow, lease, mutation))
    return output


def _shadow_from_trial(
    mutation: dict[str, Any],
    trial: TrialResult,
    workload: WorkloadManifest,
    support: bool,
) -> ShadowResult:
    declared = _declared_coordinates(mutation)
    missing = [coordinate for coordinate in declared if not trial.trial_snapshot.positive_evidence.get(coordinate)]
    workload_ok = trial.trial_snapshot.ledger_prefix_hash in set(workload.ledger_prefix_hashes)
    status = (
        "shadow_passed"
        if support
        and trial.status == "trial_observed"
        and declared
        and not missing
        and trial.trial_snapshot.records_seen > 0
        and trial.trial_snapshot.ledger_status == "ledger_prefix_valid"
        and workload_ok
        else "shadow_rejected"
    )
    return ShadowResult(
        mutation_id=str(mutation["mutation_id"]),
        status=status,
        ledger_prefix_hash=trial.trial_ledger_prefix_hash,
        observed_coordinates={
            coordinate: "acceptable" for coordinate in declared if coordinate not in missing
        },
        replayed_event_count=trial.trial_snapshot.records_seen if workload_ok else 0,
        runner_type=trial.runner_type,
        workload_id=workload.workload_id,
        input_hashes=tuple(workload.input_hashes),
        execution_receipt_hash=receipt_hash(trial.to_execution_receipt()),
        trial_ledger_path=str(trial.trial_ledger_path),
        trial_ledger_prefix_hash=trial.trial_ledger_prefix_hash,
        trial_reducer_snapshot_hash=trial.trial_reducer_snapshot_hash,
    )


def _lease_from_trial(
    mutation: dict[str, Any],
    trial: TrialResult,
    workload: WorkloadManifest,
    max_events: int,
    support: bool,
) -> LeaseResult:
    caps = mutation.get("lease_caps", {})
    caps = caps if isinstance(caps, dict) else {}
    cap_events = int(caps.get("max_events", max_events))
    external_cap = int(caps.get("max_external_effects", 0))
    workload_ok = trial.trial_snapshot.ledger_prefix_hash in set(workload.ledger_prefix_hashes)
    external_seen = int(trial.effect_counts.get("external", 0))
    status = (
        "lease_passed"
        if support
        and trial.status == "trial_observed"
        and max_events <= cap_events
        and trial.trial_snapshot.records_seen <= max_events
        and external_seen <= external_cap
        and trial.trial_snapshot.ledger_status == "ledger_prefix_valid"
        and workload_ok
        else "lease_rejected_cap_exceeded"
    )
    effect_counts = {**trial.effect_counts, "workflow_promotion": 1}
    return LeaseResult(
        mutation_id=str(mutation["mutation_id"]),
        status=status,
        ledger_prefix_hash=trial.trial_ledger_prefix_hash,
        max_events=max_events,
        effect_counts=effect_counts,
        executed_event_count=trial.trial_snapshot.records_seen if workload_ok else 0,
        rollback_available=external_seen == 0,
        resources=trial.resources,
        runner_type=trial.runner_type,
        workload_id=workload.workload_id,
        input_hashes=tuple(workload.input_hashes),
        execution_receipt_hash=receipt_hash(trial.to_execution_receipt()),
        trial_ledger_path=str(trial.trial_ledger_path),
        trial_ledger_prefix_hash=trial.trial_ledger_prefix_hash,
        trial_reducer_snapshot_hash=trial.trial_reducer_snapshot_hash,
    )


def _trial_supports_patch(
    *,
    mutation: dict[str, Any],
    trial: TrialResult,
    trial_records: list[dict[str, object]],
) -> bool:
    if trial.runner_type == "demo-replay":
        return trial.status == "trial_observed"
    if trial.status != "trial_observed":
        return False
    patch_raw = mutation.get("patch")
    if not isinstance(patch_raw, dict):
        return False
    patch = MutationPatch.from_dict(patch_raw)
    if patch.op == "set_action_grade":
        return False
    coordinate = patch.coordinate_id
    if not trial.trial_snapshot.positive_evidence.get(coordinate):
        return False
    for record in trial_records:
        payload = record.get("payload") if isinstance(record, dict) else None
        if not isinstance(payload, dict):
            continue
        model_event = payload.get("model_event", {})
        if not isinstance(model_event, dict):
            continue
        if model_event.get("trial_mode") == "deterministic_policy_effect":
            return False
        if _patch_metric_supported(model_event, patch):
            return True
    return False


def _patch_metric_supported(model_event: dict[str, object], patch: MutationPatch) -> bool:
    if str(model_event.get("patch_op", "")) != patch.op:
        return False
    if str(model_event.get("target_action_id", "")) != patch.target_action_id:
        return False
    if str(model_event.get("observed_improvement_coordinate", patch.coordinate_id)) != patch.coordinate_id:
        return False
    negative_keys_by_op = {
        "adjust_charge": ("resource_delta", "budget_delta"),
        "remove_requirement": ("blocked_action_delta", "pressure_delta"),
        "set_retry_policy": ("retry_delta", "queue_age_delta", "pressure_delta"),
        "set_validator_policy": ("validation_debt_delta", "evidence_gap_delta"),
        "set_context_compression": ("context_overflow_delta", "budget_delta"),
        "set_routing_policy": ("pressure_delta", "retry_delta"),
        "set_decomposition_depth": ("pressure_delta", "queue_age_delta"),
        "set_rollback_requirement": ("rollback_gap_delta",),
        "set_lease_cap": ("external_effect_delta", "rollback_gap_delta"),
        "set_semantic_floor": ("semantic_debt_delta",),
    }
    positive_keys_by_op = {
        "set_validator_policy": ("evidence_coverage_delta", "validation_pass_delta"),
        "set_rollback_requirement": ("rollback_receipt_delta",),
        "set_lease_cap": ("rollback_receipt_delta",),
        "set_semantic_floor": ("semantic_floor_delta",),
    }
    for key in negative_keys_by_op.get(patch.op, ()):
        value = model_event.get(key)
        if isinstance(value, (int, float)) and value < 0:
            return True
    for key in positive_keys_by_op.get(patch.op, ()):
        value = model_event.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return True
    if patch.op in {"set_rollback_requirement", "set_lease_cap"} and model_event.get("rollback_receipt_available") is True:
        return True
    return False


def _declared_coordinates(mutation: dict[str, Any]) -> tuple[str, ...]:
    raw_declared = mutation.get("declared_improvement_coordinates", [])
    return tuple(str(item) for item in raw_declared) if isinstance(raw_declared, list) else ()


def _write_trial_session(
    path: Path,
    *,
    mutation: dict[str, Any],
    shadow: dict[str, Any],
    lease: dict[str, Any],
    workload: dict[str, Any],
) -> None:
    receipt = {
        "artifact_type": "trial_session",
        "trial_session_id": f"trial_{mutation.get('mutation_id', 'unknown')}",
        "mutation_id": mutation.get("mutation_id"),
        "workload_id": workload.get("workload_id"),
        "workload_manifest_hash": receipt_hash(workload),
        "shadow_receipt_hash": receipt_hash(shadow),
        "lease_receipt_hash": receipt_hash(lease),
        "shadow_trial_ledger_path": shadow.get("trial_ledger_path"),
        "lease_trial_ledger_path": lease.get("trial_ledger_path"),
        "shadow_trial_ledger_prefix_hash": shadow.get("trial_ledger_prefix_hash"),
        "lease_trial_ledger_prefix_hash": lease.get("trial_ledger_prefix_hash"),
        "shadow_trial_reducer_snapshot_hash": shadow.get("trial_reducer_snapshot_hash"),
        "lease_trial_reducer_snapshot_hash": lease.get("trial_reducer_snapshot_hash"),
    }
    write_json(path, receipt)


def _gate_from_dict(raw: dict[str, Any]) -> Any:
    from oasg.gate import GateResult

    return GateResult(
        status=str(raw["status"]),
        baseline_ledger_prefix_hash=str(raw["baseline_ledger_prefix_hash"]),
        candidate_ledger_prefix_hash=str(raw["candidate_ledger_prefix_hash"]),
        improved_coordinates=tuple(str(item) for item in raw.get("improved_coordinates", [])),
        missing_witness_coordinates=tuple(
            str(item) for item in raw.get("missing_witness_coordinates", [])
        ),
        rejected_reasons=tuple(str(item) for item in raw.get("rejected_reasons", [])),
        positive_evidence_witness_hashes=tuple(
            str(item) for item in raw.get("positive_evidence_witness_hashes", [])
        ),
    )


def _candidate_workload(candidate_snapshot: ReducerSnapshot) -> WorkloadManifest:
    return WorkloadManifest(
        workload_id="candidate_replay",
        canonical_input_order=["candidate_ledger"],
        input_hashes=[
            domain_hash("OASG:v1.0:candidate_replay_input", candidate_snapshot.ledger_prefix_hash)
        ],
        candidate_snapshot_hash=receipt_hash(candidate_snapshot.to_dict()),
        ledger_prefix_hashes=[candidate_snapshot.ledger_prefix_hash],
    )


def _with_trial_prefix(
    workload: WorkloadManifest,
    trial_snapshot: ReducerSnapshot,
) -> WorkloadManifest:
    prefixes = list(workload.ledger_prefix_hashes)
    if trial_snapshot.ledger_prefix_hash not in prefixes:
        prefixes.append(trial_snapshot.ledger_prefix_hash)
    return WorkloadManifest(
        workload_id=workload.workload_id,
        canonical_input_order=list(workload.canonical_input_order),
        input_hashes=list(workload.input_hashes),
        baseline_snapshot_hash=workload.baseline_snapshot_hash,
        candidate_snapshot_hash=receipt_hash(trial_snapshot.to_dict()),
        replay_pairing_rule=workload.replay_pairing_rule,
        nondeterminism_seed_policy=workload.nondeterminism_seed_policy,
        allowed_nondeterminism=workload.allowed_nondeterminism,
        contamination_policy=workload.contamination_policy,
        mismatch_status_policy=workload.mismatch_status_policy,
        ledger_prefix_hashes=prefixes,
    )
