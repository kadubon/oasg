"""Runner-produced trial ledgers for decisive policy promotion."""

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

from decisive_common import condition_summary, read_json, reduction_bps, write_json  # noqa: E402
from decisive_runner import run_task, write_history  # noqa: E402
from oasg.canonical import receipt_hash  # noqa: E402
from oasg.io import read_jsonl  # noqa: E402
from oasg.ledger import verify_jsonl  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--family", required=True)
    parser.add_argument("--policy-id", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--mock-model", action="store_true")
    args = parser.parse_args()
    receipt = run_trial_bundle(
        tasks_path=Path(args.tasks),
        config_path=Path(args.config),
        family=args.family,
        policy_id=args.policy_id,
        out_dir=Path(args.out_dir),
        mock_model=args.mock_model,
    )
    print(json.dumps({"status": receipt["status"], "out_dir": str(args.out_dir)}, indent=2))
    return 0


def run_trial_bundle(
    *,
    tasks_path: Path,
    config_path: Path,
    family: str,
    policy_id: str,
    out_dir: Path,
    mock_model: bool = False,
) -> dict[str, Any]:
    config = read_json(config_path)
    tasks = [
        task
        for task in read_jsonl(tasks_path)
        if task.get("phase") == "calibration" and task.get("family") == family
    ][: int(config.get("promotion_canary_count", 2))]
    out_dir.mkdir(parents=True, exist_ok=True)
    baseline_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    for task in tasks:
        baseline_rows.append(
            run_task(
                task=task,
                condition="trial_baseline",
                config=config,
                policy_id=None,
                mock_model=mock_model,
            ).to_dict()
        )
        candidate_rows.append(
            run_task(
                task=task,
                condition="trial_candidate",
                config=config,
                policy_id=policy_id,
                active_mutation_id=f"mut_{policy_id}_{family}",
                mock_model=mock_model,
            ).to_dict()
        )
    baseline_ledger = out_dir / "baseline_trial.jsonl"
    candidate_ledger = out_dir / "candidate_trial.jsonl"
    write_history(baseline_ledger, "trial_baseline", baseline_rows)
    write_history(candidate_ledger, "trial_candidate", candidate_rows)
    baseline_summary = condition_summary(baseline_rows)
    candidate_summary = condition_summary(candidate_rows)
    baseline_auc = int(baseline_summary["operational_debt_auc"])
    candidate_auc = int(candidate_summary["operational_debt_auc"])
    improvement_bps = reduction_bps(baseline_auc=baseline_auc, candidate_auc=candidate_auc)
    improved = bool(tasks) and baseline_auc > 0 and candidate_auc < baseline_auc
    receipt = {
        "receipt_type": "trial_bundle_receipt",
        "status": "trial_improved" if improved else "trial_not_improved",
        "family": family,
        "policy_id": policy_id,
        "task_ids": [str(task["task_id"]) for task in tasks],
        "baseline_summary": baseline_summary,
        "candidate_summary": candidate_summary,
        "debt_auc_delta": candidate_auc - baseline_auc,
        "debt_reduction_bps": improvement_bps,
        "baseline_ledger_receipt": verify_jsonl(baseline_ledger).to_dict(),
        "candidate_ledger_receipt": verify_jsonl(candidate_ledger).to_dict(),
        "positive_evidence": [
            {
                "coordinate": _coordinate_for_policy(policy_id, family),
                "receipt_hash": receipt_hash(
                    {
                        "family": family,
                        "policy_id": policy_id,
                        "baseline_auc": baseline_auc,
                        "candidate_auc": candidate_auc,
                    }
                ),
            }
        ]
        if improved
        else [],
    }
    write_json(out_dir / "trial_bundle_receipt.json", receipt)
    write_json(out_dir / "baseline_rows.json", baseline_rows)
    write_json(out_dir / "candidate_rows.json", candidate_rows)
    return receipt


def _coordinate_for_policy(policy_id: str, family: str) -> str:
    if policy_id == "single_repair_retry":
        return "KLB_2.close_obligation"
    if policy_id in {"strict_json_minimal", "schema_keys_only", "receipt_template_only"}:
        return "KLB_2.validate_artifact"
    if family == "safe_python_expression":
        return "KLB_2.validate_artifact"
    return "KLB_2.close_obligation"


if __name__ == "__main__":
    raise SystemExit(main())
