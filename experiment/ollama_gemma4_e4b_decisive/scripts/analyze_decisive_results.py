"""Analyze the decisive OASG effect experiment."""

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

from decisive_common import (  # noqa: E402
    CONDITIONS,
    classify_decisive,
    condition_summary,
    paired_task_effects,
    read_json,
    rows_from_condition_dir,
    write_csv,
    write_json,
)
from oasg.canonical import receipt_hash  # noqa: E402
from oasg.ledger import verify_jsonl  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    run_dir = Path(args.run_dir)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    metrics = analyze_run(run_dir)
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
    policy_qualification = _read_optional(
        run_dir / "policy_catalog_qualification_receipt.json",
        {"status": "invalid_run"},
    )
    promotion_qualification = _read_optional(
        run_dir / "promotion_qualification_receipt.json",
        {"status": "promotion_mechanism_failure", "active_seed_count": 0},
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
        "forced_policy_vs_baseline": paired_task_effects(
            eval_rows,
            candidate_condition="forced_policy_positive_control",
        ),
        "oasg_adaptive_vs_baseline": paired_task_effects(
            eval_rows,
            candidate_condition="oasg_adaptive",
        ),
        "oasg_observe_only_vs_baseline": paired_task_effects(
            eval_rows,
            candidate_condition="oasg_observe_only",
        ),
    }
    verification = _verification_receipt(
        ledger_receipts=ledger_receipts,
        comparisons=comparisons,
        policy_qualification=policy_qualification,
        run_dir=run_dir,
    )
    classification = classify_decisive(
        summaries=summaries,
        comparisons=comparisons,
        policy_qualification=policy_qualification,
        promotion_qualification=promotion_qualification,
        seed_count=len(config.get("replicate_seeds", [])),
        config=config,
        verification_status=str(verification["status"]),
    )
    promotion_diagnostic = _promotion_diagnostic_receipt(
        promotion_qualification=promotion_qualification,
        policy_qualification=policy_qualification,
    )
    metrics = {
        "experiment_id": "ollama_gemma4_e4b_decisive",
        "classification": classification,
        "condition_summaries": summaries,
        "comparisons": {
            key: {inner_key: value for inner_key, value in item.items() if inner_key != "rows"}
            for key, item in comparisons.items()
        },
        "paired_task_table": comparisons["oasg_adaptive_vs_baseline"]["rows"],
        "epoch_table": _epoch_table(eval_rows),
        "seed_table": _seed_table(eval_rows),
        "policy_qualification": policy_qualification,
        "promotion_qualification": promotion_qualification,
        "verification": verification,
        "promotion_diagnostic": promotion_diagnostic,
        "ledger_receipts": ledger_receipts,
        "config_hash": receipt_hash(config),
        "metrics_hash": receipt_hash(
            {
                "classification": classification,
                "summaries": summaries,
                "comparisons": {
                    key: {inner_key: value for inner_key, value in item.items() if inner_key != "rows"}
                    for key, item in comparisons.items()
                },
            }
        ),
        "decision_contract": {
            "minimum_meaningful_reduction_bps": int(
                config.get("minimum_meaningful_reduction_bps", 1500)
            ),
            "effect_confirmed_min_reduction_bps": int(
                config.get("effect_confirmed_min_reduction_bps", 2000)
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
    policy_qualification: dict[str, Any],
    run_dir: Path,
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
    if policy_qualification.get("status") == "invalid_run":
        status = "invalid_run"
        reasons.append("policy_qualification_invalid")
    stage2_started = any(run_dir.glob("seed_*/baseline_fixed"))
    if (run_dir / "promotion_qualification_receipt.json").exists():
        adaptive_pairs = int(
            comparisons.get("oasg_adaptive_vs_baseline", {}).get("paired_task_count", 0)
        )
        forced_pairs = int(
            comparisons.get("forced_policy_vs_baseline", {}).get("paired_task_count", 0)
        )
        if stage2_started and (adaptive_pairs == 0 or forced_pairs == 0):
            status = "invalid_run"
            reasons.append("paired_comparison_missing")
    return {
        "receipt_type": "verification_receipt",
        "status": status,
        "invalid_ledgers": invalid_ledgers,
        "adaptive_paired_task_count": int(
            comparisons.get("oasg_adaptive_vs_baseline", {}).get("paired_task_count", 0)
        ),
        "forced_paired_task_count": int(
            comparisons.get("forced_policy_vs_baseline", {}).get("paired_task_count", 0)
        ),
        "reasons": reasons,
    }


def _promotion_diagnostic_receipt(
    *,
    promotion_qualification: dict[str, Any],
    policy_qualification: dict[str, Any],
) -> dict[str, Any]:
    active_by_seed = promotion_qualification.get("active_policies_by_seed", {})
    active_mutations = sorted(
        {
            str(item.get("mutation_id"))
            for policies in active_by_seed.values()
            for item in policies
            if item.get("mutation_id")
        }
    ) if isinstance(active_by_seed, dict) else []
    return {
        "receipt_type": "promotion_diagnostic_receipt",
        "status": "active_policy_observed" if active_mutations else "no_active_policy_observed",
        "policy_qualification_status": policy_qualification.get("status", "unknown"),
        "promotion_qualification_status": promotion_qualification.get("status", "unknown"),
        "active_seed_count": int(promotion_qualification.get("active_seed_count", 0)),
        "active_mutation_ids": active_mutations,
        "qualified_pair_count": int(policy_qualification.get("qualified_pair_count", 0)),
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
        "# OASG Decisive Effect Report",
        "",
        f"Classification: `{metrics['classification']}`",
        f"Policy qualification: `{metrics['policy_qualification'].get('status', 'unknown')}`",
        f"Promotion qualification: `{metrics['promotion_qualification'].get('status', 'unknown')}`",
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
    adaptive = metrics["comparisons"]["oasg_adaptive_vs_baseline"]
    forced = metrics["comparisons"]["forced_policy_vs_baseline"]
    lines.extend(
        [
            "",
            "## Paired Effects",
            "",
            f"Forced policy debt delta: `{forced['debt_auc_delta']}`",
            f"Adaptive debt delta: `{adaptive['debt_auc_delta']}`",
            f"Adaptive bootstrap CI: `{adaptive['bootstrap_ci']['debt_auc_delta_ci']}`",
            "",
            "Effect is claimed only for `oasg_effect_confirmed`.",
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
