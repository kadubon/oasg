"""Generate deterministic nonstationary strong-baseline tasks."""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for import_path in (SRC, ROOT):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from oasg.canonical import receipt_hash  # noqa: E402

FAMILIES = (
    "json_schema_repair",
    "validator_receipt",
    "safe_python_expression",
    "code_transform",
    "obligation_closure",
    "replay_rollback_receipt",
)

PHASES = (
    ("phase_a_calibration", "pre_drift", "calibration"),
    ("phase_b_mild_drift", "schema_key_variation", "mild"),
    ("phase_c_structural_drift", "receipt_obligation_safety_shift", "structural"),
    ("phase_d_mixed_reversion", "mixed_reversion", "mixed"),
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20260509)
    parser.add_argument("--epochs-per-phase", type=int, default=2)
    parser.add_argument("--tasks-per-epoch", type=int, default=4)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    tasks = generate_nonstationary_tasks(
        seed=args.seed,
        epochs_per_phase=args.epochs_per_phase,
        tasks_per_epoch=args.tasks_per_epoch,
    )
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for task in tasks:
            handle.write(json.dumps(task, sort_keys=True, separators=(",", ":")) + "\n")
    return 0


def generate_nonstationary_tasks(
    *,
    seed: int = 20260509,
    epochs_per_phase: int = 2,
    tasks_per_epoch: int = 4,
) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    tasks: list[dict[str, Any]] = []
    global_epoch = 0
    for phase_index, (phase_id, drift_family, difficulty) in enumerate(PHASES, start=1):
        for phase_epoch in range(1, epochs_per_phase + 1):
            global_epoch += 1
            families = list(FAMILIES)
            while len(families) < tasks_per_epoch:
                families.append(rng.choice(FAMILIES))
            rng.shuffle(families)
            for index, family in enumerate(families[:tasks_per_epoch], start=1):
                task = _task_for_family(
                    seed=seed,
                    phase_index=phase_index,
                    phase_id=phase_id,
                    phase_epoch=phase_epoch,
                    epoch=global_epoch,
                    index=index,
                    drift_family=drift_family,
                    difficulty=difficulty,
                    family=family,
                    rng=rng,
                )
                canonical_input = {
                    "task_id": task["task_id"],
                    "phase_id": phase_id,
                    "instruction": task["instruction"],
                    "validator": task["validator"],
                    "expected": task.get("expected"),
                    "schema": task.get("schema"),
                    "expected_value": task.get("expected_value"),
                }
                task["canonical_input_hash"] = receipt_hash(canonical_input)
                task["workload_hash"] = receipt_hash({"seed": seed, "canonical_input": canonical_input})
                tasks.append(task)
    return tasks


def _task_for_family(
    *,
    seed: int,
    phase_index: int,
    phase_id: str,
    phase_epoch: int,
    epoch: int,
    index: int,
    drift_family: str,
    difficulty: str,
    family: str,
    rng: random.Random,
) -> dict[str, Any]:
    task_id = f"nonstat_s{seed}_p{phase_index}_e{phase_epoch:02d}_t{index:02d}"
    base: dict[str, Any] = {
        "task_id": task_id,
        "seed": seed,
        "epoch": epoch,
        "phase_epoch": phase_epoch,
        "phase": phase_id,
        "phase_id": phase_id,
        "phase_index": phase_index,
        "burst": drift_family,
        "drift_family": drift_family,
        "difficulty_tag": difficulty,
        "family": family,
    }
    if family == "safe_python_expression":
        a = rng.randint(2, 9)
        b = rng.randint(2, 9)
        expected_value = a * b + phase_index
        return {
            **base,
            "instruction": _instruction(
                phase_id,
                f"Return a safe arithmetic expression equal to {expected_value}.",
                "safe expression",
            ),
            "validator": "python_expr",
            "expected_value": expected_value,
        }
    if family == "validator_receipt":
        expected = _phase_expected(
            phase_id,
            default={"status": "passed", "checks": 3, "failures": 0},
            mild={"result": "passed", "check_count": 3, "failure_count": 0},
            structural={"receipt_status": "passed", "evidence_checks": 3, "open_failures": 0},
            mixed={"status": "passed", "checks": 3, "failures": 0},
        )
        return {
            **base,
            "instruction": _instruction(phase_id, "Create a validator receipt.", "validator receipt"),
            "validator": "json_schema",
            "schema": _schema_for(expected),
            "expected": expected,
        }
    if family == "obligation_closure":
        expected = _phase_expected(
            phase_id,
            default={"obligation": "closed", "remaining": 0},
            mild={"obligation_state": "closed", "remaining_count": 0},
            structural={"closure": "complete", "open_obligations": 0, "evidence": "attached"},
            mixed={"obligation": "closed", "remaining": 0},
        )
        return {
            **base,
            "instruction": _instruction(phase_id, "Close the obligation.", "obligation closure"),
            "validator": "json_schema",
            "schema": _schema_for(expected),
            "expected": expected,
        }
    if family == "replay_rollback_receipt":
        expected = _phase_expected(
            phase_id,
            default={"replay": "available", "rollback": "available", "effects": 0},
            mild={"replay_receipt": "available", "rollback_receipt": "available", "effects": 0},
            structural={
                "replay": "available",
                "rollback": "available",
                "external_effects": 0,
                "receipt_version": 2,
            },
            mixed={"replay": "available", "rollback": "available", "effects": 0},
        )
        return {
            **base,
            "instruction": _instruction(phase_id, "Create replay and rollback receipts.", "receipt"),
            "validator": "json_schema",
            "schema": _schema_for(expected),
            "expected": expected,
        }
    if family == "code_transform":
        key = "identifier" if phase_id in {"phase_a_calibration", "phase_d_mixed_reversion"} else "id"
        expected = {key: f"task_{phase_index}_{phase_epoch}_{index}"}
        return {
            **base,
            "instruction": _instruction(
                phase_id,
                f"Convert Task {phase_index} {phase_epoch} {index} to snake_case identifier.",
                "identifier transform",
            ),
            "validator": "json_equals",
            "expected": expected,
        }
    key = "label" if phase_id != "phase_b_mild_drift" else "item_label"
    expected = {"ok": True, key: f"item_{phase_index}_{phase_epoch}_{index}"}
    return {
        **base,
        "instruction": _instruction(phase_id, f"Return ok true and {key}.", "JSON schema"),
        "validator": "json_schema",
        "schema": _schema_for(expected),
        "expected": expected,
    }


def _instruction(phase_id: str, base: str, label: str) -> str:
    if phase_id == "phase_a_calibration":
        return base
    if phase_id == "phase_b_mild_drift":
        return f"{base} Use the current drifted {label} field names."
    if phase_id == "phase_c_structural_drift":
        return f"{base} Include the stricter structural-drift fields."
    return f"{base} The workload may use either old or new {label} conventions."


def _phase_expected(
    phase_id: str,
    *,
    default: dict[str, Any],
    mild: dict[str, Any],
    structural: dict[str, Any],
    mixed: dict[str, Any],
) -> dict[str, Any]:
    if phase_id == "phase_b_mild_drift":
        return mild
    if phase_id == "phase_c_structural_drift":
        return structural
    if phase_id == "phase_d_mixed_reversion":
        return mixed
    return default


def _schema_for(expected: dict[str, Any]) -> dict[str, str]:
    schema: dict[str, str] = {}
    for key, value in expected.items():
        if isinstance(value, bool):
            schema[key] = "boolean"
        elif isinstance(value, int):
            schema[key] = "integer"
        else:
            schema[key] = "string"
    return schema


if __name__ == "__main__":
    raise SystemExit(main())
