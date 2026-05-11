"""Shared helpers for the strong-baseline v2 experiment."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
V1 = ROOT / "experiment" / "ollama_gemma4_e4b_strong_baseline" / "scripts"
for import_path in (V1, ROOT):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from strong_common import (  # type: ignore  # noqa: E402
    bootstrap_delta_ci,
    read_json,
    reduction_bps,
    task_debt,
)


CONDITIONS = (
    "strong_static_calibrated",
    "strong_rule_adaptive_control",
    "strong_positive_control",
    "oasg_adaptive_from_strong",
)


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


def task_cost_units(row: dict[str, Any]) -> int:
    """Pre-registered cost-to-close proxy for v2.

    Attempts dominate, then prompt/output characters, then coarse latency units.
    """

    return (
        int(row.get("attempts", 0)) * 1000
        + int(row.get("prompt_chars", 0))
        + int(row.get("output_chars", 0))
        + int(row.get("latency_ms", 0)) // 10
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
        "cost_to_close_units": sum(task_cost_units(row) for row in rows),
        "validation_failures": sum(1 for row in rows if row.get("validation_passed") is not True),
        "parse_failures": sum(1 for row in rows if row.get("parsed") is not True),
        "retries": sum(int(row.get("retries", 0)) for row in rows),
        "unresolved_obligations": sum(int(row.get("unresolved_obligations", 0)) for row in rows),
        "attempts": sum(int(row.get("attempts", 0)) for row in rows),
        "char_budget": sum(
            int(row.get("prompt_chars", 0)) + int(row.get("output_chars", 0)) for row in rows
        ),
        "latency_ms": sum(int(row.get("latency_ms", 0)) for row in rows),
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


def cost_reduction_bps(*, baseline_cost: int, candidate_cost: int) -> int:
    if baseline_cost <= 0:
        return 0
    return int(round(10000 * (baseline_cost - candidate_cost) / baseline_cost))


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
                "cost_delta": task_cost_units(candidate) - task_cost_units(baseline),
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
        "cost_to_close_delta": sum(int(row["cost_delta"]) for row in deltas),
        "closure_delta": sum(int(row["closure_delta"]) for row in deltas),
        "validation_failure_delta": sum(int(row["validation_failure_delta"]) for row in deltas),
        "parse_failure_delta": sum(int(row["parse_failure_delta"]) for row in deltas),
        "retry_delta": sum(int(row["retry_delta"]) for row in deltas),
        "debt_bootstrap_ci": bootstrap_delta_ci([int(row["debt_delta"]) for row in deltas]),
        "cost_bootstrap_ci": bootstrap_delta_ci([int(row["cost_delta"]) for row in deltas]),
        "rows": deltas,
    }


def classify_strong_v2(
    *,
    summaries: dict[str, dict[str, Any]],
    comparisons: dict[str, dict[str, Any]],
    strong_qualification: dict[str, Any],
    headroom: dict[str, Any],
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
    if headroom.get("status") == "no_incremental_headroom":
        return "strong_baseline_ceiling_no_headroom"
    if headroom.get("status") not in {"debt_headroom_exists", "efficiency_headroom_exists"}:
        return "strong_baseline_ceiling_no_headroom"
    if readiness.get("status") != "adaptive_from_strong_ready":
        return "promotion_mechanism_failure_vs_strong_baseline"

    adaptive = summaries.get("oasg_adaptive_from_strong", {})
    strong = summaries.get("strong_static_calibrated", {})
    if int(adaptive.get("hard_floor_regression_count", 0)) > 0:
        return "regression_observed"
    if int(adaptive.get("rollback_failures", 0)) > int(strong.get("rollback_failures", 0)):
        return "regression_observed"

    active_seed_count = int(readiness.get("active_seed_count", 0))
    required = int(config.get("confirmatory_min_active_seeds", 4))
    if active_seed_count < required:
        return "promotion_mechanism_failure_vs_strong_baseline"

    strong_auc = int(strong.get("operational_debt_auc", 0))
    adaptive_auc = int(adaptive.get("operational_debt_auc", 0))
    debt_effect = reduction_bps(baseline_auc=strong_auc, candidate_auc=adaptive_auc)
    paired = comparisons.get("oasg_vs_strong_static", {})
    debt_ci = paired.get("debt_bootstrap_ci", {}).get("debt_auc_delta_ci", [0, 0])
    debt_ci_upper = int(debt_ci[1]) if isinstance(debt_ci, list) and len(debt_ci) > 1 else 0
    min_debt_delta = -int(round(strong_auc * int(config.get("minimum_incremental_reduction_bps", 500)) / 10000))
    if (
        debt_effect >= int(config.get("debt_effect_confirmed_min_reduction_bps", 1000))
        and debt_ci_upper < min_debt_delta
    ):
        return "oasg_debt_effect_confirmed_vs_strong_baseline"

    strong_cost = int(strong.get("cost_to_close_units", 0))
    adaptive_cost = int(adaptive.get("cost_to_close_units", 0))
    cost_effect = cost_reduction_bps(baseline_cost=strong_cost, candidate_cost=adaptive_cost)
    cost_ci = paired.get("cost_bootstrap_ci", {}).get("debt_auc_delta_ci", [0, 0])
    cost_ci_upper = int(cost_ci[1]) if isinstance(cost_ci, list) and len(cost_ci) > 1 else 0
    min_cost_delta = -int(round(strong_cost * int(config.get("minimum_incremental_reduction_bps", 500)) / 10000))
    if (
        adaptive_auc <= strong_auc
        and int(adaptive.get("closed", 0)) >= int(strong.get("closed", 0))
        and cost_effect >= int(config.get("cost_effect_confirmed_min_reduction_bps", 1000))
        and cost_ci_upper < min_cost_delta
    ):
        return "oasg_efficiency_effect_confirmed_vs_strong_baseline"
    return "no_incremental_effect_vs_strong_baseline"


def rule_baseline_sufficient(comparisons: dict[str, dict[str, Any]]) -> bool:
    rule = comparisons.get("oasg_vs_rule_adaptive", {})
    return int(rule.get("debt_auc_delta", 0)) >= 0 and int(rule.get("cost_to_close_delta", 0)) >= 0


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
