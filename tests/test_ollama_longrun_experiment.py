from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

from oasg.events import event_record, observation_payload
from oasg.io import read_json, read_jsonl, write_json, write_jsonl
from oasg.ledger import seal_records, verify_jsonl

ROOT = Path(__file__).resolve().parents[1]
LONGRUN = ROOT / "experiment" / "ollama_gemma4_e4b_longrun"


def _load_script(name: str) -> ModuleType:
    path = LONGRUN / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_longrun_task_generator_is_deterministic() -> None:
    generator = _load_script("generate_longrun_tasks")

    first = generator.generate_longrun_tasks(seed=20260508)
    second = generator.generate_longrun_tasks(seed=20260508)

    assert first == second
    assert len(first) == 160
    assert sum(1 for task in first if task["phase"] == "warmup") == 24
    assert sum(1 for task in first if task["phase"] == "longrun_eval") == 136
    assert {"validator_failure_burst", "context_budget_pressure", "rollback_receipt_gap"} <= {
        task["burst"] for task in first
    }


def test_longrun_analysis_excludes_warmup_and_classifies_no_promotion(tmp_path: Path) -> None:
    analyze = _load_script("analyze_longrun_results")
    run_dir = tmp_path / "run"
    for condition in ("baseline_fixed", "oasg_observe_only", "oasg_adaptive"):
        (run_dir / condition).mkdir(parents=True)
        rows = [
            _result("t_warm", condition, epoch=1, phase="warmup", closed=False),
            _result("t_eval", condition, epoch=4, phase="longrun_eval", closed=False),
        ]
        write_json(run_dir / condition / "task_results.json", rows)
    write_json(run_dir / "config.json", {"model": "gemma4:e4b"})
    write_json(run_dir / "task_manifest.json", {"task_count": 2})

    metrics = analyze.analyze_run(run_dir)

    assert metrics["classification"] == "inconclusive_no_active_policy"
    assert "oasg_adaptive_vs_baseline" in metrics["comparisons"]
    assert "oasg_observe_only_vs_baseline" in metrics["comparisons"]
    assert metrics["condition_summaries"]["baseline_fixed"]["task_count"] == 1
    assert metrics["condition_summaries"]["oasg_adaptive"]["operational_debt_auc"] == 3


def test_recovery_half_life_calculation() -> None:
    analyze = _load_script("analyze_longrun_results")
    rows = [
        {"epoch": 4, "operational_debt": 10},
        {"epoch": 5, "operational_debt": 8},
        {"epoch": 6, "operational_debt": 5},
    ]

    assert analyze._recovery_half_life(rows, 4, 10) == 2


def test_runner_timeout_budget_uses_canary_and_attempt_bounds() -> None:
    runner = _load_script("run_longrun_experiment")

    timeout = runner._runner_timeout_seconds(
        {
            "canary_task_count_warmup": 2,
            "baseline_max_attempts": 1,
            "adaptive_promoted_max_attempts": 2,
            "ollama_timeout_seconds": 60,
            "trial_runner_timeout_seconds": 30,
        }
    )

    assert timeout == 390


def test_canary_selection_prioritizes_recent_failed_warmup_tasks(tmp_path: Path) -> None:
    harness = _load_script("oasg_longrun_trial_harness")
    generator = _load_script("generate_longrun_tasks")
    tasks = generator.generate_longrun_tasks(epoch_count=4, tasks_per_epoch=2, warmup_epochs=3)
    warmup_ids = [str(task["task_id"]) for task in tasks if task["phase"] == "warmup"]
    metrics = tmp_path / "recent_metrics.json"
    write_json(
        metrics,
        {
            "dominant_burst": "validator_failure_burst",
            "dominant_failure_class": "missing_key",
            "failed_task_ids": [warmup_ids[-1], warmup_ids[0]],
            "failed_task_ids_by_error": {"missing_key": [warmup_ids[-1]]},
        },
    )

    selected = harness._select_canaries(
        tasks,
        {"canary_task_count_warmup": 1},
        str(metrics),
    )

    assert [task["task_id"] for task in selected] == [warmup_ids[-1]]
    assert all(task["phase"] == "warmup" for task in selected)


def test_longrun_harness_rejects_set_action_grade_self_evidence(tmp_path: Path) -> None:
    out = _run_harness(tmp_path, op="set_action_grade", mock_model=True)

    payload = read_jsonl(out)[0]["payload"]

    assert verify_jsonl(out).status == "ledger_prefix_valid"
    assert payload["positive_evidence"] == []
    assert payload["model_event"]["rejection_reason"] == "set_action_grade_self_evidence_rejected"


def test_longrun_harness_accepts_runner_ledger_backed_improvement(tmp_path: Path) -> None:
    out = _run_harness(tmp_path, op="set_retry_policy", mock_model=True)

    payload = read_jsonl(out)[0]["payload"]
    evidence_coordinates = {item["coordinate"] for item in payload["positive_evidence"]}

    assert verify_jsonl(out).status == "ledger_prefix_valid"
    assert payload["positive_evidence"]
    assert "KLB_2.close_obligation" in evidence_coordinates
    assert "KLB_2.promote_workflow" not in evidence_coordinates
    assert len([item for item in evidence_coordinates if item.startswith("KLB_2.")]) < len(_actions())
    assert payload["model_event"]["trial_mode"] == "ollama_longrun_canary"
    assert payload["model_event"]["pressure_delta"] < 0


def test_active_policy_hash_without_mutation_ids_is_not_activation(tmp_path: Path) -> None:
    analyze = _load_script("analyze_longrun_results")
    run_dir = tmp_path / "run"
    for condition in ("baseline_fixed", "oasg_observe_only", "oasg_adaptive"):
        (run_dir / condition).mkdir(parents=True)
        row = _result("t_eval", condition, epoch=4, phase="longrun_eval", closed=True)
        if condition == "oasg_adaptive":
            row["active_policy_hash"] = "sha256:" + "1" * 64
            row["active_mutation_ids"] = []
        write_json(run_dir / condition / "task_results.json", [row])

    metrics = analyze.analyze_run(run_dir)

    assert metrics["classification"] == "inconclusive_no_active_policy"
    assert metrics["condition_summaries"]["oasg_adaptive"]["active_policy_epoch_count"] == 1
    assert metrics["condition_summaries"]["oasg_adaptive"]["active_mutation_epoch_count"] == 0


def test_trial_timeout_classifies_as_pipeline_failure(tmp_path: Path) -> None:
    analyze = _load_script("analyze_longrun_results")
    run_dir = tmp_path / "run"
    for condition in ("baseline_fixed", "oasg_observe_only", "oasg_adaptive"):
        (run_dir / condition).mkdir(parents=True)
        write_json(
            run_dir / condition / "task_results.json",
            [_result("t_eval", condition, epoch=4, phase="longrun_eval", closed=False)],
        )
    write_json(
        run_dir / "oasg_adaptive" / "trial_ledger_receipt.json",
        {
            "receipt_type": "trial_ledger_receipt",
            "status": "trial_rejected",
            "timeout_status": "timed_out",
        },
    )

    metrics = analyze.analyze_run(run_dir)

    assert metrics["classification"] == "pipeline_failure_trial_timeout"


def test_replicated_analysis_pairs_epochs_by_seed(tmp_path: Path) -> None:
    analyze = _load_script("analyze_longrun_results")
    run_dir = tmp_path / "run"
    write_json(run_dir / "config.json", {"model": "gemma4:e4b", "confirmatory_min_active_seeds": 2})
    write_json(run_dir / "preflight.json", {"status": "ok"})
    replicates = []
    for seed in (20260509, 20260510):
        seed_dir = run_dir / f"seed_{seed}"
        seed_dir.mkdir(parents=True)
        write_json(seed_dir / "config.json", {"model": "gemma4:e4b"})
        write_json(seed_dir / "preflight.json", {"status": "ok"})
        write_json(seed_dir / "task_manifest.json", {"task_generator_seed": seed})
        for condition in ("baseline_fixed", "oasg_observe_only", "oasg_adaptive"):
            (seed_dir / condition).mkdir()
            write_json(
                seed_dir / condition / "task_results.json",
                [_result("t_eval", condition, epoch=4, phase="longrun_eval", closed=False)],
            )
        replicates.append({"seed": seed, "run_dir": str(seed_dir)})
    write_json(run_dir / "replicates.json", {"replicates": replicates})

    metrics = analyze.analyze_run(run_dir)

    assert metrics["replicate_count"] == 2
    assert metrics["comparisons"]["oasg_adaptive_vs_baseline"]["paired_epoch_count"] == 2


def test_longrun_mock_smoke_generates_valid_ledgers(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    tasks = tmp_path / "tasks.jsonl"
    runs = tmp_path / "runs"
    results = tmp_path / "results"
    generator = _load_script("generate_longrun_tasks")
    write_jsonl(
        tasks,
        generator.generate_longrun_tasks(
            seed=20260508,
            epoch_count=2,
            tasks_per_epoch=2,
            warmup_epochs=1,
        ),
    )
    write_json(
        config,
        {
            "adaptive_initial_max_attempts": 1,
            "adaptive_promoted_max_attempts": 2,
            "append_lease_observations": True,
            "baseline_max_attempts": 1,
            "canary_task_count": 2,
            "condition_order": ["baseline_fixed", "oasg_observe_only", "oasg_adaptive"],
            "epoch_count": 2,
            "experiment_id": "test",
            "model": "gemma4:e4b",
            "ollama_endpoint": "http://127.0.0.1:11434",
            "optimizer_max_candidates": 1,
            "optimizer_max_iterations": 1,
            "require_active_promotion_by_epoch": 0,
            "results_dir": str(results),
            "runs_dir": str(runs),
            "task_generator_seed": 20260508,
            "tasks_path": str(tasks),
            "temperature": 0,
            "timeout_seconds": 5,
            "warmup_epochs": 1,
        },
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(LONGRUN / "scripts" / "run_longrun_experiment.py"),
            "--config",
            str(config),
            "--mock-model",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    latest = runs / "latest"
    for condition in ("baseline_fixed", "oasg_observe_only", "oasg_adaptive"):
        assert verify_jsonl(latest / condition / "history.jsonl").status == "ledger_prefix_valid"

    completed = subprocess.run(
        [
            sys.executable,
            str(LONGRUN / "scripts" / "analyze_longrun_results.py"),
            "--run-dir",
            str(latest),
            "--out",
            str(results),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    metrics = read_json(results / "metrics.json")
    assert "classification" in metrics


def _run_harness(tmp_path: Path, *, op: str, mock_model: bool) -> Path:
    candidate = tmp_path / "candidate.jsonl"
    write_jsonl(
        candidate,
        seal_records(
            [
                event_record(
                    event_id="evt_seed",
                    workflow_id="longrun",
                    component_id="seed",
                    event_type="observation",
                    payload=observation_payload(
                        dimensions={dimension: "acceptable" for dimension in _dimensions()},
                        action_grades={action: "acceptable" for action in _actions()},
                        protected_debt={dimension: "acceptable" for dimension in _dimensions()},
                    ),
                )
            ]
        ),
    )
    mutation = tmp_path / "mutation.json"
    write_json(
        mutation,
        {
            "mutation_id": f"mut_{op}",
            "patch": {
                "mutation_id": f"mut_{op}",
                "op": op,
                "target_surface": "workflow_policy",
                "target_action_id": "close_obligation",
                "coordinate_id": "KLB_2.close_obligation",
                "value": "bounded_retry" if op != "set_action_grade" else "surplus",
                "mutator_id": "test_mutator",
                "precondition_policy_hash": None,
                "resulting_policy_hash": None,
            },
        },
    )
    tasks = tmp_path / "tasks.jsonl"
    generator = _load_script("generate_longrun_tasks")
    write_jsonl(tasks, generator.generate_longrun_tasks(epoch_count=1, tasks_per_epoch=2, warmup_epochs=1))
    config = tmp_path / "config.json"
    write_json(
        config,
        {
            "canary_task_count": 2,
            "model": "gemma4:e4b",
            "ollama_endpoint": "http://127.0.0.1:11434",
            "temperature": 0,
            "timeout_seconds": 5,
        },
    )
    out = tmp_path / "trial.jsonl"
    command = [
        sys.executable,
        str(LONGRUN / "scripts" / "oasg_longrun_trial_harness.py"),
        "--mutation",
        str(mutation),
        "--candidate",
        str(candidate),
        "--trial-ledger-out",
        str(out),
        "--tasks",
        str(tasks),
        "--config",
        str(config),
    ]
    if mock_model:
        command.append("--mock-model")
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    return out


def _result(
    task_id: str,
    condition: str,
    *,
    epoch: int,
    phase: str,
    closed: bool,
) -> dict[str, object]:
    return {
        "task_id": task_id,
        "condition": condition,
        "epoch": epoch,
        "phase": phase,
        "burst": "validator_failure_burst" if epoch == 4 else "warmup_format_drift",
        "family": "json_schema_repair",
        "closed": closed,
        "parsed": closed,
        "validation_passed": closed,
        "attempts": 1,
        "retries": 0,
        "latency_ms": 10,
        "prompt_chars": 10,
        "output_chars": 5,
        "unresolved_obligations": 0 if closed else 1,
        "validator_error_class": "none" if closed else "json_parse_failed",
        "active_policy_hash": None,
        "active_mutation_ids": [],
    }


def _actions() -> tuple[str, ...]:
    return (
        "pure_read",
        "local_reversible",
        "validate_artifact",
        "close_obligation",
        "replay_artifact",
        "rollback_local_effect",
        "emit_claim",
        "promote_workflow",
    )


def _dimensions() -> tuple[str, ...]:
    return (
        "budget",
        "queue",
        "evidence",
        "replay",
        "rollback",
        "incident",
        "authority",
        "maintenance",
        "comparison",
        "boundary",
        "trusted_base",
        "taint",
    )
