"""Export language-independent JSON Schemas for OASG artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from oasg.io import write_json
from oasg.models import schema_models


def schema_documents() -> dict[str, dict[str, Any]]:
    return {name: model.model_json_schema() for name, model in schema_models().items()}


def export_schemas(output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, schema in schema_documents().items():
        path = output_dir / f"{name}.schema.json"
        write_json(path, schema)
        written.append(path)
    return written
