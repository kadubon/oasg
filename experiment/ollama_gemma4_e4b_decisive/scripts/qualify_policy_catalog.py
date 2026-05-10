"""Stage 0: qualify workflow policies before testing OASG adaptation."""

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
from generate_decisive_tasks import generate_decisive_tasks  # noqa: E402
from oasg.canonical import receipt_hash  # noqa: E402
from oasg.io import write_jsonl  # noqa: E402
from oasg.ledger import verify_jsonl  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--mock-model", action="store_true")
    args = parser.parse_args()
    receipt = qualify_policy_catalog(
        config_path=Path(args.config),
        out_dir=Path(args.out_dir),
        mock_model=args.mock_model,
    )
    print(json.dumps({"status": receipt["status"], "out_dir": str(args.out_dir)}, indent=2))
    return 0


def qualify_policy_catalog(
    *,
    config_path: Path,
    out_dir: Path,
    mock_model: bool = False,
) -> dict[str, Any]:
    config = read_json(config_path)
    catalog = read_json(config_path.parent / "policy_catalog.json")
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "config.json", config)
    write_json(out_dir / "policy_catalog.json", catalog)

    seeds = [int(seed) for seed in config.get("replicate_seeds", [config["task_generator_seed"]])]
    baseline_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    candidate_by_pair: dict[tuple[str, str], list[dict[str, Any]]] = {}
    baseline_by_family: dict[str, list[dict[str, Any]]] = {}
    seed_receipts: list[dict[str, Any]] = []

    for seed in seeds:
        seed_dir = out_dir / f"seed_{seed}"
        seed_dir.mkdir(parents=True, exist_ok=True)
        tasks = generate_decisive_tasks(
            seed=seed,
            epoch_count=int(config.get("epoch_count", 20)),
            tasks_per_epoch=8,
            warmup_epochs=int(config.get("warmup_epochs", 3)),
        )
        calibration_tasks = [task for task in tasks if task["phase"] == "calibration"]
        write_jsonl(seed_dir / "calibration_tasks.jsonl", calibration_tasks)
        seed_baseline = _run_rows(
            tasks=calibration_tasks,
            condition="baseline_fixed",
            config=config,
            policy_id=None,
            mock_model=mock_model,
            seed=seed,
        )
        baseline_rows.extend(seed_baseline)
        write_json(seed_dir / "baseline_calibration_rows.json", seed_baseline)
        write_history(seed_dir / "baseline_calibration.jsonl", "baseline_fixed", seed_baseline)
        seed_pair_receipts: list[dict[str, Any]] = []

        for policy in catalog["policies"]:
            policy_id = str(policy["policy_id"])
            for family in policy["families"]:
                family_tasks = [task for task in calibration_tasks if task["family"] == family]
                if not family_tasks:
                    continue
                rows = _run_rows(
                    tasks=family_tasks,
                    condition=f"policy_{policy_id}",
                    config=config,
                    policy_id=policy_id,
                    mock_model=mock_model,
                    seed=seed,
                )
                candidate_rows.extend(rows)
                candidate_by_pair.setdefault((str(family), policy_id), []).extend(rows)
                seed_pair_receipts.append(
                    {
                        "family": family,
                        "policy_id": policy_id,
                        "summary": condition_summary(rows),
                    }
                )
        for row in seed_baseline:
            baseline_by_family.setdefault(str(row["family"]), []).append(row)
        seed_receipts.append(
            {
                "seed": seed,
                "baseline_summary": condition_summary(seed_baseline),
                "policy_pair_count": len(seed_pair_receipts),
                "policy_pairs": seed_pair_receipts,
            }
        )

    pair_receipts: list[dict[str, Any]] = []
    qualified_pairs: list[dict[str, Any]] = []
    threshold = int(config.get("policy_qualification_min_reduction_bps", 1500))
    for (family, policy_id), rows in sorted(candidate_by_pair.items()):
        baseline_subset = baseline_by_family.get(family, [])
        baseline_summary = condition_summary(baseline_subset)
        candidate_summary = condition_summary(rows)
        baseline_auc = int(baseline_summary["operational_debt_auc"])
        candidate_auc = int(candidate_summary["operational_debt_auc"])
        improvement_bps = reduction_bps(baseline_auc=baseline_auc, candidate_auc=candidate_auc)
        qualified = baseline_auc > 0 and candidate_auc < baseline_auc and improvement_bps >= threshold
        record = {
            "family": family,
            "policy_id": policy_id,
            "status": "qualified" if qualified else "not_qualified",
            "baseline_summary": baseline_summary,
            "candidate_summary": candidate_summary,
            "debt_auc_delta": candidate_auc - baseline_auc,
            "debt_reduction_bps": improvement_bps,
            "required_reduction_bps": threshold,
        }
        pair_receipts.append(record)
        if qualified:
            qualified_pairs.append(
                {
                    "family": family,
                    "policy_id": policy_id,
                    "debt_reduction_bps": improvement_bps,
                    "candidate_debt_auc": candidate_auc,
                    "baseline_debt_auc": baseline_auc,
                }
            )

    qualified_catalog = {
        "receipt_type": "qualified_policy_catalog",
        "status": "ok" if qualified_pairs else "empty",
        "qualified_pairs": qualified_pairs,
        "forbidden_automatic_policies": catalog.get("forbidden_automatic_policies", []),
        "source_catalog_hash": receipt_hash(catalog),
        "qualification_hash": receipt_hash(pair_receipts),
    }
    status = "policy_catalog_qualified" if qualified_pairs else "workload_not_sensitive"
    receipt = {
        "receipt_type": "policy_catalog_qualification_receipt",
        "status": status,
        "qualified_pair_count": len(qualified_pairs),
        "baseline_summary": condition_summary(baseline_rows),
        "candidate_summary": condition_summary(candidate_rows),
        "pair_receipts": pair_receipts,
        "seed_receipts": seed_receipts,
        "qualified_catalog_hash": receipt_hash(qualified_catalog),
        "config_hash": receipt_hash(config),
        "policy_catalog_hash": receipt_hash(catalog),
    }
    write_json(out_dir / "qualified_policy_catalog.json", qualified_catalog)
    write_json(out_dir / "policy_catalog_qualification_receipt.json", receipt)
    write_json(out_dir / "candidate_rows.json", candidate_rows)
    write_json(out_dir / "baseline_rows.json", baseline_rows)
    write_json(
        out_dir / "baseline_calibration_receipt.json",
        verify_jsonl(out_dir / f"seed_{seeds[0]}" / "baseline_calibration.jsonl").to_dict()
        if seeds
        else {},
    )
    return receipt


def _run_rows(
    *,
    tasks: list[dict[str, Any]],
    condition: str,
    config: dict[str, Any],
    policy_id: str | None,
    mock_model: bool,
    seed: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
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


if __name__ == "__main__":
    raise SystemExit(main())
