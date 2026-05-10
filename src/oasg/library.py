"""Workflow library state for active OASG promotions."""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from oasg.canonical import receipt_hash
from oasg.io import read_json, write_json
from oasg.policy_state import MutationPatch, WorkflowPolicyState
from oasg.policy import PolicyProfile, default_policy
from oasg.scheduler import SchedulerResult


@dataclass(frozen=True)
class WorkflowLibrary:
    library_id: str
    active_policy_profile: dict[str, Any]
    policy_state: WorkflowPolicyState = field(default_factory=WorkflowPolicyState.default)
    scheduler_state: SchedulerResult | None = None
    active_mutations: tuple[dict[str, Any], ...] = ()
    quarantined: tuple[dict[str, Any], ...] = ()
    retired: tuple[dict[str, Any], ...] = ()
    mutation_outcomes: tuple[dict[str, Any], ...] = ()
    rollback_snapshots: tuple[dict[str, Any], ...] = ()
    rollback_pointer: str | None = None
    active_promotion_receipts: tuple[str, ...] = ()
    artifact_type: str = "workflow_library"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": self.artifact_type,
            "library_id": self.library_id,
            "active_policy_profile": self.active_policy_profile,
            "policy_state": self.policy_state.to_dict(),
            "scheduler_state": self.scheduler_state.to_dict()
            if self.scheduler_state is not None
            else None,
            "active_mutations": list(self.active_mutations),
            "quarantined": list(self.quarantined),
            "retired": list(self.retired),
            "mutation_outcomes": list(self.mutation_outcomes),
            "rollback_snapshots": list(self.rollback_snapshots),
            "rollback_pointer": self.rollback_pointer,
            "active_promotion_receipts": list(self.active_promotion_receipts),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "WorkflowLibrary":
        policy_state = WorkflowPolicyState.from_dict(raw.get("policy_state"))
        scheduler_raw = raw.get("scheduler_state")
        return cls(
            library_id=str(raw.get("library_id", "default")),
            active_policy_profile=dict(
                raw.get("active_policy_profile", policy_state.policy_profile)
            ),
            policy_state=policy_state,
            scheduler_state=SchedulerResult.from_dict(scheduler_raw)
            if isinstance(scheduler_raw, dict)
            else None,
            active_mutations=tuple(dict(item) for item in raw.get("active_mutations", [])),
            quarantined=tuple(dict(item) for item in raw.get("quarantined", [])),
            retired=tuple(dict(item) for item in raw.get("retired", [])),
            mutation_outcomes=tuple(dict(item) for item in raw.get("mutation_outcomes", [])),
            rollback_snapshots=tuple(dict(item) for item in raw.get("rollback_snapshots", [])),
            rollback_pointer=(
                str(raw["rollback_pointer"]) if raw.get("rollback_pointer") is not None else None
            ),
            active_promotion_receipts=tuple(
                str(item) for item in raw.get("active_promotion_receipts", [])
            ),
        )

    @property
    def policy(self) -> PolicyProfile:
        return self.policy_state.policy


def load_library(path: Path | None) -> WorkflowLibrary:
    if path is None or not path.exists():
        return WorkflowLibrary(
            library_id="default",
            active_policy_profile=default_policy().to_dict(),
            policy_state=WorkflowPolicyState.default(),
        )
    return WorkflowLibrary.from_dict(read_json(path))


class LibraryConflictError(RuntimeError):
    def __init__(self, *, expected: str, observed: str) -> None:
        super().__init__(f"workflow library hash conflict: expected {expected}, observed {observed}")
        self.expected = expected
        self.observed = observed


def write_library(
    path: Path,
    library: WorkflowLibrary,
    *,
    expected_prior_hash: str | None = None,
) -> Path:
    with _library_lock(path):
        if expected_prior_hash is not None and path.exists():
            observed = receipt_hash(load_library(path).to_dict())
            if observed != expected_prior_hash:
                raise LibraryConflictError(expected=expected_prior_hash, observed=observed)
        tmp = path.with_name(f"{path.name}.tmp")
        write_json(tmp, library.to_dict())
        tmp.replace(path)
    return path


@contextmanager
def _library_lock(path: Path, *, timeout_seconds: float = 5.0, stale_seconds: float = 300.0) -> Any:
    lock_path = path.with_name(f"{path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
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
                observed = receipt_hash(load_library(path).to_dict()) if path.exists() else "missing"
                raise LibraryConflictError(expected="library_lock_available", observed=observed)
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


def apply_active_promotion(
    library: WorkflowLibrary,
    *,
    mutation: dict[str, Any],
    active_receipt: dict[str, Any],
) -> WorkflowLibrary:
    if active_receipt.get("status") != "active_promoted":
        return library
    active_receipt_hash = receipt_hash(active_receipt)
    previous_pointer = receipt_hash(library.to_dict())
    patch_raw = mutation.get("patch")
    if not isinstance(patch_raw, dict):
        return library
    patch = MutationPatch.from_dict(patch_raw)
    precondition_hash = receipt_hash(library.policy_state.to_dict())
    if patch.precondition_policy_hash is not None and patch.precondition_policy_hash != precondition_hash:
        raise LibraryConflictError(expected=patch.precondition_policy_hash, observed=precondition_hash)
    next_state = library.policy_state.apply_patch(patch)
    resulting_hash = receipt_hash(next_state.to_dict())
    if patch.resulting_policy_hash is not None and patch.resulting_policy_hash != resulting_hash:
        raise LibraryConflictError(expected=patch.resulting_policy_hash, observed=resulting_hash)
    mutation_entry = {
        "mutation_id": mutation.get("mutation_id"),
        "target_component_id": mutation.get("target_component_id"),
        "declared_improvement_coordinates": mutation.get("declared_improvement_coordinates", []),
        "patch": patch.to_dict(),
        "policy_state_hash": resulting_hash,
        "active_receipt_hash": active_receipt_hash,
    }
    snapshot_body = {
        "policy_state": library.policy_state.to_dict(),
        "active_policy_profile": library.active_policy_profile,
        "scheduler_state": library.scheduler_state.to_dict()
        if library.scheduler_state is not None
        else None,
        "active_mutations": list(library.active_mutations),
        "active_promotion_receipts": list(library.active_promotion_receipts),
        "rollback_pointer": library.rollback_pointer,
    }
    rollback_snapshot = {
        "record_type": "rollback_snapshot",
        "snapshot_hash": receipt_hash(snapshot_body),
        **snapshot_body,
    }
    return WorkflowLibrary(
        library_id=library.library_id,
        active_policy_profile=next_state.policy_profile,
        policy_state=next_state,
        scheduler_state=library.scheduler_state,
        active_mutations=(*library.active_mutations, mutation_entry),
        quarantined=library.quarantined,
        retired=library.retired,
        rollback_snapshots=(*library.rollback_snapshots, rollback_snapshot),
        rollback_pointer=previous_pointer,
        active_promotion_receipts=(*library.active_promotion_receipts, active_receipt_hash),
        mutation_outcomes=(
            *library.mutation_outcomes,
            mutation_outcome_record(
                mutation=mutation,
                status="accepted",
                receipt_hashes=(active_receipt_hash,),
            ),
        ),
    )


def quarantine_library_entry(
    library: WorkflowLibrary,
    *,
    mutation_id: str,
    reason: str,
) -> WorkflowLibrary:
    entry = {"mutation_id": mutation_id, "reason": reason}
    return WorkflowLibrary(
        library_id=library.library_id,
        active_policy_profile=library.active_policy_profile,
        policy_state=library.policy_state,
        scheduler_state=library.scheduler_state,
        active_mutations=library.active_mutations,
        quarantined=(*library.quarantined, entry),
        retired=library.retired,
        mutation_outcomes=library.mutation_outcomes,
        rollback_snapshots=library.rollback_snapshots,
        rollback_pointer=library.rollback_pointer,
        active_promotion_receipts=library.active_promotion_receipts,
    )


def rollback_library(library: WorkflowLibrary) -> WorkflowLibrary:
    if not library.active_mutations:
        return library
    retired_entry = library.active_mutations[-1]
    snapshot = library.rollback_snapshots[-1] if library.rollback_snapshots else {}
    previous_state = WorkflowPolicyState.from_dict(snapshot.get("policy_state"))
    scheduler_raw = snapshot.get("scheduler_state")
    previous_scheduler = (
        SchedulerResult.from_dict(scheduler_raw) if isinstance(scheduler_raw, dict) else library.scheduler_state
    )
    previous_mutations = tuple(
        dict(item) for item in snapshot.get("active_mutations", library.active_mutations[:-1])
    )
    previous_receipts = tuple(
        str(item)
        for item in snapshot.get(
            "active_promotion_receipts",
            library.active_promotion_receipts[:-1],
        )
    )
    return WorkflowLibrary(
        library_id=library.library_id,
        active_policy_profile=dict(snapshot.get("active_policy_profile", previous_state.policy_profile)),
        policy_state=previous_state,
        scheduler_state=previous_scheduler,
        active_mutations=previous_mutations,
        quarantined=library.quarantined,
        retired=(*library.retired, retired_entry),
        mutation_outcomes=(
            *library.mutation_outcomes,
            mutation_outcome_record(
                mutation=retired_entry,
                status="retired",
                receipt_hashes=(),
            ),
        ),
        rollback_snapshots=library.rollback_snapshots[:-1],
        rollback_pointer=(
            str(snapshot["rollback_pointer"]) if snapshot.get("rollback_pointer") is not None else None
        ),
        active_promotion_receipts=previous_receipts,
    )


def with_scheduler_state(
    library: WorkflowLibrary,
    scheduler_state: SchedulerResult | None,
) -> WorkflowLibrary:
    return WorkflowLibrary(
        library_id=library.library_id,
        active_policy_profile=library.active_policy_profile,
        policy_state=library.policy_state,
        scheduler_state=scheduler_state,
        active_mutations=library.active_mutations,
        quarantined=library.quarantined,
        retired=library.retired,
        mutation_outcomes=library.mutation_outcomes,
        rollback_snapshots=library.rollback_snapshots,
        rollback_pointer=library.rollback_pointer,
        active_promotion_receipts=library.active_promotion_receipts,
    )


def with_mutation_outcomes(
    library: WorkflowLibrary,
    outcomes: tuple[dict[str, Any], ...],
) -> WorkflowLibrary:
    return WorkflowLibrary(
        library_id=library.library_id,
        active_policy_profile=library.active_policy_profile,
        policy_state=library.policy_state,
        scheduler_state=library.scheduler_state,
        active_mutations=library.active_mutations,
        quarantined=library.quarantined,
        retired=library.retired,
        mutation_outcomes=outcomes,
        rollback_snapshots=library.rollback_snapshots,
        rollback_pointer=library.rollback_pointer,
        active_promotion_receipts=library.active_promotion_receipts,
    )


def mutation_outcome_record(
    *,
    mutation: dict[str, Any],
    status: str,
    iteration: int = 0,
    cooldown_iterations: int = 0,
    gate_reason: str | None = None,
    runner_reason: str | None = None,
    receipt_hashes: tuple[str, ...] = (),
) -> dict[str, Any]:
    patch = mutation.get("patch")
    patch_dict = dict(patch) if isinstance(patch, dict) else {}
    return {
        "record_type": "mutation_outcome_record",
        "mutation_id": str(mutation.get("mutation_id", patch_dict.get("mutation_id", "unknown"))),
        "patch_hash": _cooldown_patch_hash(patch_dict or {"missing_patch": True}),
        "mutator_id": str(patch_dict.get("mutator_id", "unknown_mutator")),
        "status": status,
        "cooldown_until_iteration": iteration + cooldown_iterations,
        "gate_reason": gate_reason,
        "runner_reason": runner_reason,
        "receipt_hashes": list(receipt_hashes),
    }


def _cooldown_patch_hash(patch: dict[str, Any]) -> str:
    return receipt_hash(
        {
            key: value
            for key, value in patch.items()
            if key
            not in {
                "mutation_id",
                "mutator_id",
                "precondition_policy_hash",
                "resulting_policy_hash",
            }
        }
    )
