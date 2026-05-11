"""Analyze the OASG strong-baseline v2 experiment."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for import_path in (Path(__file__).resolve().parent, SRC, ROOT):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from oasg.canonical import receipt_hash  # noqa: E402
from oasg.ledger import verify_jsonl  # noqa: E402
from strong_v2_common import (  # noqa: E402
    CONDITIONS,
    classify_strong_v2,
    condition_summary,
    paired_task_effects,
    read_json,
    rows_from_condition_dir,
    rule_baseline_sufficient,
    write_csv,
    write_json,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    metrics = analyze_run(Path(args.run_dir))
    write_json(out_dir / "metrics.json", metrics)
    write_json(out_dir / "verification.json", metrics["verification"])
    write_json(out_dir / "promotion_diagnostic.json", metrics["promotion_diagnostic"])
    write_csv(out_dir / "epoch_table.csv", metrics["epoch_table"])
    write_csv(out_dir / "seed_table.csv", metrics["seed_table"])
    write_csv(out_dir / "paired_task_table.csv", metrics["paired_task_table"])
    write_json(
        out_dir / "final_strong_v2_classification_receipt.json",
        metrics["final_classification_receipt"],
    )
    (out_dir / "report.md").write_text(_render_report(metrics), encoding="utf-8", newline="\n")
    print(json.dumps({"status": "ok", "classification": metrics["classification"]}, indent=2))
    return 0


def analyze_run(run_dir: Path) -> dict[str, Any]:
    config = _read_optional(run_dir / "config.json", {})
    strong_qualification = _read_optional(
        run_dir / "strong_baseline_qualification_receipt.json",
        {"status": "invalid_run"},
    )
    headroom = _read_optional(
        run_dir / "incremental_headroom_receipt.json",
        {"status": "no_incremental_headroom", "qualified_candidates": []},
    )
    readiness = _read_optional(
        run_dir / "adaptive_readiness_from_strong_receipt.json",
        {"status": "promotion_mechanism_failure_vs_strong_baseline", "active_seed_count": 0},
    )
    seed_dirs = sorted(path for path in run_dir.glob("seed_*") if path.is_dir())
    all_rows: list[dict[str, Any]] = []
    ledger_receipts: dict[str, Any] = {}
    for seed_dir in seed_dirs:
        seed = seed_dir.name.replace("seed_", "")
        for condition in CONDITIONS:
            condition_dir = seed_dir / condition
            rows = rows_from_condition_dir(condition_dir, seed=seed)
            all_rows.extend(rows)
            ledger = condition_dir / "history.jsonl"
            if ledger.exists():
                ledger_receipts[f"{seed}:{condition}"] = verify_jsonl(ledger).to_dict()
    eval_rows = [row for row in all_rows if row.get("phase") == "longrun_eval"]
    summaries = {
        condition: condition_summary(
            [row for row in eval_rows if row.get("condition") == condition]
        )
        for condition in CONDITIONS
    }
    comparisons = {
        "oasg_vs_strong_static": paired_task_effects(
            eval_rows,
            candidate_condition="oasg_adaptive_from_strong",
            baseline_condition="strong_static_calibrated",
        ),
        "rule_vs_strong_static": paired_task_effects(
            eval_rows,
            candidate_condition="strong_rule_adaptive_control",
            baseline_condition="strong_static_calibrated",
        ),
        "positive_control_vs_strong_static": paired_task_effects(
            eval_rows,
            candidate_condition="strong_positive_control",
            baseline_condition="strong_static_calibrated",
        ),
        "oasg_vs_rule_adaptive": paired_task_effects(
            eval_rows,
            candidate_condition="oasg_adaptive_from_strong",
            baseline_condition="strong_rule_adaptive_control",
        ),
    }
    verification = _verification_receipt(
        ledger_receipts=ledger_receipts,
        comparisons=comparisons,
        readiness=readiness,
    )
    classification = classify_strong_v2(
        summaries=summaries,
        comparisons=comparisons,
        strong_qualification=strong_qualification,
        headroom=headroom,
        readiness=readiness,
        seed_count=len(config.get("replicate_seeds", [])),
        config=config,
        verification_status=str(verification["status"]),
    )
    compact_comparisons = {
        key: {inner_key: value for inner_key, value in item.items() if inner_key != "rows"}
        for key, item in comparisons.items()
    }
    metrics = {
        "experiment_id": "ollama_gemma4_e4b_strong_baseline_v2",
        "classification": classification,
        "condition_summaries": summaries,
        "comparisons": compact_comparisons,
        "paired_task_table": comparisons["oasg_vs_strong_static"]["rows"],
        "epoch_table": _epoch_table(eval_rows),
        "seed_table": _seed_table(eval_rows),
        "strong_baseline_qualification": strong_qualification,
        "incremental_headroom": headroom,
        "adaptive_readiness_from_strong": readiness,
        "verification": verification,
        "promotion_diagnostic": _promotion_diagnostic(readiness=readiness, headroom=headroom),
        "rule_baseline_sufficient": rule_baseline_sufficient(comparisons),
        "ledger_receipts": ledger_receipts,
        "config_hash": receipt_hash(config),
        "decision_contract": {
            "debt_headroom_min_reduction_bps": int(config.get("debt_headroom_min_reduction_bps", 500)),
            "cost_headroom_min_reduction_bps": int(config.get("cost_headroom_min_reduction_bps", 1000)),
            "confirmatory_min_active_seeds": int(config.get("confirmatory_min_active_seeds", 4)),
        },
    }
    metrics["metrics_hash"] = receipt_hash(
        {
            "classification": classification,
            "summaries": summaries,
            "comparisons": compact_comparisons,
        }
    )
    metrics["final_classification_receipt"] = {
        "receipt_type": "final_strong_v2_classification_receipt",
        "classification": classification,
        "metrics_hash": metrics["metrics_hash"],
        "effect_claim_allowed": classification
        in {
            "oasg_debt_effect_confirmed_vs_strong_baseline",
            "oasg_efficiency_effect_confirmed_vs_strong_baseline",
        },
    }
    return metrics


def _verification_receipt(
    *,
    ledger_receipts: dict[str, Any],
    comparisons: dict[str, dict[str, Any]],
    readiness: dict[str, Any],
) -> dict[str, Any]:
    invalid_ledgers = {
        key: receipt
        for key, receipt in ledger_receipts.items()
        if receipt.get("status") != "ledger_prefix_valid"
    }
    reasons: list[str] = []
    status = "ok"
    if invalid_ledgers:
        status = "invalid_run"
        reasons.append("ledger_verification_failed")
    if (
        readiness.get("status") == "adaptive_from_strong_ready"
        and comparisons.get("oasg_vs_strong_static", {}).get("paired_task_count", 0) == 0
    ):
        status = "invalid_run"
        reasons.append("strong_paired_comparison_missing")
    return {
        "receipt_type": "strong_v2_verification_receipt",
        "status": status,
        "invalid_ledgers": invalid_ledgers,
        "paired_task_count": int(
            comparisons.get("oasg_vs_strong_static", {}).get("paired_task_count", 0)
        ),
        "reasons": reasons,
    }


def _promotion_diagnostic(*, readiness: dict[str, Any], headroom: dict[str, Any]) -> dict[str, Any]:
    active_by_seed = readiness.get("active_changes_by_seed", {})
    active_ids = sorted(
        {
            str(item.get("mutation_id"))
            for changes in active_by_seed.values()
            for item in changes
            if item.get("mutation_id")
        }
    ) if isinstance(active_by_seed, dict) else []
    return {
        "receipt_type": "strong_v2_promotion_diagnostic",
        "status": "active_change_observed" if active_ids else "no_active_change_observed",
        "headroom_status": headroom.get("status", "unknown"),
        "readiness_status": readiness.get("status", "unknown"),
        "active_seed_count": int(readiness.get("active_seed_count", 0)),
        "qualified_candidate_count": int(headroom.get("qualified_candidate_count", 0)),
        "active_mutation_ids": active_ids,
    }


def _seed_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    table: list[dict[str, Any]] = []
    for seed in sorted({str(row.get("seed", "single")) for row in rows}):
        for condition in CONDITIONS:
            subset = [
                row
                for row in rows
                if str(row.get("seed", "single")) == seed and row.get("condition") == condition
            ]
            table.append({"seed": seed, "condition": condition, **condition_summary(subset)})
    return table


def _epoch_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    table: list[dict[str, Any]] = []
    keys = sorted(
        {
            (str(row.get("seed", "single")), str(row.get("condition")), int(row.get("epoch", 0)))
            for row in rows
        }
    )
    for seed, condition, epoch in keys:
        subset = [
            row
            for row in rows
            if str(row.get("seed", "single")) == seed
            and row.get("condition") == condition
            and int(row.get("epoch", 0)) == epoch
        ]
        if subset:
            table.append(
                {
                    "seed": seed,
                    "condition": condition,
                    "epoch": epoch,
                    "phase": str(subset[0].get("phase", "")),
                    "burst": str(subset[0].get("burst", "")),
                    **condition_summary(subset),
                }
            )
    return table


def _render_report(metrics: dict[str, Any]) -> str:
    lines = [
        "# OASG Strong-Baseline v2 Effect Report",
        "",
        f"Classification: `{metrics['classification']}`",
        "Strong baseline qualification: "
        f"`{metrics['strong_baseline_qualification'].get('status', 'unknown')}`",
        f"Incremental headroom: `{metrics['incremental_headroom'].get('status', 'unknown')}`",
        "Adaptive readiness: "
        f"`{metrics['adaptive_readiness_from_strong'].get('status', 'unknown')}`",
        "",
        "## Condition Summaries",
        "",
        "| condition | tasks | closed | debt AUC | cost units | retries | active epochs |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for condition, summary in metrics["condition_summaries"].items():
        lines.append(
            f"| {condition} | {summary['task_count']} | {summary['closed']} | "
            f"{summary['operational_debt_auc']} | {summary['cost_to_close_units']} | "
            f"{summary['retries']} | {summary['active_mutation_epoch_count']} |"
        )
    oasg = metrics["comparisons"]["oasg_vs_strong_static"]
    lines.extend(
        [
            "",
            "## Primary Strong-Baseline Comparison",
            "",
            f"OASG vs strong static debt delta: `{oasg['debt_auc_delta']}`",
            f"OASG vs strong static cost delta: `{oasg['cost_to_close_delta']}`",
            f"Debt bootstrap CI: `{oasg['debt_bootstrap_ci']['debt_auc_delta_ci']}`",
            f"Cost bootstrap CI: `{oasg['cost_bootstrap_ci']['debt_auc_delta_ci']}`",
            f"Rule baseline sufficient flag: `{metrics['rule_baseline_sufficient']}`",
            "",
            "Effect is claimed only for the two confirmed-effect classifications.",
        ]
    )
    return "\n".join(lines)


def _read_optional(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return read_json(path)
    except (OSError, json.JSONDecodeError):
        return default


if __name__ == "__main__":
    raise SystemExit(main())
