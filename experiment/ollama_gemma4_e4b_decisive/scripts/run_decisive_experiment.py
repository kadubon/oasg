"""Run the decisive OASG effect experiment."""

from __future__ import annotations

import argparse
import json
import random
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

from analyze_decisive_results import _render_report, analyze_run  # noqa: E402
from decisive_common import condition_summary, read_json, write_csv, write_json  # noqa: E402
from decisive_runner import run_task, write_history  # noqa: E402
from generate_decisive_tasks import generate_decisive_tasks  # noqa: E402
from oasg.canonical import receipt_hash  # noqa: E402
from oasg.io import write_jsonl  # noqa: E402
from oasg.ledger import verify_jsonl  # noqa: E402
from oasg_decisive_trial_harness import run_trial_bundle  # noqa: E402
from qualify_policy_catalog import qualify_policy_catalog  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--mock-model", action="store_true")
    parser.add_argument("--skip-preflight", action="store_true")
    args = parser.parse_args()

    config_path = Path(args.config)
    config = read_json(config_path)
    run_dir = _new_run_dir(ROOT / str(config["runs_dir"]))
    write_json(run_dir / "config.json", config)
    preflight = {"status": "mocked"} if args.mock_model or args.skip_preflight else _preflight(config)
    write_json(run_dir / "preflight.json", preflight)
    if preflight["status"] not in {"ok", "mocked"}:
        _finish(run_dir, ROOT / str(config["runs_dir"]), {"classification": "invalid_run"})
        print(json.dumps({"status": "invalid_run", "run_dir": str(run_dir)}, indent=2))
        return 2

    _freeze_tasks(config=config, run_dir=run_dir)
    policy_qualification = qualify_policy_catalog(
        config_path=config_path,
        out_dir=run_dir / "policy_qualification",
        mock_model=args.mock_model,
    )
    write_json(run_dir / "policy_catalog_qualification_receipt.json", policy_qualification)
    if policy_qualification["status"] != "policy_catalog_qualified":
        metrics = analyze_run(run_dir)
        _finish(run_dir, ROOT / str(config["runs_dir"]), metrics)
        print(json.dumps({"status": metrics["classification"], "run_dir": str(run_dir)}, indent=2))
        return 0

    promotion = _qualify_promotion(
        config=config,
        config_path=config_path,
        run_dir=run_dir,
        mock_model=args.mock_model,
    )
    write_json(run_dir / "promotion_qualification_receipt.json", promotion)
    if promotion["status"] != "promotion_mechanism_qualified":
        metrics = analyze_run(run_dir)
        _finish(run_dir, ROOT / str(config["runs_dir"]), metrics)
        print(json.dumps({"status": metrics["classification"], "run_dir": str(run_dir)}, indent=2))
        return 0

    _run_stage2(config=config, run_dir=run_dir, promotion=promotion, mock_model=args.mock_model)
    metrics = analyze_run(run_dir)
    _finish(run_dir, ROOT / str(config["runs_dir"]), metrics)
    print(json.dumps({"status": metrics["classification"], "run_dir": str(run_dir)}, indent=2))
    return 0


def _freeze_tasks(*, config: dict[str, Any], run_dir: Path) -> None:
    seeds = [int(seed) for seed in config.get("replicate_seeds", [config["task_generator_seed"]])]
    manifest: dict[str, Any] = {"receipt_type": "frozen_task_manifest", "seeds": []}
    for seed in seeds:
        tasks = generate_decisive_tasks(
            seed=seed,
            epoch_count=int(config.get("epoch_count", 20)),
            tasks_per_epoch=8,
            warmup_epochs=int(config.get("warmup_epochs", 3)),
        )
        seed_dir = run_dir / f"seed_{seed}"
        seed_dir.mkdir(parents=True, exist_ok=True)
        write_jsonl(seed_dir / "tasks_decisive.jsonl", tasks)
        calibration_ids = [str(task["task_id"]) for task in tasks if task["phase"] == "calibration"]
        evaluation_ids = [str(task["task_id"]) for task in tasks if task["phase"] == "longrun_eval"]
        manifest["seeds"].append(
            {
                "seed": seed,
                "task_count": len(tasks),
                "task_hash": receipt_hash({"tasks": tasks}),
                "calibration_task_ids": calibration_ids,
                "evaluation_task_ids": evaluation_ids,
                "disjoint": not bool(set(calibration_ids) & set(evaluation_ids)),
            }
        )
    manifest["status"] = "ok" if all(item["disjoint"] for item in manifest["seeds"]) else "invalid"
    manifest["manifest_hash"] = receipt_hash(manifest["seeds"])
    write_json(run_dir / "frozen_task_manifest.json", manifest)


def _qualify_promotion(
    *,
    config: dict[str, Any],
    config_path: Path,
    run_dir: Path,
    mock_model: bool,
) -> dict[str, Any]:
    qualified = read_json(run_dir / "policy_qualification" / "qualified_policy_catalog.json")
    pairs = list(qualified.get("qualified_pairs", []))
    active_by_seed: dict[str, list[dict[str, Any]]] = {}
    trial_receipts: list[dict[str, Any]] = []
    for seed in [int(seed) for seed in config.get("replicate_seeds", [config["task_generator_seed"]])]:
        seed_tasks = run_dir / f"seed_{seed}" / "tasks_decisive.jsonl"
        selected = _select_pairs_for_seed(seed=seed, pairs=pairs)
        active_by_seed[str(seed)] = []
        for pair in selected:
            out_dir = (
                run_dir
                / "promotion_qualification"
                / f"seed_{seed}"
                / f"{pair['family']}__{pair['policy_id']}"
            )
            trial = run_trial_bundle(
                tasks_path=seed_tasks,
                config_path=config_path,
                family=str(pair["family"]),
                policy_id=str(pair["policy_id"]),
                out_dir=out_dir,
                mock_model=mock_model,
            )
            trial_receipts.append(trial)
            if trial["status"] == "trial_improved":
                active_by_seed[str(seed)].append(
                    {
                        "family": pair["family"],
                        "policy_id": pair["policy_id"],
                        "mutation_id": f"mut_{pair['policy_id']}_{pair['family']}",
                        "trial_receipt_hash": receipt_hash(trial),
                    }
                )
    active_seed_count = sum(1 for policies in active_by_seed.values() if policies)
    required = int(config.get("confirmatory_min_active_seeds", 4))
    status = (
        "promotion_mechanism_qualified"
        if active_seed_count >= required
        else "promotion_mechanism_failure"
    )
    return {
        "receipt_type": "promotion_qualification_receipt",
        "status": status,
        "active_seed_count": active_seed_count,
        "required_active_seed_count": required,
        "active_policies_by_seed": active_by_seed,
        "trial_receipts": trial_receipts,
        "qualified_catalog_hash": receipt_hash(qualified),
    }


def _select_pairs_for_seed(*, seed: int, pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_family: dict[str, dict[str, Any]] = {}
    for pair in sorted(
        pairs,
        key=lambda item: (-int(item.get("debt_reduction_bps", 0)), str(item["policy_id"])),
    ):
        by_family.setdefault(str(pair["family"]), pair)
    selected = list(by_family.values())
    random.Random(seed).shuffle(selected)
    return selected[:4]


def _run_stage2(
    *,
    config: dict[str, Any],
    run_dir: Path,
    promotion: dict[str, Any],
    mock_model: bool,
) -> None:
    seeds = [int(seed) for seed in config.get("replicate_seeds", [config["task_generator_seed"]])]
    qualified = read_json(run_dir / "policy_qualification" / "qualified_policy_catalog.json")
    forced_map = _best_policy_by_family(qualified.get("qualified_pairs", []))
    order_manifest: dict[str, Any] = {"receipt_type": "condition_order_manifest", "seeds": []}
    for seed in seeds:
        seed_dir = run_dir / f"seed_{seed}"
        tasks = [
            task
            for task in _read_jsonl(seed_dir / "tasks_decisive.jsonl")
            if task.get("phase") == "longrun_eval"
        ]
        conditions = list(config["condition_order"])
        random.Random(seed).shuffle(conditions)
        order_manifest["seeds"].append({"seed": seed, "condition_order": conditions})
        active_map = {
            str(item["family"]): str(item["policy_id"])
            for item in promotion["active_policies_by_seed"].get(str(seed), [])
        }
        for condition in conditions:
            if condition == "forced_policy_positive_control":
                policy_map = forced_map
            elif condition == "oasg_adaptive":
                policy_map = active_map
            else:
                policy_map = {}
            rows = _run_condition_rows(
                tasks=tasks,
                condition=str(condition),
                config=config,
                policy_map=policy_map,
                mock_model=mock_model,
                seed=seed,
            )
            condition_dir = seed_dir / str(condition)
            condition_dir.mkdir(parents=True, exist_ok=True)
            write_json(condition_dir / "task_results.json", rows)
            write_history(condition_dir / "history.jsonl", str(condition), rows)
            write_json(condition_dir / "history_receipt.json", verify_jsonl(condition_dir / "history.jsonl").to_dict())
            write_json(condition_dir / "summary.json", condition_summary(rows))
    write_json(run_dir / "condition_order_manifest.json", order_manifest)


def _run_condition_rows(
    *,
    tasks: list[dict[str, Any]],
    condition: str,
    config: dict[str, Any],
    policy_map: dict[str, str],
    mock_model: bool,
    seed: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for task in tasks:
        family = str(task["family"])
        policy_id = policy_map.get(family)
        active_mutation = f"mut_{policy_id}_{family}" if condition == "oasg_adaptive" and policy_id else None
        row = run_task(
            task=task,
            condition=condition,
            config=config,
            policy_id=policy_id,
            active_mutation_id=active_mutation,
            mock_model=mock_model,
        ).to_dict()
        row["seed"] = str(seed)
        rows.append(row)
    return rows


def _best_policy_by_family(pairs: list[dict[str, Any]]) -> dict[str, str]:
    best: dict[str, dict[str, Any]] = {}
    for pair in pairs:
        family = str(pair["family"])
        if family not in best or int(pair["debt_reduction_bps"]) > int(best[family]["debt_reduction_bps"]):
            best[family] = pair
    return {family: str(pair["policy_id"]) for family, pair in best.items()}


def _preflight(config: dict[str, Any]) -> dict[str, Any]:
    endpoint = str(config["ollama_endpoint"]).rstrip("/")
    if endpoint not in {"http://127.0.0.1:11434", "http://localhost:11434"}:
        return {"status": "failed", "reason": "non_localhost_ollama_endpoint"}
    try:
        with urlopen(f"{endpoint}/api/tags", timeout=5) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError) as exc:
        return {"status": "failed", "reason": f"ollama_unreachable:{exc}"}
    names = [str(item.get("name", "")) for item in raw.get("models", [])]
    if str(config["model"]) not in names:
        return {"status": "failed", "reason": "model_missing", "available_models": names}
    return {"status": "ok", "model": config["model"], "available_models": names}


def _finish(run_dir: Path, runs_dir: Path, metrics: dict[str, Any]) -> None:
    write_json(run_dir / "metrics.json", metrics)
    if "verification" in metrics:
        write_json(run_dir / "verification.json", metrics["verification"])
    if "promotion_diagnostic" in metrics:
        write_json(run_dir / "promotion_diagnostic.json", metrics["promotion_diagnostic"])
    if "epoch_table" in metrics:
        write_csv(run_dir / "epoch_table.csv", metrics["epoch_table"])
    if "seed_table" in metrics:
        write_csv(run_dir / "seed_table.csv", metrics["seed_table"])
    if "paired_task_table" in metrics:
        write_csv(run_dir / "paired_task_table.csv", metrics["paired_task_table"])
    if "classification" in metrics:
        (run_dir / "report.md").write_text(_render_report(metrics), encoding="utf-8", newline="\n")
    write_json(
        run_dir / "final_effect_classification_receipt.json",
        {
            "receipt_type": "final_effect_classification_receipt",
            "status": metrics.get("classification", "invalid_run"),
            "metrics_hash": metrics.get("metrics_hash"),
        },
    )
    _write_latest_pointer(runs_dir, run_dir)


def _new_run_dir(runs_dir: Path) -> Path:
    runs_dir.mkdir(parents=True, exist_ok=True)
    name = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = runs_dir / name
    suffix = 0
    while path.exists():
        suffix += 1
        path = runs_dir / f"{name}_{suffix:02d}"
    path.mkdir(parents=True)
    return path


def _write_latest_pointer(runs_dir: Path, run_dir: Path) -> None:
    latest = runs_dir / "latest"
    if latest.exists() or latest.is_symlink():
        if latest.is_dir() and not latest.is_symlink():
            shutil.rmtree(latest)
        else:
            latest.unlink()
    shutil.copytree(run_dir, latest)
    write_json(runs_dir / "latest_pointer.json", {"latest": run_dir.name})


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                data = json.loads(line)
                if isinstance(data, dict):
                    rows.append(data)
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
