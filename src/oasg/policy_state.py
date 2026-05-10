"""Executable workflow-policy state and bounded mutation patches."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from oasg.constants import require_grade
from oasg.policy import PolicyProfile, default_policy
from oasg.reducers.core import ReducerSnapshot

PATCH_OPS = (
    "set_action_grade",
    "adjust_charge",
    "add_requirement",
    "remove_requirement",
    "set_retry_policy",
    "set_validator_policy",
    "set_lease_cap",
    "set_semantic_floor",
    "retire_action",
    "set_routing_policy",
    "set_decomposition_depth",
    "set_context_compression",
    "set_rollback_requirement",
)


@dataclass(frozen=True)
class MutationPatch:
    mutation_id: str
    op: str
    target_action_id: str
    coordinate_id: str
    value: str | int | dict[str, Any]
    mutator_id: str
    target_surface: str = "workflow_policy"
    precondition_policy_hash: str | None = None
    resulting_policy_hash: str | None = None

    def __post_init__(self) -> None:
        if self.op not in PATCH_OPS:
            raise ValueError(f"unsupported mutation patch op: {self.op!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_type": "mutation_patch",
            "mutation_id": self.mutation_id,
            "op": self.op,
            "target_surface": self.target_surface,
            "target_action_id": self.target_action_id,
            "coordinate_id": self.coordinate_id,
            "value": self.value,
            "mutator_id": self.mutator_id,
            "precondition_policy_hash": self.precondition_policy_hash,
            "resulting_policy_hash": self.resulting_policy_hash,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "MutationPatch":
        return cls(
            mutation_id=str(raw["mutation_id"]),
            op=str(raw["op"]),
            target_surface=str(raw.get("target_surface", "workflow_policy")),
            target_action_id=str(raw["target_action_id"]),
            coordinate_id=str(raw["coordinate_id"]),
            value=raw.get("value", "acceptable"),
            mutator_id=str(raw.get("mutator_id", "unknown_mutator")),
            precondition_policy_hash=(
                str(raw["precondition_policy_hash"])
                if raw.get("precondition_policy_hash") is not None
                else None
            ),
            resulting_policy_hash=(
                str(raw["resulting_policy_hash"])
                if raw.get("resulting_policy_hash") is not None
                else None
            ),
        )


@dataclass(frozen=True)
class WorkflowPolicyState:
    state_id: str
    policy_profile: dict[str, Any]
    action_grades: dict[str, str] = field(default_factory=dict)
    retry_policy: dict[str, str] = field(default_factory=dict)
    validator_policy: dict[str, str] = field(default_factory=dict)
    lease_caps: dict[str, dict[str, int]] = field(default_factory=dict)
    semantic_policy: dict[str, str] = field(default_factory=dict)
    routing_policy: dict[str, str] = field(default_factory=dict)
    decomposition_policy: dict[str, int] = field(default_factory=dict)
    context_policy: dict[str, str] = field(default_factory=dict)
    rollback_policy: dict[str, str] = field(default_factory=dict)
    requirement_policy: dict[str, tuple[str, ...]] = field(default_factory=dict)
    retired_actions: tuple[str, ...] = ()
    artifact_type: str = "workflow_policy_state"

    @classmethod
    def default(cls) -> "WorkflowPolicyState":
        return cls(
            state_id="default",
            policy_profile=default_policy().to_dict(),
            action_grades={},
        )

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "WorkflowPolicyState":
        if raw is None:
            return cls.default()
        return cls(
            state_id=str(raw.get("state_id", "default")),
            policy_profile=dict(raw.get("policy_profile", default_policy().to_dict())),
            action_grades={
                str(k): require_grade(str(v)) for k, v in raw.get("action_grades", {}).items()
            },
            retry_policy={str(k): str(v) for k, v in raw.get("retry_policy", {}).items()},
            validator_policy={str(k): str(v) for k, v in raw.get("validator_policy", {}).items()},
            lease_caps={
                str(action): {str(k): int(v) for k, v in caps.items()}
                for action, caps in raw.get("lease_caps", {}).items()
                if isinstance(caps, dict)
            },
            semantic_policy={str(k): str(v) for k, v in raw.get("semantic_policy", {}).items()},
            routing_policy={str(k): str(v) for k, v in raw.get("routing_policy", {}).items()},
            decomposition_policy={
                str(k): int(v) for k, v in raw.get("decomposition_policy", {}).items()
            },
            context_policy={str(k): str(v) for k, v in raw.get("context_policy", {}).items()},
            rollback_policy={str(k): str(v) for k, v in raw.get("rollback_policy", {}).items()},
            requirement_policy={
                str(action): tuple(str(item) for item in values)
                for action, values in raw.get("requirement_policy", {}).items()
                if isinstance(values, list)
            },
            retired_actions=tuple(str(item) for item in raw.get("retired_actions", [])),
        )

    @property
    def policy(self) -> PolicyProfile:
        return PolicyProfile.from_dict(self.policy_profile)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": self.artifact_type,
            "state_id": self.state_id,
            "policy_profile": self.policy_profile,
            "action_grades": self.action_grades,
            "retry_policy": self.retry_policy,
            "validator_policy": self.validator_policy,
            "lease_caps": self.lease_caps,
            "semantic_policy": self.semantic_policy,
            "routing_policy": self.routing_policy,
            "decomposition_policy": self.decomposition_policy,
            "context_policy": self.context_policy,
            "rollback_policy": self.rollback_policy,
            "requirement_policy": {
                action: list(values) for action, values in self.requirement_policy.items()
            },
            "retired_actions": list(self.retired_actions),
        }

    def apply_patch(self, patch: MutationPatch) -> "WorkflowPolicyState":
        if patch.target_action_id not in self.policy.action_ids:
            raise ValueError(f"unknown policy action: {patch.target_action_id!r}")
        if patch.target_action_id in self.retired_actions and patch.op != "retire_action":
            raise ValueError(f"cannot patch retired action: {patch.target_action_id!r}")
        profile = _patch_profile(self.policy_profile, patch)
        PolicyProfile.from_dict(profile)
        action_grades = dict(self.action_grades)
        retry_policy = dict(self.retry_policy)
        validator_policy = dict(self.validator_policy)
        lease_caps = {action: dict(caps) for action, caps in self.lease_caps.items()}
        semantic_policy = dict(self.semantic_policy)
        routing_policy = dict(self.routing_policy)
        decomposition_policy = dict(self.decomposition_policy)
        context_policy = dict(self.context_policy)
        rollback_policy = dict(self.rollback_policy)
        requirement_policy = dict(self.requirement_policy)
        retired_actions = tuple(self.retired_actions)

        if patch.op == "set_action_grade":
            action_grades[patch.target_action_id] = require_grade(str(patch.value))
        elif patch.op == "set_retry_policy":
            retry_policy[patch.target_action_id] = str(patch.value)
        elif patch.op == "set_validator_policy":
            validator_policy[patch.target_action_id] = str(patch.value)
        elif patch.op == "set_lease_cap":
            caps = lease_caps.setdefault(patch.target_action_id, {})
            if isinstance(patch.value, dict):
                for key, value in patch.value.items():
                    caps[str(key)] = int(value)
            else:
                caps["max_events"] = int(patch.value)
        elif patch.op == "set_semantic_floor":
            semantic_policy[patch.target_action_id] = str(patch.value)
        elif patch.op == "set_routing_policy":
            routing_policy[patch.target_action_id] = str(patch.value)
        elif patch.op == "set_decomposition_depth":
            if isinstance(patch.value, dict):
                raise ValueError("set_decomposition_depth requires an integer value")
            decomposition_policy[patch.target_action_id] = int(patch.value)
        elif patch.op == "set_context_compression":
            context_policy[patch.target_action_id] = str(patch.value)
        elif patch.op == "set_rollback_requirement":
            rollback_policy[patch.target_action_id] = str(patch.value)
            current = set(requirement_policy.get(patch.target_action_id, ()))
            current.add("rollback")
            requirement_policy[patch.target_action_id] = tuple(sorted(current))
        elif patch.op == "retire_action":
            retired_actions = tuple(sorted({*retired_actions, patch.target_action_id}))

        return WorkflowPolicyState(
            state_id=f"{self.state_id}:{patch.mutation_id}",
            policy_profile=profile,
            action_grades=action_grades,
            retry_policy=retry_policy,
            validator_policy=validator_policy,
            lease_caps=lease_caps,
            semantic_policy=semantic_policy,
            routing_policy=routing_policy,
            decomposition_policy=decomposition_policy,
            context_policy=context_policy,
            rollback_policy=rollback_policy,
            requirement_policy=requirement_policy,
            retired_actions=retired_actions,
        )


def overlay_snapshot(snapshot: ReducerSnapshot, state: WorkflowPolicyState) -> ReducerSnapshot:
    action_grades = dict(snapshot.action_grades)
    for action, grade in state.action_grades.items():
        action_grades[action] = require_grade(grade)
    for action in state.retired_actions:
        action_grades[action] = "blocked"
    return ReducerSnapshot(
        ledger_status=snapshot.ledger_status,
        ledger_prefix_hash=snapshot.ledger_prefix_hash,
        dimensions=snapshot.dimensions,
        action_grades=action_grades,
        protected_debt=snapshot.protected_debt,
        positive_evidence=snapshot.positive_evidence,
        records_seen=snapshot.records_seen,
        effect_classes=snapshot.effect_classes,
        semantic_scope=snapshot.semantic_scope,
        claim_emitting=snapshot.claim_emitting,
        taint_level=snapshot.taint_level,
        boundary_status=snapshot.boundary_status,
        trusted_base_status=snapshot.trusted_base_status,
        workflow_promotion_authorized=snapshot.workflow_promotion_authorized,
    )


def _patch_profile(raw_profile: dict[str, Any], patch: MutationPatch) -> dict[str, Any]:
    actions: list[dict[str, Any]] = [
        dict(action) for action in raw_profile.get("actions", []) if isinstance(action, dict)
    ]
    profile: dict[str, Any] = {
        "profile_id": raw_profile.get("profile_id", "OASG-REF-v1.0-default-policy"),
        "horizon": int(raw_profile.get("horizon", 2)),
        "max_trace_classes": int(raw_profile.get("max_trace_classes", 73)),
        "actions": actions,
    }
    for action in actions:
        if action.get("action_id") != patch.target_action_id:
            continue
        if patch.op == "adjust_charge":
            charges = [str(item) for item in action.get("charges", [])]
            charge_value = patch.value if isinstance(patch.value, dict) else {}
            dimension = str(charge_value.get("dimension", "budget"))
            mode = str(charge_value.get("mode", "remove"))
            if mode == "remove":
                charges = [item for item in charges if item != dimension]
            elif dimension not in charges:
                charges.append(dimension)
            action["charges"] = charges
        elif patch.op == "add_requirement":
            requirements = [str(item) for item in action.get("requirements", [])]
            requirement_value = str(patch.value)
            if requirement_value not in requirements:
                requirements.append(requirement_value)
            action["requirements"] = requirements
        elif patch.op == "remove_requirement":
            requirement_value = str(patch.value)
            action["requirements"] = [
                str(item)
                for item in action.get("requirements", [])
                if str(item) != requirement_value
            ]
        elif patch.op == "set_semantic_floor":
            action["requires_semantic_floor"] = True
            action["claim_emitting"] = bool(action.get("claim_emitting", False))
        elif patch.op == "set_rollback_requirement":
            requirements = [str(item) for item in action.get("requirements", [])]
            if "rollback" not in requirements:
                requirements.append("rollback")
            action["requirements"] = requirements
        break
    if patch.op == "retire_action":
        profile["actions"] = [
            action
            for action in profile["actions"]
            if action.get("action_id") != patch.target_action_id
        ]
    return profile
