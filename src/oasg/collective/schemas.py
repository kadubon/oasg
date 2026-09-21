"""Additive collective schema catalogue; legacy schema export remains unchanged."""

from typing import Any
from pydantic import BaseModel

from oasg.collective.wire import Contract, Execution, Source, TaskBinding


def schema_documents() -> dict[str, dict[str, Any]]:
    models: dict[str, type[BaseModel]] = {"contract": Contract, "execution": Execution,
                                        "source": Source, "task-binding": TaskBinding}
    return {name: model.model_json_schema() | {"$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:oasg:collective:"+name+":v1"}
        for name, model in models.items()}
