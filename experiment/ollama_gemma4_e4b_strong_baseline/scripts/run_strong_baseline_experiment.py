"""Run the strong-baseline OASG effect experiment."""

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

from analyze_strong_baseline_results import _render_report, analyze_run  # noqa: E402
from generate_strong_tasks import generate_strong_tasks  # noqa: E402
from oasg.canonical import receipt_hash  # noqa: E402
from oasg.io import read_jsonl, write_jsonl  # noqa: E402
from oasg.ledger import verify_jsonl  # noqa: E402
from oasg_strong_trial_harness import run_trial_bundle  # noqa: E402
from qualify_strong_baseline import qualify_strong_baseline  # noqa: E402
from strong_common import condition_summary, read_json, write_csv, write_json  # noqa: E402
from strong_runner import run_task, write_history  # noqa: E402


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
        metrics = {"classification": "invalid_run"}
        _finish(run_dir, ROOT / str(config["runs_dir"]), metrics)
        print(json.dumps({"status": "invalid_run", "run_dir": str(run_dir)}, indent=2))
        return 2

    _freeze_tasks(config=config, run_dir=run_dir)
    qualification = qualify_strong_baseline(
        config_path=config_path,
        out_dir=run_dir / "strong_baseline_qualification",
        mock_model=args.mock_model,
    )
    write_json(run_dir / "strong_baseline_qualification_receipt.json", qualification)
    strong_policy_receipt = read_json(
        run_dir / "strong_baseline_qualification" / "strong_static_policy_receipt.json"
    )
    write_json(run_dir / "strong_static_policy_receipt.json", strong_policy_receipt)
    if qualification["status"] != "strong_baseline_qualified":
        metrics = analyze_run(run_dir)
        _finish(run_dir, ROOT / str(config["runs_dir"]), metrics)
        print(json.dumps({"status": metrics["classification"], "run_dir": str(run_dir)}, indent=2))
        return 0

    readiness = _qualify_adaptive_from_strong(
        config=config,
        config_path=config_path,
        run_dir=run_dir,
        strong_policy_receipt=strong_policy_receipt,
        mock_model=args.mock_model,
    )
    write_json(run_dir / "adaptive_from_strong_readiness_receipt.json", readiness)
    _run_stage2(
        config=config,
        run_dir=run_dir,
        strong_policy_receipt=strong_policy_receipt,
        readiness=readiness,
        mock_model=args.mock_model,
    )
    metrics = analyze_run(run_dir)
    _finish(run_dir, ROOT / str(config["runs_dir"]), metrics)
    print(json.dumps({"status": metrics["classification"], "run_dir": str(run_dir)}, indent=2))
    return 0


def _freeze_tasks(*, config: dict[str, Any], run_dir: Path) -> None:
    seeds = [int(seed) for seed in config.get("replicate_seeds", [config["task_generator_seed"]])]
    manifest: dict[str, Any] = {"receipt_type": "strong_frozen_task_manifest", "seeds": []}
    for seed in seeds:
        tasks = generate_strong_tasks(
            seed=seed,
            epoch_count=int(config.get("epoch_count", 20)),
            tasks_per_epoch=8,
            warmup_epochs=int(config.get("warmup_epochs", 3)),
        )
        seed_dir = run_dir / f"seed_{seed}"
        seed_dir.mkdir(parents=True, exist_ok=True)
        write_jsonl(seed_dir / "tasks_strong_baseline.jsonl", tasks)
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


def _qualify_adaptive_from_strong(
    *,
    config: dict[str, Any],
    config_path: Path,
    run_dir: Path,
    strong_policy_receipt: dict[str, Any],
    mock_model: bool,
) -> dict[str, Any]:
    strong_map = dict(strong_policy_receipt.get("policy_by_family", {}))
    conditional = dict(strong_policy_receipt.get("conditional_policy_by_family_burst", {}))
    active_by_seed: dict[str, list[dict[str, Any]]] = {}
    trial_receipts: list[dict[str, Any]] = []
    for seed in [int(seed) for seed in config.get("replicate_seeds", [config["task_generator_seed"]])]:
        tasks_path = run_dir / f"seed_{seed}" / "tasks_strong_baseline.jsonl"
        active_by_seed[str(seed)] = []
        for key, candidate_policy in sorted(conditional.items()):
            family, burst = key.split("::", 1)
            baseline_policy = strong_map.get(family)
            if baseline_policy is None or baseline_policy == candidate_policy:
                continue
            out_dir = (
                run_dir
                / "adaptive_readiness"
                / f"seed_{seed}"
                / f"{family}__{burst}__{candidate_policy}"
            )
            trial = run_trial_bundle(
                tasks_path=tasks_path,
                config_path=config_path,
                family=family,
                burst=burst,
                baseline_policy_id=baseline_policy,
                candidate_policy_id=candidate_policy,
                out_dir=out_dir,
                mock_model=mock_model,
            )
            trial_receipts.append(trial)
            if trial["status"] == "trial_improved":
                active_by_seed[str(seed)].append(
                    {
                        "family": family,
                        "burst": burst,
                        "baseline_policy_id": baseline_policy,
                        "candidate_policy_id": candidate_policy,
                        "mutation_id": f"mut_{candidate_policy}_{family}_{burst}",
                        "trial_receipt_hash": receipt_hash(trial),
                    }
                )
    active_seed_count = sum(1 for changes in active_by_seed.values() if changes)
    required = int(config.get("confirmatory_min_active_seeds", 4))
    return {
        "receipt_type": "adaptive_from_strong_readiness_receipt",
        "status": "adaptive_from_strong_ready"
        if active_seed_count >= required
        else "promotion_mechanism_failure_vs_strong_baseline",
        "active_seed_count": active_seed_count,
        "required_active_seed_count": required,
        "strong_static_policy_hash": strong_policy_receipt.get("policy_hash"),
        "active_changes_by_seed": active_by_seed,
        "trial_receipts": trial_receipts,
    }


def _run_stage2(
    *,
    config: dict[str, Any],
    run_dir: Path,
    strong_policy_receipt: dict[str, Any],
    readiness: dict[str, Any],
    mock_model: bool,
) -> None:
    seeds = [int(seed) for seed in config.get("replicate_seeds", [config["task_generator_seed"]])]
    strong_map = dict(strong_policy_receipt.get("policy_by_family", {}))
    rule_map = dict(strong_policy_receipt.get("conditional_policy_by_family_burst", {}))
    order_manifest: dict[str, Any] = {"receipt_type": "strong_condition_order_manifest", "seeds": []}
    for seed in seeds:
        seed_dir = run_dir / f"seed_{seed}"
        tasks = [
            task
            for task in read_jsonl(seed_dir / "tasks_strong_baseline.jsonl")
            if task.get("phase") == "longrun_eval"
        ]
        conditions = list(config["condition_order"])
        random.Random(seed).shuffle(conditions)
        order_manifest["seeds"].append({"seed": seed, "condition_order": conditions})
        active_changes = readiness.get("active_changes_by_seed", {}).get(str(seed), [])
        oasg_map = {
            f"{item['family']}::{item['burst']}": str(item["candidate_policy_id"])
            for item in active_changes
        }
        for condition in conditions:
            rows = _run_condition_rows(
                tasks=tasks,
                condition=str(condition),
                config=config,
                strong_map=strong_map,
                rule_map=rule_map,
                oasg_map=oasg_map,
                mock_model=mock_model,
                seed=seed,
            )
            condition_dir = seed_dir / str(condition)
            condition_dir.mkdir(parents=True, exist_ok=True)
            write_json(condition_dir / "task_results.json", rows)
            write_history(condition_dir / "history.jsonl", str(condition), rows)
            write_json(
                condition_dir / "history_receipt.json",
                verify_jsonl(condition_dir / "history.jsonl").to_dict(),
            )
            write_json(condition_dir / "summary.json", condition_summary(rows))
    write_json(run_dir / "condition_order_manifest.json", order_manifest)


def _run_condition_rows(
    *,
    tasks: list[dict[str, Any]],
    condition: str,
    config: dict[str, Any],
    strong_map: dict[str, str],
    rule_map: dict[str, str],
    oasg_map: dict[str, str],
    mock_model: bool,
    seed: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for task in tasks:
        family = str(task["family"])
        burst = str(task["burst"])
        policy_id: str | None = None
        active_mutation_id: str | None = None
        if condition in {"observe_only", "strong_static_calibrated"}:
            policy_id = strong_map.get(family)
        elif condition == "strong_rule_adaptive_control":
            policy_id = rule_map.get(f"{family}::{burst}", strong_map.get(family))
        elif condition == "oasg_adaptive_from_strong":
            policy_id = oasg_map.get(f"{family}::{burst}", strong_map.get(family))
            if f"{family}::{burst}" in oasg_map:
                active_mutation_id = f"mut_{policy_id}_{family}_{burst}"
        row = run_task(
            task=task,
            condition=condition,
            config=config,
            policy_id=policy_id,
            active_mutation_id=active_mutation_id,
            mock_model=mock_model,
        ).to_dict()
        row["seed"] = str(seed)
        row["strong_static_policy_hash"] = receipt_hash(strong_map)
        rows.append(row)
    return rows


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
        run_dir / "final_strong_baseline_classification_receipt.json",
        {
            "receipt_type": "final_strong_baseline_classification_receipt",
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


if __name__ == "__main__":
    raise SystemExit(main())
