"""Typed pressure vectors for deterministic OASG optimization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from oasg.constants import GRADE_RANK, REQUIRED_DIMENSIONS, require_grade
from oasg.klb import KLBResult
from oasg.reducers.core import ReducerSnapshot


@dataclass(frozen=True)
class PressureResult:
    component_id: str
    coordinates: dict[str, str]
    reasons: dict[str, list[str]] = field(default_factory=dict)
    artifact_type: str = "pressure_vector"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": self.artifact_type,
            "component_id": self.component_id,
            "coordinates": self.coordinates,
            "reasons": self.reasons,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "PressureResult":
        return cls(
            component_id=str(raw["component_id"]),
            coordinates={str(k): require_grade(str(v)) for k, v in raw["coordinates"].items()},
            reasons={
                str(k): [str(item) for item in values]
                for k, values in raw.get("reasons", {}).items()
            },
        )


def compute_pressure(
    snapshot: ReducerSnapshot,
    klb: KLBResult,
    *,
    component_id: str = "workflow_policy",
) -> PressureResult:
    """Compute a typed pressure vector without scalar reward aggregation."""

    coordinates: dict[str, str] = {}
    reasons: dict[str, list[str]] = {}

    for dimension in REQUIRED_DIMENSIONS:
        grade = snapshot.dimensions.get(dimension, "blocked")
        if _below_acceptable(grade):
            coordinates[f"dimension.{dimension}"] = grade
            reasons[f"dimension.{dimension}"] = [f"{dimension}_below_acceptable"]

    for dimension, grade in snapshot.protected_debt.items():
        if _below_acceptable(grade):
            coordinate = f"protected_debt.{dimension}"
            coordinates[coordinate] = grade
            reasons[coordinate] = [f"{dimension}_debt_below_acceptable"]

    for action in klb.action_order:
        grade = klb.klb.get(action, "blocked")
        if grade != "surplus":
            coordinate = f"KLB_2.{action}"
            coordinates[coordinate] = grade
            reasons.setdefault(coordinate, []).append("future_viability_not_surplus")
        if not snapshot.positive_evidence.get(f"KLB_2.{action}"):
            coordinate = f"evidence.KLB_2.{action}"
            coordinates[coordinate] = "degraded"
            reasons[coordinate] = ["missing_positive_evidence"]

    if snapshot.boundary_status != "valid":
        coordinates["boundary.status"] = "critical"
        reasons["boundary.status"] = [snapshot.boundary_status]
    if snapshot.trusted_base_status != "valid":
        coordinates["trusted_base.status"] = "critical"
        reasons["trusted_base.status"] = [snapshot.trusted_base_status]
    if snapshot.taint_level in {"secret", "unknown_secret"}:
        coordinates["taint.status"] = "critical"
        reasons["taint.status"] = [snapshot.taint_level]
    if snapshot.claim_emitting and snapshot.semantic_scope in {"none", "operational_only"}:
        coordinates["semantic.floor"] = "critical"
        reasons["semantic.floor"] = ["claim_emitting_without_semantic_floor"]

    return PressureResult(component_id=component_id, coordinates=coordinates, reasons=reasons)


def pressure_rank(grade: str) -> int:
    """Return higher pressure for worse finite-chain grades."""

    return len(GRADE_RANK) - 1 - GRADE_RANK[require_grade(grade)]


def _below_acceptable(grade: str) -> bool:
    return GRADE_RANK[require_grade(grade)] < GRADE_RANK["acceptable"]
