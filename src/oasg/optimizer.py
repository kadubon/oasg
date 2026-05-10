"""End-to-end local OASG optimization runner."""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from oasg.canonical import receipt_hash
from oasg.gate import evaluate_gate
from oasg.io import read_json, write_json
from oasg.klb import calculate_klb
from oasg.ledger import append_jsonl
from oasg.library import (
    LibraryConflictError,
    WorkflowLibrary,
    apply_active_promotion,
    load_library,
    mutation_outcome_record,
    with_scheduler_state,
    with_mutation_outcomes,
    write_library,
)
from oasg.models import ComparisonContract, PositiveEvidenceWitness, WorkloadManifest
from oasg.mutators import MutatorProfile, propose_mutations
from oasg.optimizer_state import (
    OptimizerState,
    checkpoint_optimizer_state,
    load_optimizer_state,
    with_trial_state,
    write_optimizer_state,
)
from oasg.operations import (
    build_klb_witness,
    write_active_promotion,
    write_comparison_bundle,
    write_mutation_candidate,
    write_trial_bundle,
)
from oasg.policy import PolicyProfile
from oasg.policy_state import MutationPatch, overlay_snapshot
from oasg.pressure import compute_pressure
from oasg.reducers.core import reduce_ledger
from oasg.scheduler import schedule_pressure
from oasg.scheduler import SchedulerResult


@dataclass(frozen=True)
class OptimizerRunResult:
    receipt: dict[str, Any]
    library: WorkflowLibrary
    paths: dict[str, Path]


def plan_optimizer(
    *,
    history: Path,
    out_dir: Path,
    library_path: Path | None,
    policy: PolicyProfile | None = None,
    previous_scheduler: SchedulerResult | None = None,
    mutator_profile: MutatorProfile | None = None,
    optimizer_state: OptimizerState | None = None,
    max_candidates: int = 4,
) -> dict[str, Path]:
    library = load_library(library_path)
    if previous_scheduler is not None:
        library = with_scheduler_state(library, previous_scheduler)
    context = _build_context(
        history=history,
        out_dir=out_dir,
        library=library,
        policy=policy,
        mutator_profile=mutator_profile,
        optimizer_state=optimizer_state,
        max_candidates=max_candidates,
    )
    _write_context_artifacts(context)
    return {
        "pressure": context["pressure_path"],
        "scheduler": context["scheduler_path"],
        "mutation_batch": context["mutation_batch_path"],
    }


def run_optimizer(
    *,
    history: Path,
    library_path: Path,
    out_dir: Path,
    policy: PolicyProfile | None = None,
    max_candidates: int = 4,
    max_events: int = 1,
    cycles: int = 1,
    runner_type: str = "ledger-replay",
    runner_command: tuple[str, ...] | None = None,
    runner_timeout_seconds: int = 30,
    previous_scheduler: SchedulerResult | None = None,
    mutator_profile: MutatorProfile | None = None,
    optimizer_state: OptimizerState | None = None,
) -> OptimizerRunResult:
    out_dir.mkdir(parents=True, exist_ok=True)

    gate_receipts: list[dict[str, Any]] = []
    active_receipts: list[dict[str, Any]] = []
    runner_receipts: list[dict[str, Any]] = []
    candidate_paths: list[dict[str, str]] = []
    final_library = load_library(library_path)
    initial_library_hash = receipt_hash(final_library.to_dict()) if library_path.exists() else None
    optimizer_state = optimizer_state or OptimizerState(run_id="oasg-run")
    if previous_scheduler is not None:
        final_library = with_scheduler_state(final_library, previous_scheduler)
    last_context: dict[str, Any] | None = None
    cycles_completed = 0

    for cycle_index in range(max(1, cycles)):
        cycle_dir = out_dir / f"cycle_{cycle_index + 1:03d}"
        context = _build_context(
            history=history,
            out_dir=cycle_dir,
            library=final_library,
            policy=policy,
            mutator_profile=mutator_profile,
            optimizer_state=optimizer_state,
            max_candidates=max_candidates,
        )
        cycles_completed += 1
        last_context = context
        _write_context_artifacts(context)
        final_library = with_scheduler_state(final_library, context["scheduler"])
        promoted_this_cycle = False

        for proposal in context["mutation_batch"].proposals:
            candidate_dir = cycle_dir / proposal.mutation_id
            proposal_patch = _bind_patch_hashes(final_library, proposal.patch)
            try:
                candidate_policy = final_library.policy_state.apply_patch(proposal_patch).policy
            except (KeyError, ValueError, TypeError):
                continue
            paths = write_mutation_candidate(
                candidate_dir,
                mutation_id=proposal.mutation_id,
                coordinate=proposal.coordinate,
                action_id=proposal.action_id,
                to_grade=proposal.to_grade,
                policy=context["policy"],
                baseline_snapshot=context["snapshot"],
                patch=proposal_patch,
                allow_synthetic_evidence=False,
            )
            comparison_dir = candidate_dir / "comparison"
            comparison_dir.mkdir(parents=True, exist_ok=True)
            trial_paths = write_trial_bundle(
                paths["mutation"],
                paths["candidate"],
                comparison_dir,
                None,
                runner_type=runner_type,
                runner_command=runner_command,
                runner_timeout_seconds=runner_timeout_seconds,
                max_events=max_events,
                policy=context["policy"],
            )
            shadow_path = trial_paths["shadow"]
            lease_path = trial_paths["lease"]
            shadow_raw = read_json(shadow_path)
            lease_raw = read_json(lease_path)
            runner_receipts.extend([shadow_raw, lease_raw])
            trial_candidate = trial_paths["trial"]
            comparison = write_comparison_bundle(
                comparison_dir,
                baseline=history,
                candidate=trial_candidate,
                policy=context["policy"],
                baseline_policy=context["policy"],
                candidate_policy=candidate_policy,
            )
            trial_session_path = trial_paths["trial_session"]
            witness_path = candidate_dir / "comparison" / "positive_evidence_witnesses.json"
            build_klb_witness(
                coordinate=proposal.coordinate,
                candidate_snapshot_path=comparison["candidate_snapshot"],
                candidate_klb_path=comparison["candidate_klb"],
                contract_path=comparison["contract"],
                workload_path=comparison["workload"],
                output=witness_path,
            )
            gate = evaluate_gate(
                context["snapshot"],
                reduce_ledger(trial_candidate),
                context["klb"],
                calculate_klb(reduce_ledger(trial_candidate), candidate_policy),
                ComparisonContract.model_validate(read_json(comparison["contract"])),
                WorkloadManifest.model_validate(read_json(comparison["workload"])),
                [
                    PositiveEvidenceWitness.model_validate(item)
                    for item in read_json(witness_path)
                ],
            )
            gate_path = candidate_dir / "comparison" / "gate.json"
            write_json(gate_path, gate.to_dict())
            gate_receipts.append(gate.to_dict())
            candidate_paths.append(
                {
                    name: str(path)
                    for name, path in {
                        **paths,
                        **comparison,
                        "shadow": shadow_path,
                        "lease": lease_path,
                        "trial_session": trial_session_path,
                        "trial_candidate": trial_candidate,
                        "trial_receipt": trial_paths["trial_receipt"],
                        "execution": trial_paths["execution"],
                    }.items()
                }
            )

            if gate.status != "safe_promotion":
                continue

            active_path = candidate_dir / "comparison" / "active.json"
            write_active_promotion(
                safe_gate_receipt=gate.to_dict(),
                shadow_path=shadow_path,
                lease_path=lease_path,
                mutation_path=paths["mutation"],
                output=active_path,
            )
            active = read_json(active_path)
            active_receipts.append(active)
            if active.get("status") == "active_promoted":
                final_library = apply_active_promotion(
                    final_library,
                    mutation=read_json(paths["mutation"]),
                    active_receipt=active,
                )
                promoted_this_cycle = True
                break
            final_library = with_mutation_outcomes(
                final_library,
                (
                    *final_library.mutation_outcomes,
                    mutation_outcome_record(
                        mutation=read_json(paths["mutation"]),
                        status="rejected",
                        iteration=optimizer_state.iteration + cycle_index,
                        cooldown_iterations=(mutator_profile or MutatorProfile()).cooldown_iterations,
                        runner_reason="active_promotion_rejected",
                        receipt_hashes=(receipt_hash(active),),
                    ),
                ),
            )
        for gate_receipt, path_map in zip(gate_receipts, candidate_paths, strict=False):
            if gate_receipt.get("status") == "safe_promotion":
                continue
            mutation_path = Path(path_map.get("mutation", ""))
            if not mutation_path.exists():
                continue
            final_library = with_mutation_outcomes(
                final_library,
                (
                    *final_library.mutation_outcomes,
                    mutation_outcome_record(
                        mutation=read_json(mutation_path),
                        status="rejected"
                        if str(gate_receipt.get("status", "")).startswith("rejected")
                        else "inconclusive",
                        iteration=optimizer_state.iteration + cycle_index,
                        cooldown_iterations=(mutator_profile or MutatorProfile()).cooldown_iterations,
                        gate_reason=str(gate_receipt.get("status", "unknown")),
                        receipt_hashes=(receipt_hash(gate_receipt),),
                    ),
                ),
            )
        if not context["mutation_batch"].proposals:
            break
        if not promoted_this_cycle and cycles <= 1:
            break

    if last_context is None:
        last_context = _build_context(
            history=history,
            out_dir=out_dir / "cycle_001",
            library=final_library,
            policy=policy,
            mutator_profile=mutator_profile,
            optimizer_state=optimizer_state,
            max_candidates=max_candidates,
        )

    status = (
        "active_promoted"
        if any(item.get("status") == "active_promoted" for item in active_receipts)
        else "no_valid_candidate"
    )
    checkpoint = checkpoint_optimizer_state(
        optimizer_state,
        ledger_prefix_hash=last_context["snapshot"].ledger_prefix_hash,
        append_index=last_context["snapshot"].records_seen,
        scheduler_state=final_library.scheduler_state,
        mutation_outcomes=final_library.mutation_outcomes,
        last_library_hash=receipt_hash(final_library.to_dict()),
    )
    try:
        write_library(library_path, final_library, expected_prior_hash=initial_library_hash)
    except LibraryConflictError as exc:
        status = "library_conflict"
        conflict_path = out_dir / "library_conflict_receipt.json"
        write_json(
            conflict_path,
            {
                "receipt_type": "library_conflict_receipt",
                "status": "library_conflict",
                "expected_library_hash": exc.expected,
                "observed_library_hash": exc.observed,
            },
        )
    receipt = {
        "receipt_type": "optimizer_run_receipt",
        "status": status,
        "baseline_ledger_prefix_hash": last_context["snapshot"].ledger_prefix_hash,
        "consumed_from_append_index": optimizer_state.last_append_index,
        "consumed_to_append_index": last_context["snapshot"].records_seen,
        "optimizer_state_hash": checkpoint.checkpoint_hash,
        "pressure_vector_hash": receipt_hash(last_context["pressure"].to_dict()),
        "scheduler_state_hash": receipt_hash(last_context["scheduler"].to_dict()),
        "mutation_batch_hash": receipt_hash(last_context["mutation_batch"].to_dict()),
        "gate_receipt_hashes": [receipt_hash(item) for item in gate_receipts],
        "active_promotion_receipt_hashes": [receipt_hash(item) for item in active_receipts],
        "runner_receipt_hashes": [receipt_hash(item) for item in runner_receipts],
        "trial_ledger_prefix_hashes": [
            str(item["trial_ledger_prefix_hash"])
            for item in runner_receipts
            if item.get("trial_ledger_prefix_hash") is not None
        ],
        "trial_reducer_snapshot_hashes": [
            str(item["trial_reducer_snapshot_hash"])
            for item in runner_receipts
            if item.get("trial_reducer_snapshot_hash") is not None
        ],
        "library_hash": receipt_hash(final_library.to_dict()),
        "candidate_paths": candidate_paths,
        "cycles_completed": cycles_completed,
    }
    optimizer_receipt = out_dir / "optimizer_run_receipt.json"
    write_json(optimizer_receipt, receipt)
    return OptimizerRunResult(
        receipt=receipt,
        library=final_library,
        paths={
            "optimizer_run_receipt": optimizer_receipt,
            "workflow_library": library_path,
            "pressure": last_context["pressure_path"],
            "scheduler": last_context["scheduler_path"],
            "mutation_batch": last_context["mutation_batch_path"],
        },
    )


def _build_context(
    history: Path,
    out_dir: Path,
    library: WorkflowLibrary,
    policy: PolicyProfile | None,
    mutator_profile: MutatorProfile | None,
    optimizer_state: OptimizerState | None,
    max_candidates: int,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    active_policy = policy or library.policy
    snapshot = overlay_snapshot(reduce_ledger(history), library.policy_state)
    klb = calculate_klb(snapshot, active_policy)
    pressure = compute_pressure(snapshot, klb)
    scheduler = schedule_pressure(
        pressure,
        previous=library.scheduler_state,
        max_selected=max_candidates,
    )
    mutation_batch = propose_mutations(
        snapshot,
        klb,
        scheduler,
        active_policy,
        max_candidates=max_candidates,
        mutator_profile=mutator_profile,
        outcome_memory=library.mutation_outcomes
        if optimizer_state is None
        else (*library.mutation_outcomes, *optimizer_state.mutation_outcomes),
        iteration=optimizer_state.iteration if optimizer_state is not None else 0,
    )
    return {
        "library": library,
        "policy": active_policy,
        "snapshot": snapshot,
        "klb": klb,
        "pressure": pressure,
        "scheduler": scheduler,
        "mutation_batch": mutation_batch,
        "pressure_path": out_dir / "pressure_vector.json",
        "scheduler_path": out_dir / "scheduler_state.json",
        "mutation_batch_path": out_dir / "mutation_batch.json",
    }


def _write_context_artifacts(context: dict[str, Any]) -> None:
    write_json(context["pressure_path"], context["pressure"].to_dict())
    write_json(context["scheduler_path"], context["scheduler"].to_dict())
    write_json(context["mutation_batch_path"], context["mutation_batch"].to_dict())


def _bind_patch_hashes(library: WorkflowLibrary, patch: MutationPatch) -> MutationPatch:
    precondition_hash = receipt_hash(library.policy_state.to_dict())
    resulting_state = library.policy_state.apply_patch(patch)
    return MutationPatch(
        mutation_id=patch.mutation_id,
        op=patch.op,
        target_action_id=patch.target_action_id,
        coordinate_id=patch.coordinate_id,
        value=patch.value,
        mutator_id=patch.mutator_id,
        target_surface=patch.target_surface,
        precondition_policy_hash=precondition_hash,
        resulting_policy_hash=receipt_hash(resulting_state.to_dict()),
    )


def watch_optimizer(
    *,
    history: Path,
    library_path: Path,
    state_path: Path,
    out_dir: Path,
    policy: PolicyProfile | None = None,
    mutator_profile: MutatorProfile | None = None,
    max_candidates: int = 4,
    max_events: int = 1,
    max_iterations: int = 1,
    interval_seconds: float = 0.0,
    runner_type: str = "ledger-replay",
    runner_command: tuple[str, ...] | None = None,
    runner_timeout_seconds: int = 30,
    append_lease_observations: bool = False,
) -> dict[str, Any]:
    import time

    out_dir.mkdir(parents=True, exist_ok=True)
    state = load_optimizer_state(state_path)
    run_receipts: list[dict[str, Any]] = []
    final_status = "no_new_work"

    for iteration_index in range(max_iterations):
        snapshot = reduce_ledger(history)
        if state.last_append_index > snapshot.records_seen:
            final_status = "stale_optimizer_state"
            break
        if (
            state.last_append_index == snapshot.records_seen
            and state.last_observed_ledger_prefix_hash is not None
            and state.last_observed_ledger_prefix_hash != snapshot.ledger_prefix_hash
        ):
            final_status = "stale_optimizer_state"
            break
        if (
            state.last_append_index == snapshot.records_seen
            and state.last_observed_ledger_prefix_hash == snapshot.ledger_prefix_hash
        ):
            final_status = "no_new_work"
            break
        iteration_dir = out_dir / f"watch_{state.iteration + 1:06d}"
        result = run_optimizer(
            history=history,
            library_path=library_path,
            out_dir=iteration_dir,
            policy=policy,
            max_candidates=max_candidates,
            max_events=max_events,
            cycles=1,
            runner_type=runner_type,
            runner_command=runner_command,
            runner_timeout_seconds=runner_timeout_seconds,
            previous_scheduler=state.scheduler_state,
            mutator_profile=mutator_profile,
            optimizer_state=state,
        )
        final_status = str(result.receipt["status"])
        state = checkpoint_optimizer_state(
            state,
            ledger_prefix_hash=str(result.receipt["baseline_ledger_prefix_hash"]),
            append_index=int(result.receipt["consumed_to_append_index"]),
            scheduler_state=result.library.scheduler_state,
            mutation_outcomes=result.library.mutation_outcomes,
            last_library_hash=str(result.receipt["library_hash"]),
        )
        append_receipts: list[dict[str, Any]] = []
        if append_lease_observations and final_status == "active_promoted":
            for path_map in result.receipt.get("candidate_paths", []):
                if not isinstance(path_map, dict):
                    continue
                trial_path = path_map.get("trial_candidate")
                if not trial_path:
                    continue
                append_receipt = append_jsonl(
                    history,
                    Path(str(trial_path)),
                    history,
                    expected_prefix_hash=state.last_observed_ledger_prefix_hash,
                )
                append_receipts.append(append_receipt.to_dict())
                if append_receipt.status != "appended":
                    final_status = "stale_optimizer_state"
                    break
                snapshot_after_append = reduce_ledger(history)
                state = checkpoint_optimizer_state(
                    state,
                    ledger_prefix_hash=snapshot_after_append.ledger_prefix_hash,
                    append_index=snapshot_after_append.records_seen,
                    scheduler_state=result.library.scheduler_state,
                    mutation_outcomes=result.library.mutation_outcomes,
                    last_library_hash=str(result.receipt["library_hash"]),
                )
        write_optimizer_state(state_path, state)
        run_receipt = dict(result.receipt)
        if append_receipts:
            run_receipt["ledger_append_receipts"] = append_receipts
        run_receipts.append(run_receipt)
        if final_status != "active_promoted":
            break
        if interval_seconds > 0 and iteration_index + 1 < max_iterations:
            time.sleep(interval_seconds)

    receipt = {
        "receipt_type": "optimizer_watch_receipt",
        "status": final_status,
        "optimizer_state_hash": state.checkpoint_hash,
        "state_path": str(state_path),
        "run_receipt_hashes": [receipt_hash(item) for item in run_receipts],
        "iterations_completed": len(run_receipts),
    }
    write_json(out_dir / "optimizer_watch_receipt.json", receipt)
    return receipt


def supervise_optimizer(
    *,
    history: Path,
    library_path: Path,
    state_path: Path,
    out_dir: Path,
    policy: PolicyProfile | None = None,
    mutator_profile: MutatorProfile | None = None,
    max_candidates: int = 4,
    max_events: int = 1,
    max_iterations: int = 1,
    interval_seconds: float = 0.0,
    runner_type: str = "ledger-replay",
    runner_command: tuple[str, ...] | None = None,
    runner_timeout_seconds: int = 30,
    append_lease_observations: bool = False,
    require_active_by_epoch: int | None = None,
) -> dict[str, Any]:
    """Durable supervisor transaction over state, history, library, and trials."""

    out_dir.mkdir(parents=True, exist_ok=True)
    with _supervisor_lock(out_dir):
        state = load_optimizer_state(state_path)
        recovered_trials = tuple(state.active_trial_ids)
        for trial_id in recovered_trials:
            state = with_trial_state(
                state,
                trial_id=trial_id,
                status="quarantined",
                receipt_hashes=(),
            )
        trial_id = f"trial_{state.run_id}_{state.iteration + 1:06d}"
        state = with_trial_state(state, trial_id=trial_id, status="pending")
        write_optimizer_state(state_path, state)
        receipt = watch_optimizer(
            history=history,
            library_path=library_path,
            state_path=state_path,
            out_dir=out_dir,
            policy=policy,
            mutator_profile=mutator_profile,
            max_candidates=max_candidates,
            max_events=max_events,
            max_iterations=max_iterations,
            interval_seconds=interval_seconds,
            runner_type=runner_type,
            runner_command=runner_command,
            runner_timeout_seconds=runner_timeout_seconds,
            append_lease_observations=append_lease_observations,
        )
        final_state = load_optimizer_state(state_path)
        active_ready = _library_has_active_policy(library_path)
        receipt_status = str(receipt.get("status", "unknown"))
        if (
            require_active_by_epoch is not None
            and not active_ready
            and final_state.iteration >= require_active_by_epoch
            and receipt_status != "active_promoted"
        ):
            receipt = {
                **receipt,
                "status": "inconclusive_no_active_policy",
                "required_active_by_epoch": require_active_by_epoch,
            }
        trial_status = "promoted" if receipt.get("status") == "active_promoted" else "rejected"
        final_state = with_trial_state(
            final_state,
            trial_id=trial_id,
            status=trial_status,
            receipt_hashes=(receipt_hash(receipt),),
        )
        write_optimizer_state(state_path, final_state)
        supervisor_receipt = {
            "receipt_type": "optimizer_supervisor_receipt",
            "status": receipt.get("status", "unknown"),
            "trial_id": trial_id,
            "recovered_trial_ids": list(recovered_trials),
            "adaptive_readiness": {
                "receipt_type": "adaptive_readiness_receipt",
                "status": "active_policy_ready" if active_ready else "no_active_policy",
                "required_active_by_epoch": require_active_by_epoch,
            },
            "optimizer_state_hash": final_state.checkpoint_hash,
            "watch_receipt_hash": receipt_hash(receipt),
            "watch_receipt": receipt,
        }
        write_json(out_dir / "optimizer_supervisor_receipt.json", supervisor_receipt)
        return supervisor_receipt


def _library_has_active_policy(library_path: Path) -> bool:
    if not library_path.exists():
        return False
    try:
        library = load_library(library_path)
    except (OSError, ValueError, TypeError):
        return False
    return bool(library.active_mutations)


@contextmanager
def _supervisor_lock(out_dir: Path, *, timeout_seconds: float = 5.0, stale_seconds: float = 300.0) -> Any:
    lock_path = out_dir / "supervisor.lock"
    deadline = time.monotonic() + timeout_seconds
    fd: int | None = None
    while fd is None:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"pid={os.getpid()}\ntime={time.time()}\n".encode("utf-8"))
        except FileExistsError:
            try:
                age = time.time() - lock_path.stat().st_mtime
            except FileNotFoundError:
                continue
            if age > stale_seconds:
                stale_path = lock_path.with_suffix(lock_path.suffix + ".stale")
                try:
                    lock_path.replace(stale_path)
                except FileNotFoundError:
                    continue
                continue
            if time.monotonic() >= deadline:
                raise RuntimeError("optimizer supervisor lock is held")
            time.sleep(0.05)
    try:
        yield
    finally:
        if fd is not None:
            os.close(fd)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass
