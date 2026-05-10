"""Durable optimizer checkpoints for long-running local OASG loops."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from oasg.canonical import receipt_hash
from oasg.io import read_json, write_json
from oasg.scheduler import SchedulerResult


@dataclass(frozen=True)
class OptimizerState:
    run_id: str
    iteration: int = 0
    last_observed_ledger_prefix_hash: str | None = None
    last_append_index: int = 0
    scheduler_state: SchedulerResult | None = None
    mutation_outcomes: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    active_trial_ids: tuple[str, ...] = ()
    quarantined_trial_ids: tuple[str, ...] = ()
    trial_states: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    checkpoint_hash: str | None = None
    last_library_hash: str | None = None
    artifact_type: str = "optimizer_state"

    def to_dict(self, *, include_checkpoint_hash: bool = True) -> dict[str, Any]:
        value = {
            "artifact_type": self.artifact_type,
            "run_id": self.run_id,
            "iteration": self.iteration,
            "last_observed_ledger_prefix_hash": self.last_observed_ledger_prefix_hash,
            "last_append_index": self.last_append_index,
            "scheduler_state": self.scheduler_state.to_dict()
            if self.scheduler_state is not None
            else None,
            "mutation_outcomes": list(self.mutation_outcomes),
            "active_trial_ids": list(self.active_trial_ids),
            "quarantined_trial_ids": list(self.quarantined_trial_ids),
            "trial_states": list(self.trial_states),
            "checkpoint_hash": self.checkpoint_hash if include_checkpoint_hash else None,
            "last_library_hash": self.last_library_hash,
        }
        return value

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "OptimizerState":
        scheduler = raw.get("scheduler_state")
        return cls(
            run_id=str(raw.get("run_id", "oasg-local")),
            iteration=int(raw.get("iteration", 0)),
            last_observed_ledger_prefix_hash=(
                str(raw["last_observed_ledger_prefix_hash"])
                if raw.get("last_observed_ledger_prefix_hash") is not None
                else None
            ),
            last_append_index=int(raw.get("last_append_index", 0)),
            scheduler_state=SchedulerResult.from_dict(scheduler)
            if isinstance(scheduler, dict)
            else None,
            mutation_outcomes=tuple(
                dict(item) for item in raw.get("mutation_outcomes", [])
            ),
            active_trial_ids=tuple(str(item) for item in raw.get("active_trial_ids", [])),
            quarantined_trial_ids=tuple(
                str(item) for item in raw.get("quarantined_trial_ids", [])
            ),
            trial_states=tuple(dict(item) for item in raw.get("trial_states", [])),
            checkpoint_hash=(
                str(raw["checkpoint_hash"]) if raw.get("checkpoint_hash") is not None else None
            ),
            last_library_hash=(
                str(raw["last_library_hash"]) if raw.get("last_library_hash") is not None else None
            ),
        )


def load_optimizer_state(path: Path | None, *, run_id: str = "oasg-local") -> OptimizerState:
    if path is None or not path.exists():
        return OptimizerState(run_id=run_id)
    return OptimizerState.from_dict(read_json(path))


def checkpoint_optimizer_state(
    state: OptimizerState,
    *,
    ledger_prefix_hash: str,
    append_index: int,
    scheduler_state: SchedulerResult | None,
    mutation_outcomes: tuple[dict[str, Any], ...],
    last_library_hash: str | None,
) -> OptimizerState:
    next_state = OptimizerState(
        run_id=state.run_id,
        iteration=state.iteration + 1,
        last_observed_ledger_prefix_hash=ledger_prefix_hash,
        last_append_index=append_index,
        scheduler_state=scheduler_state,
        mutation_outcomes=mutation_outcomes,
        active_trial_ids=state.active_trial_ids,
        quarantined_trial_ids=state.quarantined_trial_ids,
        trial_states=state.trial_states,
        last_library_hash=last_library_hash,
    )
    checkpoint = receipt_hash(next_state.to_dict(include_checkpoint_hash=False))
    return OptimizerState(
        run_id=next_state.run_id,
        iteration=next_state.iteration,
        last_observed_ledger_prefix_hash=next_state.last_observed_ledger_prefix_hash,
        last_append_index=next_state.last_append_index,
        scheduler_state=next_state.scheduler_state,
        mutation_outcomes=next_state.mutation_outcomes,
        active_trial_ids=next_state.active_trial_ids,
        quarantined_trial_ids=next_state.quarantined_trial_ids,
        trial_states=next_state.trial_states,
        checkpoint_hash=checkpoint,
        last_library_hash=next_state.last_library_hash,
    )


def write_optimizer_state(path: Path, state: OptimizerState) -> Path:
    write_json(path, state.to_dict())
    return path


def with_trial_state(
    state: OptimizerState,
    *,
    trial_id: str,
    status: str,
    receipt_hashes: tuple[str, ...] = (),
) -> OptimizerState:
    retained = tuple(item for item in state.trial_states if item.get("trial_id") != trial_id)
    record = {
        "record_type": "pending_trial",
        "trial_id": trial_id,
        "status": status,
        "receipt_hashes": list(receipt_hashes),
    }
    active = tuple(item for item in state.active_trial_ids if item != trial_id)
    quarantined = state.quarantined_trial_ids
    if status in {"pending", "shadowed", "leased", "gated"}:
        active = tuple(sorted({*active, trial_id}))
    elif status == "quarantined":
        quarantined = tuple(sorted({*quarantined, trial_id}))
    next_state = OptimizerState(
        run_id=state.run_id,
        iteration=state.iteration,
        last_observed_ledger_prefix_hash=state.last_observed_ledger_prefix_hash,
        last_append_index=state.last_append_index,
        scheduler_state=state.scheduler_state,
        mutation_outcomes=state.mutation_outcomes,
        active_trial_ids=active,
        quarantined_trial_ids=quarantined,
        trial_states=(*retained, record),
        last_library_hash=state.last_library_hash,
    )
    return OptimizerState(
        run_id=next_state.run_id,
        iteration=next_state.iteration,
        last_observed_ledger_prefix_hash=next_state.last_observed_ledger_prefix_hash,
        last_append_index=next_state.last_append_index,
        scheduler_state=next_state.scheduler_state,
        mutation_outcomes=next_state.mutation_outcomes,
        active_trial_ids=next_state.active_trial_ids,
        quarantined_trial_ids=next_state.quarantined_trial_ids,
        trial_states=next_state.trial_states,
        checkpoint_hash=receipt_hash(next_state.to_dict(include_checkpoint_hash=False)),
        last_library_hash=next_state.last_library_hash,
    )


__all__ = [
    "OptimizerState",
    "checkpoint_optimizer_state",
    "load_optimizer_state",
    "with_trial_state",
    "write_optimizer_state",
]
