"""Run the strong-baseline v2 OASG effect experiment."""

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

from analyze_strong_baseline_v2_results import _render_report, analyze_run  # noqa: E402
from generate_strong_v2_tasks import generate_strong_tasks  # noqa: E402
from oasg.canonical import receipt_hash  # noqa: E402
from oasg.io import read_jsonl, write_jsonl  # noqa: E402
from oasg.ledger import verify_jsonl  # noqa: E402
from qualify_incremental_headroom import qualify_incremental_headroom  # noqa: E402
from qualify_strong_baseline_v2 import qualify_strong_baseline_v2  # noqa: E402
from strong_v2_common import condition_summary, read_json, write_csv, write_json  # noqa: E402
from strong_v2_runner import run_task, write_history  # noqa: E402


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
    qualification = qualify_strong_baseline_v2(
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
        _finish_with_analysis(run_dir, config)
        return 0

    headroom = qualify_incremental_headroom(
        config_path=config_path,
        strong_policy_receipt_path=run_dir / "strong_static_policy_receipt.json",
        out_dir=run_dir / "incremental_headroom",
        mock_model=args.mock_model,
    )
    write_json(run_dir / "incremental_headroom_receipt.json", headroom)
    if headroom["status"] == "no_incremental_headroom":
        _write_stop_receipt(run_dir, "strong_baseline_ceiling_no_headroom")
        _finish_with_analysis(run_dir, config)
        return 0

    readiness = _readiness_from_headroom(config=config, headroom=headroom)
    write_json(run_dir / "adaptive_readiness_from_strong_receipt.json", readiness)
    if readiness["status"] != "adaptive_from_strong_ready":
        _write_stop_receipt(run_dir, "promotion_mechanism_failure_vs_strong_baseline")
        _finish_with_analysis(run_dir, config)
        return 0

    _run_stage3(
        config=config,
        run_dir=run_dir,
        strong_policy_receipt=strong_policy_receipt,
        headroom=headroom,
        readiness=readiness,
        mock_model=args.mock_model,
    )
    _finish_with_analysis(run_dir, config)
    return 0


def _finish_with_analysis(run_dir: Path, config: dict[str, Any]) -> None:
    metrics = analyze_run(run_dir)
    _finish(run_dir, ROOT / str(config["runs_dir"]), metrics)
    print(json.dumps({"status": metrics["classification"], "run_dir": str(run_dir)}, indent=2))


def _freeze_tasks(*, config: dict[str, Any], run_dir: Path) -> None:
    seeds = [int(seed) for seed in config.get("replicate_seeds", [config["task_generator_seed"]])]
    manifest: dict[str, Any] = {"receipt_type": "strong_v2_frozen_task_manifest", "seeds": []}
    for seed in seeds:
        tasks = generate_strong_tasks(
            seed=seed,
            epoch_count=int(config.get("epoch_count", 20)),
            tasks_per_epoch=8,
            warmup_epochs=int(config.get("warmup_epochs", 3)),
        )
        seed_dir = run_dir / f"seed_{seed}"
        seed_dir.mkdir(parents=True, exist_ok=True)
        write_jsonl(seed_dir / "tasks_strong_baseline_v2.jsonl", tasks)
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


def _readiness_from_headroom(*, config: dict[str, Any], headroom: dict[str, Any]) -> dict[str, Any]:
    active_by_seed: dict[str, list[dict[str, Any]]] = {}
    for candidate in headroom.get("qualified_candidates", []):
        seed = str(candidate["seed"])
        active_by_seed.setdefault(seed, []).append(candidate)
    active_seed_count = sum(1 for changes in active_by_seed.values() if changes)
    required = int(config.get("confirmatory_min_active_seeds", 4))
    return {
        "receipt_type": "adaptive_readiness_from_strong_receipt",
        "status": "adaptive_from_strong_ready"
        if active_seed_count >= required
        else "promotion_mechanism_failure_vs_strong_baseline",
        "active_seed_count": active_seed_count,
        "required_active_seed_count": required,
        "active_changes_by_seed": active_by_seed,
        "source_headroom_status": headroom.get("status"),
        "source_headroom_hash": receipt_hash(headroom),
    }


def _run_stage3(
    *,
    config: dict[str, Any],
    run_dir: Path,
    strong_policy_receipt: dict[str, Any],
    headroom: dict[str, Any],
    readiness: dict[str, Any],
    mock_model: bool,
) -> None:
    seeds = [int(seed) for seed in config.get("replicate_seeds", [config["task_generator_seed"]])]
    strong_map = dict(strong_policy_receipt.get("policy_by_family", {}))
    positive_map = _best_headroom_map(headroom.get("qualified_candidates", []))
    order_manifest: dict[str, Any] = {"receipt_type": "strong_v2_condition_order_manifest", "seeds": []}
    for seed in seeds:
        seed_dir = run_dir / f"seed_{seed}"
        tasks = [
            task
            for task in read_jsonl(seed_dir / "tasks_strong_baseline_v2.jsonl")
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
                positive_map=positive_map,
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
    write_json(run_dir / "strong_v2_condition_order_manifest.json", order_manifest)


def _run_condition_rows(
    *,
    tasks: list[dict[str, Any]],
    condition: str,
    config: dict[str, Any],
    strong_map: dict[str, str],
    positive_map: dict[str, str],
    oasg_map: dict[str, str],
    mock_model: bool,
    seed: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for task in tasks:
        family = str(task["family"])
        burst = str(task["burst"])
        key = f"{family}::{burst}"
        policy_id = strong_map.get(family)
        active_mutation_id: str | None = None
        if condition in {"strong_rule_adaptive_control", "strong_positive_control"}:
            policy_id = positive_map.get(key, policy_id)
        elif condition == "oasg_adaptive_from_strong":
            policy_id = oasg_map.get(key, policy_id)
            if key in oasg_map:
                active_mutation_id = f"mut_{policy_id}_{family}_{burst}_v2"
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


def _best_headroom_map(candidates: list[dict[str, Any]]) -> dict[str, str]:
    best: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        key = f"{candidate['family']}::{candidate['burst']}"
        score = (
            2 if candidate.get("improvement_kind") == "debt" else 1,
            int(candidate.get("debt_reduction_bps", 0)),
            int(candidate.get("cost_reduction_bps", 0)),
        )
        current = best.get(key)
        current_score = (
            2 if current and current.get("improvement_kind") == "debt" else 1,
            int(current.get("debt_reduction_bps", 0)) if current else -1,
            int(current.get("cost_reduction_bps", 0)) if current else -1,
        )
        if current is None or score > current_score:
            best[key] = candidate
    return {key: str(candidate["candidate_policy_id"]) for key, candidate in best.items()}


def _write_stop_receipt(run_dir: Path, classification: str) -> None:
    write_json(
        run_dir / "interruption_or_stop_receipt.json",
        {
            "receipt_type": "strong_v2_stop_receipt",
            "status": "early_stop",
            "classification": classification,
            "reason": (
                "Required preregistered stage failed; held-out evaluation was not run because "
                "it would not identify the primary OASG effect question."
            ),
        },
    )


def _finish(run_dir: Path, runs_dir: Path, metrics: dict[str, Any]) -> None:
    write_json(run_dir / "metrics.json", metrics)
    if "verification" in metrics:
        write_json(run_dir / "verification.json", metrics["verification"])
    if "promotion_diagnostic" in metrics:
        write_json(run_dir / "promotion_diagnostic.json", metrics["promotion_diagnostic"])
    write_json(
        run_dir / "final_strong_v2_classification_receipt.json",
        {
            "receipt_type": "final_strong_v2_classification_receipt",
            "classification": metrics.get("classification", "invalid_run"),
            "metrics_hash": metrics.get("metrics_hash"),
        },
    )
    write_csv(run_dir / "epoch_table.csv", metrics.get("epoch_table", []))
    write_csv(run_dir / "seed_table.csv", metrics.get("seed_table", []))
    write_csv(run_dir / "paired_task_table.csv", metrics.get("paired_task_table", []))
    (run_dir / "report.md").write_text(_render_report(metrics), encoding="utf-8", newline="\n")
    _write_latest_pointer(runs_dir, run_dir)


def _write_latest_pointer(runs_dir: Path, run_dir: Path) -> None:
    latest = runs_dir / "latest"
    if latest.exists():
        shutil.rmtree(latest)
    shutil.copytree(run_dir, latest)
    write_json(runs_dir / "latest_pointer.json", {"latest": run_dir.name})


def _new_run_dir(runs_dir: Path) -> Path:
    runs_dir.mkdir(parents=True, exist_ok=True)
    run_dir = runs_dir / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    suffix = 1
    while run_dir.exists():
        run_dir = runs_dir / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_{suffix}"
        suffix += 1
    run_dir.mkdir(parents=True)
    return run_dir


def _preflight(config: dict[str, Any]) -> dict[str, Any]:
    endpoint = str(config.get("ollama_endpoint", ""))
    if endpoint not in {"http://127.0.0.1:11434", "http://localhost:11434"}:
        return {"status": "invalid_endpoint", "endpoint": endpoint}
    try:
        with urlopen(f"{endpoint}/api/tags", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError) as exc:
        return {"status": "ollama_unavailable", "error": str(exc)}
    models = [str(item.get("name", "")) for item in payload.get("models", [])]
    return {
        "status": "ok" if config.get("model") in models else "model_missing",
        "model": config.get("model"),
        "available_models": models,
    }


if __name__ == "__main__":
    raise SystemExit(main())
