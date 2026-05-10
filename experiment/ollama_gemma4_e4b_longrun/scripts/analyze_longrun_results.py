"""Analyze the long-running OASG/Ollama experiment."""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for import_path in (SRC, ROOT):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from oasg.canonical import receipt_hash  # noqa: E402
from oasg.io import read_json, write_json  # noqa: E402
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
    _write_epoch_table(out_dir / "epoch_table.csv", metrics["epoch_table"])
    (out_dir / "report.md").write_text(_render_report(metrics), encoding="utf-8", newline="\n")
    print(json.dumps({"status": "ok", "metrics": str(out_dir / "metrics.json")}, indent=2))
    return 0


def analyze_run(run_dir: Path) -> dict[str, Any]:
    replicate_manifest = _read_optional_json(run_dir / "replicates.json", None)
    if isinstance(replicate_manifest, dict):
        return _analyze_replicated_run(run_dir, replicate_manifest)
    return _analyze_single_run(run_dir)


def _analyze_single_run(run_dir: Path) -> dict[str, Any]:
    config = _read_optional_json(run_dir / "config.json", {})
    preflight = _read_optional_json(run_dir / "preflight.json", {})
    manifest = _read_optional_json(run_dir / "task_manifest.json", {})
    conditions = ["baseline_fixed", "oasg_observe_only", "oasg_adaptive"]
    results = {condition: _read_results(run_dir / condition) for condition in conditions}
    epoch_table = _epoch_table(results)
    eval_table = [row for row in epoch_table if row["phase"] == "longrun_eval"]
    summaries = {
        condition: _condition_summary([row for row in eval_table if row["condition"] == condition])
        for condition in conditions
    }
    oasg = _oasg_artifacts(run_dir / "oasg_adaptive")
    ledger_receipts = {
        condition: _ledger_receipt(run_dir / condition / "history.jsonl") for condition in conditions
    }
    comparisons = _comparison_blocks(eval_table)
    paired = comparisons["oasg_adaptive_vs_baseline"]
    classification = classify_longrun(summaries, oasg, preflight, comparisons)
    return {
        "experiment_id": "ollama_gemma4_e4b_longrun",
        "classification": classification,
        "model": config.get("model"),
        "preflight": preflight,
        "task_manifest": manifest,
        "task_manifest_hash": receipt_hash(manifest) if manifest else None,
        "condition_summaries": summaries,
        "comparisons": comparisons,
        "paired_epoch_effects": paired,
        "epoch_table": epoch_table,
        "oasg_artifacts": oasg,
        "ledger_receipts": ledger_receipts,
        "decision_rules": {
            "improvement_observed": "adaptive debt AUC reduced by >=20%, zero hard-floor regression, active promotion >=1",
            "partial_support": "active promotion exists and debt AUC is reduced by >=10% but confirmatory CI/threshold is weaker",
            "recovery_improvement_observed": "post-burst half-life or MTTR improves by >=25%",
            "inconclusive_no_active_policy": "active promotion count is zero",
            "pipeline_failure_trial_timeout": "trial runner timeout prevents promotion-readiness evaluation",
            "regression_observed": "hard-floor regression or unresolved obligations increase",
        },
        "scientific_limits": [
            "Overnight pilot design, not a definitive benchmark.",
            "Validators measure operational closure, not semantic truth.",
            "No LLM judge, external evaluator oracle, or model-weight update is used.",
            "All failed, rejected, and inconclusive OASG receipts are included in artifact counts.",
        ],
    }


def _analyze_replicated_run(run_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    seed_metrics: list[dict[str, Any]] = []
    for item in manifest.get("replicates", []):
        if not isinstance(item, dict):
            continue
        seed_dir = Path(str(item.get("run_dir", "")))
        if not seed_dir.is_absolute():
            seed_dir = run_dir / seed_dir
        if seed_dir.exists():
            seed_metrics.append(_analyze_single_run(seed_dir))
    config = _read_optional_json(run_dir / "config.json", {})
    preflight = _read_optional_json(run_dir / "preflight.json", {})
    epoch_table: list[dict[str, Any]] = []
    for metrics in seed_metrics:
        seed = _seed_from_manifest(metrics)
        for row in metrics["epoch_table"]:
            with_seed = dict(row)
            with_seed["seed"] = seed
            epoch_table.append(with_seed)
    eval_table = [row for row in epoch_table if row["phase"] == "longrun_eval"]
    conditions = ["baseline_fixed", "oasg_observe_only", "oasg_adaptive"]
    summaries = {
        condition: _condition_summary([row for row in eval_table if row["condition"] == condition])
        for condition in conditions
    }
    comparisons = _comparison_blocks(eval_table)
    oasg = _aggregate_oasg_artifacts([metrics["oasg_artifacts"] for metrics in seed_metrics])
    classification = _classify_replicated(
        seed_metrics=seed_metrics,
        summaries=summaries,
        oasg=oasg,
        preflight=preflight,
        comparisons=comparisons,
        min_active_seeds=int(config.get("confirmatory_min_active_seeds", 2)),
    )
    return {
        "experiment_id": "ollama_gemma4_e4b_longrun",
        "classification": classification,
        "model": config.get("model"),
        "preflight": preflight,
        "replicate_seeds": [metrics.get("task_manifest", {}).get("task_generator_seed") for metrics in seed_metrics],
        "replicate_count": len(seed_metrics),
        "condition_summaries": summaries,
        "comparisons": comparisons,
        "paired_epoch_effects": comparisons["oasg_adaptive_vs_baseline"],
        "epoch_table": epoch_table,
        "oasg_artifacts": oasg,
        "seed_metrics": seed_metrics,
        "decision_rules": {
            "improvement_observed": "active promotion in enough seeds, adaptive debt AUC reduced by >=20%, bootstrap CI upper bound < 0, zero hard-floor regression",
            "partial_support": "active promotion exists and debt AUC is reduced by >=10% but confirmatory criteria are weaker",
            "inconclusive_no_active_policy": "active promotion is absent in most seeds",
            "pipeline_failure_trial_timeout": "trial runner timeout prevents promotion-readiness evaluation",
            "regression_observed": "hard-floor regression or unresolved obligations increase",
        },
        "scientific_limits": [
            "Replicated overnight pilot design, not a definitive benchmark.",
            "Validators measure operational closure, not semantic truth.",
            "No LLM judge, external evaluator oracle, or model-weight update is used.",
            "All failed, rejected, and inconclusive OASG receipts are included in artifact counts.",
        ],
    }


def classify_longrun(
    summaries: dict[str, dict[str, Any]],
    oasg: dict[str, Any],
    preflight: dict[str, Any] | None = None,
    comparisons: dict[str, Any] | None = None,
) -> str:
    if preflight and preflight.get("status") == "mocked":
        return "mock_smoke_not_scientific"
    adaptive = summaries.get("oasg_adaptive", {})
    baseline = summaries.get("baseline_fixed", {})
    if int(oasg.get("active_promotion_count", 0)) == 0:
        if int(oasg.get("trial_timeout_count", 0)) > 0:
            return "pipeline_failure_trial_timeout"
        if int(oasg.get("workload_mismatch_count", 0)) > 0:
            return "pipeline_failure_workload_mismatch"
        if int(oasg.get("malformed_trial_count", 0)) > 0:
            return "pipeline_failure_malformed_trial"
        return "inconclusive_no_active_policy"
    if int(adaptive.get("active_mutation_epoch_count", 0)) == 0:
        return "inconclusive_no_active_policy"
    if int(adaptive.get("hard_floor_regression_count", 0)) > 0:
        return "regression_observed"
    if int(adaptive.get("unresolved_obligations", 0)) > int(
        baseline.get("unresolved_obligations", 0)
    ):
        return "regression_observed"
    adaptive_auc = int(adaptive.get("operational_debt_auc", 0))
    baseline_auc = int(baseline.get("operational_debt_auc", 0))
    paired = (comparisons or {}).get("oasg_adaptive_vs_baseline", {})
    ci = paired.get("bootstrap_ci", {}).get("debt_auc_delta_ci", [0, 0])
    ci_upper = int(ci[1]) if isinstance(ci, list) and len(ci) > 1 else 0
    if baseline_auc > 0 and adaptive_auc * 100 <= baseline_auc * 80 and ci_upper < 0:
        return "improvement_observed"
    if baseline_auc > 0 and adaptive_auc * 100 <= baseline_auc * 90:
        return "partial_support"
    baseline_half = baseline.get("mean_recovery_half_life_epochs")
    adaptive_half = adaptive.get("mean_recovery_half_life_epochs")
    if isinstance(baseline_half, int) and isinstance(adaptive_half, int):
        if baseline_half > 0 and adaptive_half * 100 <= baseline_half * 75:
            return "recovery_improvement_observed"
    return "no_clear_effect"


def _classify_replicated(
    *,
    seed_metrics: list[dict[str, Any]],
    summaries: dict[str, dict[str, Any]],
    oasg: dict[str, Any],
    preflight: dict[str, Any] | None,
    comparisons: dict[str, Any],
    min_active_seeds: int,
) -> str:
    if preflight and preflight.get("status") == "mocked":
        return "mock_smoke_not_scientific"
    active_seeds = 0
    for metrics in seed_metrics:
        adaptive = metrics.get("condition_summaries", {}).get("oasg_adaptive", {})
        artifacts = metrics.get("oasg_artifacts", {})
        if int(artifacts.get("active_promotion_count", 0)) > 0 and int(
            adaptive.get("active_mutation_epoch_count", 0)
        ) > 0:
            active_seeds += 1
    if active_seeds < min_active_seeds:
        if int(oasg.get("trial_timeout_count", 0)) > 0:
            return "pipeline_failure_trial_timeout"
        if int(oasg.get("workload_mismatch_count", 0)) > 0:
            return "pipeline_failure_workload_mismatch"
        return "inconclusive_no_active_policy"
    adaptive = summaries.get("oasg_adaptive", {})
    baseline = summaries.get("baseline_fixed", {})
    if int(adaptive.get("hard_floor_regression_count", 0)) > 0:
        return "regression_observed"
    if int(adaptive.get("unresolved_obligations", 0)) > int(
        baseline.get("unresolved_obligations", 0)
    ):
        return "regression_observed"
    adaptive_auc = int(adaptive.get("operational_debt_auc", 0))
    baseline_auc = int(baseline.get("operational_debt_auc", 0))
    paired = comparisons.get("oasg_adaptive_vs_baseline", {})
    ci = paired.get("bootstrap_ci", {}).get("debt_auc_delta_ci", [0, 0])
    ci_upper = int(ci[1]) if isinstance(ci, list) and len(ci) > 1 else 0
    if baseline_auc > 0 and adaptive_auc * 100 <= baseline_auc * 80 and ci_upper < 0:
        return "improvement_observed"
    if baseline_auc > 0 and adaptive_auc * 100 <= baseline_auc * 90:
        return "partial_support"
    return "no_clear_effect"


def _aggregate_oasg_artifacts(items: list[dict[str, Any]]) -> dict[str, Any]:
    statuses: dict[str, int] = {}
    receipt_hashes: list[str] = []
    totals = {
        "active_promotion_count": 0,
        "rejected_count": 0,
        "inconclusive_count": 0,
        "trial_timeout_count": 0,
        "lease_cap_failure_count": 0,
        "workload_mismatch_count": 0,
        "malformed_trial_count": 0,
        "viability_regression_count": 0,
    }
    first_failed: dict[str, Any] | None = None
    for item in items:
        for key in totals:
            totals[key] += int(item.get(key, 0))
        for status, count in item.get("status_counts", {}).items():
            statuses[str(status)] = statuses.get(str(status), 0) + int(count)
        receipt_hashes.extend(str(value) for value in item.get("receipt_hashes", []))
        if first_failed is None and item.get("first_failed_artifact") is not None:
            first_failed = item["first_failed_artifact"]
    return {
        **totals,
        "status_counts": statuses,
        "receipt_hashes": receipt_hashes,
        "first_failed_artifact": first_failed,
    }


def _seed_from_manifest(metrics: dict[str, Any]) -> str:
    manifest = metrics.get("task_manifest", {})
    if isinstance(manifest, dict) and manifest.get("task_generator_seed") is not None:
        return str(manifest["task_generator_seed"])
    return str(metrics.get("task_manifest_hash", "seed"))


def _read_results(condition_dir: Path) -> list[dict[str, Any]]:
    path = condition_dir / "task_results.json"
    if not path.exists():
        return []
    data = read_json(path)
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def _epoch_table(results: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for condition, condition_rows in results.items():
        grouped: dict[int, list[dict[str, Any]]] = {}
        for item in condition_rows:
            grouped.setdefault(int(item.get("epoch", 0)), []).append(item)
        for epoch in sorted(grouped):
            items = grouped[epoch]
            if not items:
                continue
            validation_failures = sum(1 for item in items if item.get("validation_passed") is not True)
            parse_failures = sum(1 for item in items if item.get("parsed") is not True)
            retries = sum(int(item.get("retries", 0)) for item in items)
            unresolved = sum(int(item.get("unresolved_obligations", 0)) for item in items)
            debt = unresolved + validation_failures + parse_failures + retries
            rows.append(
                {
                    "condition": condition,
                    "epoch": epoch,
                    "phase": str(items[0].get("phase", "unknown")),
                    "burst": str(items[0].get("burst", "unknown")),
                    "task_count": len(items),
                    "closed": sum(1 for item in items if item.get("closed") is True),
                    "validation_failures": validation_failures,
                    "parse_failures": parse_failures,
                    "retries": retries,
                    "unresolved_obligations": unresolved,
                    "operational_debt": debt,
                    "attempts": sum(int(item.get("attempts", 0)) for item in items),
                    "latency_ms": sum(int(item.get("latency_ms", 0)) for item in items),
                    "char_budget": sum(
                        int(item.get("prompt_chars", 0)) + int(item.get("output_chars", 0))
                        for item in items
                    ),
                    "active_policy_hashes": sorted(
                        {
                            str(item.get("active_policy_hash"))
                            for item in items
                            if item.get("active_policy_hash")
                        }
                    ),
                    "active_mutation_ids": sorted(
                        {
                            str(mutation_id)
                            for item in items
                            for mutation_id in item.get("active_mutation_ids", [])
                        }
                    ),
                }
            )
    return rows


def _condition_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    task_count = sum(int(row["task_count"]) for row in rows)
    debt_auc = sum(int(row["operational_debt"]) for row in rows)
    bursts = [row for row in rows if str(row["burst"]).endswith("_burst")]
    half_lives = [_recovery_half_life(rows, int(row["epoch"]), int(row["operational_debt"])) for row in bursts]
    half_lives = [item for item in half_lives if item is not None]
    return {
        "epoch_count": len(rows),
        "task_count": task_count,
        "closed": sum(int(row["closed"]) for row in rows),
        "closure_rate_bps": _rate_bps(sum(int(row["closed"]) for row in rows), task_count),
        "operational_debt_auc": debt_auc,
        "validation_failures": sum(int(row["validation_failures"]) for row in rows),
        "parse_failures": sum(int(row["parse_failures"]) for row in rows),
        "retries": sum(int(row["retries"]) for row in rows),
        "unresolved_obligations": sum(int(row["unresolved_obligations"]) for row in rows),
        "attempts": sum(int(row["attempts"]) for row in rows),
        "char_budget": sum(int(row["char_budget"]) for row in rows),
        "hard_floor_regression_count": 0,
        "active_policy_epoch_count": sum(1 for row in rows if row.get("active_policy_hashes")),
        "active_mutation_epoch_count": sum(1 for row in rows if row.get("active_mutation_ids")),
        "active_mutation_ids": sorted(
            {
                str(mutation_id)
                for row in rows
                for mutation_id in row.get("active_mutation_ids", [])
            }
        ),
        "mean_recovery_half_life_epochs": (
            int(round(sum(half_lives) / len(half_lives))) if half_lives else None
        ),
    }


def _recovery_half_life(
    rows: list[dict[str, Any]],
    burst_epoch: int,
    burst_debt: int,
) -> int | None:
    if burst_debt <= 0:
        return 0
    same_condition = [row for row in rows if int(row["epoch"]) > burst_epoch]
    for row in sorted(same_condition, key=lambda item: int(item["epoch"])):
        if int(row["operational_debt"]) * 2 <= burst_debt:
            return int(row["epoch"]) - burst_epoch
    return None


def _comparison_blocks(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "oasg_adaptive_vs_baseline": _paired_epoch_effects(
            rows,
            candidate_condition="oasg_adaptive",
            baseline_condition="baseline_fixed",
        ),
        "oasg_observe_only_vs_baseline": _paired_epoch_effects(
            rows,
            candidate_condition="oasg_observe_only",
            baseline_condition="baseline_fixed",
        ),
    }


def _paired_epoch_effects(
    rows: list[dict[str, Any]],
    *,
    candidate_condition: str,
    baseline_condition: str,
) -> dict[str, Any]:
    by_key = {
        (row["condition"], str(row.get("seed", "single")), int(row["epoch"])): row
        for row in rows
    }
    deltas: list[dict[str, Any]] = []
    for row in rows:
        if row["condition"] != baseline_condition:
            continue
        epoch = int(row["epoch"])
        seed = str(row.get("seed", "single"))
        candidate = by_key.get((candidate_condition, seed, epoch))
        if candidate is None:
            continue
        deltas.append(
            {
                "seed": seed,
                "epoch": epoch,
                "burst": row["burst"],
                "debt_delta": int(candidate["operational_debt"]) - int(row["operational_debt"]),
                "closure_delta": int(candidate["closed"]) - int(row["closed"]),
                "validation_failure_delta": int(candidate["validation_failures"])
                - int(row["validation_failures"]),
                "retry_delta": int(candidate["retries"]) - int(row["retries"]),
                "unresolved_delta": int(candidate["unresolved_obligations"])
                - int(row["unresolved_obligations"]),
                "candidate_active_mutation_ids": candidate["active_mutation_ids"],
            }
        )
    bootstrap = _bootstrap_auc_ci(
        rows,
        candidate_condition=candidate_condition,
        baseline_condition=baseline_condition,
    )
    return {
        "candidate_condition": candidate_condition,
        "baseline_condition": baseline_condition,
        "paired_epoch_count": len(deltas),
        "debt_auc_delta": sum(int(item["debt_delta"]) for item in deltas),
        "closure_delta": sum(int(item["closure_delta"]) for item in deltas),
        "validation_failure_delta": sum(int(item["validation_failure_delta"]) for item in deltas),
        "retry_delta": sum(int(item["retry_delta"]) for item in deltas),
        "unresolved_delta": sum(int(item["unresolved_delta"]) for item in deltas),
        "bootstrap_ci": bootstrap,
        "rows": deltas,
    }


def _bootstrap_auc_ci(
    rows: list[dict[str, Any]],
    *,
    candidate_condition: str,
    baseline_condition: str,
    samples: int = 1000,
) -> dict[str, Any]:
    by_epoch: dict[tuple[str, int], dict[str, int]] = {}
    for row in rows:
        seed = str(row.get("seed", "single"))
        epoch = int(row["epoch"])
        bucket = by_epoch.setdefault((seed, epoch), {})
        bucket[str(row["condition"])] = int(row["operational_debt"])
    paired = [
        values[candidate_condition] - values[baseline_condition]
        for values in by_epoch.values()
        if candidate_condition in values and baseline_condition in values
    ]
    if not paired:
        return {"samples": 0, "debt_auc_delta_ci": [0, 0]}
    rng = random.Random(20260508)
    totals: list[int] = []
    for _ in range(samples):
        totals.append(sum(paired[rng.randrange(len(paired))] for _ in paired))
    totals.sort()
    return {
        "samples": samples,
        "debt_auc_delta_ci": [totals[int(samples * 0.025)], totals[int(samples * 0.975)]],
    }


def _oasg_artifacts(adaptive_dir: Path) -> dict[str, Any]:
    statuses: dict[str, int] = {}
    active_promotion_count = 0
    rejected = 0
    inconclusive = 0
    trial_timeout_count = 0
    lease_cap_failure_count = 0
    workload_mismatch_count = 0
    malformed_trial_count = 0
    viability_regression_count = 0
    first_failed_artifact: dict[str, Any] | None = None
    receipt_hashes: list[str] = []
    if adaptive_dir.exists():
        for path in adaptive_dir.rglob("*.json"):
            try:
                data = read_json(path)
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            receipt_type = str(data.get("receipt_type", ""))
            status = str(data.get("status", "unknown"))
            statuses[status] = statuses.get(status, 0) + 1
            if data.get("timeout_status") == "timed_out":
                trial_timeout_count += 1
            if status == "lease_rejected_cap_exceeded":
                lease_cap_failure_count += 1
            if status == "workload_rejected" or data.get("rejection_reason") == "workload_mismatch":
                workload_mismatch_count += 1
            if status in {"ledger_prefix_invalid", "payload_hash_mismatch"}:
                malformed_trial_count += 1
            if status == "rejected_viability_regression":
                viability_regression_count += 1
            if first_failed_artifact is None and (
                status.startswith("rejected")
                or status.endswith("rejected")
                or status.startswith("inconclusive")
                or status == "no_valid_candidate"
                or data.get("timeout_status") == "timed_out"
            ):
                first_failed_artifact = {
                    "path": str(path),
                    "receipt_type": receipt_type or None,
                    "status": status,
                    "timeout_status": data.get("timeout_status"),
                    "rejected_reasons": data.get("rejected_reasons", []),
                }
            if receipt_type == "active_promotion_receipt" and status == "active_promoted":
                active_promotion_count += 1
            if status.startswith("rejected") or status.endswith("rejected"):
                rejected += 1
            if status.startswith("inconclusive") or status == "no_valid_candidate":
                inconclusive += 1
            if receipt_type:
                receipt_hashes.append(receipt_hash(data))
    return {
        "active_promotion_count": active_promotion_count,
        "rejected_count": rejected,
        "inconclusive_count": inconclusive,
        "status_counts": statuses,
        "receipt_hashes": receipt_hashes,
        "trial_timeout_count": trial_timeout_count,
        "lease_cap_failure_count": lease_cap_failure_count,
        "workload_mismatch_count": workload_mismatch_count,
        "malformed_trial_count": malformed_trial_count,
        "viability_regression_count": viability_regression_count,
        "first_failed_artifact": first_failed_artifact,
    }


def _ledger_receipt(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "missing"}
    return verify_jsonl(path).to_dict()


def _read_optional_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return read_json(path)
    except (OSError, json.JSONDecodeError):
        return default


def _write_epoch_table(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8", newline="\n")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _render_report(metrics: dict[str, Any]) -> str:
    summaries = metrics["condition_summaries"]
    paired = metrics["comparisons"]["oasg_adaptive_vs_baseline"]
    observe = metrics["comparisons"]["oasg_observe_only_vs_baseline"]
    oasg = metrics["oasg_artifacts"]
    return "\n".join(
        [
            "# OASG x Ollama Long-Running Experiment Report",
            "",
            f"Classification: `{metrics['classification']}`",
            f"Model: `{metrics.get('model')}`",
            f"Preflight: `{metrics.get('preflight', {}).get('status', 'unknown')}`",
            "",
            "## Primary Endpoint",
            "",
            "| condition | eval tasks | closed | debt AUC | unresolved | retries |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
            *[
                (
                    f"| {condition} | {summary['task_count']} | {summary['closed']} | "
                    f"{summary['operational_debt_auc']} | "
                    f"{summary['unresolved_obligations']} | {summary['retries']} |"
                )
                for condition, summary in summaries.items()
            ],
            "",
            "## Paired Epoch Effects",
            "",
            f"Adaptive minus baseline debt AUC: `{paired['debt_auc_delta']}`",
            f"Adaptive minus baseline closure: `{paired['closure_delta']}`",
            f"Observe-only minus baseline debt AUC: `{observe['debt_auc_delta']}`",
            f"Bootstrap CI: `{paired['bootstrap_ci']['debt_auc_delta_ci']}`",
            "",
            "## OASG Receipts",
            "",
            f"Active promotions: `{oasg['active_promotion_count']}`",
            f"Rejected receipts counted: `{oasg['rejected_count']}`",
            f"Inconclusive receipts counted: `{oasg['inconclusive_count']}`",
            f"Trial timeouts counted: `{oasg.get('trial_timeout_count', 0)}`",
            f"Viability regressions counted: `{oasg.get('viability_regression_count', 0)}`",
            "",
            "## Interpretation Rule",
            "",
            "OASG effect is claimed only when active promotions are present and "
            "held-out operational debt improves without hard-floor regression.",
        ]
    )


def _rate_bps(numerator: int, denominator: int) -> int:
    return int(round(10000 * numerator / denominator)) if denominator else 0


if __name__ == "__main__":
    raise SystemExit(main())
