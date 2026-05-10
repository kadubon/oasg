"""Stage A qualification for the definitive OASG effect protocol."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
LONGRUN = ROOT / "experiment" / "ollama_gemma4_e4b_longrun" / "scripts"
for import_path in (Path(__file__).resolve().parent, LONGRUN, SRC, ROOT):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from definitive_common import condition_summary, reduction_bps, write_json  # noqa: E402
from generate_longrun_tasks import generate_longrun_tasks  # noqa: E402
from oasg.canonical import receipt_hash  # noqa: E402
from oasg.experiment_tools import diagnose_promotion  # noqa: E402
from oasg.io import read_json, write_jsonl  # noqa: E402
from oasg.policy import default_policy  # noqa: E402
from oasg.policy_state import WorkflowPolicyState  # noqa: E402
from run_longrun_experiment import _run_condition, _run_task  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--mock-model", action="store_true")
    args = parser.parse_args()

    receipt = qualify_mechanism(
        config_path=Path(args.config),
        out_dir=Path(args.out_dir),
        mock_model=args.mock_model,
    )
    print(json.dumps({"status": receipt["status"], "out_dir": str(args.out_dir)}, indent=2))
    return 0


def qualify_mechanism(
    *,
    config_path: Path,
    out_dir: Path,
    mock_model: bool = False,
) -> dict[str, Any]:
    config = read_json(config_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "config.json", config)
    catalog_path = config_path.parent / "policy_catalog.json"
    if catalog_path.exists():
        shutil.copyfile(catalog_path, out_dir / "policy_catalog.json")

    seeds = [int(seed) for seed in config.get("replicate_seeds", [config["task_generator_seed"]])]
    baseline_rows: list[dict[str, Any]] = []
    forced_rows: list[dict[str, Any]] = []
    seed_receipts: list[dict[str, Any]] = []

    for seed in seeds:
        tasks = generate_longrun_tasks(
            seed=seed,
            epoch_count=int(config.get("epoch_count", 20)),
            tasks_per_epoch=8,
            warmup_epochs=int(config.get("warmup_epochs", 3)),
        )
        calibration_tasks = [task for task in tasks if task["phase"] == "warmup"]
        seed_dir = out_dir / f"seed_{seed}"
        seed_dir.mkdir(parents=True, exist_ok=True)
        write_jsonl(seed_dir / "calibration_tasks.jsonl", calibration_tasks)

        seed_baseline = _run_calibration_condition(
            tasks=calibration_tasks,
            config=config,
            condition="baseline_fixed",
            forced=False,
            mock_model=mock_model,
            seed=seed,
        )
        seed_forced = _run_calibration_condition(
            tasks=calibration_tasks,
            config=config,
            condition="forced_policy_positive_control",
            forced=True,
            mock_model=mock_model,
            seed=seed,
        )
        baseline_rows.extend(seed_baseline)
        forced_rows.extend(seed_forced)
        write_json(seed_dir / "baseline_calibration_rows.json", seed_baseline)
        write_json(seed_dir / "forced_policy_calibration_rows.json", seed_forced)

        oasg_dir = seed_dir / "oasg_probe"
        probe_config = {
            **config,
            "condition_order": ["oasg_adaptive"],
            "tasks_path": str(seed_dir / "calibration_tasks.jsonl"),
            "runs_dir": str(seed_dir),
            "task_generator_seed": seed,
            "require_active_promotion_by_epoch": int(config.get("warmup_epochs", 3)),
        }
        _run_condition(
            condition="oasg_adaptive",
            tasks=calibration_tasks,
            config=probe_config,
            run_dir=oasg_dir / "oasg_adaptive",
            mock_model=mock_model,
        )
        diagnostic = diagnose_promotion(oasg_dir)
        seed_receipts.append(
            {
                "seed": seed,
                "baseline_summary": condition_summary(seed_baseline),
                "forced_summary": condition_summary(seed_forced),
                "promotion_diagnostic": diagnostic,
            }
        )

    baseline_summary = condition_summary(baseline_rows)
    forced_summary = condition_summary(forced_rows)
    sensitivity = _workload_sensitivity_receipt(
        baseline_summary=baseline_summary,
        forced_summary=forced_summary,
        config=config,
    )
    active_seed_count = sum(
        1
        for item in seed_receipts
        if item["promotion_diagnostic"]["adaptive_readiness"]["status"] == "active_policy_ready"
    )
    min_active = int(config.get("confirmatory_min_active_seeds", 4))
    if sensitivity["status"] != "workload_sensitive":
        status = "workload_not_sensitive"
    elif active_seed_count < min_active:
        status = "promotion_mechanism_failure"
    else:
        status = "mechanism_qualified"

    forced_control = {
        "receipt_type": "forced_policy_control_receipt",
        "status": "forced_policy_improved"
        if sensitivity["status"] == "workload_sensitive"
        else "forced_policy_not_improved",
        "baseline_summary": baseline_summary,
        "forced_summary": forced_summary,
    }
    receipt = {
        "receipt_type": "mechanism_qualification_receipt",
        "status": status,
        "stage_b_allowed": status == "mechanism_qualified",
        "active_seed_count": active_seed_count,
        "required_active_seed_count": min_active,
        "workload_sensitivity": sensitivity,
        "forced_policy_control": forced_control,
        "seed_receipts": seed_receipts,
        "config_hash": receipt_hash(config),
        "policy_catalog_hash": receipt_hash(read_json(catalog_path)) if catalog_path.exists() else None,
    }
    write_json(out_dir / "workload_sensitivity_receipt.json", sensitivity)
    write_json(out_dir / "forced_policy_control_receipt.json", forced_control)
    write_json(out_dir / "mechanism_qualification_receipt.json", receipt)
    return receipt


def _run_calibration_condition(
    *,
    tasks: list[dict[str, Any]],
    config: dict[str, Any],
    condition: str,
    forced: bool,
    mock_model: bool,
    seed: int,
) -> list[dict[str, Any]]:
    policy_state = _forced_policy_state() if forced else None
    max_attempts = int(
        config.get("forced_policy_max_attempts", 2)
        if forced
        else config.get("baseline_max_attempts", 1)
    )
    rows: list[dict[str, Any]] = []
    for task in tasks:
        result = _run_task(
            task=task,
            # Forced positive-control must exercise the same executable prompt
            # branch that active OASG policies would use. The row is relabeled
            # after execution so pairing remains condition-stable.
            condition="oasg_adaptive" if forced else condition,
            config=config,
            max_attempts=max_attempts,
            policy_state=policy_state,
            mock_model=mock_model,
        ).to_dict()
        result["condition"] = condition
        result["seed"] = str(seed)
        rows.append(result)
    return rows


def _forced_policy_state() -> WorkflowPolicyState:
    policy = default_policy().to_dict()
    return WorkflowPolicyState(
        state_id="forced:mut_forced_policy",
        policy_profile=policy,
        retry_policy={"close_obligation": "bounded_retry_max_2"},
        validator_policy={"validate_artifact": "strict_json_and_schema"},
        context_policy={"replay_artifact": "context_shortening_policy"},
        rollback_policy={"rollback_local_effect": "receipt_required"},
    )


def _workload_sensitivity_receipt(
    *,
    baseline_summary: dict[str, Any],
    forced_summary: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    baseline_auc = int(baseline_summary["operational_debt_auc"])
    forced_auc = int(forced_summary["operational_debt_auc"])
    improvement_bps = reduction_bps(baseline_auc=baseline_auc, candidate_auc=forced_auc)
    threshold = int(config.get("qualification_min_reduction_bps", 1500))
    status = (
        "workload_sensitive"
        if forced_auc < baseline_auc and improvement_bps >= threshold
        else "workload_not_sensitive"
    )
    return {
        "receipt_type": "workload_sensitivity_receipt",
        "status": status,
        "baseline_debt_auc": baseline_auc,
        "forced_debt_auc": forced_auc,
        "debt_auc_delta": forced_auc - baseline_auc,
        "debt_reduction_bps": improvement_bps,
        "required_reduction_bps": threshold,
    }


if __name__ == "__main__":
    raise SystemExit(main())
