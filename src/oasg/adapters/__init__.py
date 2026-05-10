"""Model and tool adapter protocols."""

from oasg.adapters.contracts import ModelConnector, ModelEvent
from oasg.adapters.local_command import invoke_command
from oasg.adapters.python_function import invoke_function
from oasg.ingest import model_event_record

__all__ = ["ModelConnector", "ModelEvent", "invoke_command", "invoke_function", "model_event_record"]
