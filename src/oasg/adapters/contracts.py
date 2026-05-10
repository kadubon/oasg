"""Provider-neutral model connector contracts.

Adapters are intentionally outside the trusted gate. They emit observable events; they do not
decide whether a workflow mutation improves OASG state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ModelEvent:
    provider: str
    model: str
    prompt_hash: str
    output_hash: str
    resources: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "prompt_hash": self.prompt_hash,
            "output_hash": self.output_hash,
            "resources": self.resources,
            "metadata": self.metadata,
        }

    def to_event_record(
        self,
        *,
        event_id: str,
        workflow_id: str,
        component_id: str = "model",
        dimensions: dict[str, str] | None = None,
        action_grades: dict[str, str] | None = None,
        protected_debt: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        from oasg.ingest import model_event_record

        return model_event_record(
            self,
            event_id=event_id,
            workflow_id=workflow_id,
            component_id=component_id,
            dimensions=dimensions,
            action_grades=action_grades,
            protected_debt=protected_debt,
        )


class ModelConnector(Protocol):
    """Protocol for model connectors that produce observable events."""

    def invoke(self, prompt: str) -> ModelEvent:
        """Run a model-like callable and return an observable event."""
