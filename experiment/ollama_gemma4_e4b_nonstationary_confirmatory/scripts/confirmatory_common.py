"""Shared helpers for the nonstationary confirmatory experiment."""

from __future__ import annotations

import csv
import json
import random
from pathlib import Path
from typing import Any, Iterable


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

REQUIRED_VARIANTS = (
    "full_drift_confirmatory",
    "no_mixed_reversion_ablation",
    "mixed_reversion_only_probe",
    "delayed_drift_recovery",
)

MIXED_CATEGORIES = {"mixed"}


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
    active_retirement_ids = sorted(
        mutation_id
        for mutation_id in active_ids
        if "policy_retirement" in mutation_id or "policy_tightening" in mutation_id
    )
    cost_units = sum(task_cost_units(row) for row in rows)
    return {
        "task_count": task_count,
        "closed": closed,
        "closure_rate_bps": int(round(10000 * closed / task_count)) if task_count else 0,
        "operational_debt_auc": sum(task_debt(row) for row in rows),
        "cost_units": cost_units,
        "cost_to_close_units": cost_units,
        "closure_adjusted_cost_units": cost_units + (task_count - closed) * 10000,
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
        "active_retirement_ids": active_retirement_ids,
        "retirement_count": len(active_retirement_ids),
        "hard_floor_regression_count": sum(int(row.get("hard_floor_regression", 0)) for row in rows),
        "rollback_failures": sum(int(row.get("rollback_failure", 0)) for row in rows),
        "evidence_gap": sum(int(row.get("evidence_gap", 0)) for row in rows),
        "rollback_gap": sum(int(row.get("rollback_gap", 0)) for row in rows),
    }


def reduction_bps(*, baseline: int, candidate: int) -> int:
    if baseline <= 0:
        return 0
    return int(round(10000 * (baseline - candidate) / baseline))


def bootstrap_delta_ci(
    deltas: list[int], *, samples: int = 1000, seed: int = 20260513
) -> dict[str, Any]:
    if not deltas:
        return {"samples": 0, "delta_ci": [0, 0]}
    rng = random.Random(seed)
    totals = [sum(deltas[rng.randrange(len(deltas))] for _ in deltas) for _ in range(samples)]
    totals.sort()
    lower_index = max(0, min(samples - 1, int(samples * 0.025)))
    upper_index = max(0, min(samples - 1, int(samples * 0.975)))
    return {"samples": samples, "delta_ci": [totals[lower_index], totals[upper_index]]}


def post_drift_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if row.get("phase_role") == "post_drift"
        and row.get("condition") in MAIN_CONDITIONS
    ]


def paired_task_effects(
    rows: list[dict[str, Any]],
    *,
    candidate_condition: str,
    baseline_condition: str,
    bootstrap_samples: int,
    bootstrap_seed: int,
    filters: dict[str, set[str]] | None = None,
) -> dict[str, Any]:
    source = [row for row in rows if _row_matches(row, filters)]
    by_key = {
        (
            str(row.get("variant_id", "")),
            str(row.get("seed", "")),
            str(row.get("task_id", "")),
            str(row.get("condition", "")),
        ): row
        for row in source
    }
    deltas: list[dict[str, Any]] = []
    baseline_debt_total = 0
    candidate_debt_total = 0
    baseline_cost_total = 0
    candidate_cost_total = 0
    for baseline in source:
        if baseline.get("condition") != baseline_condition:
            continue
        key = (
            str(baseline.get("variant_id", "")),
            str(baseline.get("seed", "")),
            str(baseline.get("task_id", "")),
            candidate_condition,
        )
        candidate = by_key.get(key)
        if candidate is None:
            continue
        baseline_debt = task_debt(baseline)
        candidate_debt = task_debt(candidate)
        baseline_cost = task_cost_units(baseline)
        candidate_cost = task_cost_units(candidate)
        baseline_debt_total += baseline_debt
        candidate_debt_total += candidate_debt
        baseline_cost_total += baseline_cost
        candidate_cost_total += candidate_cost
        deltas.append(
            {
                "variant_id": str(baseline.get("variant_id", "")),
                "seed": str(baseline.get("seed", "")),
                "phase_id": str(baseline.get("phase_id", "")),
                "phase_category": str(baseline.get("phase_category", "")),
                "phase_role": str(baseline.get("phase_role", "")),
                "task_id": str(baseline.get("task_id", "")),
                "epoch": int(baseline.get("epoch", 0)),
                "candidate_condition": candidate_condition,
                "baseline_condition": baseline_condition,
                "baseline_debt": baseline_debt,
                "candidate_debt": candidate_debt,
                "baseline_cost": baseline_cost,
                "candidate_cost": candidate_cost,
                "debt_delta": candidate_debt - baseline_debt,
                "cost_delta": candidate_cost - baseline_cost,
                "closure_delta": int(candidate.get("closed") is True)
                - int(baseline.get("closed") is True),
                "validation_failure_delta": int(candidate.get("validation_passed") is not True)
                - int(baseline.get("validation_passed") is not True),
                "parse_failure_delta": int(candidate.get("parsed") is not True)
                - int(baseline.get("parsed") is not True),
                "retry_delta": int(candidate.get("retries", 0)) - int(baseline.get("retries", 0)),
            }
        )
    debt_deltas = [int(row["debt_delta"]) for row in deltas]
    cost_deltas = [int(row["cost_delta"]) for row in deltas]
    closure_deltas = [int(row["closure_delta"]) for row in deltas]
    return {
        "candidate_condition": candidate_condition,
        "baseline_condition": baseline_condition,
        "paired_task_count": len(deltas),
        "baseline_debt_auc": baseline_debt_total,
        "candidate_debt_auc": candidate_debt_total,
        "baseline_cost_units": baseline_cost_total,
        "candidate_cost_units": candidate_cost_total,
        "debt_reduction_bps": reduction_bps(
            baseline=baseline_debt_total, candidate=candidate_debt_total
        ),
        "cost_regression_bps": -reduction_bps(
            baseline=baseline_cost_total, candidate=candidate_cost_total
        ),
        "debt_auc_delta": sum(debt_deltas),
        "cost_to_close_delta": sum(cost_deltas),
        "closure_delta": sum(closure_deltas),
        "validation_failure_delta": sum(int(row["validation_failure_delta"]) for row in deltas),
        "parse_failure_delta": sum(int(row["parse_failure_delta"]) for row in deltas),
        "retry_delta": sum(int(row["retry_delta"]) for row in deltas),
        "debt_bootstrap_ci": bootstrap_delta_ci(
            debt_deltas, samples=bootstrap_samples, seed=bootstrap_seed
        ),
        "cost_bootstrap_ci": bootstrap_delta_ci(
            cost_deltas, samples=bootstrap_samples, seed=bootstrap_seed + 1
        ),
        "closure_bootstrap_ci": bootstrap_delta_ci(
            closure_deltas, samples=bootstrap_samples, seed=bootstrap_seed + 2
        ),
        "rows": deltas,
    }


def classify_confirmatory(
    *,
    summaries: dict[str, dict[str, Any]],
    comparisons: dict[str, dict[str, Any]],
    ablations: dict[str, dict[str, Any]],
    drift_class_effects: dict[str, dict[str, Any]] | None = None,
    oracle_headroom: dict[str, Any],
    active_seed_count: int,
    stable_a2_active_mutations: int,
    verification_status: str,
    completed_variants: set[str],
    config: dict[str, Any],
    interrupted: bool,
) -> str:
    if verification_status != "ok":
        return "inconclusive_invalid_ledgers"
    primary = comparisons.get("oasg_vs_strong_static", {})
    if interrupted or int(primary.get("paired_task_count", 0)) <= 0:
        return "interrupted_before_primary_evaluation"
    required = set(config.get("required_variants", REQUIRED_VARIANTS))
    if (
        completed_variants != required
        or int(primary.get("paired_task_count", 0)) < int(config.get("minimum_paired_task_count", 1))
        or not bool(config.get("allow_effect_claim", False))
    ):
        return "inconclusive_insufficient_power"
    if oracle_headroom.get("status") != "oracle_headroom_present":
        return "oracle_headroom_absent"

    strong = summaries.get("strong_static_calibrated", {})
    adaptive = summaries.get("oasg_adaptive_from_strong", {})
    if int(adaptive.get("hard_floor_regression_count", 0)) > int(
        strong.get("hard_floor_regression_count", 0)
    ):
        return "no_incremental_effect_under_drift"

    strong_debt = int(strong.get("operational_debt_auc", 0))
    adaptive_debt = int(adaptive.get("operational_debt_auc", 0))
    debt_reduction = reduction_bps(baseline=strong_debt, candidate=adaptive_debt)
    primary_ci_upper = _ci_upper(primary)
    strong_cost = int(strong.get("cost_to_close_units", 0))
    adaptive_cost = int(adaptive.get("cost_to_close_units", 0))
    cost_regression_bps = -reduction_bps(baseline=strong_cost, candidate=adaptive_cost)
    cost_ci_regression_bps = _cost_ci_upper_regression_bps(primary)

    if debt_reduction > 0 and (
        cost_regression_bps
        > int(config.get("cost_regression_tolerance_bps", 1000))
        or cost_ci_regression_bps > int(config.get("cost_regression_tolerance_bps", 1000))
    ):
        return "inconclusive_cost_regression"

    observe = comparisons.get("oasg_vs_observe_only", {})
    rule = comparisons.get("oasg_vs_rule_adaptive", {})
    if debt_reduction >= int(config.get("control_support_min_reduction_bps", 500)):
        if int(observe.get("debt_auc_delta", 0)) >= 0:
            return "observe_only_explains_effect"
        if int(rule.get("debt_auc_delta", 0)) >= 0:
            return "rule_adaptive_explains_effect"

    if debt_reduction <= 0 or int(primary.get("debt_auc_delta", 0)) >= 0:
        return "no_incremental_effect_under_drift"

    no_phase_d = ablations.get("no_phase_d", {})
    mixed_only = ablations.get("mixed_only", {})
    structural_only = ablations.get("structural_only", {})
    mild_only = ablations.get("mild_only", {})
    no_phase_d_reduction = int(no_phase_d.get("debt_reduction_bps", 0))
    mixed_reduction = int(mixed_only.get("debt_reduction_bps", 0))
    structural_reduction = int(structural_only.get("debt_reduction_bps", 0))
    mild_reduction = int(mild_only.get("debt_reduction_bps", 0))
    support_threshold = int(config.get("control_support_min_reduction_bps", 500))
    full_threshold = int(config.get("post_drift_effect_min_reduction_bps", 1500))
    min_active = int(config.get("confirmatory_min_active_seeds", 4))

    no_phase_d_supported = (
        no_phase_d_reduction >= support_threshold and _ci_upper(no_phase_d) <= 0
    )
    structural_supported = (
        structural_reduction >= support_threshold
        and _ci_upper(structural_only) <= 0
        and _oracle_class_present(oracle_headroom, "structural")
    )
    mild_supported = (
        mild_reduction >= support_threshold
        and _ci_upper(mild_only) <= 0
        and _oracle_class_present(oracle_headroom, "mild")
    )
    mixed_supported = (
        mixed_reduction >= support_threshold
        and _ci_upper(mixed_only) <= 0
        and _oracle_class_present(oracle_headroom, "mixed")
    )

    if mixed_supported and not structural_supported:
        if debt_reduction >= full_threshold and primary_ci_upper < 0:
            return "oasg_nonstationary_phase_specific_support"
        return "mixed_reversion_only_effect"
    if structural_supported and not mixed_supported:
        return "no_mixed_reversion_support"
    if (
        debt_reduction >= full_threshold
        and primary_ci_upper < 0
        and active_seed_count >= min_active
        and stable_a2_active_mutations == 0
        and no_phase_d_supported
        and structural_supported
        and mixed_supported
    ):
        return "oasg_nonstationary_confirmed"
    if debt_reduction >= support_threshold and (
        structural_supported or mixed_supported or mild_supported
    ):
        return "oasg_nonstationary_phase_specific_support"
    return "no_incremental_effect_under_drift"


def adaptation_lag(rows: list[dict[str, Any]]) -> dict[str, int | None]:
    lags: dict[str, int | None] = {}
    for variant_id in sorted({str(row.get("variant_id", "")) for row in rows}):
        phase_ids = sorted(
            {
                str(row.get("phase_id", ""))
                for row in rows
                if row.get("variant_id") == variant_id and row.get("phase_role") == "post_drift"
            }
        )
        for phase_id in phase_ids:
            phase_rows = [
                row
                for row in rows
                if row.get("condition") == "oasg_adaptive_from_strong"
                and row.get("variant_id") == variant_id
                and row.get("phase_id") == phase_id
            ]
            epochs = sorted({int(row.get("epoch", 0)) for row in phase_rows})
            lag: int | None = None
            for offset, epoch in enumerate(epochs):
                if any(
                    row.get("active_mutation_ids")
                    for row in phase_rows
                    if int(row.get("epoch", 0)) == epoch
                ):
                    lag = offset
                    break
            lags[f"{variant_id}:{phase_id}"] = lag
    return lags


def rows_from_condition_dir(condition_dir: Path, *, seed: str, variant_id: str) -> list[dict[str, Any]]:
    path = condition_dir / "task_results.json"
    if not path.exists():
        return []
    rows = read_json(path)
    assert isinstance(rows, list)
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            row.setdefault("seed", seed)
            row.setdefault("variant_id", variant_id)
            normalized.append(row)
    return normalized


def compact_comparison(comparison: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in comparison.items() if key != "rows"}


def _row_matches(row: dict[str, Any], filters: dict[str, set[str]] | None) -> bool:
    if filters is None:
        return True
    return all(str(row.get(key, "")) in allowed for key, allowed in filters.items())


def _ci_upper(comparison: dict[str, Any]) -> int:
    ci = comparison.get("debt_bootstrap_ci", {}).get("delta_ci", [0, 0])
    if isinstance(ci, list) and len(ci) > 1:
        return int(ci[1])
    return 0


def _cost_ci_upper_regression_bps(comparison: dict[str, Any]) -> int:
    baseline = int(comparison.get("baseline_cost_units", 0))
    if baseline <= 0:
        return 0
    ci = comparison.get("cost_bootstrap_ci", {}).get("delta_ci", [0, 0])
    if isinstance(ci, list) and len(ci) > 1:
        return int(round(10000 * max(0, int(ci[1])) / baseline))
    return max(0, int(comparison.get("cost_regression_bps", 0)))


def _oracle_class_present(oracle_headroom: dict[str, Any], drift_class: str) -> bool:
    by_class = oracle_headroom.get("oracle_headroom_by_drift_class")
    if not isinstance(by_class, dict):
        return oracle_headroom.get("status") == "oracle_headroom_present"
    item = by_class.get(drift_class, {})
    return item.get("status") == "oracle_headroom_present"
