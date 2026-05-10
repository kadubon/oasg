"""Bounded workflow-policy mutation proposals."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from oasg.canonical import receipt_hash
from oasg.constants import GRADE_RANK
from oasg.klb import KLBResult
from oasg.io import read_json
from oasg.models import MutatorProfile as MutatorProfileModel
from oasg.policy_state import MutationPatch
from oasg.policy import PolicyProfile
from oasg.reducers.core import ReducerSnapshot
from oasg.scheduler import SchedulerResult


@dataclass(frozen=True)
class MutatorProfile:
    profile_id: str = "OASG-REF-v1.0-mutators"
    enabled_mutators: tuple[str, ...] = ()
    max_candidates: int = 4
    per_family_max_candidates: dict[str, int] | None = None
    cooldown_iterations: int = 3
    unsafe_surface_allowlist: tuple[str, ...] = ()
    retry_limit: int = 1

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "MutatorProfile":
        if raw is None:
            return cls()
        record = MutatorProfileModel.model_validate(raw)
        return cls(
            profile_id=record.profile_id,
            enabled_mutators=tuple(record.enabled_mutators),
            max_candidates=record.max_candidates,
            per_family_max_candidates={
                str(k): int(v) for k, v in record.per_family_max_candidates.items()
            },
            cooldown_iterations=record.cooldown_iterations,
            unsafe_surface_allowlist=tuple(record.unsafe_surface_allowlist),
            retry_limit=record.retry_limit,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": "mutator_profile",
            "profile_id": self.profile_id,
            "enabled_mutators": list(self.enabled_mutators),
            "max_candidates": self.max_candidates,
            "per_family_max_candidates": self.per_family_max_candidates or {},
            "cooldown_iterations": self.cooldown_iterations,
            "unsafe_surface_allowlist": list(self.unsafe_surface_allowlist),
            "retry_limit": self.retry_limit,
        }


@dataclass(frozen=True)
class MutationProposal:
    mutation_id: str
    coordinate: str
    action_id: str
    to_grade: str
    mutator_id: str
    reason: str
    patch: MutationPatch

    def to_dict(self) -> dict[str, Any]:
        return {
            "mutation_id": self.mutation_id,
            "coordinate": self.coordinate,
            "action_id": self.action_id,
            "to_grade": self.to_grade,
            "mutator_id": self.mutator_id,
            "reason": self.reason,
            "patch": self.patch.to_dict(),
        }


@dataclass(frozen=True)
class MutationBatch:
    proposals: tuple[MutationProposal, ...]
    receipt_type: str = "mutation_batch"

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt_type": self.receipt_type,
            "proposals": [proposal.to_dict() for proposal in self.proposals],
        }


def propose_mutations(
    snapshot: ReducerSnapshot,
    klb: KLBResult,
    scheduler: SchedulerResult,
    policy: PolicyProfile,
    *,
    max_candidates: int = 4,
    mutator_profile: MutatorProfile | None = None,
    outcome_memory: tuple[dict[str, Any], ...] = (),
    iteration: int = 0,
) -> MutationBatch:
    """Create deterministic local reversible workflow-policy proposals."""

    profile = mutator_profile or MutatorProfile(max_candidates=max_candidates)
    effective_max = min(max_candidates, profile.max_candidates)
    proposals: list[MutationProposal] = []
    seen_actions: set[str] = set()
    per_family_counts: dict[str, int] = {}

    for coordinate in _starved_first(scheduler.selected_coordinates, scheduler.starvation_violation):
        action_id = _action_from_coordinate(coordinate)
        if action_id is None:
            proposal = _proposal_for_pressure(
                coordinate,
                snapshot,
                klb,
                policy,
                len(proposals) + 1,
                seen_actions,
            )
            if proposal is not None and _proposal_allowed(
                proposal,
                profile,
                outcome_memory,
                iteration,
                per_family_counts,
            ):
                seen_actions.add(proposal.action_id)
                proposals.append(proposal)
                _count_family(proposal, per_family_counts)
            if len(proposals) >= effective_max:
                return MutationBatch(tuple(proposals))
            continue
        if action_id in seen_actions:
            continue
        if not _action_mutatable(action_id, policy, profile):
            continue
        current = klb.klb.get(action_id, snapshot.action_grades.get(action_id, "blocked"))
        if GRADE_RANK[current] >= GRADE_RANK["surplus"]:
            continue
        proposal = _action_policy_proposal(
            action_id,
            len(proposals) + 1,
            mutator_id="action_policy_repair_v1_0",
            reason=f"scheduled:{coordinate}",
        )
        if proposal is None:
            continue
        if not _proposal_allowed(
            proposal,
            profile,
            outcome_memory,
            iteration,
            per_family_counts,
        ):
            continue
        seen_actions.add(action_id)
        proposals.append(
            proposal
        )
        _count_family(proposal, per_family_counts)
        if len(proposals) >= effective_max:
            return MutationBatch(tuple(proposals))

    for action_id in policy.action_ids:
        if action_id in seen_actions or not _action_mutatable(action_id, policy, profile):
            continue
        current = klb.klb.get(action_id, snapshot.action_grades.get(action_id, "blocked"))
        if GRADE_RANK[current] >= GRADE_RANK["surplus"]:
            continue
        proposal = _action_policy_proposal(
            action_id,
            len(proposals) + 1,
            mutator_id="bounded_exploration_v1_0",
            reason="bounded_exploration",
        )
        if proposal is None:
            continue
        if not _proposal_allowed(
            proposal,
            profile,
            outcome_memory,
            iteration,
            per_family_counts,
        ):
            continue
        seen_actions.add(action_id)
        proposals.append(
            proposal
        )
        _count_family(proposal, per_family_counts)
        if len(proposals) >= effective_max:
            break

    return MutationBatch(tuple(proposals))


def _proposal_for_pressure(
    coordinate: str,
    snapshot: ReducerSnapshot,
    klb: KLBResult,
    policy: PolicyProfile,
    index: int,
    seen_actions: set[str],
) -> MutationProposal | None:
    if coordinate in {"dimension.budget", "protected_debt.budget"}:
        action_id = _first_action_with_charge(policy, "budget", seen_actions)
        if action_id is not None:
            return _patch_proposal(
                action_id,
                index,
                coordinate=f"KLB_2.{action_id}",
                to_grade="surplus",
                op="adjust_charge",
                value={"mode": "remove", "dimension": "budget"},
                mutator_id="budget_charge_relief_v1_0",
                reason=f"pressure:{coordinate}",
            )
    if coordinate in {"dimension.queue", "protected_debt.queue"}:
        return _patch_proposal(
            "close_obligation",
            index,
            coordinate="KLB_2.close_obligation",
            to_grade="surplus",
            op="set_retry_policy",
            value="bounded_exponential_backoff",
            mutator_id="retry_backoff_v1_0",
            reason=f"pressure:{coordinate}",
        )
    if coordinate in {"dimension.rollback", "protected_debt.rollback"}:
        return _patch_proposal(
            "rollback_local_effect",
            index,
            coordinate="KLB_2.rollback_local_effect",
            to_grade="surplus",
            op="set_lease_cap",
            value={"max_events": 1, "max_external_effects": 0},
            mutator_id="lease_cap_tightening_v1_0",
            reason=f"pressure:{coordinate}",
        )
    if coordinate in {"dimension.maintenance", "protected_debt.maintenance"}:
        action_id = _first_non_surplus_action(snapshot, klb, policy, seen_actions)
        if action_id is not None:
            return _patch_proposal(
                action_id,
                index,
                coordinate=f"KLB_2.{action_id}",
                to_grade="surplus",
                op="set_validator_policy",
                value="pre_and_post",
                mutator_id="validator_placement_v1_0",
                reason=f"pressure:{coordinate}",
            )
    if coordinate in {"dimension.evidence", "protected_debt.evidence"}:
        return _patch_proposal(
            "validate_artifact",
            index,
            coordinate="KLB_2.validate_artifact",
            to_grade="surplus",
            op="set_validator_policy",
            value="pre_and_post",
            mutator_id="validator_pre_post_v1_0",
            reason=f"pressure:{coordinate}",
        )
    if coordinate in {"dimension.replay", "protected_debt.replay"}:
        return _patch_proposal(
            "replay_artifact",
            index,
            coordinate="KLB_2.replay_artifact",
            to_grade="surplus",
            op="set_context_compression",
            value="artifact_digest",
            mutator_id="context_compression_v1_0",
            reason=f"pressure:{coordinate}",
        )
    if coordinate in {"dimension.boundary", "protected_debt.boundary"}:
        return _patch_proposal(
            "local_reversible",
            index,
            coordinate="KLB_2.local_reversible",
            to_grade="surplus",
            op="set_rollback_requirement",
            value="required",
            mutator_id="rollback_requirement_v1_0",
            reason=f"pressure:{coordinate}",
        )
    if coordinate in {"dimension.taint", "protected_debt.taint"}:
        return _patch_proposal(
            "pure_read",
            index,
            coordinate="KLB_2.pure_read",
            to_grade="surplus",
            op="set_routing_policy",
            value="public_only",
            mutator_id="taint_aware_routing_v1_0",
            reason=f"pressure:{coordinate}",
        )
    if coordinate in {"dimension.comparison", "protected_debt.comparison"}:
        return _patch_proposal(
            "validate_artifact",
            index,
            coordinate="KLB_2.validate_artifact",
            to_grade="surplus",
            op="set_decomposition_depth",
            value=1,
            mutator_id="decomposition_tightening_v1_0",
            reason=f"pressure:{coordinate}",
        )
    if coordinate.startswith("semantic"):
        return _patch_proposal(
            "emit_claim",
            index,
            coordinate="KLB_2.emit_claim",
            to_grade="surplus",
            op="set_semantic_floor",
            value="validator_required",
            mutator_id="semantic_floor_insertion_v1_0",
            reason=f"pressure:{coordinate}",
        )
    return None


def _action_policy_proposal(
    action_id: str,
    index: int,
    *,
    mutator_id: str,
    reason: str,
) -> MutationProposal | None:
    if action_id == "pure_read":
        return _patch_proposal(
            action_id,
            index,
            coordinate=f"KLB_2.{action_id}",
            to_grade="surplus",
            op="set_routing_policy",
            value="public_only",
            mutator_id="routing_policy_v1_0",
            reason=reason,
        )
    if action_id == "close_obligation":
        return _patch_proposal(
            action_id,
            index,
            coordinate=f"KLB_2.{action_id}",
            to_grade="surplus",
            op="set_retry_policy",
            value="bounded_exponential_backoff",
            mutator_id="retry_backoff_v1_0",
            reason=reason,
        )
    if action_id == "validate_artifact":
        return _patch_proposal(
            action_id,
            index,
            coordinate=f"KLB_2.{action_id}",
            to_grade="surplus",
            op="set_validator_policy",
            value="pre_and_post",
            mutator_id="validator_pre_post_v1_0",
            reason=reason,
        )
    if action_id == "replay_artifact":
        return _patch_proposal(
            action_id,
            index,
            coordinate=f"KLB_2.{action_id}",
            to_grade="surplus",
            op="set_context_compression",
            value="artifact_digest",
            mutator_id="context_compression_v1_0",
            reason=reason,
        )
    if action_id in {"local_reversible", "rollback_local_effect"}:
        return _patch_proposal(
            action_id,
            index,
            coordinate=f"KLB_2.{action_id}",
            to_grade="surplus",
            op="set_rollback_requirement",
            value="required",
            mutator_id="rollback_requirement_v1_0",
            reason=reason,
        )
    return _patch_proposal(
        action_id,
        index,
        coordinate=f"KLB_2.{action_id}",
        to_grade="surplus",
        op="set_validator_policy",
        value="pre_and_post",
        mutator_id=_normalize_mutator_id(mutator_id),
        reason=reason,
    )


def _patch_proposal(
    action_id: str,
    index: int,
    *,
    coordinate: str,
    to_grade: str,
    op: str,
    value: str | int | dict[str, Any],
    mutator_id: str,
    reason: str,
) -> MutationProposal:
    mutation_id = f"mut_auto_{index:03d}_{action_id}"
    patch = MutationPatch(
        mutation_id=mutation_id,
        op=op,
        target_action_id=action_id,
        coordinate_id=coordinate,
        value=value,
        mutator_id=mutator_id,
    )
    return MutationProposal(
        mutation_id=mutation_id,
        coordinate=coordinate,
        action_id=action_id,
        to_grade=to_grade,
        mutator_id=mutator_id,
        reason=reason,
        patch=patch,
    )


def _action_from_coordinate(coordinate: str) -> str | None:
    if coordinate.startswith("KLB_2."):
        return coordinate.split(".", 1)[1]
    if coordinate.startswith("evidence.KLB_2."):
        return coordinate.rsplit(".", 1)[1]
    return None


def _action_mutatable(
    action_id: str,
    policy: PolicyProfile,
    profile: MutatorProfile | None = None,
) -> bool:
    action = policy.action(action_id)
    allowlist = set(profile.unsafe_surface_allowlist) if profile is not None else set()
    if action.requires_workflow_promotion_authority:
        return False
    if (action.claim_emitting or action.requires_semantic_floor) and "semantic" not in allowlist:
        return False
    if action.effect_class not in {"pure", "simulated", "local_reversible"}:
        return False
    return True


def _first_action_with_charge(
    policy: PolicyProfile,
    dimension: str,
    seen_actions: set[str],
) -> str | None:
    for action in policy.actions:
        if action.action_id in seen_actions or not _action_mutatable(action.action_id, policy):
            continue
        if dimension in action.charges:
            return action.action_id
    return None


def _first_non_surplus_action(
    snapshot: ReducerSnapshot,
    klb: KLBResult,
    policy: PolicyProfile,
    seen_actions: set[str],
) -> str | None:
    for action_id in policy.action_ids:
        if action_id in seen_actions or not _action_mutatable(action_id, policy):
            continue
        current = klb.klb.get(action_id, snapshot.action_grades.get(action_id, "blocked"))
        if GRADE_RANK[current] < GRADE_RANK["surplus"]:
            return action_id
    return None


def _starved_first(
    selected: tuple[str, ...],
    starvation: tuple[str, ...],
) -> tuple[str, ...]:
    ordered = [coordinate for coordinate in starvation if coordinate in selected]
    ordered.extend(coordinate for coordinate in selected if coordinate not in ordered)
    return tuple(ordered)


def _proposal_allowed(
    proposal: MutationProposal,
    profile: MutatorProfile,
    outcome_memory: tuple[dict[str, Any], ...],
    iteration: int,
    per_family_counts: dict[str, int],
) -> bool:
    enabled = {_normalize_mutator_id(item) for item in profile.enabled_mutators}
    if enabled and _normalize_mutator_id(proposal.mutator_id) not in enabled:
        return False
    family = _mutator_family(proposal.mutator_id)
    family_limit = (profile.per_family_max_candidates or {}).get(family)
    if family_limit is not None and per_family_counts.get(family, 0) >= family_limit:
        return False
    patch_hash = _cooldown_patch_hash(proposal.patch.to_dict())
    failures = 0
    for outcome in outcome_memory:
        if outcome.get("patch_hash") != patch_hash:
            continue
        if str(outcome.get("status")) in {"accepted", "retired"}:
            return False
        if int(outcome.get("cooldown_until_iteration", 0)) > iteration:
            return False
        if str(outcome.get("status")) in {"rejected", "inconclusive", "quarantined"}:
            failures += 1
    return failures <= profile.retry_limit


def _count_family(proposal: MutationProposal, per_family_counts: dict[str, int]) -> None:
    family = _mutator_family(proposal.mutator_id)
    per_family_counts[family] = per_family_counts.get(family, 0) + 1


def _mutator_family(mutator_id: str) -> str:
    return _normalize_mutator_id(mutator_id).rsplit("_v1_", 1)[0]


def _normalize_mutator_id(mutator_id: str) -> str:
    return (
        mutator_id.replace("_v0_5", "_v1_0")
        .replace("_v0_6", "_v1_0")
        .replace("_v0_7", "_v1_0")
    )


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


def load_mutator_profile(path: Path | None) -> MutatorProfile:
    if path is None:
        return MutatorProfile()
    return MutatorProfile.from_dict(read_json(path))
