"""CrewAI adapter pattern for OASG.

CrewAI can own crew/task execution. OASG observes the resulting operational facts and decides
workflow-policy promotion outside the crew.

This file does not require CrewAI unless `require_crewai_available()` is called.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Mapping
from typing import Any

from oasg.adapters.contracts import ModelEvent
from oasg.canonical import domain_hash
from oasg.constants import ACTION_CLASSES, REQUIRED_DIMENSIONS
from oasg.ingest import model_event_record


def crew_task_result_to_oasg_event(
    result: str | Mapping[str, Any],
    *,
    task_name: str,
    event_id: str,
    workflow_id: str = "crewai_agent",
) -> dict[str, Any]:
    """Convert a CrewAI task result into an OASG observation event."""

    output = str(dict(result)) if isinstance(result, Mapping) else result
    model_event = ModelEvent(
        provider="crewai",
        model="crew_task",
        prompt_hash=domain_hash("OASG:v1.0:crewai_task", task_name),
        output_hash=domain_hash("OASG:v1.0:crewai_output", output),
        resources={"output_chars": len(output)},
        metadata={"task_name": task_name},
    )
    action_grades = {action: "acceptable" for action in ACTION_CLASSES}
    action_grades["emit_claim"] = "blocked"
    action_grades["promote_workflow"] = "blocked"
    return model_event_record(
        model_event,
        event_id=event_id,
        workflow_id=workflow_id,
        component_id=task_name,
        collector_id="crewai_adapter",
        dimensions={dimension: "acceptable" for dimension in REQUIRED_DIMENSIONS},
        action_grades=action_grades,
        protected_debt={dimension: "acceptable" for dimension in REQUIRED_DIMENSIONS},
    )


def require_crewai_available() -> None:
    if importlib.util.find_spec("crewai") is None:
        raise RuntimeError(
            "CrewAI is not installed. Use this file as an optional integration pattern in your "
            "application environment. OASG itself does not depend on CrewAI."
        )
