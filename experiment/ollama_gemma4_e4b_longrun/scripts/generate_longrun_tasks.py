"""Generate deterministic long-running OASG/Ollama experiment tasks."""

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

BURSTS = {
    1: "warmup_format_drift",
    2: "warmup_backlog",
    3: "warmup_rollback_gap",
    4: "validator_failure_burst",
    5: "recovery",
    8: "context_budget_pressure",
    9: "recovery",
    12: "stale_format_drift",
    13: "recovery",
    16: "rollback_receipt_gap",
    17: "recovery",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--seed", type=int, default=20260508)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--tasks-per-epoch", type=int, default=8)
    parser.add_argument("--warmup-epochs", type=int, default=3)
    args = parser.parse_args()

    tasks = generate_longrun_tasks(
        seed=args.seed,
        epoch_count=args.epochs,
        tasks_per_epoch=args.tasks_per_epoch,
        warmup_epochs=args.warmup_epochs,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as handle:
        for task in tasks:
            handle.write(json.dumps(task, sort_keys=True, separators=(",", ":")) + "\n")
    print(json.dumps({"status": "ok", "task_count": len(tasks), "out": str(out)}, indent=2))
    return 0


def generate_longrun_tasks(
    *,
    seed: int = 20260508,
    epoch_count: int = 20,
    tasks_per_epoch: int = 8,
    warmup_epochs: int = 3,
) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    tasks: list[dict[str, Any]] = []
    for epoch in range(1, epoch_count + 1):
        phase = "warmup" if epoch <= warmup_epochs else "longrun_eval"
        burst = BURSTS.get(epoch, "steady")
        for slot in range(1, tasks_per_epoch + 1):
            family = FAMILIES[(epoch + slot + rng.randrange(len(FAMILIES))) % len(FAMILIES)]
            tasks.append(_task_for(epoch, slot, phase, burst, family))
    return tasks


def _task_for(
    epoch: int,
    slot: int,
    phase: str,
    burst: str,
    family: str,
) -> dict[str, Any]:
    task_id = f"longrun_e{epoch:02d}_t{slot:02d}"
    base = {
        "task_id": task_id,
        "epoch": epoch,
        "slot": slot,
        "phase": phase,
        "burst": burst,
        "family": family,
    }
    n = epoch * 10 + slot
    if family == "json_schema_repair":
        return {
            **base,
            "validator": "json_schema",
            "schema": {
                "id": "string",
                "status": "string",
                "count": "integer",
                "closed": "boolean",
            },
            "expected": {
                "id": task_id,
                "status": "ok",
                "count": n,
                "closed": True,
            },
            "instruction": (
                "Return a JSON object with id, status, count, and closed. "
                f"Use id {task_id}, status ok, count {n}, closed true."
            ),
        }
    if family == "validator_receipt":
        return {
            **base,
            "validator": "json_schema",
            "schema": {
                "receipt_type": "string",
                "status": "string",
                "failures": "integer",
                "valid": "boolean",
            },
            "expected": {
                "receipt_type": "validator_receipt",
                "status": "passed",
                "failures": 0,
                "valid": True,
            },
            "instruction": (
                "Construct a validator receipt JSON object with receipt_type "
                "validator_receipt, status passed, failures 0, valid true."
            ),
        }
    if family == "safe_python_expression":
        left = epoch + slot
        right = slot + 3
        return {
            **base,
            "validator": "python_expr",
            "expected_value": left * right,
            "instruction": (
                "Return JSON with key expression containing a Python expression "
                f"that evaluates to {left * right} using only literals and operators."
            ),
        }
    if family == "code_transform":
        source = f"long_run_value_{epoch}_{slot}"
        expected = "".join(part.capitalize() for part in source.split("_"))
        return {
            **base,
            "validator": "json_equals",
            "expected": {"identifier": expected, "style": "PascalCase"},
            "instruction": (
                f"Convert identifier {source} to PascalCase. Return JSON with "
                "identifier and style."
            ),
        }
    if family == "obligation_closure":
        return {
            **base,
            "validator": "json_schema",
            "schema": {
                "obligation_id": "string",
                "closed": "boolean",
                "evidence": "string",
                "remaining": "integer",
            },
            "expected": {
                "obligation_id": f"obl_{epoch:02d}_{slot:02d}",
                "closed": True,
                "evidence": "validator_passed",
                "remaining": 0,
            },
            "instruction": (
                f"Close obligation obl_{epoch:02d}_{slot:02d}. Return JSON with "
                "obligation_id, closed true, evidence validator_passed, remaining 0."
            ),
        }
    return {
        **base,
        "validator": "json_schema",
        "schema": {
            "artifact_id": "string",
            "replay_receipt": "string",
            "rollback_receipt": "string",
            "rollback_available": "boolean",
        },
        "expected": {
            "artifact_id": f"art_{epoch:02d}_{slot:02d}",
            "replay_receipt": "replay_passed",
            "rollback_receipt": "rollback_available",
            "rollback_available": True,
        },
        "instruction": (
            f"Create replay and rollback receipt JSON for artifact art_{epoch:02d}_{slot:02d}. "
            "Use replay_passed, rollback_available, and rollback_available true."
        ),
    }


if __name__ == "__main__":
    raise SystemExit(main())
