"""Run the nonstationary confirmatory experiment."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for import_path in (Path(__file__).resolve().parent, SRC, ROOT):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from analyze_confirmatory_results import analyze_run  # noqa: E402
from confirmatory_common import (  # noqa: E402
    ALL_CONDITIONS,
    MAIN_CONDITIONS,
    REQUIRED_VARIANTS,
    condition_summary,
    read_json,
    reduction_bps,
    task_debt,
    write_csv,
    write_json,
)
from confirmatory_runner import run_task, write_history  # noqa: E402
from generate_confirmatory_tasks import FAMILIES, generate_confirmatory_tasks, phase_schedule  # noqa: E402
from oasg.canonical import receipt_hash  # noqa: E402
from oasg.io import read_jsonl, write_jsonl  # noqa: E402
from oasg.ledger import verify_jsonl  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--variant", action="append", choices=sorted(REQUIRED_VARIANTS))
    parser.add_argument("--all-variants", action="store_true")
    parser.add_argument("--mock-model", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-epochs", type=int, default=None)
    parser.add_argument("--out-dir", default=None)
    args = parser.parse_args()

    config_path = Path(args.config)
    config = read_json(config_path)
    variants = _selected_variants(config=config, selected=args.variant, all_variants=args.all_variants)
    config["selected_variants"] = variants
    if args.max_epochs is not None:
        config["max_epochs"] = args.max_epochs
    runs_base = Path(args.out_dir) if args.out_dir else ROOT / str(config["runs_dir"])
    if args.resume and (runs_base / "latest").exists():
        metrics = analyze_run(runs_base / "latest")
        print(json.dumps({"status": metrics["classification"], "run_dir": str(runs_base / "latest")}, indent=2))
        return 0
    run_dir = _new_run_dir(runs_base)
    write_json(run_dir / "config.json", config)

    preflight = {"status": "mocked"} if args.mock_model else _preflight(config)
    write_json(run_dir / "preflight.json", preflight)
    if preflight["status"] not in {"ok", "mocked"}:
        _write_interruption(run_dir, "preflight_failed", {"preflight": preflight})
        _finish_with_analysis(run_dir, config)
        return 2

    _freeze_tasks(config=config, run_dir=run_dir, variants=variants)
    _write_setup_receipts(config_path=config_path, config=config, run_dir=run_dir, variants=variants)

    for variant_id in variants:
        variant_dir = run_dir / variant_id
        calibration = _calibrate_strong_baseline(
            config_path=config_path,
            config=config,
            variant_id=variant_id,
            run_dir=run_dir,
            mock_model=args.mock_model,
        )
        write_json(variant_dir / "strong_baseline_calibration_receipt.json", calibration)
        if calibration["status"] not in {
            "strong_baseline_calibrated",
            "strong_baseline_calibrated_phase_a_ceiling",
        }:
            _write_interruption(
                variant_dir,
                "strong_baseline_calibration_failed",
                {"variant_id": variant_id, "calibration": calibration},
            )
            continue
        oracle = _oracle_headroom(
            config_path=config_path,
            config=config,
            variant_id=variant_id,
            run_dir=run_dir,
            strong_policy=calibration["policy_by_family"],
            mock_model=args.mock_model,
        )
        write_json(variant_dir / "oracle_headroom_receipt.json", oracle)
        readiness = _run_online_conditions(
            config=config,
            variant_id=variant_id,
            run_dir=run_dir,
            strong_policy=calibration["policy_by_family"],
            oracle=oracle,
            mock_model=args.mock_model,
        )
        write_json(variant_dir / "adaptive_readiness_receipt.json", readiness)

    _finish_with_analysis(run_dir, config)
    return 0


def _finish_with_analysis(run_dir: Path, config: dict[str, Any]) -> None:
    metrics = analyze_run(run_dir)
    write_json(run_dir / "metrics.json", metrics)
    write_json(run_dir / "verification.json", metrics["verification"])
    write_json(run_dir / "classification_receipt.json", metrics["classification_receipt"])
    write_json(run_dir / "no_leakage_receipt.json", metrics["no_leakage_receipt"])
    write_json(run_dir / "oracle_headroom_receipt.json", metrics["oracle_headroom_receipt"])
    write_json(run_dir / "adaptation_lag_receipt.json", metrics["adaptation_lag_receipt"])
    write_json(run_dir / "ablation_receipt.json", metrics["ablation_receipt"])
    write_json(run_dir / "drift_class_effect_receipt.json", metrics["drift_class_effect_receipt"])
    write_json(run_dir / "retirement_effect_receipt.json", metrics["retirement_effect_receipt"])
    write_csv(run_dir / "variant_table.csv", metrics["variant_table"])
    write_csv(run_dir / "phase_table.csv", metrics["phase_table"])
    write_csv(run_dir / "seed_table.csv", metrics["seed_table"])
    write_csv(run_dir / "epoch_table.csv", metrics["epoch_table"])
    write_csv(run_dir / "paired_task_table.csv", metrics["paired_task_table"])
    (run_dir / "report.md").write_text(metrics["report_markdown"], encoding="utf-8", newline="\n")
    _finish(run_dir, ROOT / str(config["runs_dir"]))
    print(json.dumps({"status": metrics["classification"], "run_dir": str(run_dir)}, indent=2))


def _selected_variants(
    *, config: dict[str, Any], selected: list[str] | None, all_variants: bool
) -> list[str]:
    configured = [str(variant) for variant in config.get("variants", REQUIRED_VARIANTS)]
    if all_variants:
        return configured
    if selected:
        return selected
    return configured


def _freeze_tasks(*, config: dict[str, Any], run_dir: Path, variants: list[str]) -> None:
    manifest: dict[str, Any] = {
        "receipt_type": "confirmatory_frozen_task_manifest",
        "variants": [],
    }
    for variant_id in variants:
        variant_dir = run_dir / variant_id
        variant_dir.mkdir(parents=True, exist_ok=True)
        variant_manifest: dict[str, Any] = {"variant_id": variant_id, "seeds": []}
        for seed in [int(seed) for seed in config["replicate_seeds"]]:
            tasks = generate_confirmatory_tasks(
                seed=seed,
                variant_id=variant_id,
                epochs_per_phase=int(config["epochs_per_phase"]),
                tasks_per_epoch=int(config["tasks_per_epoch"]),
            )
            if config.get("max_epochs") is not None:
                max_epoch = int(config["max_epochs"])
                tasks = [task for task in tasks if int(task["epoch"]) <= max_epoch]
            seed_dir = variant_dir / f"seed_{seed}"
            seed_dir.mkdir(parents=True, exist_ok=True)
            write_jsonl(seed_dir / "tasks_confirmatory.jsonl", tasks)
            phase_a_ids = [
                str(task["task_id"]) for task in tasks if task["phase_role"] == "calibration"
            ]
            eval_ids = [
                str(task["task_id"]) for task in tasks if task["phase_role"] != "calibration"
            ]
            variant_manifest["seeds"].append(
                {
                    "seed": seed,
                    "task_count": len(tasks),
                    "task_hash": receipt_hash({"tasks": tasks}),
                    "phase_a_task_ids": phase_a_ids,
                    "non_calibration_task_ids": eval_ids,
                    "disjoint": not bool(set(phase_a_ids) & set(eval_ids)),
                }
            )
        manifest["variants"].append(variant_manifest)
    manifest["status"] = (
        "ok"
        if all(item["disjoint"] for variant in manifest["variants"] for item in variant["seeds"])
        else "invalid"
    )
    manifest["manifest_hash"] = receipt_hash(manifest["variants"])
    write_json(run_dir / "frozen_task_manifest.json", manifest)


def _write_setup_receipts(
    *, config_path: Path, config: dict[str, Any], run_dir: Path, variants: list[str]
) -> None:
    workload = {
        "receipt_type": "workload_config_receipt",
        "status": "configured",
        "experiment_id": config["experiment_id"],
        "config_hash": receipt_hash(config),
        "config_path_hint": config_path.name,
        "seed_list": list(config["replicate_seeds"]),
        "variant_ids": variants,
        "condition_list": list(ALL_CONDITIONS),
        "claim_scope": (
            "confirmatory effect claim requires all configured variants and the main real Ollama run"
        ),
    }
    drift = {
        "receipt_type": "drift_schedule_receipt",
        "status": "configured",
        "config_hash": receipt_hash(config),
        "variants": {
            variant_id: [
                {
                    "phase_id": phase["phase_id"],
                    "phase_role": phase["phase_role"],
                    "phase_category": phase["phase_category"],
                    "drift_family": phase["drift_family"],
                }
                for phase in phase_schedule(variant_id)
            ]
            for variant_id in variants
        },
    }
    no_leakage = {
        "receipt_type": "no_leakage_receipt",
        "status": "configured",
        "config_hash": receipt_hash(config),
        "rules": [
            "strong static calibration uses Phase A only",
            "primary metrics exclude Phase A and Phase A2 stable control rows",
            "OASG adaptive uses only prior online observations",
            "rule adaptive uses recent observed failures and not future phase labels",
            "oracle phase control is non-deployable and excluded from primary claims",
        ],
    }
    write_json(run_dir / "workload_config_receipt.json", workload)
    write_json(run_dir / "drift_schedule_receipt.json", drift)
    write_json(run_dir / "no_leakage_receipt.json", no_leakage)


def _calibrate_strong_baseline(
    *,
    config_path: Path,
    config: dict[str, Any],
    variant_id: str,
    run_dir: Path,
    mock_model: bool,
) -> dict[str, Any]:
    catalog = read_json(config_path.parent / "policy_catalog.json")
    candidate_policies = [None] + [
        str(policy["policy_id"])
        for policy in catalog["policies"]
        if policy.get("eligible_for_oasg_promotion") is True
        and policy.get("policy_id") not in {"policy_retirement", "policy_tightening"}
    ]
    all_rows: list[dict[str, Any]] = []
    policy_by_family: dict[str, str | None] = {}
    for family in FAMILIES:
        best_policy: str | None = None
        best_summary: dict[str, Any] | None = None
        for policy_id in candidate_policies:
            rows = _run_policy_subset(
                config=config,
                run_dir=run_dir,
                variant_id=variant_id,
                family=family,
                phase_roles={"calibration"},
                policy_id=policy_id,
                condition="strong_calibration_candidate",
                mock_model=mock_model,
            )
            for row in rows:
                row["calibration_candidate_policy_id"] = policy_id
            all_rows.extend(rows)
            summary = condition_summary(rows)
            if _summary_better(summary, best_summary):
                best_summary = summary
                best_policy = policy_id
        policy_by_family[family] = best_policy
    weak_rows = [row for row in all_rows if row.get("calibration_candidate_policy_id") is None]
    strong_rows: list[dict[str, Any]] = []
    for family, policy_id in policy_by_family.items():
        strong_rows.extend(
            _run_policy_subset(
                config=config,
                run_dir=run_dir,
                variant_id=variant_id,
                family=family,
                phase_roles={"calibration"},
                policy_id=policy_id,
                condition="strong_calibration_selected",
                mock_model=mock_model,
            )
        )
    weak_summary = condition_summary(weak_rows)
    strong_summary = condition_summary(strong_rows)
    weak_debt = int(weak_summary["operational_debt_auc"])
    strong_debt = int(strong_summary["operational_debt_auc"])
    reduction = reduction_bps(
        baseline=weak_debt,
        candidate=strong_debt,
    )
    if weak_debt == 0 and strong_debt == 0:
        status = "strong_baseline_calibrated_phase_a_ceiling"
    elif strong_debt > weak_debt:
        status = "strong_baseline_not_qualified"
    else:
        status = (
            "strong_baseline_calibrated"
            if reduction >= int(config.get("strong_baseline_min_reduction_bps", 1000))
            else "strong_baseline_not_qualified"
        )
    receipt = {
        "receipt_type": "strong_baseline_calibration_receipt",
        "status": status,
        "variant_id": variant_id,
        "policy_by_family": policy_by_family,
        "policy_hash": receipt_hash(policy_by_family),
        "weak_summary": weak_summary,
        "strong_summary": strong_summary,
        "strong_static_debt_reduction_bps": reduction,
        "phase_scope": "phase_a_calibration_only",
        "no_leakage_statement": "no post-drift task rows were used for calibration",
        "config_hash": receipt_hash(config),
        "policy_catalog_hash": receipt_hash(read_json(config_path.parent / "policy_catalog.json")),
    }
    write_json(run_dir / variant_id / "strong_baseline_calibration_rows.json", all_rows)
    return receipt


def _oracle_headroom(
    *,
    config_path: Path,
    config: dict[str, Any],
    variant_id: str,
    run_dir: Path,
    strong_policy: dict[str, str | None],
    mock_model: bool,
) -> dict[str, Any]:
    catalog = read_json(config_path.parent / "policy_catalog.json")
    policies = [
        str(policy["policy_id"])
        for policy in catalog["policies"]
        if policy.get("eligible_for_oasg_promotion") is True
    ]
    probe_receipts: list[dict[str, Any]] = []
    phase_items = [
        phase for phase in phase_schedule(variant_id) if phase["phase_role"] == "post_drift"
    ]
    first_epoch_only = bool(config.get("oracle_probe_first_epoch_only", False))
    for phase in phase_items:
        phase_id = str(phase["phase_id"])
        for family in FAMILIES:
            baseline_policy = strong_policy.get(family)
            baseline_rows = _run_policy_subset(
                config=config,
                run_dir=run_dir,
                variant_id=variant_id,
                family=family,
                phase_ids={phase_id},
                policy_id=baseline_policy,
                condition="oracle_strong_probe",
                mock_model=mock_model,
                first_epoch_only=first_epoch_only,
            )
            baseline_summary = condition_summary(baseline_rows)
            best_policy = baseline_policy
            best_summary = baseline_summary
            for policy_id in policies:
                candidate_rows = _run_policy_subset(
                    config=config,
                    run_dir=run_dir,
                    variant_id=variant_id,
                    family=family,
                    phase_ids={phase_id},
                    policy_id=policy_id,
                    condition="oracle_candidate_probe",
                    mock_model=mock_model,
                    first_epoch_only=first_epoch_only,
                )
                candidate_summary = condition_summary(candidate_rows)
                if _summary_better(candidate_summary, best_summary):
                    best_summary = candidate_summary
                    best_policy = policy_id
            delta = best_summary["operational_debt_auc"] - baseline_summary["operational_debt_auc"]
            probe_receipts.append(
                {
                    "variant_id": variant_id,
                    "phase_id": phase_id,
                    "phase_category": phase["phase_category"],
                    "family": family,
                    "baseline_policy_id": baseline_policy,
                    "oracle_policy_id": best_policy,
                    "debt_auc_delta": delta,
                    "baseline_summary": baseline_summary,
                    "oracle_summary": best_summary,
                    "status": "oracle_improved" if delta < 0 else "oracle_not_improved",
                }
            )
    improved = [receipt for receipt in probe_receipts if receipt["status"] == "oracle_improved"]
    return {
        "receipt_type": "oracle_headroom_receipt",
        "status": "oracle_headroom_present" if improved else "oracle_headroom_absent",
        "variant_id": variant_id,
        "probe_count": len(probe_receipts),
        "improved_probe_count": len(improved),
        "probe_receipts": probe_receipts,
        "config_hash": receipt_hash(config),
        "non_deployable_control": True,
    }


def _run_online_conditions(
    *,
    config: dict[str, Any],
    variant_id: str,
    run_dir: Path,
    strong_policy: dict[str, str | None],
    oracle: dict[str, Any],
    mock_model: bool,
) -> dict[str, Any]:
    active_by_seed: dict[str, list[dict[str, Any]]] = {}
    rejection_count = 0
    for seed in [int(seed) for seed in config["replicate_seeds"]]:
        seed_dir = run_dir / variant_id / f"seed_{seed}"
        tasks = read_jsonl(seed_dir / "tasks_confirmatory.jsonl")
        _run_diagnostic_conditions(
            config=config,
            seed=seed,
            seed_dir=seed_dir,
            tasks=tasks,
            strong_policy=strong_policy,
            oracle=oracle,
            mock_model=mock_model,
        )
        for condition in MAIN_CONDITIONS:
            rows = _run_online_condition(
                config=config,
                condition=condition,
                tasks=tasks,
                strong_policy=strong_policy,
                seed=str(seed),
                mock_model=mock_model,
            )
            active_by_seed.setdefault(str(seed), []).extend(
                _active_changes_from_rows(rows, condition=condition)
            )
            _write_condition(seed_dir, condition, rows)
            if condition == "oasg_adaptive_from_strong":
                rejection_count += sum(1 for row in rows if row.get("candidate_rejected"))
    active_seed_count = sum(1 for changes in active_by_seed.values() if changes)
    return {
        "receipt_type": "adaptive_readiness_receipt",
        "status": "adaptive_readiness_passed" if active_seed_count > 0 else "adaptive_readiness_failed",
        "variant_id": variant_id,
        "active_seed_count": active_seed_count,
        "active_changes_by_seed": active_by_seed,
        "rejection_count": rejection_count,
        "config_hash": receipt_hash(config),
    }


def _run_online_condition(
    *,
    config: dict[str, Any],
    condition: str,
    tasks: list[dict[str, Any]],
    strong_policy: dict[str, str | None],
    seed: str,
    mock_model: bool,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    active_policy_by_family = dict(strong_policy)
    rule_policy_by_family = dict(strong_policy)
    for epoch in sorted({int(task["epoch"]) for task in tasks}):
        epoch_tasks = [task for task in tasks if int(task["epoch"]) == epoch]
        epoch_rows: list[dict[str, Any]] = []
        for task in epoch_tasks:
            family = str(task["family"])
            policy_id = _policy_for_condition(
                condition=condition,
                family=family,
                strong_policy=strong_policy,
                active_policy_by_family=active_policy_by_family,
                rule_policy_by_family=rule_policy_by_family,
            )
            mutation_id = (
                f"mut_{policy_id}_{family}_{task['phase_id']}"
                if condition == "oasg_adaptive_from_strong"
                and task.get("phase_role") == "post_drift"
                and policy_id != strong_policy.get(family)
                else None
            )
            row = run_task(
                task=task,
                condition=condition,
                config=config,
                policy_id=policy_id,
                active_mutation_id=mutation_id,
                mock_model=mock_model,
            ).to_dict()
            row["seed"] = seed
            epoch_rows.append(row)
        rows.extend(epoch_rows)
        if condition == "rule_adaptive_control":
            _update_rule_policy(rule_policy_by_family, epoch_rows)
        if (
            condition == "oasg_adaptive_from_strong"
            and any(row.get("phase_role") == "post_drift" for row in epoch_rows)
        ):
            promoted, rejected = _promote_from_prior_epoch(
                config=config,
                epoch_rows=epoch_rows,
                strong_policy=strong_policy,
                active_policy_by_family=active_policy_by_family,
                mock_model=mock_model,
            )
            for row in epoch_rows:
                row["promoted_after_epoch"] = promoted
                row["candidate_rejected"] = bool(rejected)
    return rows


def _run_diagnostic_conditions(
    *,
    config: dict[str, Any],
    seed: int,
    seed_dir: Path,
    tasks: list[dict[str, Any]],
    strong_policy: dict[str, str | None],
    oracle: dict[str, Any],
    mock_model: bool,
) -> None:
    weak_tasks = [
        task
        for task in tasks
        if task["phase_role"] == "calibration"
        or (task["phase_role"] == "post_drift" and int(task["phase_epoch"]) == 1)
    ]
    weak_rows = [
        run_task(
            task=task,
            condition="weak_fixed",
            config=config,
            policy_id=None,
            mock_model=mock_model,
        ).to_dict()
        for task in weak_tasks
    ]
    for row in weak_rows:
        row["seed"] = str(seed)
    _write_condition(seed_dir, "weak_fixed", weak_rows)

    oracle_map = _oracle_policy_map(oracle)
    oracle_tasks = [
        task
        for task in tasks
        if task["phase_role"] == "post_drift" and int(task["phase_epoch"]) == 1
    ]
    oracle_rows = []
    for task in oracle_tasks:
        key = (str(task["phase_id"]), str(task["family"]))
        policy_id = oracle_map.get(key, strong_policy.get(str(task["family"])))
        row = run_task(
            task=task,
            condition="strong_static_oracle_phase_control",
            config=config,
            policy_id=policy_id,
            mock_model=mock_model,
        ).to_dict()
        row["seed"] = str(seed)
        oracle_rows.append(row)
    _write_condition(seed_dir, "strong_static_oracle_phase_control", oracle_rows)


def _write_condition(seed_dir: Path, condition: str, rows: list[dict[str, Any]]) -> None:
    condition_dir = seed_dir / condition
    condition_dir.mkdir(parents=True, exist_ok=True)
    write_json(condition_dir / "task_results.json", rows)
    write_history(condition_dir / "history.jsonl", condition, rows)
    write_json(condition_dir / "history_receipt.json", verify_jsonl(condition_dir / "history.jsonl").to_dict())
    write_json(condition_dir / "summary.json", condition_summary(rows))


def _promote_from_prior_epoch(
    *,
    config: dict[str, Any],
    epoch_rows: list[dict[str, Any]],
    strong_policy: dict[str, str | None],
    active_policy_by_family: dict[str, str | None],
    mock_model: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    promoted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    families = sorted(
        {
            str(row["family"])
            for row in epoch_rows
            if task_debt(row) > 0 or _retirement_pressure(row)
        }
    )
    for family in families[: int(config.get("max_candidates_per_optimization", 3))]:
        source_rows = [row for row in epoch_rows if row["family"] == family][:2]
        if not source_rows:
            continue
        active_policy = active_policy_by_family.get(family, strong_policy.get(family))
        baseline_summary = condition_summary(source_rows)
        best_policy = active_policy
        best_summary = baseline_summary
        best_candidate_rows: list[dict[str, Any]] = []
        for policy_id in _candidate_policies_for_family(family):
            if policy_id == active_policy:
                continue
            candidate_rows = [
                run_task(
                    task=dict(prior_row["task_payload"]),
                    condition="oasg_candidate_canary",
                    config=config,
                    policy_id=policy_id,
                    mock_model=mock_model,
                ).to_dict()
                for prior_row in source_rows
                if isinstance(prior_row.get("task_payload"), dict)
            ]
            candidate_summary = condition_summary(candidate_rows)
            if _summary_better(candidate_summary, best_summary):
                best_summary = candidate_summary
                best_policy = policy_id
                best_candidate_rows = candidate_rows
        if best_policy != active_policy and _summary_better(best_summary, baseline_summary):
            active_policy_by_family[family] = best_policy
            mutation_type = (
                "retirement"
                if best_policy in {"policy_retirement", "policy_tightening"}
                else "promotion"
            )
            promoted.append(
                {
                    "family": family,
                    "policy_id": best_policy,
                    "mutation_id": f"mut_{best_policy}_{family}_{source_rows[0]['phase_id']}",
                    "mutation_type": mutation_type,
                    "baseline_summary": baseline_summary,
                    "candidate_summary": best_summary,
                    "canary_task_ids": [str(row["task_id"]) for row in source_rows],
                    "positive_evidence_hash": receipt_hash(
                        {"candidate_rows": best_candidate_rows}
                    ),
                    "evidence_source": "runner_observed_canary_rows",
                }
            )
        else:
            rejected.append({"family": family, "reason": "no_canary_improvement"})
    return promoted, rejected


def _candidate_policies_for_family(family: str) -> list[str]:
    base = [
        "strict_json_minimal",
        "schema_keys_only",
        "single_repair_retry",
        "context_shortening_policy",
        "policy_retirement",
        "policy_tightening",
    ]
    if family == "safe_python_expression":
        return [
            "family_safe_expr_prompt",
            "single_repair_retry",
            "context_shortening_policy",
            "policy_retirement",
        ]
    if family in {"validator_receipt", "replay_rollback_receipt"}:
        return [
            "receipt_template_only",
            "strict_json_minimal",
            "single_repair_retry",
            "policy_retirement",
            "policy_tightening",
        ]
    return base


def _update_rule_policy(rule_policy_by_family: dict[str, str | None], rows: list[dict[str, Any]]) -> None:
    failures = [row for row in rows if task_debt(row) > 0]
    mixed_pressure = [
        row
        for row in rows
        if row.get("phase_category") == "mixed" and _retirement_pressure(row)
    ]
    for family in sorted({str(row["family"]) for row in mixed_pressure}):
        rule_policy_by_family[family] = "policy_retirement"
    if not failures:
        return
    for family in sorted({str(row["family"]) for row in failures}):
        family_rows = [row for row in failures if row["family"] == family]
        parse_failures = sum(1 for row in family_rows if row.get("parsed") is not True)
        validation_failures = sum(1 for row in family_rows if row.get("validation_passed") is not True)
        rollback_gap = sum(int(row.get("rollback_gap", 0)) for row in family_rows)
        if rollback_gap and family in {"replay_rollback_receipt", "validator_receipt"}:
            rule_policy_by_family[family] = "receipt_template_only"
        elif parse_failures:
            rule_policy_by_family[family] = "strict_json_minimal"
        elif validation_failures and family == "safe_python_expression":
            rule_policy_by_family[family] = "family_safe_expr_prompt"
        elif validation_failures:
            rule_policy_by_family[family] = "schema_keys_only"


def _retirement_pressure(row: dict[str, Any]) -> bool:
    policy = row.get("configured_policy_id")
    return (
        row.get("phase_category") == "mixed"
        and policy
        in {
            "single_repair_retry",
            "receipt_template_only",
            "phase_c_structural_receipt_policy",
            "policy_tightening",
        }
        and (
            int(row.get("queue_pressure", 0)) > 0
            or int(row.get("retries", 0)) > 0
            or int(row.get("prompt_chars", 0)) + int(row.get("output_chars", 0))
            > int(row.get("baseline_char_budget", 0))
        )
    )


def _policy_for_condition(
    *,
    condition: str,
    family: str,
    strong_policy: dict[str, str | None],
    active_policy_by_family: dict[str, str | None],
    rule_policy_by_family: dict[str, str | None],
) -> str | None:
    if condition == "rule_adaptive_control":
        return rule_policy_by_family.get(family)
    if condition == "oasg_adaptive_from_strong":
        return active_policy_by_family.get(family)
    return strong_policy.get(family)


def _run_policy_subset(
    *,
    config: dict[str, Any],
    run_dir: Path,
    variant_id: str,
    family: str,
    policy_id: str | None,
    condition: str,
    mock_model: bool,
    phase_roles: set[str] | None = None,
    phase_ids: set[str] | None = None,
    first_epoch_only: bool = False,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for seed in [int(seed) for seed in config["replicate_seeds"]]:
        tasks = [
            task
            for task in read_jsonl(
                run_dir / variant_id / f"seed_{seed}" / "tasks_confirmatory.jsonl"
            )
            if task["family"] == family
            and (phase_roles is None or task["phase_role"] in phase_roles)
            and (phase_ids is None or task["phase_id"] in phase_ids)
        ]
        if first_epoch_only and tasks:
            first_epoch = min(int(task["epoch"]) for task in tasks)
            tasks = [task for task in tasks if int(task["epoch"]) == first_epoch]
        for task in tasks:
            row = run_task(
                task=task,
                condition=condition,
                config=config,
                policy_id=policy_id,
                mock_model=mock_model,
            ).to_dict()
            row["seed"] = str(seed)
            rows.append(row)
    return rows


def _oracle_policy_map(oracle: dict[str, Any]) -> dict[tuple[str, str], str | None]:
    mapping: dict[tuple[str, str], str | None] = {}
    for receipt in oracle.get("probe_receipts", []):
        mapping[(str(receipt["phase_id"]), str(receipt["family"]))] = receipt.get("oracle_policy_id")
    return mapping


def _active_changes_from_rows(rows: list[dict[str, Any]], *, condition: str) -> list[dict[str, Any]]:
    if condition != "oasg_adaptive_from_strong":
        return []
    changes: dict[str, dict[str, Any]] = {}
    for row in rows:
        for mutation_id in row.get("active_mutation_ids", []):
            changes[str(mutation_id)] = {
                "mutation_id": str(mutation_id),
                "variant_id": str(row.get("variant_id", "")),
                "phase_id": str(row.get("phase_id", "")),
                "family": str(row.get("family", "")),
                "policy_id": row.get("configured_policy_id"),
            }
    return list(changes.values())


def _summary_better(candidate: dict[str, Any], baseline: dict[str, Any] | None) -> bool:
    if baseline is None:
        return True
    cand_key = (
        int(candidate.get("operational_debt_auc", 0)),
        int(candidate.get("cost_to_close_units", 0)),
        -int(candidate.get("closed", 0)),
    )
    base_key = (
        int(baseline.get("operational_debt_auc", 0)),
        int(baseline.get("cost_to_close_units", 0)),
        -int(baseline.get("closed", 0)),
    )
    return cand_key < base_key


def _new_run_dir(base: Path) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = base / stamp
    counter = 1
    while path.exists():
        counter += 1
        path = base / f"{stamp}_{counter}"
    path.mkdir(parents=True)
    return path


def _finish(run_dir: Path, runs_dir: Path) -> None:
    latest = runs_dir / "latest"
    if latest.exists():
        shutil.rmtree(latest)
    shutil.copytree(run_dir, latest)
    write_json(runs_dir / "latest_pointer.json", {"latest": run_dir.name})


def _write_interruption(run_dir: Path, status: str, detail: dict[str, Any]) -> None:
    write_json(
        run_dir / "interruption_receipt.json",
        {
            "receipt_type": "interruption_receipt",
            "status": status,
            "detail_hash": receipt_hash(detail),
            "detail": detail,
        },
    )


def _preflight(config: dict[str, Any]) -> dict[str, Any]:
    endpoint = str(config.get("ollama_endpoint", "http://127.0.0.1:11434")).rstrip("/")
    if endpoint not in {"http://127.0.0.1:11434", "http://localhost:11434"}:
        return {"status": "invalid_endpoint", "endpoint": endpoint}
    try:
        with urlopen(f"{endpoint}/api/tags", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError) as exc:
        return {"status": "ollama_unavailable", "error": str(exc)}
    names = sorted(str(model.get("name", "")) for model in payload.get("models", []))
    return {
        "status": "ok" if config.get("model") in names else "model_missing",
        "model": config.get("model"),
        "available_models": names,
    }


if __name__ == "__main__":
    raise SystemExit(main())
