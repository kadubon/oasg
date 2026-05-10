"""Generate deterministic effect-oriented OASG pilot tasks."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any


def generate_effect_tasks(seed: int = 20260508) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    tasks: list[dict[str, Any]] = []
    families = (
        "strict_json_extraction",
        "schema_repair",
        "safe_python_expression",
        "code_transform",
        "validator_receipt",
    )
    for index in range(60):
        phase = "calibration" if index < 12 else "evaluation"
        family = families[index % len(families)]
        ordinal = index + 1
        if family == "strict_json_extraction":
            values = rng.sample(range(1, 40), 5)
            evens = sorted({value for value in values if value % 2 == 0})
            tasks.append(
                {
                    "task_id": f"effect_{ordinal:03d}",
                    "phase": phase,
                    "family": family,
                    "validator": "json_equals",
                    "instruction": (
                        "Extract the sorted unique even integers from "
                        f"{values} and return them under key result."
                    ),
                    "expected": {"result": evens},
                }
            )
        elif family == "schema_repair":
            retries = rng.randint(0, 2)
            scope = "local" if index % 2 == 0 else "trial"
            tasks.append(
                {
                    "task_id": f"effect_{ordinal:03d}",
                    "phase": phase,
                    "family": family,
                    "validator": "json_schema",
                    "instruction": (
                        "Create a validation receipt with keys status, retries, scope, "
                        f"and rollback_available. Use status closed, retries {retries}, "
                        f"scope {scope}, rollback_available true."
                    ),
                    "schema": {
                        "type": "object",
                        "required": ["status", "retries", "scope", "rollback_available"],
                        "properties": {
                            "status": {"const": "closed"},
                            "retries": {"const": retries},
                            "scope": {"const": scope},
                            "rollback_available": {"const": True},
                        },
                    },
                }
            )
        elif family == "safe_python_expression":
            a = rng.randint(2, 9)
            b = rng.randint(3, 11)
            expected = (a * a) + b
            tasks.append(
                {
                    "task_id": f"effect_{ordinal:03d}",
                    "phase": phase,
                    "family": family,
                    "validator": "python_expr",
                    "instruction": (
                        "Return a Python expression under key expression. It must evaluate "
                        f"to {expected} without imports, calls, attributes, or subscripts."
                    ),
                    "expected_value": expected,
                }
            )
        elif family == "code_transform":
            name = f"closeTask{ordinal}"
            snake = f"close_task_{ordinal}"
            tasks.append(
                {
                    "task_id": f"effect_{ordinal:03d}",
                    "phase": phase,
                    "family": family,
                    "validator": "json_equals",
                    "instruction": (
                        f"Convert the identifier {name} to snake_case and return keys "
                        "identifier and style."
                    ),
                    "expected": {"identifier": snake, "style": "snake_case"},
                }
            )
        else:
            task_id = f"obl_{ordinal:03d}"
            tasks.append(
                {
                    "task_id": f"effect_{ordinal:03d}",
                    "phase": phase,
                    "family": family,
                    "validator": "json_equals",
                    "instruction": (
                        "Create an operational validator receipt for obligation "
                        f"{task_id}. Return keys obligation_id, closed, failures, and evidence."
                    ),
                    "expected": {
                        "obligation_id": task_id,
                        "closed": True,
                        "failures": 0,
                        "evidence": "deterministic_validator",
                    },
                }
            )
    return tasks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--seed", type=int, default=20260508)
    args = parser.parse_args()
    tasks = generate_effect_tasks(args.seed)
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(task, sort_keys=True, separators=(",", ":")) + "\n" for task in tasks)
    path.write_text(text, encoding="utf-8", newline="\n")
    print(json.dumps({"status": "ok", "task_count": len(tasks), "out": str(path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
