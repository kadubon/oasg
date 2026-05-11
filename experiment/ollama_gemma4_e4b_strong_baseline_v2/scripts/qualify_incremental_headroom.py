"""Stage 1: qualify incremental headroom over the strong static baseline."""

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

from generate_strong_v2_tasks import generate_strong_tasks  # noqa: E402
from oasg.canonical import receipt_hash  # noqa: E402
from oasg.io import write_jsonl  # noqa: E402
from oasg_strong_v2_trial_harness import run_trial_bundle  # noqa: E402
from strong_v2_common import condition_summary, read_json, task_debt, write_json  # noqa: E402
from strong_v2_runner import run_task  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--strong-policy-receipt", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--mock-model", action="store_true")
    args = parser.parse_args()
    receipt = qualify_incremental_headroom(
        config_path=Path(args.config),
        strong_policy_receipt_path=Path(args.strong_policy_receipt),
        out_dir=Path(args.out_dir),
        mock_model=args.mock_model,
    )
    print(json.dumps({"status": receipt["status"], "out_dir": str(args.out_dir)}, indent=2))
    return 0


def qualify_incremental_headroom(
    *,
    config_path: Path,
    strong_policy_receipt_path: Path,
    out_dir: Path,
    mock_model: bool = False,
) -> dict[str, Any]:
    config = read_json(config_path)
    incremental_catalog_path = config_path.parent / "incremental_policy_catalog.json"
    catalog = read_json(
        incremental_catalog_path if incremental_catalog_path.exists() else config_path.parent / "policy_catalog.json"
    )
    strong_policy_receipt = _complete_strong_policy_receipt(
        config=config,
        receipt=read_json(strong_policy_receipt_path),
    )
    strong_map = dict(strong_policy_receipt.get("policy_by_family", {}))
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "config.json", config)
    write_json(out_dir / "policy_catalog.json", catalog)
    write_json(out_dir / "strong_static_policy_receipt.json", strong_policy_receipt)

    seeds = [int(seed) for seed in config.get("replicate_seeds", [config["task_generator_seed"]])]
    trial_receipts: list[dict[str, Any]] = []
    qualified_candidates: list[dict[str, Any]] = []
    baseline_probe_rows: list[dict[str, Any]] = []
    for seed in seeds:
        tasks = generate_strong_tasks(
            seed=seed,
            epoch_count=int(config.get("epoch_count", 20)),
            tasks_per_epoch=8,
            warmup_epochs=int(config.get("warmup_epochs", 3)),
        )
        calibration_tasks = [task for task in tasks if task["phase"] == "calibration"]
        tasks_path = out_dir / f"seed_{seed}" / "calibration_tasks.jsonl"
        write_jsonl(tasks_path, calibration_tasks)
        for family, baseline_policy in sorted(strong_map.items()):
            bursts = sorted({str(task["burst"]) for task in calibration_tasks if task["family"] == family})
            for burst in bursts:
                family_burst_tasks = [
                    task
                    for task in calibration_tasks
                    if task["family"] == family and task["burst"] == burst
                ]
                baseline_rows = [
                    run_task(
                        task=task,
                        condition="strong_v2_headroom_baseline_probe",
                        config=config,
                        policy_id=str(baseline_policy),
                        mock_model=mock_model,
                    ).to_dict()
                    for task in family_burst_tasks
                ]
                for row in baseline_rows:
                    row["seed"] = str(seed)
                baseline_probe_rows.extend(baseline_rows)
                selected_task_ids = _select_canaries(
                    baseline_rows=baseline_rows,
                    max_count=int(config.get("promotion_canary_count", 2)),
                )
                if not selected_task_ids:
                    continue
                for policy in catalog.get("policies", []):
                    candidate_policy = str(policy["policy_id"])
                    if candidate_policy == baseline_policy:
                        continue
                    if family not in set(policy.get("families", [])):
                        continue
                    if candidate_policy in set(catalog.get("forbidden_automatic_policies", [])):
                        continue
                    trial = run_trial_bundle(
                        tasks_path=tasks_path,
                        config_path=config_path,
                        family=str(family),
                        burst=burst,
                        baseline_policy_id=str(baseline_policy),
                        candidate_policy_id=candidate_policy,
                        out_dir=(
                            out_dir
                            / "trials"
                            / f"seed_{seed}"
                            / f"{family}__{burst}__{candidate_policy}"
                        ),
                        task_ids=selected_task_ids,
                        mock_model=mock_model,
                    )
                    trial["seed"] = seed
                    trial_receipts.append(trial)
                    if trial["status"] in {"trial_debt_improved", "trial_efficiency_improved"}:
                        qualified_candidates.append(_candidate_from_trial(seed=seed, trial=trial))

    status = _headroom_status(qualified_candidates)
    receipt = {
        "receipt_type": "incremental_headroom_receipt",
        "status": status,
        "qualified_candidate_count": len(qualified_candidates),
        "qualified_candidates": qualified_candidates,
        "trial_count": len(trial_receipts),
        "trial_status_counts": _status_counts(trial_receipts),
        "baseline_probe_summary": condition_summary(baseline_probe_rows),
        "trial_receipts": trial_receipts,
        "strong_static_policy_hash": strong_policy_receipt.get("policy_hash"),
        "config_hash": receipt_hash(config),
        "policy_catalog_hash": receipt_hash(catalog),
    }
    write_json(out_dir / "incremental_headroom_receipt.json", receipt)
    write_json(out_dir / "baseline_probe_rows.json", baseline_probe_rows)
    return receipt


def _select_canaries(*, baseline_rows: list[dict[str, Any]], max_count: int) -> list[str]:
    debt_rows = [row for row in baseline_rows if task_debt(row) > 0]
    source = debt_rows if debt_rows else baseline_rows
    return [str(row["task_id"]) for row in source[:max_count]]


def _candidate_from_trial(*, seed: int, trial: dict[str, Any]) -> dict[str, Any]:
    return {
        "seed": seed,
        "family": str(trial["family"]),
        "burst": str(trial["burst"]),
        "baseline_policy_id": str(trial["baseline_policy_id"]),
        "candidate_policy_id": str(trial["candidate_policy_id"]),
        "improvement_kind": str(trial["improvement_kind"]),
        "mutation_id": (
            f"mut_{trial['candidate_policy_id']}_{trial['family']}_{trial['burst']}_"
            f"{trial['improvement_kind']}"
        ),
        "trial_receipt_hash": receipt_hash(trial),
        "debt_auc_delta": int(trial["debt_auc_delta"]),
        "cost_to_close_delta": int(trial["cost_to_close_delta"]),
        "debt_reduction_bps": int(trial["debt_reduction_bps"]),
        "cost_reduction_bps": int(trial["cost_reduction_bps"]),
        "positive_evidence": trial.get("positive_evidence", []),
    }


def _headroom_status(candidates: list[dict[str, Any]]) -> str:
    if any(candidate["improvement_kind"] == "debt" for candidate in candidates):
        return "debt_headroom_exists"
    if any(candidate["improvement_kind"] == "efficiency" for candidate in candidates):
        return "efficiency_headroom_exists"
    return "no_incremental_headroom"


def _status_counts(trials: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for trial in trials:
        status = str(trial.get("status", "unknown"))
        counts[status] = counts.get(status, 0) + 1
    return counts


def _complete_strong_policy_receipt(
    *,
    config: dict[str, Any],
    receipt: dict[str, Any],
) -> dict[str, Any]:
    policy_by_family = dict(receipt.get("policy_by_family", {}))
    defaults = dict(config.get("strong_static_default_policy_by_family", {}))
    filled: dict[str, str] = {}
    for family, policy_id in sorted(defaults.items()):
        if family not in policy_by_family:
            policy_by_family[str(family)] = str(policy_id)
            filled[str(family)] = str(policy_id)
    updated = dict(receipt)
    updated["policy_by_family"] = policy_by_family
    updated["default_filled_policy_by_family"] = filled
    updated["policy_hash"] = receipt_hash(policy_by_family)
    updated["strong_static_policy_completion"] = (
        "completed_with_preregistered_defaults" if filled else "already_complete"
    )
    return updated


if __name__ == "__main__":
    raise SystemExit(main())
