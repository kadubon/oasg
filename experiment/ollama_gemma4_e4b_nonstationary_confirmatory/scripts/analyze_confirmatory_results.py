"""Analyze the nonstationary confirmatory experiment."""

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

from confirmatory_common import (  # noqa: E402
    ALL_CONDITIONS,
    MAIN_CONDITIONS,
    REQUIRED_VARIANTS,
    adaptation_lag,
    classify_confirmatory,
    compact_comparison,
    condition_summary,
    paired_task_effects,
    post_drift_rows,
    read_json,
    rows_from_condition_dir,
    task_cost_units,
    task_debt,
    write_csv,
    write_json,
)
from oasg.canonical import receipt_hash  # noqa: E402
from oasg.ledger import verify_jsonl  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--bootstrap-samples", type=int, default=None)
    parser.add_argument("--classification-only", action="store_true")
    args = parser.parse_args()
    run_dir = Path(args.run_dir)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    metrics = analyze_run(run_dir, bootstrap_samples=args.bootstrap_samples)
    write_json(out_dir / "metrics.json", metrics)
    write_json(out_dir / "verification.json", metrics["verification"])
    write_json(out_dir / "classification_receipt.json", metrics["classification_receipt"])
    write_json(out_dir / "no_leakage_receipt.json", metrics["no_leakage_receipt"])
    write_json(out_dir / "oracle_headroom_receipt.json", metrics["oracle_headroom_receipt"])
    write_json(out_dir / "adaptation_lag_receipt.json", metrics["adaptation_lag_receipt"])
    write_json(out_dir / "ablation_receipt.json", metrics["ablation_receipt"])
    write_json(out_dir / "drift_class_effect_receipt.json", metrics["drift_class_effect_receipt"])
    write_json(out_dir / "retirement_effect_receipt.json", metrics["retirement_effect_receipt"])
    if not args.classification_only:
        write_csv(out_dir / "variant_table.csv", metrics["variant_table"])
        write_csv(out_dir / "phase_table.csv", metrics["phase_table"])
        write_csv(out_dir / "seed_table.csv", metrics["seed_table"])
        write_csv(out_dir / "epoch_table.csv", metrics["epoch_table"])
        write_csv(out_dir / "paired_task_table.csv", metrics["paired_task_table"])
        (out_dir / "report.md").write_text(
            metrics["report_markdown"], encoding="utf-8", newline="\n"
        )
    print(json.dumps({"status": "ok", "classification": metrics["classification"]}, indent=2))
    return 0


def analyze_run(run_dir: Path, bootstrap_samples: int | None = None) -> dict[str, Any]:
    config = _read_optional(run_dir / "config.json", {})
    if bootstrap_samples is not None:
        config["bootstrap_samples"] = bootstrap_samples
    all_rows: list[dict[str, Any]] = []
    ledger_receipts: dict[str, Any] = {}
    variant_receipts = _variant_receipts(run_dir)
    completed_variants = set(variant_receipts)
    for variant_id in completed_variants:
        variant_dir = run_dir / variant_id
        for seed_dir in sorted(path for path in variant_dir.glob("seed_*") if path.is_dir()):
            seed = seed_dir.name.replace("seed_", "")
            for condition in ALL_CONDITIONS:
                condition_dir = seed_dir / condition
                all_rows.extend(
                    rows_from_condition_dir(condition_dir, seed=seed, variant_id=variant_id)
                )
                ledger = condition_dir / "history.jsonl"
                if ledger.exists():
                    ledger_receipts[f"{variant_id}:{seed}:{condition}"] = verify_jsonl(ledger).to_dict()

    primary_rows = post_drift_rows(all_rows)
    summaries = {
        condition: condition_summary(
            [row for row in primary_rows if row.get("condition") == condition]
        )
        for condition in MAIN_CONDITIONS
    }
    bootstrap_count = int(config.get("bootstrap_samples", 1000))
    bootstrap_seed = int(config.get("bootstrap_seed", 20260513))
    comparisons = _comparisons(primary_rows, bootstrap_count=bootstrap_count, seed=bootstrap_seed)
    ablations = _ablation_comparisons(
        primary_rows, bootstrap_count=bootstrap_count, seed=bootstrap_seed
    )
    drift_class_effects = _drift_class_effects(
        all_rows, bootstrap_count=bootstrap_count, seed=bootstrap_seed
    )
    retirement_effect = _retirement_effect(primary_rows)
    oracle = _aggregate_oracle(variant_receipts)
    no_leakage = _no_leakage_receipt(run_dir, config, completed_variants)
    verification = _verification_receipt(
        ledger_receipts=ledger_receipts,
        comparisons=comparisons,
        no_leakage=no_leakage,
        config=config,
    )
    active_seed_count = _active_post_drift_seed_count(primary_rows)
    stable_a2_active_mutations = _stable_a2_active_mutations(all_rows)
    interrupted = (run_dir / "interruption_receipt.json").exists()
    classification = classify_confirmatory(
        summaries=summaries,
        comparisons=comparisons,
        ablations=ablations,
        drift_class_effects=drift_class_effects,
        oracle_headroom=oracle,
        active_seed_count=active_seed_count,
        stable_a2_active_mutations=stable_a2_active_mutations,
        verification_status=str(verification["status"]),
        completed_variants=completed_variants,
        config=config,
        interrupted=interrupted,
    )
    compact = {key: compact_comparison(value) for key, value in comparisons.items()}
    compact_ablations = {key: compact_comparison(value) for key, value in ablations.items()}
    compact_drift_class = {
        key: compact_comparison(value) for key, value in drift_class_effects.items()
    }
    variant_table = _variant_table(primary_rows)
    phase_table = _phase_table(primary_rows)
    seed_table = _seed_table(primary_rows)
    epoch_table = _epoch_table(primary_rows)
    paired_rows = comparisons.get("oasg_vs_strong_static", {}).get("rows", [])
    metrics = {
        "experiment_id": "ollama_gemma4_e4b_nonstationary_confirmatory",
        "classification": classification,
        "completed_variants": sorted(completed_variants),
        "condition_summaries": summaries,
        "comparisons": compact,
        "ablations": compact_ablations,
        "drift_class_effects": compact_drift_class,
        "retirement_effect": retirement_effect,
        "variant_table": variant_table,
        "phase_table": phase_table,
        "seed_table": seed_table,
        "epoch_table": epoch_table,
        "paired_task_table": paired_rows,
        "active_post_drift_seed_count": active_seed_count,
        "stable_a2_active_mutations": stable_a2_active_mutations,
        "adaptation_lag": adaptation_lag(primary_rows),
        "variant_receipts": variant_receipts,
        "oracle_headroom": oracle,
        "no_leakage_receipt": no_leakage,
        "verification": verification,
        "ledger_receipts": ledger_receipts,
        "config_hash": receipt_hash(config),
        "decision_contract": {
            "post_drift_effect_min_reduction_bps": int(
                config.get("post_drift_effect_min_reduction_bps", 1500)
            ),
            "control_support_min_reduction_bps": int(
                config.get("control_support_min_reduction_bps", 500)
            ),
            "cost_regression_tolerance_bps": int(config.get("cost_regression_tolerance_bps", 1000)),
            "confirmatory_min_active_seeds": int(config.get("confirmatory_min_active_seeds", 4)),
        },
    }
    metrics["metrics_hash"] = receipt_hash(
        {
            "classification": classification,
            "summaries": summaries,
            "comparisons": compact,
            "ablations": compact_ablations,
            "drift_class_effects": compact_drift_class,
            "active_seed_count": active_seed_count,
        }
    )
    metrics["classification_receipt"] = {
        "receipt_type": "final_nonstationary_confirmatory_classification_receipt",
        "classification": classification,
        "metrics_hash": metrics["metrics_hash"],
        "effect_claim_allowed": classification == "oasg_nonstationary_confirmed",
        "completed_variants": sorted(completed_variants),
    }
    metrics["oracle_headroom_receipt"] = oracle
    metrics["adaptation_lag_receipt"] = {
        "receipt_type": "adaptation_lag_receipt",
        "status": "computed",
        "adaptation_lag": metrics["adaptation_lag"],
        "metrics_hash": metrics["metrics_hash"],
    }
    metrics["ablation_receipt"] = {
        "receipt_type": "ablation_receipt",
        "status": "computed",
        "no_phase_d": compact_ablations.get("no_phase_d", {}),
        "mixed_only": compact_ablations.get("mixed_only", {}),
        "structural_only": compact_ablations.get("structural_only", {}),
        "mild_only": compact_ablations.get("mild_only", {}),
        "metrics_hash": metrics["metrics_hash"],
    }
    metrics["drift_class_effect_receipt"] = {
        "receipt_type": "drift_class_effect_receipt",
        "status": "computed",
        "drift_class_effects": compact_drift_class,
        "interpretation_label": _drift_interpretation_label(
            compact_drift_class,
            support_threshold_bps=int(config.get("control_support_min_reduction_bps", 500)),
        ),
        "metrics_hash": metrics["metrics_hash"],
    }
    metrics["retirement_effect_receipt"] = {
        "receipt_type": "retirement_effect_receipt",
        "status": "computed",
        **retirement_effect,
        "metrics_hash": metrics["metrics_hash"],
    }
    metrics["report_markdown"] = _render_report(metrics)
    return metrics


def _comparisons(
    rows: list[dict[str, Any]], *, bootstrap_count: int, seed: int
) -> dict[str, dict[str, Any]]:
    return {
        "oasg_vs_strong_static": paired_task_effects(
            rows,
            candidate_condition="oasg_adaptive_from_strong",
            baseline_condition="strong_static_calibrated",
            bootstrap_samples=bootstrap_count,
            bootstrap_seed=seed,
        ),
        "oasg_vs_observe_only": paired_task_effects(
            rows,
            candidate_condition="oasg_adaptive_from_strong",
            baseline_condition="oasg_observe_only_from_strong",
            bootstrap_samples=bootstrap_count,
            bootstrap_seed=seed + 10,
        ),
        "oasg_vs_rule_adaptive": paired_task_effects(
            rows,
            candidate_condition="oasg_adaptive_from_strong",
            baseline_condition="rule_adaptive_control",
            bootstrap_samples=bootstrap_count,
            bootstrap_seed=seed + 20,
        ),
    }


def _ablation_comparisons(
    rows: list[dict[str, Any]], *, bootstrap_count: int, seed: int
) -> dict[str, dict[str, Any]]:
    no_phase_d_rows = [
        row
        for row in rows
        if str(row.get("phase_category", "")) not in {"mixed"}
        and row.get("variant_id") != "mixed_reversion_only_probe"
    ]
    mixed_rows = [row for row in rows if str(row.get("phase_category", "")) == "mixed"]
    structural_rows = [
        row
        for row in rows
        if str(row.get("phase_category", "")) in {"structural", "structural_surface"}
        and row.get("phase_role") == "post_drift"
    ]
    mild_rows = [row for row in rows if str(row.get("phase_category", "")) == "mild"]
    return {
        "no_phase_d": paired_task_effects(
            no_phase_d_rows,
            candidate_condition="oasg_adaptive_from_strong",
            baseline_condition="strong_static_calibrated",
            bootstrap_samples=bootstrap_count,
            bootstrap_seed=seed + 30,
        ),
        "mixed_only": paired_task_effects(
            mixed_rows,
            candidate_condition="oasg_adaptive_from_strong",
            baseline_condition="strong_static_calibrated",
            bootstrap_samples=bootstrap_count,
            bootstrap_seed=seed + 40,
        ),
        "structural_only": paired_task_effects(
            structural_rows,
            candidate_condition="oasg_adaptive_from_strong",
            baseline_condition="strong_static_calibrated",
            bootstrap_samples=bootstrap_count,
            bootstrap_seed=seed + 50,
        ),
        "mild_only": paired_task_effects(
            mild_rows,
            candidate_condition="oasg_adaptive_from_strong",
            baseline_condition="strong_static_calibrated",
            bootstrap_samples=bootstrap_count,
            bootstrap_seed=seed + 60,
        ),
    }


def _drift_class_effects(
    rows: list[dict[str, Any]], *, bootstrap_count: int, seed: int
) -> dict[str, dict[str, Any]]:
    effects: dict[str, dict[str, Any]] = {}
    classes = {
        "mild": {"mild"},
        "structural": {"structural", "structural_surface"},
        "mixed": {"mixed"},
        "delayed_stable": {"stable"},
    }
    for index, (label, categories) in enumerate(classes.items()):
        source = [
            row
            for row in rows
            if str(row.get("phase_category", "")) in categories
            and row.get("condition") in MAIN_CONDITIONS
            and (
                label == "delayed_stable"
                or row.get("phase_role") == "post_drift"
            )
        ]
        effects[label] = paired_task_effects(
            source,
            candidate_condition="oasg_adaptive_from_strong",
            baseline_condition="strong_static_calibrated",
            bootstrap_samples=bootstrap_count,
            bootstrap_seed=seed + 70 + index,
        )
    return effects


def _retirement_effect(rows: list[dict[str, Any]]) -> dict[str, Any]:
    adaptive_rows = [
        row for row in rows if row.get("condition") == "oasg_adaptive_from_strong"
    ]
    retired = [
        row
        for row in adaptive_rows
        if any(
            "policy_retirement" in str(mutation_id)
            or "policy_tightening" in str(mutation_id)
            for mutation_id in row.get("active_mutation_ids", [])
        )
    ]
    mixed_retired = [row for row in retired if row.get("phase_category") == "mixed"]
    return {
        "active_retirement_ids": sorted(
            {
                str(mutation_id)
                for row in retired
                for mutation_id in row.get("active_mutation_ids", [])
                if "policy_retirement" in str(mutation_id)
                or "policy_tightening" in str(mutation_id)
            }
        ),
        "retirement_count": len(retired),
        "mixed_retirement_count": len(mixed_retired),
        "retirement_debt_auc": sum(task_debt(row) for row in retired),
        "retirement_cost_units": sum(row.get("cost_units", task_cost_units(row)) for row in retired),
    }


def _variant_receipts(run_dir: Path) -> dict[str, dict[str, Any]]:
    receipts: dict[str, dict[str, Any]] = {}
    for variant_dir in sorted(path for path in run_dir.iterdir() if path.is_dir()):
        calibration = _read_optional(
            variant_dir / "strong_baseline_calibration_receipt.json",
            {"status": "missing"},
        )
        oracle = _read_optional(
            variant_dir / "oracle_headroom_receipt.json",
            {"status": "missing"},
        )
        readiness = _read_optional(
            variant_dir / "adaptive_readiness_receipt.json",
            {"status": "missing"},
        )
        if calibration["status"] != "missing" or oracle["status"] != "missing":
            receipts[variant_dir.name] = {
                "calibration": calibration,
                "oracle": oracle,
                "readiness": readiness,
            }
    return receipts


def _aggregate_oracle(variant_receipts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    probes: list[dict[str, Any]] = []
    for variant_id, receipt in variant_receipts.items():
        oracle = receipt.get("oracle", {})
        for probe in oracle.get("probe_receipts", []):
            item = dict(probe)
            item.setdefault("variant_id", variant_id)
            item.setdefault(
                "phase_category", _phase_category_from_id(str(item.get("phase_id", "")))
            )
            probes.append(item)
    improved = [probe for probe in probes if probe.get("status") == "oracle_improved"]
    by_class: dict[str, dict[str, Any]] = {}
    for drift_class in ("mild", "structural", "mixed", "delayed_stable"):
        categories = {"structural", "structural_surface"} if drift_class == "structural" else {drift_class}
        subset = [probe for probe in probes if str(probe.get("phase_category", "")) in categories]
        improved_subset = [probe for probe in subset if probe.get("status") == "oracle_improved"]
        by_class[drift_class] = {
            "status": "oracle_headroom_present" if improved_subset else "oracle_headroom_absent",
            "probe_count": len(subset),
            "improved_probe_count": len(improved_subset),
            "probe_receipts_hash": receipt_hash({"probe_receipts": subset}),
        }
    return {
        "receipt_type": "oracle_headroom_receipt",
        "status": "oracle_headroom_present" if improved else "oracle_headroom_absent",
        "probe_count": len(probes),
        "improved_probe_count": len(improved),
        "oracle_headroom_by_drift_class": by_class,
        "non_deployable_control": True,
        "probe_receipts_hash": receipt_hash({"probe_receipts": probes}),
    }


def _phase_category_from_id(phase_id: str) -> str:
    if "phase_b" in phase_id:
        return "mild"
    if "phase_c" in phase_id:
        return "structural"
    if "phase_d" in phase_id:
        return "mixed"
    if "phase_a2" in phase_id:
        return "stable"
    return "calibration"


def _verification_receipt(
    *,
    ledger_receipts: dict[str, Any],
    comparisons: dict[str, dict[str, Any]],
    no_leakage: dict[str, Any],
    config: dict[str, Any],
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
    if no_leakage.get("status") != "ok":
        status = "invalid"
        reasons.append("no_leakage_violation")
    if comparisons.get("oasg_vs_strong_static", {}).get("paired_task_count", 0) == 0:
        status = "invalid"
        reasons.append("primary_pairing_missing")
    return {
        "receipt_type": "confirmatory_verification_receipt",
        "status": status,
        "invalid_ledgers": invalid_ledgers,
        "paired_task_count": int(comparisons.get("oasg_vs_strong_static", {}).get("paired_task_count", 0)),
        "minimum_paired_task_count": int(config.get("minimum_paired_task_count", 1)),
        "reasons": reasons,
    }


def _no_leakage_receipt(
    run_dir: Path, config: dict[str, Any], completed_variants: set[str]
) -> dict[str, Any]:
    manifest = _read_optional(run_dir / "frozen_task_manifest.json", {"status": "missing"})
    disjoint = manifest.get("status") == "ok"
    required = set(config.get("required_variants", REQUIRED_VARIANTS))
    return {
        "receipt_type": "no_leakage_receipt",
        "status": "ok" if disjoint else "invalid",
        "phase_a_only_calibration": True,
        "primary_excludes_phase_a": True,
        "primary_excludes_phase_a2": True,
        "completed_variants": sorted(completed_variants),
        "required_variants": sorted(required),
        "variant_set_complete": completed_variants == required,
        "manifest_hash": manifest.get("manifest_hash"),
        "statement": (
            "Strong static calibration uses Phase A only. OASG and rule adaptive conditions are "
            "online over observed rows. Oracle control is diagnostic and non-deployable."
        ),
    }


def _active_post_drift_seed_count(rows: list[dict[str, Any]]) -> int:
    return len(
        {
            str(row.get("seed", ""))
            for row in rows
            if row.get("condition") == "oasg_adaptive_from_strong"
            and row.get("phase_role") == "post_drift"
            and row.get("active_mutation_ids")
        }
    )


def _stable_a2_active_mutations(rows: list[dict[str, Any]]) -> int:
    return sum(
        1
        for row in rows
        if row.get("condition") == "oasg_adaptive_from_strong"
        and row.get("phase_id") == "phase_a2_stable_continuation"
        and row.get("active_mutation_ids")
    )


def _variant_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    table: list[dict[str, Any]] = []
    for variant_id in sorted({str(row.get("variant_id", "")) for row in rows}):
        for condition in MAIN_CONDITIONS:
            subset = [
                row
                for row in rows
                if row.get("variant_id") == variant_id and row.get("condition") == condition
            ]
            table.append({"variant_id": variant_id, "condition": condition, **condition_summary(subset)})
    return table


def _phase_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    table: list[dict[str, Any]] = []
    keys = sorted(
        {
            (
                str(row.get("variant_id", "")),
                str(row.get("phase_id", "")),
                str(row.get("phase_category", "")),
            )
            for row in rows
        }
    )
    for variant_id, phase_id, phase_category in keys:
        for condition in MAIN_CONDITIONS:
            subset = [
                row
                for row in rows
                if row.get("variant_id") == variant_id
                and row.get("phase_id") == phase_id
                and row.get("condition") == condition
            ]
            table.append(
                {
                    "variant_id": variant_id,
                    "phase_id": phase_id,
                    "phase_category": phase_category,
                    "condition": condition,
                    **condition_summary(subset),
                }
            )
    return table


def _seed_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    table: list[dict[str, Any]] = []
    for seed in sorted({str(row.get("seed", "")) for row in rows}):
        for condition in MAIN_CONDITIONS:
            subset = [
                row
                for row in rows
                if str(row.get("seed", "")) == seed and row.get("condition") == condition
            ]
            table.append({"seed": seed, "condition": condition, **condition_summary(subset)})
    return table


def _epoch_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    table: list[dict[str, Any]] = []
    keys = sorted(
        {
            (
                str(row.get("variant_id", "")),
                str(row.get("seed", "")),
                str(row.get("phase_id", "")),
                int(row.get("epoch", 0)),
            )
            for row in rows
        }
    )
    for variant_id, seed, phase_id, epoch in keys:
        for condition in MAIN_CONDITIONS:
            subset = [
                row
                for row in rows
                if row.get("variant_id") == variant_id
                and str(row.get("seed", "")) == seed
                and row.get("phase_id") == phase_id
                and int(row.get("epoch", 0)) == epoch
                and row.get("condition") == condition
            ]
            table.append(
                {
                    "variant_id": variant_id,
                    "seed": seed,
                    "phase_id": phase_id,
                    "epoch": epoch,
                    "condition": condition,
                    **condition_summary(subset),
                }
            )
    return table


def _render_report(metrics: dict[str, Any]) -> str:
    primary = metrics["comparisons"].get("oasg_vs_strong_static", {})
    observe = metrics["comparisons"].get("oasg_vs_observe_only", {})
    rule = metrics["comparisons"].get("oasg_vs_rule_adaptive", {})
    ablations = metrics.get("ablations", {})
    drift = metrics.get("drift_class_effects", {})
    retirement = metrics.get("retirement_effect", {})
    interpretation_label = metrics.get("drift_class_effect_receipt", {}).get(
        "interpretation_label", "not_computed"
    )
    return "\n".join(
        [
            "# OASG Nonstationary Confirmatory Experiment Report",
            "",
            f"Final classification: `{metrics['classification']}`",
            "",
            "## Scientific Question",
            "",
            (
                "Does OASG adaptive workflow-policy promotion still show post-drift recovery over "
                "a Phase-A-calibrated strong static workflow when the prior positive result is "
                "replicated across larger variants and ablations?"
            ),
            "",
            (
                "This protocol does not test whether OASG is strong for nonstationarity in general. "
                "It tests whether this implementation shows receipt-backed recovery within the frozen "
                "drift classes below."
            ),
            "",
            "## Integrity Summary",
            "",
            f"- Verification: `{metrics['verification']['status']}`.",
            f"- Completed variants: `{', '.join(metrics['completed_variants'])}`.",
            f"- Primary paired post-drift tasks: `{primary.get('paired_task_count', 0)}`.",
            f"- Active post-drift OASG seeds: `{metrics['active_post_drift_seed_count']}`.",
            f"- Stable A2 active mutation rows: `{metrics['stable_a2_active_mutations']}`.",
            "",
            "## Primary Comparison",
            "",
            (
                "- `oasg_adaptive_from_strong` vs `strong_static_calibrated`: "
                f"debt delta `{primary.get('debt_auc_delta', 0)}`, "
                f"debt CI `{primary.get('debt_bootstrap_ci', {}).get('delta_ci', [0, 0])}`, "
                f"cost delta `{primary.get('cost_to_close_delta', 0)}`, "
                f"cost CI `{primary.get('cost_bootstrap_ci', {}).get('delta_ci', [0, 0])}`."
            ),
            (
                "- OASG vs observe-only: "
                f"debt delta `{observe.get('debt_auc_delta', 0)}`, "
                f"CI `{observe.get('debt_bootstrap_ci', {}).get('delta_ci', [0, 0])}`."
            ),
            (
                "- OASG vs rule-adaptive: "
                f"debt delta `{rule.get('debt_auc_delta', 0)}`, "
                f"CI `{rule.get('debt_bootstrap_ci', {}).get('delta_ci', [0, 0])}`."
            ),
            "",
            "## Ablation Summary",
            "",
            (
                "- No-Phase-D aggregate: "
                f"`{ablations.get('no_phase_d', {}).get('debt_auc_delta', 0)}` debt delta, "
                f"CI `{ablations.get('no_phase_d', {}).get('debt_bootstrap_ci', {}).get('delta_ci', [0, 0])}`."
            ),
            (
                "- Mixed-reversion-only aggregate: "
                f"`{ablations.get('mixed_only', {}).get('debt_auc_delta', 0)}` debt delta, "
                f"CI `{ablations.get('mixed_only', {}).get('debt_bootstrap_ci', {}).get('delta_ci', [0, 0])}`."
            ),
            (
                "- Structural-only aggregate: "
                f"`{ablations.get('structural_only', {}).get('debt_auc_delta', 0)}` debt delta, "
                f"CI `{ablations.get('structural_only', {}).get('debt_bootstrap_ci', {}).get('delta_ci', [0, 0])}`."
            ),
            (
                "- Mild-only aggregate: "
                f"`{ablations.get('mild_only', {}).get('debt_auc_delta', 0)}` debt delta, "
                f"CI `{ablations.get('mild_only', {}).get('debt_bootstrap_ci', {}).get('delta_ci', [0, 0])}`."
            ),
            "",
            "## Drift-Class Effects",
            "",
            f"- Interpretation label: `{interpretation_label}`.",
            *[
                (
                    f"- `{label}`: debt delta `{effect.get('debt_auc_delta', 0)}`, "
                    f"reduction `{effect.get('debt_reduction_bps', 0)}` bps, "
                    f"CI `{effect.get('debt_bootstrap_ci', {}).get('delta_ci', [0, 0])}`, "
                    f"cost delta `{effect.get('cost_to_close_delta', 0)}`."
                )
                for label, effect in sorted(drift.items())
            ],
            "",
            "## Cost And Retirement",
            "",
            (
                "- Primary cost-to-close delta: "
                f"`{primary.get('cost_to_close_delta', 0)}`, "
                f"CI `{primary.get('cost_bootstrap_ci', {}).get('delta_ci', [0, 0])}`."
            ),
            f"- Active retirement/tightening rows: `{retirement.get('retirement_count', 0)}`.",
            f"- Mixed retirement/tightening rows: `{retirement.get('mixed_retirement_count', 0)}`.",
            "",
            "## Scientific Interpretation",
            "",
            _interpretation(metrics["classification"]),
            "",
            "## Claims Not Supported",
            "",
            "- This is not evidence that the model became more intelligent.",
            "- This is not a universal OASG effectiveness proof.",
            "- The oracle control is not a deployable baseline.",
            "- Mock/small results are wiring checks only.",
            "",
            "## Public Artifacts",
            "",
            "- `metrics.json`",
            "- `verification.json`",
            "- `classification_receipt.json`",
            "- `no_leakage_receipt.json`",
            "- `oracle_headroom_receipt.json`",
            "- `adaptation_lag_receipt.json`",
            "- `ablation_receipt.json`",
            "- `drift_class_effect_receipt.json`",
            "- `retirement_effect_receipt.json`",
            "- `variant_table.csv`, `phase_table.csv`, `seed_table.csv`, `epoch_table.csv`",
            "- `paired_task_table.csv`",
            "",
            "## Reproduction",
            "",
            "```powershell",
            "uv sync",
            "uv run python experiment\\ollama_gemma4_e4b_nonstationary_confirmatory\\scripts\\run_confirmatory_experiment.py --config experiment\\ollama_gemma4_e4b_nonstationary_confirmatory\\config_confirmatory_small.json --mock-model --all-variants",
            "uv run python experiment\\ollama_gemma4_e4b_nonstationary_confirmatory\\scripts\\analyze_confirmatory_results.py --run-dir experiment\\ollama_gemma4_e4b_nonstationary_confirmatory\\runs\\latest --out experiment\\ollama_gemma4_e4b_nonstationary_confirmatory\\results",
            "```",
            "",
        ]
    )


def _interpretation(classification: str) -> str:
    if classification == "oasg_nonstationary_confirmed":
        return (
            "The all-variant real run supports post-drift operational recovery by OASG under the "
            "frozen protocol. The claim remains limited to this workload, model, implementation, "
            "and threshold contract."
        )
    if classification == "oasg_nonstationary_phase_specific_support":
        return (
            "The result supports a narrower phase-specific interpretation. The observed effect is "
            "not broad across all drift types."
        )
    if classification == "mixed_reversion_only_effect":
        return (
            "The primary comparison favors OASG, but the ablation contract narrows the effect to "
            "mixed reversion or policy-retirement-sensitive drift rather than broad confirmatory "
            "nonstationary support."
        )
    if classification == "no_mixed_reversion_support":
        return (
            "The ablation pattern supports drift recovery without mixed reversion, but it does not "
            "satisfy the full broad-confirmation contract."
        )
    if classification == "inconclusive_insufficient_power":
        return "The run is a protocol or diagnostic run and does not justify a confirmatory claim."
    return "The run does not support a positive OASG confirmatory effect claim under this protocol."


def _drift_interpretation_label(
    drift_class_effects: dict[str, dict[str, Any]], *, support_threshold_bps: int = 500
) -> str:
    supported = {
        label
        for label, effect in drift_class_effects.items()
        if int(effect.get("debt_reduction_bps", 0)) >= support_threshold_bps
        and int(effect.get("debt_bootstrap_ci", {}).get("delta_ci", [0, 1])[1]) <= 0
    }
    if {"mild", "structural", "mixed"} <= supported:
        return "broad_nonstationary_support_within_protocol"
    if "mixed" in supported and "structural" not in supported:
        return "mixed_reversion_or_retirement_specific_support"
    if "structural" in supported and "mixed" not in supported:
        return "structural_drift_specific_support"
    if supported:
        return "limited_drift_class_support"
    return "no_drift_class_support"


def _read_optional(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return read_json(path)


if __name__ == "__main__":
    raise SystemExit(main())
