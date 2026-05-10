"""Shared helpers for the definitive OASG effect protocol."""

from __future__ import annotations

import csv
import json
import random
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]


CONDITIONS = (
    "baseline_fixed",
    "oasg_observe_only",
    "forced_policy_positive_control",
    "oasg_adaptive",
)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
        newline="\n",
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8", newline="\n")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def task_debt(row: dict[str, Any]) -> int:
    return (
        int(row.get("unresolved_obligations", 0))
        + (0 if row.get("validation_passed") is True else 1)
        + (0 if row.get("parsed") is True else 1)
        + int(row.get("retries", 0))
        + int(row.get("queue_pressure", 0))
    )


def condition_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    task_count = len(rows)
    closed = sum(1 for row in rows if row.get("closed") is True)
    debt_auc = sum(task_debt(row) for row in rows)
    active_ids = sorted(
        {
            str(mutation_id)
            for row in rows
            for mutation_id in row.get("active_mutation_ids", [])
        }
    )
    return {
        "task_count": task_count,
        "closed": closed,
        "closure_rate_bps": int(round(10000 * closed / task_count)) if task_count else 0,
        "operational_debt_auc": debt_auc,
        "validation_failures": sum(1 for row in rows if row.get("validation_passed") is not True),
        "parse_failures": sum(1 for row in rows if row.get("parsed") is not True),
        "retries": sum(int(row.get("retries", 0)) for row in rows),
        "unresolved_obligations": sum(int(row.get("unresolved_obligations", 0)) for row in rows),
        "attempts": sum(int(row.get("attempts", 0)) for row in rows),
        "char_budget": sum(
            int(row.get("prompt_chars", 0)) + int(row.get("output_chars", 0)) for row in rows
        ),
        "active_mutation_ids": active_ids,
        "active_mutation_epoch_count": len(
            {
                int(row.get("epoch", 0))
                for row in rows
                if row.get("active_mutation_ids")
            }
        ),
        "hard_floor_regression_count": sum(int(row.get("hard_floor_regression", 0)) for row in rows),
    }


def paired_task_effects(
    rows: list[dict[str, Any]],
    *,
    candidate_condition: str,
    baseline_condition: str = "baseline_fixed",
) -> dict[str, Any]:
    by_key = {
        (str(row.get("seed", "single")), str(row.get("task_id")), str(row.get("condition"))): row
        for row in rows
    }
    deltas: list[dict[str, Any]] = []
    for row in rows:
        if row.get("condition") != baseline_condition:
            continue
        key = (str(row.get("seed", "single")), str(row.get("task_id")), candidate_condition)
        candidate = by_key.get(key)
        if candidate is None:
            continue
        deltas.append(
            {
                "seed": str(row.get("seed", "single")),
                "task_id": str(row.get("task_id")),
                "epoch": int(row.get("epoch", 0)),
                "phase": str(row.get("phase", "")),
                "candidate_condition": candidate_condition,
                "baseline_condition": baseline_condition,
                "debt_delta": task_debt(candidate) - task_debt(row),
                "closure_delta": int(candidate.get("closed") is True) - int(row.get("closed") is True),
                "validation_failure_delta": int(candidate.get("validation_passed") is not True)
                - int(row.get("validation_passed") is not True),
                "parse_failure_delta": int(candidate.get("parsed") is not True)
                - int(row.get("parsed") is not True),
                "retry_delta": int(candidate.get("retries", 0)) - int(row.get("retries", 0)),
            }
        )
    return {
        "candidate_condition": candidate_condition,
        "baseline_condition": baseline_condition,
        "paired_task_count": len(deltas),
        "debt_auc_delta": sum(int(row["debt_delta"]) for row in deltas),
        "closure_delta": sum(int(row["closure_delta"]) for row in deltas),
        "validation_failure_delta": sum(int(row["validation_failure_delta"]) for row in deltas),
        "parse_failure_delta": sum(int(row["parse_failure_delta"]) for row in deltas),
        "retry_delta": sum(int(row["retry_delta"]) for row in deltas),
        "bootstrap_ci": bootstrap_delta_ci([int(row["debt_delta"]) for row in deltas]),
        "rows": deltas,
    }


def bootstrap_delta_ci(deltas: list[int], *, samples: int = 1000) -> dict[str, Any]:
    if not deltas:
        return {"samples": 0, "debt_auc_delta_ci": [0, 0]}
    rng = random.Random(20260509)
    totals: list[int] = []
    for _ in range(samples):
        totals.append(sum(deltas[rng.randrange(len(deltas))] for _ in deltas))
    totals.sort()
    return {
        "samples": samples,
        "debt_auc_delta_ci": [totals[int(samples * 0.025)], totals[int(samples * 0.975)]],
    }


def reduction_bps(*, baseline_auc: int, candidate_auc: int) -> int:
    if baseline_auc <= 0:
        return 0
    return int(round(10000 * (baseline_auc - candidate_auc) / baseline_auc))


def classify_effect(
    *,
    summaries: dict[str, dict[str, Any]],
    comparisons: dict[str, dict[str, Any]],
    mechanism: dict[str, Any],
    min_active_seeds: int,
    min_meaningful_bps: int,
    confirmed_bps: int,
) -> str:
    mechanism_status = str(mechanism.get("status", "invalid_run"))
    if mechanism_status in {
        "workload_not_sensitive",
        "promotion_mechanism_failure",
        "invalid_run",
    }:
        return mechanism_status
    if mechanism_status != "mechanism_qualified":
        return "invalid_run"

    adaptive = summaries.get("oasg_adaptive", {})
    baseline = summaries.get("baseline_fixed", {})
    active_seed_count = int(mechanism.get("active_seed_count", 0))
    if active_seed_count < min_active_seeds:
        return "promotion_mechanism_failure"
    if int(adaptive.get("hard_floor_regression_count", 0)) > 0:
        return "regression_observed"
    if int(adaptive.get("unresolved_obligations", 0)) > int(
        baseline.get("unresolved_obligations", 0)
    ):
        return "regression_observed"

    baseline_auc = int(baseline.get("operational_debt_auc", 0))
    adaptive_auc = int(adaptive.get("operational_debt_auc", 0))
    effect_bps = reduction_bps(baseline_auc=baseline_auc, candidate_auc=adaptive_auc)
    paired = comparisons.get("oasg_adaptive_vs_baseline", {})
    ci = paired.get("bootstrap_ci", {}).get("debt_auc_delta_ci", [0, 0])
    ci_upper = int(ci[1]) if isinstance(ci, list) and len(ci) > 1 else 0
    meaningful_delta = -int(round(baseline_auc * min_meaningful_bps / 10000))
    if effect_bps >= confirmed_bps and ci_upper < meaningful_delta:
        return "oasg_effect_confirmed"
    if effect_bps < min_meaningful_bps and ci_upper > meaningful_delta:
        return "no_practical_oasg_effect"
    return "no_practical_oasg_effect"


def rows_from_condition_dir(condition_dir: Path, *, seed: int | str | None = None) -> list[dict[str, Any]]:
    path = condition_dir / "task_results.json"
    if not path.exists():
        return []
    data = read_json(path)
    rows = [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []
    if seed is not None:
        for row in rows:
            row.setdefault("seed", str(seed))
    return rows

