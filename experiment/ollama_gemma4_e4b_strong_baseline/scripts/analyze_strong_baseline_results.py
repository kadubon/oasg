"""Analyze the OASG strong-baseline experiment."""

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
from strong_common import (  # noqa: E402
    CONDITIONS,
    classify_strong_baseline,
    condition_summary,
    paired_task_effects,
    read_json,
    rows_from_condition_dir,
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
    (out_dir / "report.md").write_text(_render_report(metrics), encoding="utf-8", newline="\n")
    print(json.dumps({"status": "ok", "classification": metrics["classification"]}, indent=2))
    return 0


def analyze_run(run_dir: Path) -> dict[str, Any]:
    config = _read_optional(run_dir / "config.json", {})
    strong_qualification = _read_optional(
        run_dir / "strong_baseline_qualification_receipt.json",
        {"status": "invalid_run"},
    )
    readiness = _read_optional(
        run_dir / "adaptive_from_strong_readiness_receipt.json",
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
        "strong_static_vs_weak": paired_task_effects(
            eval_rows,
            candidate_condition="strong_static_calibrated",
            baseline_condition="weak_fixed",
        ),
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
        "oasg_vs_rule_adaptive": paired_task_effects(
            eval_rows,
            candidate_condition="oasg_adaptive_from_strong",
            baseline_condition="strong_rule_adaptive_control",
        ),
        "observe_only_vs_weak": paired_task_effects(
            eval_rows,
            candidate_condition="observe_only",
            baseline_condition="weak_fixed",
        ),
    }
    verification = _verification_receipt(ledger_receipts=ledger_receipts, comparisons=comparisons)
    classification = classify_strong_baseline(
        summaries=summaries,
        comparisons=comparisons,
        strong_qualification=strong_qualification,
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
        "experiment_id": "ollama_gemma4_e4b_strong_baseline",
        "classification": classification,
        "condition_summaries": summaries,
        "comparisons": compact_comparisons,
        "paired_task_table": comparisons["oasg_vs_strong_static"]["rows"],
        "epoch_table": _epoch_table(eval_rows),
        "seed_table": _seed_table(eval_rows),
        "strong_baseline_qualification": strong_qualification,
        "adaptive_from_strong_readiness": readiness,
        "verification": verification,
        "promotion_diagnostic": _promotion_diagnostic(readiness=readiness),
        "ledger_receipts": ledger_receipts,
        "config_hash": receipt_hash(config),
        "metrics_hash": receipt_hash(
            {
                "classification": classification,
                "summaries": summaries,
                "comparisons": compact_comparisons,
            }
        ),
        "decision_contract": {
            "minimum_incremental_reduction_bps": int(
                config.get("minimum_incremental_reduction_bps", 500)
            ),
            "incremental_effect_confirmed_min_reduction_bps": int(
                config.get("incremental_effect_confirmed_min_reduction_bps", 1000)
            ),
            "confirmatory_min_active_seeds": int(
                config.get("confirmatory_min_active_seeds", 4)
            ),
        },
    }
    return metrics


def _verification_receipt(
    *,
    ledger_receipts: dict[str, Any],
    comparisons: dict[str, dict[str, Any]],
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
    if comparisons.get("oasg_vs_strong_static", {}).get("paired_task_count", 0) == 0:
        status = "invalid_run"
        reasons.append("strong_paired_comparison_missing")
    return {
        "receipt_type": "strong_baseline_verification_receipt",
        "status": status,
        "invalid_ledgers": invalid_ledgers,
        "paired_task_count": int(
            comparisons.get("oasg_vs_strong_static", {}).get("paired_task_count", 0)
        ),
        "reasons": reasons,
    }


def _promotion_diagnostic(*, readiness: dict[str, Any]) -> dict[str, Any]:
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
        "receipt_type": "strong_baseline_promotion_diagnostic",
        "status": "active_change_observed" if active_ids else "no_active_change_observed",
        "readiness_status": readiness.get("status", "unknown"),
        "active_seed_count": int(readiness.get("active_seed_count", 0)),
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
        "# OASG Strong-Baseline Effect Report",
        "",
        f"Classification: `{metrics['classification']}`",
        "Strong baseline qualification: "
        f"`{metrics['strong_baseline_qualification'].get('status', 'unknown')}`",
        "Adaptive readiness: "
        f"`{metrics['adaptive_from_strong_readiness'].get('status', 'unknown')}`",
        "",
        "## Condition Summaries",
        "",
        "| condition | tasks | closed | debt AUC | retries | active epochs |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for condition, summary in metrics["condition_summaries"].items():
        lines.append(
            f"| {condition} | {summary['task_count']} | {summary['closed']} | "
            f"{summary['operational_debt_auc']} | {summary['retries']} | "
            f"{summary['active_mutation_epoch_count']} |"
        )
    oasg = metrics["comparisons"]["oasg_vs_strong_static"]
    rule = metrics["comparisons"]["oasg_vs_rule_adaptive"]
    lines.extend(
        [
            "",
            "## Primary Strong-Baseline Comparison",
            "",
            f"OASG vs strong static debt delta: `{oasg['debt_auc_delta']}`",
            f"OASG vs strong static bootstrap CI: `{oasg['bootstrap_ci']['debt_auc_delta_ci']}`",
            f"OASG vs rule-adaptive debt delta: `{rule['debt_auc_delta']}`",
            "",
            "Effect is claimed only for "
            "`oasg_incremental_effect_confirmed_vs_strong_baseline`.",
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
