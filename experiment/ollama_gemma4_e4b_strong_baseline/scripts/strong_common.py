"""Shared helpers for the strong-baseline OASG experiment."""

from __future__ import annotations

import csv
import json
import random
from pathlib import Path
from typing import Any

CONDITIONS = (
    "weak_fixed",
    "observe_only",
    "strong_static_calibrated",
    "strong_rule_adaptive_control",
    "oasg_adaptive_from_strong",
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
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def task_debt(row: dict[str, Any]) -> int:
    return (
        int(row.get("unresolved_obligations", 0))
        + int(row.get("validation_passed") is not True)
        + int(row.get("parsed") is not True)
        + int(row.get("retries", 0))
        + int(row.get("queue_pressure", 0))
        + int(row.get("rollback_gap", 0))
        + int(row.get("evidence_gap", 0))
    )


def condition_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    task_count = len(rows)
    closed = sum(1 for row in rows if row.get("closed") is True)
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
        "operational_debt_auc": sum(task_debt(row) for row in rows),
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
        "rollback_failures": sum(int(row.get("rollback_failure", 0)) for row in rows),
    }


def reduction_bps(*, baseline_auc: int, candidate_auc: int) -> int:
    if baseline_auc <= 0:
        return 0
    return int(round(10000 * (baseline_auc - candidate_auc) / baseline_auc))


def bootstrap_delta_ci(deltas: list[int], *, samples: int = 1000) -> dict[str, Any]:
    if not deltas:
        return {"samples": 0, "debt_auc_delta_ci": [0, 0]}
    rng = random.Random(20260511)
    totals = [sum(deltas[rng.randrange(len(deltas))] for _ in deltas) for _ in range(samples)]
    totals.sort()
    return {
        "samples": samples,
        "debt_auc_delta_ci": [totals[int(samples * 0.025)], totals[int(samples * 0.975)]],
    }


def paired_task_effects(
    rows: list[dict[str, Any]],
    *,
    candidate_condition: str,
    baseline_condition: str,
) -> dict[str, Any]:
    by_key = {
        (str(row.get("seed", "single")), str(row.get("task_id")), str(row.get("condition"))): row
        for row in rows
    }
    deltas: list[dict[str, Any]] = []
    for baseline in rows:
        if baseline.get("condition") != baseline_condition:
            continue
        key = (str(baseline.get("seed", "single")), str(baseline.get("task_id")), candidate_condition)
        candidate = by_key.get(key)
        if candidate is None:
            continue
        deltas.append(
            {
                "seed": str(baseline.get("seed", "single")),
                "task_id": str(baseline.get("task_id")),
                "epoch": int(baseline.get("epoch", 0)),
                "phase": str(baseline.get("phase", "")),
                "candidate_condition": candidate_condition,
                "baseline_condition": baseline_condition,
                "debt_delta": task_debt(candidate) - task_debt(baseline),
                "closure_delta": int(candidate.get("closed") is True)
                - int(baseline.get("closed") is True),
                "validation_failure_delta": int(candidate.get("validation_passed") is not True)
                - int(baseline.get("validation_passed") is not True),
                "parse_failure_delta": int(candidate.get("parsed") is not True)
                - int(baseline.get("parsed") is not True),
                "retry_delta": int(candidate.get("retries", 0)) - int(baseline.get("retries", 0)),
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


def classify_strong_baseline(
    *,
    summaries: dict[str, dict[str, Any]],
    comparisons: dict[str, dict[str, Any]],
    strong_qualification: dict[str, Any],
    readiness: dict[str, Any],
    seed_count: int,
    config: dict[str, Any],
    verification_status: str,
) -> str:
    if verification_status != "ok":
        return "invalid_run"
    if seed_count < int(config.get("confirmatory_min_active_seeds", 4)):
        return "exploratory_only"
    if strong_qualification.get("status") != "strong_baseline_qualified":
        return "workload_not_sensitive"
    if readiness.get("status") != "adaptive_from_strong_ready":
        return "promotion_mechanism_failure_vs_strong_baseline"

    adaptive = summaries.get("oasg_adaptive_from_strong", {})
    strong = summaries.get("strong_static_calibrated", {})
    if int(adaptive.get("hard_floor_regression_count", 0)) > 0:
        return "regression_observed"
    if int(adaptive.get("rollback_failures", 0)) > int(strong.get("rollback_failures", 0)):
        return "regression_observed"

    active_seed_count = int(readiness.get("active_seed_count", 0))
    if active_seed_count < int(config.get("confirmatory_min_active_seeds", 4)):
        return "promotion_mechanism_failure_vs_strong_baseline"

    strong_auc = int(strong.get("operational_debt_auc", 0))
    adaptive_auc = int(adaptive.get("operational_debt_auc", 0))
    effect_bps = reduction_bps(baseline_auc=strong_auc, candidate_auc=adaptive_auc)
    paired = comparisons.get("oasg_vs_strong_static", {})
    ci = paired.get("bootstrap_ci", {}).get("debt_auc_delta_ci", [0, 0])
    ci_upper = int(ci[1]) if isinstance(ci, list) and len(ci) > 1 else 0
    min_delta = -int(round(strong_auc * int(config.get("minimum_incremental_reduction_bps", 500)) / 10000))
    rule = comparisons.get("oasg_vs_rule_adaptive", {})
    rule_delta = int(rule.get("debt_auc_delta", 0))

    if effect_bps >= int(config.get("minimum_incremental_reduction_bps", 500)) and rule_delta >= 0:
        return "rule_baseline_sufficient"
    if (
        effect_bps >= int(config.get("incremental_effect_confirmed_min_reduction_bps", 1000))
        and ci_upper < min_delta
    ):
        return "oasg_incremental_effect_confirmed_vs_strong_baseline"
    if effect_bps >= int(config.get("minimum_incremental_reduction_bps", 500)):
        return "partial_incremental_support"
    return "no_incremental_effect_vs_strong_baseline"


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
