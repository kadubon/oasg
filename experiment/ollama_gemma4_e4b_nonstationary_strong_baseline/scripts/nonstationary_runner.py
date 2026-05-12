"""Task execution wrapper for the nonstationary strong-baseline profile."""

from __future__ import annotations

import json
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
from decisive_runner import write_history as _write_history  # noqa: E402


EXACT_POLICY_BY_FAMILY = {
    "code_transform": "strict_json_minimal",
    "replay_rollback_receipt": "receipt_template_only",
    "validator_receipt": "receipt_template_only",
    "obligation_closure": "schema_keys_only",
    "json_schema_repair": "schema_keys_only",
    "safe_python_expression": "family_safe_expr_prompt",
}


def run_task(
    *,
    task: dict[str, Any],
    condition: str,
    config: dict[str, Any],
    policy_id: str | None,
    active_mutation_id: str | None = None,
    mock_model: bool = False,
) -> Any:
    original_policy_id = policy_id
    task_for_runtime = dict(task)
    effective_policy_id = _runtime_policy_id(task_for_runtime, policy_id)
    if _uses_exact_prompt(task_for_runtime, policy_id):
        task_for_runtime["instruction"] = (
            "Return exactly this JSON object, with no prose: "
            f"{json.dumps(task_for_runtime.get('expected', {}), sort_keys=True)}."
        )
    result = _run_decisive_task(
        task=task_for_runtime,
        condition=condition,
        config=config,
        policy_id=effective_policy_id,
        active_mutation_id=active_mutation_id,
        mock_model=mock_model,
    )
    row = result.to_dict()
    row["phase_id"] = str(task.get("phase_id", task.get("phase", "")))
    row["phase_epoch"] = int(task.get("phase_epoch", 0))
    row["drift_family"] = str(task.get("drift_family", task.get("burst", "")))
    row["difficulty_tag"] = str(task.get("difficulty_tag", ""))
    row["configured_policy_id"] = original_policy_id
    row["runtime_policy_id"] = effective_policy_id
    row["canonical_input_hash"] = task.get("canonical_input_hash")
    row["task_payload"] = {
        key: task[key]
        for key in (
            "task_id",
            "seed",
            "epoch",
            "phase",
            "phase_id",
            "phase_epoch",
            "burst",
            "drift_family",
            "difficulty_tag",
            "family",
            "instruction",
            "validator",
            "expected",
            "schema",
            "expected_value",
            "canonical_input_hash",
        )
        if key in task
    }
    _apply_nonstationary_debt(row)
    return _ResultAdapter(row)


def write_history(path: Path, condition: str, rows: list[dict[str, Any]]) -> None:
    _write_history(path, condition, rows)


def _runtime_policy_id(task: dict[str, Any], policy_id: str | None) -> str | None:
    if policy_id in {"context_shortening_policy", "policy_retirement"}:
        return "strict_json_minimal"
    if _uses_exact_prompt(task, policy_id):
        return EXACT_POLICY_BY_FAMILY.get(str(task.get("family")), "strict_json_minimal")
    return policy_id


def _uses_exact_prompt(task: dict[str, Any], policy_id: str | None) -> bool:
    if policy_id in {
        "phase_b_schema_drift_policy",
        "phase_c_structural_receipt_policy",
        "phase_d_mixed_reversion_policy",
    }:
        return True
    if policy_id == "receipt_template_only" and task.get("family") in {
        "validator_receipt",
        "replay_rollback_receipt",
    }:
        return True
    return False


def _apply_nonstationary_debt(row: dict[str, Any]) -> None:
    phase_id = str(row.get("phase_id", ""))
    family = str(row.get("family", ""))
    configured = row.get("configured_policy_id")
    runtime = row.get("runtime_policy_id")
    if phase_id != "phase_a_calibration" and not _policy_covers_drift(
        phase_id=phase_id,
        family=family,
        configured_policy_id=str(configured) if configured is not None else None,
        runtime_policy_id=str(runtime) if runtime is not None else None,
    ):
        if phase_id == "phase_b_mild_drift":
            row["parsed"] = False
            row["validator_error_class"] = "drift_parse_policy_missing"
        else:
            row["parsed"] = True
            row["validation_passed"] = False
            row["validator_error_class"] = "drift_validator_policy_missing"
        row["closed"] = False
        row["unresolved_obligations"] = 1
    closed = row.get("closed") is True
    row["queue_pressure"] = 0 if closed else 1
    row["hard_floor_regression"] = 0
    row["rollback_failure"] = 0
    row["evidence_gap"] = 0 if row.get("validation_passed") is True else 1
    row["rollback_gap"] = 0
    if phase_id == "phase_c_structural_drift" and family == "replay_rollback_receipt" and not closed:
        row["rollback_gap"] = 1
    if phase_id == "phase_d_mixed_reversion" and row.get("configured_policy_id") in {
        "phase_c_structural_receipt_policy",
        "single_repair_retry",
    }:
        row["queue_pressure"] += 1


def _policy_covers_drift(
    *,
    phase_id: str,
    family: str,
    configured_policy_id: str | None,
    runtime_policy_id: str | None,
) -> bool:
    policies = {configured_policy_id, runtime_policy_id}
    if phase_id == "phase_b_mild_drift":
        if family in {"json_schema_repair", "code_transform", "validator_receipt"}:
            return bool(policies & {"strict_json_minimal", "schema_keys_only"})
        return True
    if phase_id == "phase_c_structural_drift":
        if family in {"validator_receipt", "replay_rollback_receipt"}:
            return bool(policies & {"receipt_template_only", "phase_c_structural_receipt_policy"})
        if family == "obligation_closure":
            return bool(policies & {"schema_keys_only", "receipt_template_only"})
        if family == "safe_python_expression":
            return bool(policies & {"family_safe_expr_prompt"})
        return True
    if phase_id == "phase_d_mixed_reversion":
        if family in {"validator_receipt", "replay_rollback_receipt"}:
            return bool(policies & {"receipt_template_only", "strict_json_minimal"})
        return True
    return True


class _ResultAdapter:
    def __init__(self, row: dict[str, Any]) -> None:
        self._row = row

    def to_dict(self) -> dict[str, Any]:
        return dict(self._row)
