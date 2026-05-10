"""LangGraph adapter pattern for OASG.

LangGraph can own durable execution and resume semantics. OASG can sit beside it as the
evidence-backed workflow-policy promotion gate.

This file does not require LangGraph unless `build_langgraph_observer_node()` is called.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Mapping
from typing import Any

from oasg.adapters.contracts import ModelEvent
from oasg.canonical import domain_hash
from oasg.constants import ACTION_CLASSES, REQUIRED_DIMENSIONS
from oasg.ingest import model_event_record


def langgraph_state_to_oasg_event(
    state: Mapping[str, Any],
    *,
    event_id: str,
    workflow_id: str = "langgraph_agent",
) -> dict[str, Any]:
    """Convert a LangGraph-like state mapping into an OASG observation event."""

    prompt = str(state.get("prompt", ""))
    output = str(state.get("last_output", ""))
    model_event = ModelEvent(
        provider="langgraph",
        model=str(state.get("model", "unknown")),
        prompt_hash=domain_hash("OASG:v1.0:langgraph_prompt", prompt),
        output_hash=domain_hash("OASG:v1.0:langgraph_output", output),
        resources={
            "attempts": int(state.get("attempts", 1)),
            "output_chars": len(output),
        },
        metadata={
            "node": str(state.get("node", "unknown")),
            "validation_status": str(state.get("validation_status", "unknown")),
        },
    )
    action_grades = {action: "acceptable" for action in ACTION_CLASSES}
    action_grades["emit_claim"] = "blocked"
    action_grades["promote_workflow"] = "blocked"
    return model_event_record(
        model_event,
        event_id=event_id,
        workflow_id=workflow_id,
        component_id=str(state.get("node", "langgraph_node")),
        collector_id="langgraph_adapter",
        dimensions={dimension: "acceptable" for dimension in REQUIRED_DIMENSIONS},
        action_grades=action_grades,
        protected_debt={dimension: "acceptable" for dimension in REQUIRED_DIMENSIONS},
    )


def build_langgraph_observer_node() -> Any:
    """Return a LangGraph node function when LangGraph is installed."""

    if importlib.util.find_spec("langgraph") is None:
        raise RuntimeError(
            "LangGraph is not installed. Install it in your application environment to use this "
            "optional observer node. OASG itself does not depend on LangGraph."
        )

    def observe_node(state: Mapping[str, Any]) -> dict[str, Any]:
        event = langgraph_state_to_oasg_event(
            state,
            event_id=str(state.get("oasg_event_id", "evt_langgraph_observation")),
        )
        return {"oasg_event": event}

    return observe_node
