"""Task execution wrapper for the strong-baseline v2 profile."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
V1 = ROOT / "experiment" / "ollama_gemma4_e4b_strong_baseline" / "scripts"
for import_path in (V1, ROOT):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from strong_runner import run_task as _run_v1_task  # type: ignore  # noqa: E402
from strong_runner import runtime_policy_id, write_history  # type: ignore  # noqa: E402,F401


def run_task(
    *,
    task: dict[str, Any],
    condition: str,
    config: dict[str, Any],
    policy_id: str | None,
    active_mutation_id: str | None = None,
    mock_model: bool = False,
) -> Any:
    return _run_v1_task(
        task=task,
        condition=condition,
        config=config,
        policy_id=policy_id,
        active_mutation_id=active_mutation_id,
        mock_model=mock_model,
    )

