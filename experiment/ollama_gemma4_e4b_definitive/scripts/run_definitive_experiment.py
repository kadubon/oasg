"""Run the two-stage definitive OASG effect experiment."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
LONGRUN = ROOT / "experiment" / "ollama_gemma4_e4b_longrun" / "scripts"
for import_path in (Path(__file__).resolve().parent, LONGRUN, SRC, ROOT):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from analyze_definitive_results import analyze_run  # noqa: E402
from definitive_common import write_json  # noqa: E402
from generate_longrun_tasks import generate_longrun_tasks  # noqa: E402
from oasg.io import read_json, write_jsonl  # noqa: E402
from oasg.ledger import verify_jsonl  # noqa: E402
from oasg.policy import default_policy  # noqa: E402
from oasg.policy_state import WorkflowPolicyState  # noqa: E402
from oasg.reducers.core import reduce_ledger  # noqa: E402
from qualify_mechanism import qualify_mechanism  # noqa: E402
from run_longrun_experiment import (  # noqa: E402
    _initial_event,
    _preflight,
    _result_event,
    _run_condition,
    _run_task,
    _task_manifest,
    _write_history,
)


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
        final = {"receipt_type": "final_effect_classification_receipt", "status": "invalid_run"}
        write_json(run_dir / "final_effect_classification_receipt.json", final)
        _write_latest_pointer(ROOT / str(config["runs_dir"]), run_dir)
        print(json.dumps({"status": "invalid_run", "run_dir": str(run_dir)}, indent=2))
        return 2

    qualification = qualify_mechanism(
        config_path=config_path,
        out_dir=run_dir / "qualification",
        mock_model=args.mock_model,
    )
    write_json(run_dir / "mechanism_qualification_receipt.json", qualification)
    if qualification["status"] != "mechanism_qualified":
        metrics = analyze_run(run_dir)
        write_json(run_dir / "metrics.json", metrics)
        write_json(run_dir / "verification.json", metrics["verification"])
        write_json(run_dir / "promotion_diagnostic.json", metrics["promotion_diagnostic"])
        write_json(
            run_dir / "final_effect_classification_receipt.json",
            {
                "receipt_type": "final_effect_classification_receipt",
                "status": metrics["classification"],
                "mechanism_status": qualification["status"],
            },
        )
        _write_latest_pointer(ROOT / str(config["runs_dir"]), run_dir)
        print(json.dumps({"status": metrics["classification"], "run_dir": str(run_dir)}, indent=2))
        return 0

    seeds = [int(seed) for seed in config.get("replicate_seeds", [config["task_generator_seed"]])]
    for seed in seeds:
        seed_dir = run_dir / f"seed_{seed}"
        seed_dir.mkdir(parents=True, exist_ok=True)
        seed_config = {
            **config,
            "task_generator_seed": seed,
            "tasks_path": str(seed_dir / "tasks_definitive.jsonl"),
            "runs_dir": str(run_dir),
        }
        tasks = generate_longrun_tasks(
            seed=seed,
            epoch_count=int(config.get("epoch_count", 20)),
            tasks_per_epoch=8,
            warmup_epochs=int(config.get("warmup_epochs", 3)),
        )
        write_jsonl(seed_dir / "tasks_definitive.jsonl", tasks)
        write_json(seed_dir / "task_manifest.json", _task_manifest(tasks, seed=seed))
        for condition in config["condition_order"]:
            condition = str(condition)
            if condition == "forced_policy_positive_control":
                _run_forced_condition(
                    tasks=tasks,
                    config=seed_config,
                    run_dir=seed_dir / condition,
                    mock_model=args.mock_model,
                    seed=seed,
                )
            else:
                _run_condition(
                    condition=condition,
                    tasks=tasks,
                    config=seed_config,
                    run_dir=seed_dir / condition,
                    mock_model=args.mock_model,
                )
    metrics = analyze_run(run_dir)
    write_json(run_dir / "metrics.json", metrics)
    write_json(run_dir / "verification.json", metrics["verification"])
    write_json(run_dir / "promotion_diagnostic.json", metrics["promotion_diagnostic"])
    write_json(
        run_dir / "final_effect_classification_receipt.json",
        {
            "receipt_type": "final_effect_classification_receipt",
            "status": metrics["classification"],
            "metrics_hash": metrics.get("metrics_hash"),
        },
    )
    _write_latest_pointer(ROOT / str(config["runs_dir"]), run_dir)
    print(json.dumps({"status": metrics["classification"], "run_dir": str(run_dir)}, indent=2))
    return 0


def _run_forced_condition(
    *,
    tasks: list[dict[str, Any]],
    config: dict[str, Any],
    run_dir: Path,
    mock_model: bool,
    seed: int,
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    policy_state = WorkflowPolicyState(
        state_id="forced:mut_forced_policy",
        policy_profile=default_policy().to_dict(),
        retry_policy={"close_obligation": "bounded_retry_max_2"},
        validator_policy={"validate_artifact": "strict_json_and_schema"},
        context_policy={"replay_artifact": "context_shortening_policy"},
        rollback_policy={"rollback_local_effect": "receipt_required"},
    )
    raw_events = [_initial_event("forced_policy_positive_control")]
    results: list[dict[str, Any]] = []
    for task in tasks:
        result = _run_task(
            task=task,
            # Reuse the adaptive prompt path so the positive-control policy is
            # executable rather than a label-only condition.
            condition="oasg_adaptive",
            config=config,
            max_attempts=int(config.get("forced_policy_max_attempts", 2)),
            policy_state=policy_state,
            mock_model=mock_model,
        )
        result = replace(result, condition="forced_policy_positive_control")
        row = result.to_dict()
        row["seed"] = str(seed)
        results.append(row)
        raw_events.append(_result_event(result))
    history = run_dir / "history.jsonl"
    _write_history(history, raw_events)
    write_json(run_dir / "task_results.json", results)
    write_json(run_dir / "history_receipt.json", verify_jsonl(history).to_dict())
    write_json(run_dir / "final_snapshot.json", reduce_ledger(history).to_dict())


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
