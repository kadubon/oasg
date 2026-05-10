"""Policy profile for the bounded v1.0 viability kernel."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from oasg.constants import MAX_TRACE_CLASSES, REQUIRED_DIMENSIONS, require_grade
from oasg.io import read_json, write_json
from oasg.models import PolicyProfileRecord


@dataclass(frozen=True)
class ActionPolicy:
    action_id: str
    requirements: tuple[str, ...]
    charges: tuple[str, ...] = ()
    effect_class: str = "pure"
    claim_emitting: bool = False
    requires_semantic_floor: bool = False
    blocks_secret_taint: bool = False
    requires_workflow_promotion_authority: bool = False

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ActionPolicy":
        return cls(
            action_id=str(raw["action_id"]),
            requirements=tuple(str(item) for item in raw.get("requirements", [])),
            charges=tuple(str(item) for item in raw.get("charges", [])),
            effect_class=str(raw.get("effect_class", "pure")),
            claim_emitting=bool(raw.get("claim_emitting", False)),
            requires_semantic_floor=bool(raw.get("requires_semantic_floor", False)),
            blocks_secret_taint=bool(raw.get("blocks_secret_taint", False)),
            requires_workflow_promotion_authority=bool(
                raw.get("requires_workflow_promotion_authority", False)
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "requirements": list(self.requirements),
            "charges": list(self.charges),
            "effect_class": self.effect_class,
            "claim_emitting": self.claim_emitting,
            "requires_semantic_floor": self.requires_semantic_floor,
            "blocks_secret_taint": self.blocks_secret_taint,
            "requires_workflow_promotion_authority": self.requires_workflow_promotion_authority,
        }


@dataclass(frozen=True)
class PolicyProfile:
    profile_id: str
    horizon: int
    max_trace_classes: int
    actions: tuple[ActionPolicy, ...]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "PolicyProfile":
        record = PolicyProfileRecord.model_validate(raw)
        actions = tuple(
            ActionPolicy.from_dict(action.model_dump(mode="json"))
            for action in record.actions
        )
        if not actions:
            raise ValueError("policy profile must contain at least one action")
        if len(actions) > 8:
            raise ValueError("v1.0 policy profile supports at most 8 action classes")
        if record.horizon != 2:
            raise ValueError("v1.0 policy profile supports horizon=2 only")
        action_ids = [action.action_id for action in actions]
        if len(set(action_ids)) != len(action_ids):
            raise ValueError("policy profile action_id values must be unique")
        return cls(
            profile_id=record.profile_id,
            horizon=2,
            max_trace_classes=record.max_trace_classes,
            actions=actions,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "horizon": self.horizon,
            "max_trace_classes": self.max_trace_classes,
            "actions": [action.to_dict() for action in self.actions],
        }

    @property
    def action_ids(self) -> tuple[str, ...]:
        return tuple(action.action_id for action in self.actions)

    def action(self, action_id: str) -> ActionPolicy:
        for action in self.actions:
            if action.action_id == action_id:
                return action
        raise KeyError(action_id)


def default_policy() -> PolicyProfile:
    return PolicyProfile(
        profile_id="OASG-REF-v1.0-default-policy",
        horizon=2,
        max_trace_classes=MAX_TRACE_CLASSES,
        actions=(
            ActionPolicy("pure_read", ("budget", "evidence", "authority")),
            ActionPolicy("local_reversible", ("budget", "rollback", "authority"), ("budget",), "local_reversible", blocks_secret_taint=True),
            ActionPolicy("validate_artifact", ("budget", "evidence", "authority"), ("budget",)),
            ActionPolicy("close_obligation", ("queue", "authority"), ("queue",)),
            ActionPolicy("replay_artifact", ("replay", "evidence", "authority"), ("budget",)),
            ActionPolicy("rollback_local_effect", ("rollback", "authority"), ("rollback",), "local_reversible"),
            ActionPolicy(
                "emit_claim",
                ("evidence", "semantic_floor", "authority"),
                ("evidence",),
                claim_emitting=True,
                requires_semantic_floor=True,
                blocks_secret_taint=True,
            ),
            ActionPolicy(
                "promote_workflow",
                ("comparison", "trusted_base", "authority"),
                ("comparison", "trusted_base"),
                "workflow_promotion",
                blocks_secret_taint=True,
                requires_workflow_promotion_authority=True,
            ),
        ),
    )


def load_policy(path: Path | None) -> PolicyProfile:
    if path is None:
        return default_policy()
    return PolicyProfile.from_dict(read_json(path))


def write_default_policy(path: Path) -> None:
    write_json(path, default_policy().to_dict())


def validate_policy_grades(raw: dict[str, str]) -> dict[str, str]:
    output = {dimension: raw.get(dimension, "blocked") for dimension in REQUIRED_DIMENSIONS}
    for key, value in raw.items():
        output[str(key)] = require_grade(str(value))
    return output
