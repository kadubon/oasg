"""Deterministic mutation scheduling for OASG pressure vectors."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from oasg.pressure import PressureResult, pressure_rank


DEFAULT_SELECTION_DEADLINE = 16


@dataclass(frozen=True)
class SchedulerResult:
    selected_component_id: str
    selected_coordinates: tuple[str, ...]
    pressure_age: dict[str, int] = field(default_factory=dict)
    selection_deadline: dict[str, int] = field(default_factory=dict)
    exploration_debt: dict[str, int] = field(default_factory=dict)
    starvation_violation: tuple[str, ...] = ()
    artifact_type: str = "scheduler_state"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": self.artifact_type,
            "selected_component_id": self.selected_component_id,
            "selected_coordinates": list(self.selected_coordinates),
            "pressure_age": self.pressure_age,
            "selection_deadline": self.selection_deadline,
            "exploration_debt": self.exploration_debt,
            "starvation_violation": list(self.starvation_violation),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SchedulerResult":
        return cls(
            selected_component_id=str(raw["selected_component_id"]),
            selected_coordinates=tuple(str(item) for item in raw.get("selected_coordinates", [])),
            pressure_age={str(k): int(v) for k, v in raw.get("pressure_age", {}).items()},
            selection_deadline={
                str(k): int(v) for k, v in raw.get("selection_deadline", {}).items()
            },
            exploration_debt={
                str(k): int(v) for k, v in raw.get("exploration_debt", {}).items()
            },
            starvation_violation=tuple(str(item) for item in raw.get("starvation_violation", [])),
        )


def schedule_pressure(
    pressure: PressureResult,
    *,
    previous: SchedulerResult | None = None,
    max_selected: int = 4,
    deadline: int = DEFAULT_SELECTION_DEADLINE,
) -> SchedulerResult:
    """Select pressure coordinates using typed ranks and bounded fairness debt."""

    previous_age = previous.pressure_age if previous is not None else {}
    coordinates = sorted(
        pressure.coordinates,
        key=lambda item: (
            -pressure_rank(pressure.coordinates[item]),
            -previous_age.get(item, 0),
            item,
        ),
    )
    pressure_age = {
        coordinate: previous_age.get(coordinate, 0) + 1 for coordinate in pressure.coordinates
    }
    starved_candidates = [
        coordinate for coordinate in coordinates if pressure_age[coordinate] > deadline
    ]
    ordered = [
        *starved_candidates,
        *(coordinate for coordinate in coordinates if coordinate not in starved_candidates),
    ]
    selected = tuple(ordered[:max_selected])
    selection_deadline = {
        coordinate: deadline - min(deadline, pressure_age[coordinate])
        for coordinate in pressure.coordinates
    }
    exploration_debt = {
        coordinate: 0 if coordinate in selected else pressure_age[coordinate]
        for coordinate in pressure.coordinates
    }
    starvation = tuple(
        sorted(
            coordinate
            for coordinate, age in pressure_age.items()
            if age > deadline and coordinate not in selected
        )
    )
    return SchedulerResult(
        selected_component_id=pressure.component_id,
        selected_coordinates=selected,
        pressure_age=pressure_age,
        selection_deadline=selection_deadline,
        exploration_debt=exploration_debt,
        starvation_violation=starvation,
    )
