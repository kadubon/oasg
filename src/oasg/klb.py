"""Bounded KLB_2 calculation for the conservative v1.0 profile."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Any

from oasg.constants import (
    GRADE_RANK,
    grade_min,
    not_worse,
    require_grade,
)
from oasg.policy import PolicyProfile, default_policy
from oasg.reducers.core import ReducerSnapshot


@dataclass(frozen=True)
class KLBResult:
    status: str
    horizon: int
    trace_count: int
    max_trace_classes: int
    action_order: tuple[str, ...]
    klb: dict[str, str]
    ledger_prefix_hash: str
    viable_trace_count: dict[str, int] | None = None
    abstract_trace_receipts: tuple[dict[str, Any], ...] = ()
    receipt_type: str = "klb_receipt"

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt_type": self.receipt_type,
            "status": self.status,
            "horizon": self.horizon,
            "trace_count": self.trace_count,
            "max_trace_classes": self.max_trace_classes,
            "action_order": list(self.action_order),
            "klb": self.klb,
            "ledger_prefix_hash": self.ledger_prefix_hash,
            "viable_trace_count": self.viable_trace_count or {},
            "abstract_trace_receipts": list(self.abstract_trace_receipts),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "KLBResult":
        return cls(
            status=str(value["status"]),
            horizon=int(value["horizon"]),
            trace_count=int(value["trace_count"]),
            max_trace_classes=int(value["max_trace_classes"]),
            action_order=tuple(str(item) for item in value["action_order"]),
            klb={str(k): require_grade(str(v)) for k, v in value["klb"].items()},
            ledger_prefix_hash=str(value["ledger_prefix_hash"]),
            viable_trace_count={
                str(k): int(v) for k, v in value.get("viable_trace_count", {}).items()
            },
            abstract_trace_receipts=tuple(
                dict(item) for item in value.get("abstract_trace_receipts", [])
            ),
        )


def enumerate_traces(policy: PolicyProfile | None = None) -> list[tuple[str, ...]]:
    policy = policy or default_policy()
    actions = policy.action_ids
    traces: list[tuple[str, ...]] = [()]
    traces.extend((action,) for action in actions)
    traces.extend(product(actions, repeat=2))
    return traces


def calculate_klb(snapshot: ReducerSnapshot, policy: PolicyProfile | None = None) -> KLBResult:
    policy = policy or default_policy()
    action_ids = policy.action_ids
    traces = enumerate_traces(policy)
    if len(traces) > policy.max_trace_classes:
        return KLBResult(
            status="inconclusive_klb_overflow",
            horizon=policy.horizon,
            trace_count=len(traces),
            max_trace_classes=policy.max_trace_classes,
            action_order=action_ids,
            klb={action: "blocked" for action in action_ids},
            ledger_prefix_hash=snapshot.ledger_prefix_hash,
            viable_trace_count={action: 0 for action in action_ids},
        )

    protected_floor = _protected_floor(snapshot)
    trace_receipts = tuple(
        _trace_receipt(index, trace, snapshot, policy) for index, trace in enumerate(traces)
    )
    viable_counts = {
        action: sum(
            1
            for trace, receipt in zip(traces, trace_receipts, strict=True)
            if action in trace and receipt["status"] == "trace_viable"
        )
        for action in action_ids
    }
    klb = {
        action: _coordinate_grade(
            action,
            snapshot.action_grades.get(action, "blocked"),
            protected_floor,
            viable_counts[action],
        )
        for action in action_ids
    }
    return KLBResult(
        status="ok",
        horizon=policy.horizon,
        trace_count=len(traces),
        max_trace_classes=policy.max_trace_classes,
        action_order=action_ids,
        klb=klb,
        ledger_prefix_hash=snapshot.ledger_prefix_hash,
        viable_trace_count=viable_counts,
        abstract_trace_receipts=trace_receipts,
    )


def _protected_floor(snapshot: ReducerSnapshot) -> str:
    floor = "surplus"
    for value in snapshot.dimensions.values():
        floor = grade_min(floor, value)
    return floor


def _coordinate_grade(
    action: str,
    action_grade: str,
    protected_floor: str,
    viable_trace_count: int,
) -> str:
    action_grade = require_grade(action_grade)
    if action_grade == "blocked" or viable_trace_count == 0:
        return "blocked"
    if not not_worse(protected_floor, "acceptable"):
        return "degraded" if GRADE_RANK[action_grade] >= GRADE_RANK["acceptable"] else action_grade
    if action_grade == "surplus" and viable_trace_count >= 2:
        return "surplus"
    if GRADE_RANK[action_grade] >= GRADE_RANK["acceptable"]:
        return "acceptable"
    return action_grade


def _trace_viable(
    trace: tuple[str, ...],
    snapshot: ReducerSnapshot,
    policy: PolicyProfile,
) -> bool:
    state = dict(snapshot.dimensions)
    for action in trace:
        if not _action_viable(action, state, snapshot, policy):
            return False
        for charged in policy.action(action).charges:
            state[charged] = _degrade(state.get(charged, "blocked"))
    return True


def _trace_receipt(
    index: int,
    trace: tuple[str, ...],
    snapshot: ReducerSnapshot,
    policy: PolicyProfile,
) -> dict[str, Any]:
    state = dict(snapshot.dimensions)
    status = "trace_viable"
    for action in trace:
        if not _action_viable(action, state, snapshot, policy):
            status = "trace_infeasible"
            break
        for charged in policy.action(action).charges:
            state[charged] = _degrade(state.get(charged, "blocked"))
    return {
        "receipt_type": "abstract_trace_receipt",
        "trace_id": f"trace_{index:04d}",
        "action_class_ids": list(trace),
        "status": status,
        "resulting_grades": state,
        "taint_grade": "blocked"
        if snapshot.taint_level not in {"secret", "unknown_secret"}
        else "critical",
    }


def _action_viable(
    action: str,
    state: dict[str, str],
    snapshot: ReducerSnapshot,
    policy: PolicyProfile,
) -> bool:
    action_policy = policy.action(action)
    if not_worse(snapshot.action_grades.get(action, "blocked"), "acceptable") is False:
        return False
    if action_policy.requires_semantic_floor and snapshot.semantic_scope in {"none", "operational_only"}:
        return False
    if action_policy.requires_workflow_promotion_authority and not snapshot.workflow_promotion_authorized:
        return False
    if action_policy.blocks_secret_taint and snapshot.taint_level in {"secret", "unknown_secret"}:
        return False
    for dimension in action_policy.requirements:
        if not not_worse(state.get(dimension, "blocked"), "acceptable"):
            return False
    return snapshot.boundary_status == "valid" and snapshot.trusted_base_status == "valid"


def _degrade(grade: str) -> str:
    grade = require_grade(grade)
    rank = max(0, GRADE_RANK[grade] - 1)
    for candidate, candidate_rank in GRADE_RANK.items():
        if candidate_rank == rank:
            return candidate
    return "blocked"
