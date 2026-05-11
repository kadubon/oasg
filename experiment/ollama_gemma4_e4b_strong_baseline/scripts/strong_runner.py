"""Task execution helpers for the strong-baseline profile."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
DECISIVE = ROOT / "experiment" / "ollama_gemma4_e4b_decisive" / "scripts"
SRC = ROOT / "src"
for import_path in (DECISIVE, SRC, ROOT):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from decisive_runner import run_task as _run_decisive_task  # noqa: E402
from decisive_runner import write_history  # noqa: E402,F401


RUNTIME_POLICY_ALIASES = {
    "context_shortening_policy": "strict_json_minimal",
    "validator_placement_tightening": "schema_keys_only",
    "rollback_evidence_requirement_tightening": "receipt_template_only",
}


def runtime_policy_id(policy_id: str | None) -> str | None:
    if policy_id is None:
        return None
    return RUNTIME_POLICY_ALIASES.get(policy_id, policy_id)


def run_task(
    *,
    task: dict[str, Any],
    condition: str,
    config: dict[str, Any],
    policy_id: str | None,
    active_mutation_id: str | None = None,
    mock_model: bool = False,
) -> Any:
    result = _run_decisive_task(
        task=task,
        condition=condition,
        config=config,
        policy_id=runtime_policy_id(policy_id),
        active_mutation_id=active_mutation_id,
        mock_model=mock_model,
    )
    row = result.to_dict()
    row["configured_policy_id"] = policy_id
    row["runtime_policy_id"] = runtime_policy_id(policy_id)
    return _ResultAdapter(row)


class _ResultAdapter:
    def __init__(self, row: dict[str, Any]) -> None:
        self._row = row

    def to_dict(self) -> dict[str, Any]:
        return dict(self._row)
