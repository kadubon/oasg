"""Analyze the time-boxed nonstationary strong-baseline experiment."""

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

from nonstationary_common import (  # noqa: E402
    ALL_CONDITIONS,
    MAIN_CONDITIONS,
    PHASE_IDS,
    adaptation_lag,
    classify_nonstationary,
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
    write_json(out_dir / "nonstationary_effect_receipt.json", metrics["nonstationary_effect_receipt"])
    write_json(
        out_dir / "final_nonstationary_classification_receipt.json",
        metrics["final_classification_receipt"],
    )
    write_csv(out_dir / "phase_table.csv", metrics["phase_table"])
    write_csv(out_dir / "seed_table.csv", metrics["seed_table"])
    write_csv(out_dir / "epoch_table.csv", metrics["epoch_table"])
    write_csv(out_dir / "paired_task_table.csv", metrics["paired_task_table"])
    (out_dir / "report.md").write_text(metrics["report_markdown"], encoding="utf-8", newline="\n")
    print(json.dumps({"status": "ok", "classification": metrics["classification"]}, indent=2))
    return 0


def analyze_run(run_dir: Path) -> dict[str, Any]:
    config = _read_optional(run_dir / "config.json", {})
    calibration = _read_optional(
        run_dir / "strong_baseline_calibration_receipt.json",
        {"status": "strong_baseline_not_qualified"},
    )
    oracle = _read_optional(
        run_dir / "oracle_headroom_receipt.json",
        {"status": "oracle_headroom_absent"},
    )
    readiness = _read_optional(
        run_dir / "adaptive_readiness_receipt.json",
        {"status": "adaptive_readiness_failed", "active_seed_count": 0},
    )
    all_rows: list[dict[str, Any]] = []
    ledger_receipts: dict[str, Any] = {}
    for seed_dir in sorted(path for path in run_dir.glob("seed_*") if path.is_dir()):
        seed = seed_dir.name.replace("seed_", "")
        for condition in ALL_CONDITIONS:
            condition_dir = seed_dir / condition
            rows = rows_from_condition_dir(condition_dir, seed=seed)
            all_rows.extend(rows)
            ledger = condition_dir / "history.jsonl"
            if ledger.exists():
                ledger_receipts[f"{seed}:{condition}"] = verify_jsonl(ledger).to_dict()

    post_drift_rows = [
        row
        for row in all_rows
        if row.get("phase_id", row.get("phase")) != "phase_a_calibration"
        and row.get("condition") in MAIN_CONDITIONS
    ]
    summaries = {
        condition: condition_summary(
            [row for row in post_drift_rows if row.get("condition") == condition]
        )
        for condition in MAIN_CONDITIONS
    }
    comparisons = {
        "oasg_vs_strong_static": paired_task_effects(
            post_drift_rows,
            candidate_condition="oasg_adaptive_from_strong",
            baseline_condition="strong_static_calibrated",
        ),
        "oasg_vs_observe_only": paired_task_effects(
            post_drift_rows,
            candidate_condition="oasg_adaptive_from_strong",
            baseline_condition="oasg_observe_only_from_strong",
        ),
        "oasg_vs_rule_adaptive": paired_task_effects(
            post_drift_rows,
            candidate_condition="oasg_adaptive_from_strong",
            baseline_condition="rule_adaptive_control",
        ),
    }
    oracle_comparison = _oracle_probe_comparison(all_rows)
    verification = _verification_receipt(
        ledger_receipts=ledger_receipts,
        comparisons=comparisons,
        calibration=calibration,
        oracle=oracle,
    )
    classification = classify_nonstationary(
        summaries=summaries,
        comparisons=comparisons,
        oracle_headroom=oracle,
        readiness=readiness,
        verification_status=str(verification["status"]),
        config=config,
    )
    compact_comparisons = {
        key: {inner_key: value for inner_key, value in item.items() if inner_key != "rows"}
        for key, item in comparisons.items()
    }
    phase_table = _phase_table(post_drift_rows)
    seed_table = _seed_table(post_drift_rows)
    epoch_table = _epoch_table(post_drift_rows)
    paired_rows = comparisons["oasg_vs_strong_static"]["rows"]
    metrics = {
        "experiment_id": "ollama_gemma4_e4b_nonstationary_strong_baseline",
        "classification": classification,
        "condition_summaries": summaries,
        "comparisons": compact_comparisons,
        "oracle_probe_comparison": oracle_comparison,
        "paired_task_table": paired_rows,
        "phase_table": phase_table,
        "seed_table": seed_table,
        "epoch_table": epoch_table,
        "adaptation_lag": adaptation_lag(post_drift_rows),
        "strong_baseline_calibration": calibration,
        "oracle_headroom": oracle,
        "adaptive_readiness": readiness,
        "verification": verification,
        "ledger_receipts": ledger_receipts,
        "config_hash": receipt_hash(config),
        "decision_contract": {
            "post_drift_effect_min_reduction_bps": int(
                config.get("post_drift_effect_min_reduction_bps", 1500)
            ),
            "minimum_partial_debt_reduction_bps": int(
                config.get("minimum_partial_debt_reduction_bps", 500)
            ),
            "cost_regression_tolerance_bps": int(config.get("cost_regression_tolerance_bps", 1000)),
        },
    }
    metrics["metrics_hash"] = receipt_hash(
        {
            "classification": classification,
            "summaries": summaries,
            "comparisons": compact_comparisons,
            "adaptation_lag": metrics["adaptation_lag"],
        }
    )
    metrics["nonstationary_effect_receipt"] = {
        "receipt_type": "nonstationary_effect_receipt",
        "status": classification,
        "metrics_hash": metrics["metrics_hash"],
        "phase_scope": "post_drift_only",
        "effect_claim_allowed": classification == "oasg_nonstationary_effect_confirmed_timeboxed",
    }
    metrics["final_classification_receipt"] = {
        "receipt_type": "final_nonstationary_classification_receipt",
        "classification": classification,
        "metrics_hash": metrics["metrics_hash"],
        "effect_claim_allowed": classification == "oasg_nonstationary_effect_confirmed_timeboxed",
    }
    metrics["report_markdown"] = _render_report(metrics)
    return metrics


def _verification_receipt(
    *,
    ledger_receipts: dict[str, Any],
    comparisons: dict[str, dict[str, Any]],
    calibration: dict[str, Any],
    oracle: dict[str, Any],
) -> dict[str, Any]:
    invalid_ledgers = {
        key: receipt
        for key, receipt in ledger_receipts.items()
        if receipt.get("status") != "ledger_prefix_valid"
    }
    reasons: list[str] = []
    status = "ok"
    if invalid_ledgers:
        status = "invalid"
        reasons.append("ledger_verification_failed")
    if (
        oracle.get("status") == "oracle_headroom_present"
        and comparisons.get("oasg_vs_strong_static", {}).get("paired_task_count", 0) == 0
    ):
        status = "invalid"
        reasons.append("primary_pairing_missing")
    if calibration.get("status") not in {
        "strong_baseline_calibrated",
        "strong_baseline_not_qualified",
    }:
        status = "invalid"
        reasons.append("calibration_receipt_missing")
    if oracle.get("status") not in {"oracle_headroom_present", "oracle_headroom_absent"}:
        status = "invalid"
        reasons.append("oracle_receipt_missing")
    return {
        "receipt_type": "nonstationary_verification_receipt",
        "status": "ok" if status == "ok" else "invalid",
        "invalid_ledgers": invalid_ledgers,
        "paired_task_count": int(comparisons.get("oasg_vs_strong_static", {}).get("paired_task_count", 0)),
        "reasons": reasons,
    }


def _phase_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    table: list[dict[str, Any]] = []
    for phase_id in PHASE_IDS[1:]:
        for condition in MAIN_CONDITIONS:
            subset = [
                row
                for row in rows
                if row.get("phase_id") == phase_id and row.get("condition") == condition
            ]
            table.append({"phase_id": phase_id, "condition": condition, **condition_summary(subset)})
    return table


def _seed_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    table: list[dict[str, Any]] = []
    for seed in sorted({str(row.get("seed", "single")) for row in rows}):
        for condition in MAIN_CONDITIONS:
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
            (
                str(row.get("seed", "single")),
                str(row.get("condition")),
                str(row.get("phase_id", "")),
                int(row.get("epoch", 0)),
            )
            for row in rows
        }
    )
    for seed, condition, phase_id, epoch in keys:
        subset = [
            row
            for row in rows
            if str(row.get("seed", "single")) == seed
            and row.get("condition") == condition
            and row.get("phase_id") == phase_id
            and int(row.get("epoch", 0)) == epoch
        ]
        table.append(
            {
                "seed": seed,
                "condition": condition,
                "phase_id": phase_id,
                "epoch": epoch,
                **condition_summary(subset),
            }
        )
    return table


def _oracle_probe_comparison(rows: list[dict[str, Any]]) -> dict[str, Any]:
    oracle_rows = [
        row for row in rows if row.get("condition") == "strong_static_oracle_phase_control"
    ]
    strong_probe_rows = [
        row
        for row in rows
        if row.get("condition") == "strong_static_calibrated"
        and row.get("phase_id") != "phase_a_calibration"
        and int(row.get("phase_epoch", 0)) == 1
    ]
    return {
        "oracle_summary": condition_summary(oracle_rows),
        "strong_probe_summary": condition_summary(strong_probe_rows),
    }


def _render_report(metrics: dict[str, Any]) -> str:
    summaries = metrics["condition_summaries"]
    primary = metrics["comparisons"]["oasg_vs_strong_static"]
    lines = [
        "# OASG Nonstationary Strong-Baseline Report",
        "",
        f"Classification: `{metrics['classification']}`",
        "",
        "This protocol tests time-ordered workflow drift response, not model intelligence.",
        "It asks whether OASG can recover post-drift operational performance from observable",
        "history while staying fail-closed about promotion.",
        "",
        "## Integrity",
        "",
        f"- Verification status: `{metrics['verification']['status']}`",
        f"- Paired post-drift task count: `{metrics['verification']['paired_task_count']}`",
        f"- Metrics hash: `{metrics['metrics_hash']}`",
        "",
        "## No-Leakage Statement",
        "",
        "Strong static calibration uses Phase A only. Primary metrics exclude Phase A. OASG adaptive",
        "may use only prior online observations. Oracle phase control is non-deployable and excluded",
        "from the primary comparison.",
        "",
        "## Workload Drift",
        "",
        "- Phase A: pre-drift calibration only.",
        "- Phase B: schema-key aliases and stricter JSON formatting.",
        "- Phase C: receipt, obligation, safe-expression, evidence, and rollback shifts.",
        "- Phase D: mixed old/new requirements to test overfitting and retirement value.",
        "",
        "The drift is deterministic and encoded in the frozen task manifest. This is a controlled",
        "operational-workflow drift, not random benchmark noise.",
        "",
        "## Controls",
        "",
        "- `strong_static_calibrated`: deployable static policy chosen from Phase A only.",
        "- `oasg_observe_only_from_strong`: same initial policy with OASG observation but no promotion.",
        "- `rule_adaptive_control`: simple recent-failure heuristic without OASG promotion receipts.",
        "- `strong_static_oracle_phase_control`: non-deployable phase-knowledge probe for headroom.",
        "",
        "## Condition Summaries",
        "",
        "| condition | tasks | closed | debt AUC | cost units | hard-floor regressions |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for condition, summary in summaries.items():
        lines.append(
            f"| `{condition}` | {summary['task_count']} | {summary['closed']} | "
            f"{summary['operational_debt_auc']} | {summary['cost_to_close_units']} | "
            f"{summary['hard_floor_regression_count']} |"
        )
    lines.extend(
        [
            "",
            "## Primary Comparison",
            "",
            "- Candidate: `oasg_adaptive_from_strong`",
            "- Baseline: `strong_static_calibrated`",
            f"- Debt AUC delta: `{primary['debt_auc_delta']}`",
            f"- Debt bootstrap CI: `{primary['debt_bootstrap_ci']['delta_ci']}`",
            f"- Cost-to-close delta: `{primary['cost_to_close_delta']}`",
            f"- Cost bootstrap CI: `{primary['cost_bootstrap_ci']['delta_ci']}`",
            f"- Adaptation lag: `{metrics['adaptation_lag']}`",
            "",
            "## Claims Supported",
            "",
            "- A positive OASG effect is supported only when the final classification is",
            "  `oasg_nonstationary_effect_confirmed_timeboxed`.",
            "- The claim, if present, is limited to this model, task distribution, implementation,",
            "  thresholds, and time-boxed protocol.",
            "",
            "## Claims Not Supported",
            "",
            "- This experiment does not test model-weight improvement.",
            "- It does not use or validate an LLM judge.",
            "- It does not prove universal OASG effectiveness.",
            "- Negative or inconclusive classifications remain valid evidence and are not hidden.",
            "",
            "## Public Artifacts",
            "",
            "- `metrics.json`",
            "- `verification.json`",
            "- `phase_table.csv`",
            "- `seed_table.csv`",
            "- `epoch_table.csv`",
            "- `paired_task_table.csv`",
            "- `final_nonstationary_classification_receipt.json`",
            "",
            "## Reproduction",
            "",
            "```powershell",
            (
                "uv run python "
                "experiment\\ollama_gemma4_e4b_nonstationary_strong_baseline\\scripts\\"
                "run_nonstationary_experiment.py --config "
                "experiment\\ollama_gemma4_e4b_nonstationary_strong_baseline\\"
                "config_nonstationary.json"
            ),
            (
                "uv run python "
                "experiment\\ollama_gemma4_e4b_nonstationary_strong_baseline\\scripts\\"
                "analyze_nonstationary_results.py --run-dir "
                "experiment\\ollama_gemma4_e4b_nonstationary_strong_baseline\\runs\\latest "
                "--out experiment\\ollama_gemma4_e4b_nonstationary_strong_baseline\\results"
            ),
            "```",
            "",
            "## Scientific Interpretation",
            "",
            "Effect is claimed only for `oasg_nonstationary_effect_confirmed_timeboxed`. Other",
            "classifications are negative or inconclusive evidence for this implementation, workload,",
            "model, and threshold set. They are not universal conclusions about OASG.",
        ]
    )
    return "\n".join(lines) + "\n"


def _read_optional(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return read_json(path)


if __name__ == "__main__":
    raise SystemExit(main())
