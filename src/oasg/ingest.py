"""Convert adapter outputs into ready-to-seal OASG event records."""

from __future__ import annotations

from typing import Any

from oasg.adapters.contracts import ModelEvent
from oasg.events import event_record, observation_payload


def model_event_record(
    model_event: ModelEvent,
    *,
    event_id: str,
    workflow_id: str,
    component_id: str = "model",
    collector_id: str = "adapter",
    dimensions: dict[str, str] | None = None,
    action_grades: dict[str, str] | None = None,
    protected_debt: dict[str, str] | None = None,
    proof_obligation_receipts: list[dict[str, Any]] | None = None,
    repair_receipts: list[dict[str, Any]] | None = None,
    positive_evidence: list[dict[str, str]] | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return event_record(
        event_id=event_id,
        workflow_id=workflow_id,
        component_id=component_id,
        collector_id=collector_id,
        event_type="observation",
        payload=observation_payload(
            dimensions=dimensions,
            action_grades=action_grades,
            protected_debt=protected_debt,
            proof_obligation_receipts=proof_obligation_receipts,
            repair_receipts=repair_receipts,
            positive_evidence=positive_evidence,
            policy=policy,
            model_event=model_event.to_payload(),
        ),
    )
