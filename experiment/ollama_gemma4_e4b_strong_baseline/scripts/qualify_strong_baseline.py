"""Stage 0: qualify a strong static baseline from calibration tasks only."""

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

from generate_strong_tasks import generate_strong_tasks  # noqa: E402
from oasg.canonical import receipt_hash  # noqa: E402
from oasg.io import write_jsonl  # noqa: E402
from oasg.ledger import verify_jsonl  # noqa: E402
from strong_common import condition_summary, read_json, reduction_bps, write_json  # noqa: E402
from strong_runner import run_task, write_history  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--mock-model", action="store_true")
    args = parser.parse_args()
    receipt = qualify_strong_baseline(
        config_path=Path(args.config),
        out_dir=Path(args.out_dir),
        mock_model=args.mock_model,
    )
    print(json.dumps({"status": receipt["status"], "out_dir": str(args.out_dir)}, indent=2))
    return 0


def qualify_strong_baseline(
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

    weak_rows: list[dict[str, Any]] = []
    candidate_by_pair: dict[tuple[str, str], list[dict[str, Any]]] = {}
    weak_by_family: dict[str, list[dict[str, Any]]] = {}
    candidate_by_burst_pair: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    weak_by_burst_family: dict[tuple[str, str], list[dict[str, Any]]] = {}
    seed_receipts: list[dict[str, Any]] = []

    for seed in seeds:
        seed_dir = out_dir / f"seed_{seed}"
        seed_dir.mkdir(parents=True, exist_ok=True)
        tasks = generate_strong_tasks(
            seed=seed,
            epoch_count=int(config.get("epoch_count", 20)),
            tasks_per_epoch=8,
            warmup_epochs=int(config.get("warmup_epochs", 3)),
        )
        calibration_tasks = [task for task in tasks if task["phase"] == "calibration"]
        write_jsonl(seed_dir / "calibration_tasks.jsonl", calibration_tasks)
        seed_weak = _run_rows(
            tasks=calibration_tasks,
            condition="weak_fixed",
            config=config,
            policy_id=None,
            mock_model=mock_model,
            seed=seed,
        )
        weak_rows.extend(seed_weak)
        write_json(seed_dir / "weak_calibration_rows.json", seed_weak)
        write_history(seed_dir / "weak_calibration.jsonl", "weak_fixed", seed_weak)
        for row in seed_weak:
            family = str(row["family"])
            burst = str(row["burst"])
            weak_by_family.setdefault(family, []).append(row)
            weak_by_burst_family.setdefault((family, burst), []).append(row)

        pair_count = 0
        for policy in catalog["policies"]:
            policy_id = str(policy["policy_id"])
            runtime_policy = str(policy.get("runtime_policy_id", policy_id))
            for family in policy["families"]:
                family_tasks = [task for task in calibration_tasks if task["family"] == family]
                if not family_tasks:
                    continue
                rows = _run_rows(
                    tasks=family_tasks,
                    condition=f"policy_{policy_id}",
                    config=config,
                    policy_id=runtime_policy,
                    mock_model=mock_model,
                    seed=seed,
                )
                candidate_by_pair.setdefault((str(family), policy_id), []).extend(rows)
                for row in rows:
                    candidate_by_burst_pair.setdefault(
                        (str(family), str(row["burst"]), policy_id),
                        [],
                    ).append(row)
                pair_count += 1
        seed_receipts.append(
            {
                "seed": seed,
                "weak_summary": condition_summary(seed_weak),
                "policy_pair_count": pair_count,
            }
        )

    pair_receipts = _pair_receipts(
        candidate_by_pair,
        {family: condition_summary(rows) for family, rows in weak_by_family.items()},
        int(config.get("strong_baseline_min_reduction_bps", 1500)),
    )
    strong_policy = _best_policy_by_family(pair_receipts)
    strong_rows = _run_policy_map_rows(
        out_dir=out_dir,
        config=config,
        seeds=seeds,
        policy_map=strong_policy,
        condition="strong_static_calibrated",
        mock_model=mock_model,
    )
    weak_summary = condition_summary(weak_rows)
    strong_summary = condition_summary(strong_rows)
    strong_reduction = reduction_bps(
        baseline_auc=int(weak_summary["operational_debt_auc"]),
        candidate_auc=int(strong_summary["operational_debt_auc"]),
    )
    status = (
        "strong_baseline_qualified"
        if strong_policy
        and strong_reduction >= int(config.get("strong_baseline_min_reduction_bps", 1500))
        else "workload_not_sensitive"
    )
    conditional_receipts = _conditional_receipts(
        candidate_by_burst_pair,
        {key: condition_summary(rows) for key, rows in weak_by_burst_family.items()},
        int(config.get("minimum_incremental_reduction_bps", 500)),
    )
    conditional_policy = _best_policy_by_family_burst(conditional_receipts)
    strong_policy_receipt = {
        "receipt_type": "strong_static_policy_receipt",
        "status": "ok" if strong_policy else "empty",
        "policy_by_family": strong_policy,
        "conditional_policy_by_family_burst": conditional_policy,
        "policy_hash": receipt_hash(strong_policy),
        "conditional_policy_hash": receipt_hash(conditional_policy),
    }
    receipt = {
        "receipt_type": "strong_baseline_qualification_receipt",
        "status": status,
        "weak_summary": weak_summary,
        "strong_static_summary": strong_summary,
        "strong_static_debt_reduction_bps": strong_reduction,
        "required_reduction_bps": int(config.get("strong_baseline_min_reduction_bps", 1500)),
        "pair_receipts": pair_receipts,
        "conditional_pair_receipts": conditional_receipts,
        "seed_receipts": seed_receipts,
        "strong_static_policy_hash": strong_policy_receipt["policy_hash"],
        "conditional_policy_hash": strong_policy_receipt["conditional_policy_hash"],
        "config_hash": receipt_hash(config),
        "policy_catalog_hash": receipt_hash(catalog),
    }
    write_json(out_dir / "strong_static_policy_receipt.json", strong_policy_receipt)
    write_json(out_dir / "strong_baseline_qualification_receipt.json", receipt)
    write_json(out_dir / "weak_rows.json", weak_rows)
    write_json(out_dir / "strong_static_rows.json", strong_rows)
    if seeds:
        write_json(
            out_dir / "weak_calibration_receipt.json",
            verify_jsonl(out_dir / f"seed_{seeds[0]}" / "weak_calibration.jsonl").to_dict(),
        )
    return receipt


def _pair_receipts(
    candidate_by_pair: dict[tuple[str, str], list[dict[str, Any]]],
    weak_summaries: dict[str, dict[str, Any]],
    threshold: int,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for (family, policy_id), rows in sorted(candidate_by_pair.items()):
        weak = weak_summaries.get(family, condition_summary([]))
        candidate = condition_summary(rows)
        weak_auc = int(weak["operational_debt_auc"])
        candidate_auc = int(candidate["operational_debt_auc"])
        reduction = reduction_bps(baseline_auc=weak_auc, candidate_auc=candidate_auc)
        records.append(
            {
                "family": family,
                "policy_id": policy_id,
                "status": "qualified" if weak_auc > 0 and candidate_auc < weak_auc and reduction >= threshold else "not_qualified",
                "weak_summary": weak,
                "candidate_summary": candidate,
                "debt_auc_delta": candidate_auc - weak_auc,
                "debt_reduction_bps": reduction,
                "required_reduction_bps": threshold,
            }
        )
    return records


def _conditional_receipts(
    candidate_by_burst_pair: dict[tuple[str, str, str], list[dict[str, Any]]],
    weak_summaries: dict[tuple[str, str], dict[str, Any]],
    threshold: int,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for (family, burst, policy_id), rows in sorted(candidate_by_burst_pair.items()):
        weak = weak_summaries.get((family, burst), condition_summary([]))
        candidate = condition_summary(rows)
        weak_auc = int(weak["operational_debt_auc"])
        candidate_auc = int(candidate["operational_debt_auc"])
        reduction = reduction_bps(baseline_auc=weak_auc, candidate_auc=candidate_auc)
        records.append(
            {
                "family": family,
                "burst": burst,
                "policy_id": policy_id,
                "status": "qualified" if weak_auc > 0 and candidate_auc < weak_auc and reduction >= threshold else "not_qualified",
                "weak_summary": weak,
                "candidate_summary": candidate,
                "debt_auc_delta": candidate_auc - weak_auc,
                "debt_reduction_bps": reduction,
                "required_reduction_bps": threshold,
            }
        )
    return records


def _best_policy_by_family(pair_receipts: list[dict[str, Any]]) -> dict[str, str]:
    best: dict[str, dict[str, Any]] = {}
    for receipt in pair_receipts:
        if receipt["status"] != "qualified":
            continue
        family = str(receipt["family"])
        if family not in best or int(receipt["debt_reduction_bps"]) > int(best[family]["debt_reduction_bps"]):
            best[family] = receipt
    return {family: str(receipt["policy_id"]) for family, receipt in best.items()}


def _best_policy_by_family_burst(receipts: list[dict[str, Any]]) -> dict[str, str]:
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for receipt in receipts:
        if receipt["status"] != "qualified":
            continue
        key = (str(receipt["family"]), str(receipt["burst"]))
        if key not in best or int(receipt["debt_reduction_bps"]) > int(best[key]["debt_reduction_bps"]):
            best[key] = receipt
    return {f"{family}::{burst}": str(receipt["policy_id"]) for (family, burst), receipt in best.items()}


def _run_policy_map_rows(
    *,
    out_dir: Path,
    config: dict[str, Any],
    seeds: list[int],
    policy_map: dict[str, str],
    condition: str,
    mock_model: bool,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for seed in seeds:
        tasks = generate_strong_tasks(
            seed=seed,
            epoch_count=int(config.get("epoch_count", 20)),
            tasks_per_epoch=8,
            warmup_epochs=int(config.get("warmup_epochs", 3)),
        )
        calibration_tasks = [task for task in tasks if task["phase"] == "calibration"]
        seed_rows = _run_rows(
            tasks=calibration_tasks,
            condition=condition,
            config=config,
            policy_id=None,
            policy_map=policy_map,
            mock_model=mock_model,
            seed=seed,
        )
        rows.extend(seed_rows)
        write_history(out_dir / f"seed_{seed}" / f"{condition}.jsonl", condition, seed_rows)
    return rows


def _run_rows(
    *,
    tasks: list[dict[str, Any]],
    condition: str,
    config: dict[str, Any],
    policy_id: str | None,
    mock_model: bool,
    seed: int,
    policy_map: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for task in tasks:
        selected_policy = policy_map.get(str(task["family"])) if policy_map is not None else policy_id
        row = run_task(
            task=task,
            condition=condition,
            config=config,
            policy_id=selected_policy,
            mock_model=mock_model,
        ).to_dict()
        row["seed"] = str(seed)
        rows.append(row)
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
