"""Deterministic task generator for the strong-baseline experiment."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any

FAMILIES = (
    "json_schema_repair",
    "validator_receipt",
    "safe_python_expression",
    "code_transform",
    "obligation_closure",
    "replay_rollback_receipt",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20260509)
    parser.add_argument("--epoch-count", type=int, default=20)
    parser.add_argument("--tasks-per-epoch", type=int, default=8)
    parser.add_argument("--warmup-epochs", type=int, default=3)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    tasks = generate_strong_tasks(
        seed=args.seed,
        epoch_count=args.epoch_count,
        tasks_per_epoch=args.tasks_per_epoch,
        warmup_epochs=args.warmup_epochs,
    )
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for task in tasks:
            handle.write(json.dumps(task, sort_keys=True, separators=(",", ":")) + "\n")
    return 0


def generate_strong_tasks(
    *,
    seed: int = 20260509,
    epoch_count: int = 20,
    tasks_per_epoch: int = 8,
    warmup_epochs: int = 3,
) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    tasks: list[dict[str, Any]] = []
    for epoch in range(1, epoch_count + 1):
        phase = "calibration" if epoch <= warmup_epochs else "longrun_eval"
        burst = _burst_for_epoch(epoch, warmup_epochs)
        families = list(FAMILIES)
        while len(families) < tasks_per_epoch:
            families.append(rng.choice(FAMILIES))
        rng.shuffle(families)
        for index, family in enumerate(families[:tasks_per_epoch], start=1):
            tasks.append(_task_for_family(seed, epoch, index, phase, burst, family, rng))
    return tasks


def _burst_for_epoch(epoch: int, warmup_epochs: int) -> str:
    if epoch <= warmup_epochs:
        return ("warmup_schema_drift", "warmup_receipt_gap", "warmup_safe_expr_gap")[
            (epoch - 1) % 3
        ]
    return (
        "schema_drift",
        "validator_burst",
        "context_budget_burst",
        "receipt_family_burst",
        "safe_expression_burst",
        "recovery",
    )[(epoch - warmup_epochs - 1) % 6]


def _task_for_family(
    seed: int,
    epoch: int,
    index: int,
    phase: str,
    burst: str,
    family: str,
    rng: random.Random,
) -> dict[str, Any]:
    task_id = f"strong_s{seed}_e{epoch:02d}_t{index:02d}"
    base: dict[str, Any] = {
        "task_id": task_id,
        "seed": seed,
        "epoch": epoch,
        "phase": phase,
        "burst": burst,
        "family": family,
    }
    if family == "safe_python_expression":
        a = rng.randint(2, 9)
        b = rng.randint(2, 9)
        return {
            **base,
            "instruction": f"Return a safe arithmetic expression equal to {a * b + 3}.",
            "validator": "python_expr",
            "expected_value": a * b + 3,
        }
    if family == "validator_receipt":
        expected = {"status": "passed", "checks": 3, "failures": 0}
        return {
            **base,
            "instruction": "Create a validator receipt with status passed, checks 3, failures 0.",
            "validator": "json_schema",
            "schema": {"status": "string", "checks": "integer", "failures": "integer"},
            "expected": expected,
        }
    if family == "obligation_closure":
        expected = {"obligation": "closed", "remaining": 0}
        return {
            **base,
            "instruction": "Close the obligation and report remaining count zero.",
            "validator": "json_schema",
            "schema": {"obligation": "string", "remaining": "integer"},
            "expected": expected,
        }
    if family == "replay_rollback_receipt":
        expected = {"replay": "available", "rollback": "available", "effects": 0}
        return {
            **base,
            "instruction": "Create replay and rollback receipts with zero external effects.",
            "validator": "json_schema",
            "schema": {"replay": "string", "rollback": "string", "effects": "integer"},
            "expected": expected,
        }
    if family == "code_transform":
        expected = {"identifier": f"task_{epoch}_{index}"}
        return {
            **base,
            "instruction": f"Convert 'Task {epoch} {index}' to snake_case identifier.",
            "validator": "json_equals",
            "expected": expected,
        }
    expected = {"ok": True, "label": f"item_{epoch}_{index}"}
    return {
        **base,
        "instruction": f"Return ok true and label item_{epoch}_{index}.",
        "validator": "json_schema",
        "schema": {"ok": "boolean", "label": "string"},
        "expected": expected,
    }


if __name__ == "__main__":
    raise SystemExit(main())
