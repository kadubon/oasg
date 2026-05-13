"""Generate deterministic tasks for the nonstationary confirmatory experiment."""

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

VARIANT_PHASES: dict[str, tuple[dict[str, str], ...]] = {
    "full_drift_confirmatory": (
        {
            "phase_id": "phase_a_calibration",
            "phase_role": "calibration",
            "phase_category": "calibration",
            "drift_family": "pre_drift",
            "difficulty_tag": "calibration",
        },
        {
            "phase_id": "phase_b_mild_drift",
            "phase_role": "post_drift",
            "phase_category": "mild",
            "drift_family": "schema_key_variation",
            "difficulty_tag": "mild_drift",
        },
        {
            "phase_id": "phase_c_structural_drift",
            "phase_role": "post_drift",
            "phase_category": "structural",
            "drift_family": "receipt_obligation_safety_shift",
            "difficulty_tag": "structural_drift",
        },
        {
            "phase_id": "phase_d_mixed_reversion",
            "phase_role": "post_drift",
            "phase_category": "mixed",
            "drift_family": "mixed_reversion",
            "difficulty_tag": "mixed_reversion",
        },
    ),
    "no_mixed_reversion_ablation": (
        {
            "phase_id": "phase_a_calibration",
            "phase_role": "calibration",
            "phase_category": "calibration",
            "drift_family": "pre_drift",
            "difficulty_tag": "calibration",
        },
        {
            "phase_id": "phase_b_mild_drift",
            "phase_role": "post_drift",
            "phase_category": "mild",
            "drift_family": "schema_key_variation",
            "difficulty_tag": "mild_drift",
        },
        {
            "phase_id": "phase_c1_structural_drift",
            "phase_role": "post_drift",
            "phase_category": "structural",
            "drift_family": "receipt_obligation_safety_shift",
            "difficulty_tag": "structural_drift",
        },
        {
            "phase_id": "phase_c2_structural_surface_shift",
            "phase_role": "post_drift",
            "phase_category": "structural_surface",
            "drift_family": "surface_form_shift_without_reversion",
            "difficulty_tag": "structural_surface_shift",
        },
    ),
    "mixed_reversion_only_probe": (
        {
            "phase_id": "phase_a_calibration",
            "phase_role": "calibration",
            "phase_category": "calibration",
            "drift_family": "pre_drift",
            "difficulty_tag": "calibration",
        },
        {
            "phase_id": "phase_d1_mixed_reversion",
            "phase_role": "post_drift",
            "phase_category": "mixed",
            "drift_family": "mixed_reversion_old_new_60_40",
            "difficulty_tag": "mixed_reversion",
        },
        {
            "phase_id": "phase_d2_mixed_ratio_shift",
            "phase_role": "post_drift",
            "phase_category": "mixed",
            "drift_family": "mixed_reversion_old_new_40_60",
            "difficulty_tag": "mixed_ratio_shift",
        },
    ),
    "delayed_drift_recovery": (
        {
            "phase_id": "phase_a_calibration",
            "phase_role": "calibration",
            "phase_category": "calibration",
            "drift_family": "pre_drift",
            "difficulty_tag": "calibration",
        },
        {
            "phase_id": "phase_a2_stable_continuation",
            "phase_role": "stable_control",
            "phase_category": "stable",
            "drift_family": "stable_continuation",
            "difficulty_tag": "pre_drift_stable",
        },
        {
            "phase_id": "phase_c_structural_drift",
            "phase_role": "post_drift",
            "phase_category": "structural",
            "drift_family": "delayed_structural_shift",
            "difficulty_tag": "structural_drift",
        },
        {
            "phase_id": "phase_d_partial_reversion",
            "phase_role": "post_drift",
            "phase_category": "mixed",
            "drift_family": "partial_reversion",
            "difficulty_tag": "partial_reversion",
        },
    ),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20260509)
    parser.add_argument("--variant", default="full_drift_confirmatory", choices=sorted(VARIANT_PHASES))
    parser.add_argument("--epochs-per-phase", type=int, default=2)
    parser.add_argument("--tasks-per-epoch", type=int, default=6)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    tasks = generate_confirmatory_tasks(
        seed=args.seed,
        variant_id=args.variant,
        epochs_per_phase=args.epochs_per_phase,
        tasks_per_epoch=args.tasks_per_epoch,
    )
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for task in tasks:
            handle.write(json.dumps(task, sort_keys=True, separators=(",", ":")) + "\n")
    return 0


def phase_schedule(variant_id: str) -> tuple[dict[str, str], ...]:
    return VARIANT_PHASES[variant_id]


def generate_confirmatory_tasks(
    *,
    seed: int,
    variant_id: str,
    epochs_per_phase: int,
    tasks_per_epoch: int,
) -> list[dict[str, Any]]:
    rng = random.Random(f"{seed}:{variant_id}")
    tasks: list[dict[str, Any]] = []
    global_epoch = 0
    for phase_index, phase in enumerate(phase_schedule(variant_id), start=1):
        for phase_epoch in range(1, epochs_per_phase + 1):
            global_epoch += 1
            families = list(FAMILIES)
            while len(families) < tasks_per_epoch:
                families.append(rng.choice(FAMILIES))
            rng.shuffle(families)
            for index, family in enumerate(families[:tasks_per_epoch], start=1):
                task = _task_for_family(
                    seed=seed,
                    variant_id=variant_id,
                    phase=phase,
                    phase_index=phase_index,
                    phase_epoch=phase_epoch,
                    epoch=global_epoch,
                    index=index,
                    family=family,
                    rng=rng,
                )
                canonical_input = {
                    "task_id": task["task_id"],
                    "variant_id": variant_id,
                    "phase_id": task["phase_id"],
                    "phase_role": task["phase_role"],
                    "instruction": task["instruction"],
                    "validator": task["validator"],
                    "expected": task.get("expected"),
                    "schema": task.get("schema"),
                    "expected_value": task.get("expected_value"),
                }
                task["canonical_input_hash"] = receipt_hash(canonical_input)
                task["workload_hash"] = receipt_hash(
                    {"seed": seed, "variant_id": variant_id, "canonical_input": canonical_input}
                )
                tasks.append(task)
    return tasks


def _task_for_family(
    *,
    seed: int,
    variant_id: str,
    phase: dict[str, str],
    phase_index: int,
    phase_epoch: int,
    epoch: int,
    index: int,
    family: str,
    rng: random.Random,
) -> dict[str, Any]:
    task_id = (
        f"confirm_{_variant_short_id(variant_id)}_s{seed}_p{phase_index}_"
        f"e{phase_epoch:02d}_t{index:02d}"
    )
    base: dict[str, Any] = {
        "task_id": task_id,
        "seed": seed,
        "variant_id": variant_id,
        "epoch": epoch,
        "phase_epoch": phase_epoch,
        "phase": phase["phase_id"],
        "phase_id": phase["phase_id"],
        "phase_index": phase_index,
        "phase_role": phase["phase_role"],
        "phase_category": phase["phase_category"],
        "burst": phase["drift_family"],
        "drift_family": phase["drift_family"],
        "difficulty_tag": phase["difficulty_tag"],
        "family": family,
        "input_payload": {
            "variant_id": variant_id,
            "phase_id": phase["phase_id"],
            "family": family,
            "index": index,
        },
        "expected_validator_behavior": "deterministic_parser_or_schema_check",
    }
    if family == "safe_python_expression":
        value = rng.randint(2, 9) * rng.randint(2, 9) + phase_index
        return {
            **base,
            "instruction": _instruction(phase, f"Return a safe arithmetic expression equal to {value}."),
            "validator": "python_expr",
            "expected_value": value,
        }
    expected = _expected_for_family(
        family=family,
        phase_category=phase["phase_category"],
        phase_index=phase_index,
        phase_epoch=phase_epoch,
        index=index,
    )
    validator = "json_equals" if family == "code_transform" else "json_schema"
    task = {
        **base,
        "instruction": _instruction(phase, _instruction_body(family, expected)),
        "validator": validator,
        "expected": expected,
    }
    if validator == "json_schema":
        task["schema"] = _schema_for(expected)
    return task


def _expected_for_family(
    *, family: str, phase_category: str, phase_index: int, phase_epoch: int, index: int
) -> dict[str, Any]:
    if family == "validator_receipt":
        if phase_category in {"structural", "structural_surface"}:
            return {"receipt_status": "passed", "evidence_checks": 3, "open_failures": 0}
        if phase_category == "mild":
            return {"result": "passed", "check_count": 3, "failure_count": 0}
        return {"status": "passed", "checks": 3, "failures": 0}
    if family == "obligation_closure":
        if phase_category in {"structural", "structural_surface"}:
            return {"closure": "complete", "open_obligations": 0, "evidence": "attached"}
        if phase_category == "mild":
            return {"obligation_state": "closed", "remaining_count": 0}
        return {"obligation": "closed", "remaining": 0}
    if family == "replay_rollback_receipt":
        if phase_category in {"structural", "structural_surface"}:
            return {
                "replay": "available",
                "rollback": "available",
                "external_effects": 0,
                "receipt_version": 2,
            }
        if phase_category == "mild":
            return {"replay_receipt": "available", "rollback_receipt": "available", "effects": 0}
        return {"replay": "available", "rollback": "available", "effects": 0}
    if family == "code_transform":
        key = "id" if phase_category in {"mild", "structural_surface"} else "identifier"
        return {key: f"task_{phase_index}_{phase_epoch}_{index}"}
    key = "item_label" if phase_category in {"mild", "structural_surface"} else "label"
    return {"ok": True, key: f"item_{phase_index}_{phase_epoch}_{index}"}


def _instruction(phase: dict[str, str], body: str) -> str:
    category = phase["phase_category"]
    if category == "calibration":
        return body
    if category == "stable":
        return f"{body} Keep the original stable format."
    if category == "mild":
        return f"{body} Use current alias keys and strict JSON only."
    if category in {"structural", "structural_surface"}:
        return f"{body} Use the current receipt schema and close all obligations."
    return f"{body} Handle old and new accepted forms without extra prose."


def _instruction_body(family: str, expected: dict[str, Any]) -> str:
    if family == "validator_receipt":
        return "Create a validator receipt."
    if family == "obligation_closure":
        return "Close the obligation."
    if family == "replay_rollback_receipt":
        return "Create replay and rollback receipts."
    if family == "code_transform":
        return f"Convert the item into {next(iter(expected.keys()))} JSON."
    return "Return the requested JSON object."


def _schema_for(expected: dict[str, Any]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for key, value in expected.items():
        if isinstance(value, bool):
            mapping[key] = "boolean"
        elif isinstance(value, int):
            mapping[key] = "integer"
        else:
            mapping[key] = "string"
    return mapping


def _variant_short_id(variant_id: str) -> str:
    return {
        "full_drift_confirmatory": "full",
        "no_mixed_reversion_ablation": "nomix",
        "mixed_reversion_only_probe": "mixonly",
        "delayed_drift_recovery": "delay",
    }[variant_id]


if __name__ == "__main__":
    raise SystemExit(main())

