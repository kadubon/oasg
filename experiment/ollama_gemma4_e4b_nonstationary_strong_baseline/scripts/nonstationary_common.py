"""Shared helpers for the nonstationary strong-baseline experiment."""

from __future__ import annotations

import csv
import json
import random
from pathlib import Path
from typing import Any


MAIN_CONDITIONS = (
    "strong_static_calibrated",
    "oasg_observe_only_from_strong",
    "rule_adaptive_control",
    "oasg_adaptive_from_strong",
)

DIAGNOSTIC_CONDITIONS = (
    "weak_fixed",
    "strong_static_oracle_phase_control",
)

ALL_CONDITIONS = MAIN_CONDITIONS + DIAGNOSTIC_CONDITIONS

PHASE_IDS = (
    "phase_a_calibration",
    "phase_b_mild_drift",
    "phase_c_structural_drift",
    "phase_d_mixed_reversion",
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


def task_cost_units(row: dict[str, Any]) -> int:
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
        "active_mutation_count": len(active_ids),
        "active_mutation_epoch_count": len(
            {
                (str(row.get("phase_id", row.get("phase", ""))), int(row.get("epoch", 0)))
                for row in rows
                if row.get("active_mutation_ids")
            }
        ),
        "hard_floor_regression_count": sum(int(row.get("hard_floor_regression", 0)) for row in rows),
        "rollback_failures": sum(int(row.get("rollback_failure", 0)) for row in rows),
        "evidence_gap": sum(int(row.get("evidence_gap", 0)) for row in rows),
        "rollback_gap": sum(int(row.get("rollback_gap", 0)) for row in rows),
    }


def reduction_bps(*, baseline: int, candidate: int) -> int:
    if baseline <= 0:
        return 0
    return int(round(10000 * (baseline - candidate) / baseline))


def bootstrap_delta_ci(deltas: list[int], *, samples: int = 1000) -> dict[str, Any]:
    if not deltas:
        return {"samples": 0, "delta_ci": [0, 0]}
    rng = random.Random(20260513)
    totals = [sum(deltas[rng.randrange(len(deltas))] for _ in deltas) for _ in range(samples)]
    totals.sort()
    return {"samples": samples, "delta_ci": [totals[int(samples * 0.025)], totals[int(samples * 0.975)]]}


def paired_task_effects(
    rows: list[dict[str, Any]],
    *,
    candidate_condition: str,
    baseline_condition: str,
    post_drift_only: bool = True,
) -> dict[str, Any]:
    source = [
        row
        for row in rows
        if not post_drift_only or row.get("phase_id", row.get("phase")) != "phase_a_calibration"
    ]
    by_key = {
        (str(row.get("seed", "single")), str(row.get("task_id")), str(row.get("condition"))): row
        for row in source
    }
    deltas: list[dict[str, Any]] = []
    for baseline in source:
        if baseline.get("condition") != baseline_condition:
            continue
        key = (str(baseline.get("seed", "single")), str(baseline.get("task_id")), candidate_condition)
        candidate = by_key.get(key)
        if candidate is None:
            continue
        deltas.append(
            {
                "seed": str(baseline.get("seed", "single")),
                "phase_id": str(baseline.get("phase_id", baseline.get("phase", ""))),
                "task_id": str(baseline.get("task_id")),
                "epoch": int(baseline.get("epoch", 0)),
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
        "closure_bootstrap_ci": bootstrap_delta_ci([int(row["closure_delta"]) for row in deltas]),
        "rows": deltas,
    }


def classify_nonstationary(
    *,
    summaries: dict[str, dict[str, Any]],
    comparisons: dict[str, dict[str, Any]],
    oracle_headroom: dict[str, Any],
    readiness: dict[str, Any],
    verification_status: str,
    config: dict[str, Any],
) -> str:
    if verification_status != "ok":
        return "inconclusive_invalid_ledgers"
    primary = comparisons.get("oasg_vs_strong_static", {})
    if int(primary.get("paired_task_count", 0)) <= 0:
        return "interrupted_before_primary_evaluation"
    if oracle_headroom.get("status") != "oracle_headroom_present":
        return "oracle_headroom_absent"
    if readiness.get("status") != "adaptive_readiness_passed":
        return "adaptive_readiness_failed"

    adaptive = summaries.get("oasg_adaptive_from_strong", {})
    strong = summaries.get("strong_static_calibrated", {})
    if int(adaptive.get("hard_floor_regression_count", 0)) > int(
        strong.get("hard_floor_regression_count", 0)
    ):
        return "no_incremental_effect_under_drift"

    strong_debt = int(strong.get("operational_debt_auc", 0))
    adaptive_debt = int(adaptive.get("operational_debt_auc", 0))
    debt_reduction = reduction_bps(baseline=strong_debt, candidate=adaptive_debt)
    debt_ci = primary.get("debt_bootstrap_ci", {}).get("delta_ci", [0, 0])
    debt_ci_upper = int(debt_ci[1]) if isinstance(debt_ci, list) and len(debt_ci) > 1 else 0

    strong_cost = int(strong.get("cost_to_close_units", 0))
    adaptive_cost = int(adaptive.get("cost_to_close_units", 0))
    cost_regression = -reduction_bps(baseline=strong_cost, candidate=adaptive_cost)
    if debt_reduction > 0 and cost_regression > int(config.get("cost_regression_tolerance_bps", 1000)):
        return "inconclusive_cost_regression"

    rule = comparisons.get("oasg_vs_rule_adaptive", {})
    if debt_reduction >= int(config.get("minimum_partial_debt_reduction_bps", 500)) and int(
        rule.get("debt_auc_delta", 0)
    ) >= 0:
        return "rule_adaptive_explains_effect"
    if (
        debt_reduction >= int(config.get("post_drift_effect_min_reduction_bps", 1500))
        and debt_ci_upper < 0
        and int(rule.get("debt_auc_delta", 0)) < 0
    ):
        return "oasg_nonstationary_effect_confirmed_timeboxed"
    if debt_reduction >= int(config.get("minimum_partial_debt_reduction_bps", 500)):
        return "partial_nonstationary_support"
    return "no_incremental_effect_under_drift"


def adaptation_lag(rows: list[dict[str, Any]]) -> dict[str, int | None]:
    lags: dict[str, int | None] = {}
    for phase_id in PHASE_IDS[1:]:
        phase_rows = [
            row
            for row in rows
            if row.get("condition") == "oasg_adaptive_from_strong" and row.get("phase_id") == phase_id
        ]
        epochs = sorted({int(row.get("epoch", 0)) for row in phase_rows})
        lag: int | None = None
        for offset, epoch in enumerate(epochs):
            if any(row.get("active_mutation_ids") for row in phase_rows if int(row.get("epoch", 0)) == epoch):
                lag = offset
                break
        lags[phase_id] = lag
    return lags


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
