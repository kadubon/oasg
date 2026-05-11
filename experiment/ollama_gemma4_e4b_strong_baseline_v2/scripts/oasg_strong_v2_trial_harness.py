"""Runner-produced trial ledgers for strong-baseline v2 headroom/readiness."""

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
from oasg.io import read_jsonl  # noqa: E402
from oasg.ledger import verify_jsonl  # noqa: E402
from strong_v2_common import (  # noqa: E402
    condition_summary,
    cost_reduction_bps,
    read_json,
    reduction_bps,
    task_cost_units,
    task_debt,
    write_json,
)
from strong_v2_runner import run_task, write_history  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--family", required=True)
    parser.add_argument("--burst", required=True)
    parser.add_argument("--baseline-policy-id", required=True)
    parser.add_argument("--candidate-policy-id", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--task-ids", default="")
    parser.add_argument("--mock-model", action="store_true")
    args = parser.parse_args()
    receipt = run_trial_bundle(
        tasks_path=Path(args.tasks),
        config_path=Path(args.config),
        family=args.family,
        burst=args.burst,
        baseline_policy_id=args.baseline_policy_id,
        candidate_policy_id=args.candidate_policy_id,
        out_dir=Path(args.out_dir),
        task_ids=[item for item in args.task_ids.split(",") if item],
        mock_model=args.mock_model,
    )
    print(json.dumps({"status": receipt["status"], "out_dir": str(args.out_dir)}, indent=2))
    return 0


def run_trial_bundle(
    *,
    tasks_path: Path,
    config_path: Path,
    family: str,
    burst: str,
    baseline_policy_id: str,
    candidate_policy_id: str,
    out_dir: Path,
    task_ids: list[str] | None = None,
    mock_model: bool = False,
) -> dict[str, Any]:
    config = read_json(config_path)
    selected_ids = set(task_ids or [])
    tasks = [
        task
        for task in read_jsonl(tasks_path)
        if task.get("phase") == "calibration"
        and task.get("family") == family
        and task.get("burst") == burst
        and (not selected_ids or str(task.get("task_id")) in selected_ids)
    ][: int(config.get("promotion_canary_count", 2))]
    out_dir.mkdir(parents=True, exist_ok=True)
    baseline_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    for task in tasks:
        baseline_rows.append(
            run_task(
                task=task,
                condition="strong_v2_trial_baseline",
                config=config,
                policy_id=baseline_policy_id,
                mock_model=mock_model,
            ).to_dict()
        )
        candidate_rows.append(
            run_task(
                task=task,
                condition="strong_v2_trial_candidate",
                config=config,
                policy_id=candidate_policy_id,
                active_mutation_id=f"mut_{candidate_policy_id}_{family}_{burst}",
                mock_model=mock_model,
            ).to_dict()
        )
    baseline_ledger = out_dir / "baseline_trial.jsonl"
    candidate_ledger = out_dir / "candidate_trial.jsonl"
    write_history(baseline_ledger, "strong_v2_trial_baseline", baseline_rows)
    write_history(candidate_ledger, "strong_v2_trial_candidate", candidate_rows)
    baseline_summary = condition_summary(baseline_rows)
    candidate_summary = condition_summary(candidate_rows)
    baseline_auc = int(baseline_summary["operational_debt_auc"])
    candidate_auc = int(candidate_summary["operational_debt_auc"])
    baseline_cost = int(baseline_summary["cost_to_close_units"])
    candidate_cost = int(candidate_summary["cost_to_close_units"])
    debt_reduction = reduction_bps(baseline_auc=baseline_auc, candidate_auc=candidate_auc)
    cost_reduction = cost_reduction_bps(
        baseline_cost=baseline_cost,
        candidate_cost=candidate_cost,
    )
    debt_improved = (
        bool(tasks)
        and baseline_auc > 0
        and candidate_auc < baseline_auc
        and debt_reduction >= int(config.get("debt_headroom_min_reduction_bps", 500))
    )
    efficiency_improved = (
        bool(tasks)
        and candidate_auc <= baseline_auc
        and int(candidate_summary["closed"]) >= int(baseline_summary["closed"])
        and cost_reduction >= int(config.get("cost_headroom_min_reduction_bps", 1000))
    )
    if debt_improved:
        status = "trial_debt_improved"
        improvement_kind = "debt"
    elif efficiency_improved:
        status = "trial_efficiency_improved"
        improvement_kind = "efficiency"
    else:
        status = "trial_not_improved"
        improvement_kind = "none"
    receipt = {
        "receipt_type": "strong_v2_trial_bundle_receipt",
        "status": status,
        "improvement_kind": improvement_kind,
        "family": family,
        "burst": burst,
        "baseline_policy_id": baseline_policy_id,
        "candidate_policy_id": candidate_policy_id,
        "task_ids": [str(task["task_id"]) for task in tasks],
        "baseline_summary": baseline_summary,
        "candidate_summary": candidate_summary,
        "debt_auc_delta": candidate_auc - baseline_auc,
        "cost_to_close_delta": candidate_cost - baseline_cost,
        "debt_reduction_bps": debt_reduction,
        "cost_reduction_bps": cost_reduction,
        "baseline_ledger_receipt": verify_jsonl(baseline_ledger).to_dict(),
        "candidate_ledger_receipt": verify_jsonl(candidate_ledger).to_dict(),
        "canary_rows": _canary_rows(baseline_rows, candidate_rows),
        "positive_evidence": _positive_evidence(
            improvement_kind=improvement_kind,
            family=family,
            burst=burst,
            baseline_policy_id=baseline_policy_id,
            candidate_policy_id=candidate_policy_id,
            baseline_auc=baseline_auc,
            candidate_auc=candidate_auc,
            baseline_cost=baseline_cost,
            candidate_cost=candidate_cost,
        ),
    }
    write_json(out_dir / "trial_bundle_receipt.json", receipt)
    write_json(out_dir / "baseline_rows.json", baseline_rows)
    write_json(out_dir / "candidate_rows.json", candidate_rows)
    return receipt


def _canary_rows(
    baseline_rows: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_task = {str(row["task_id"]): row for row in candidate_rows}
    records: list[dict[str, Any]] = []
    for baseline in baseline_rows:
        candidate = by_task.get(str(baseline["task_id"]))
        if candidate is None:
            continue
        records.append(
            {
                "task_id": str(baseline["task_id"]),
                "family": str(baseline["family"]),
                "burst": str(baseline["burst"]),
                "baseline_policy_id": baseline.get("policy_id"),
                "candidate_policy_id": candidate.get("policy_id"),
                "baseline_debt": task_debt(baseline),
                "candidate_debt": task_debt(candidate),
                "baseline_cost": task_cost_units(baseline),
                "candidate_cost": task_cost_units(candidate),
                "baseline_attempts": int(baseline.get("attempts", 0)),
                "candidate_attempts": int(candidate.get("attempts", 0)),
                "baseline_closed": bool(baseline.get("closed")),
                "candidate_closed": bool(candidate.get("closed")),
                "baseline_validator_error": str(baseline.get("validator_error_class", "")),
                "candidate_validator_error": str(candidate.get("validator_error_class", "")),
            }
        )
    return records


def _positive_evidence(
    *,
    improvement_kind: str,
    family: str,
    burst: str,
    baseline_policy_id: str,
    candidate_policy_id: str,
    baseline_auc: int,
    candidate_auc: int,
    baseline_cost: int,
    candidate_cost: int,
) -> list[dict[str, str]]:
    if improvement_kind == "none":
        return []
    coordinate = (
        "operational_debt_auc"
        if improvement_kind == "debt"
        else "cost_to_close_units"
    )
    return [
        {
            "coordinate": coordinate,
            "receipt_hash": receipt_hash(
                {
                    "improvement_kind": improvement_kind,
                    "family": family,
                    "burst": burst,
                    "baseline_policy_id": baseline_policy_id,
                    "candidate_policy_id": candidate_policy_id,
                    "baseline_auc": baseline_auc,
                    "candidate_auc": candidate_auc,
                    "baseline_cost": baseline_cost,
                    "candidate_cost": candidate_cost,
                }
            ),
        }
    ]


if __name__ == "__main__":
    raise SystemExit(main())
