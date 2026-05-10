"""Small JSON and JSONL I/O helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from oasg.canonical import canonical_json_dumps


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json_dumps(value) + "\n", encoding="utf-8", newline="\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        parsed = json.loads(line)
        if not isinstance(parsed, dict):
            raise ValueError(f"JSONL line {line_number} is not an object")
        records.append(parsed)
    return records


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(canonical_json_dumps(record) + "\n" for record in records)
    path.write_text(text, encoding="utf-8", newline="\n")
