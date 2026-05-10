from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

from oasg.io import read_json, write_json

ROOT = Path(__file__).resolve().parents[1]
DECISIVE = ROOT / "experiment" / "ollama_gemma4_e4b_decisive"


def _load_script(name: str) -> ModuleType:
    path = DECISIVE / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"decisive_{name}", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[f"decisive_{name}"] = module
    spec.loader.exec_module(module)
    return module


def test_decisive_task_generator_is_deterministic_and_disjoint() -> None:
    generator = _load_script("generate_decisive_tasks")

    first = generator.generate_decisive_tasks(seed=20260509, epoch_count=4, warmup_epochs=1)
    second = generator.generate_decisive_tasks(seed=20260509, epoch_count=4, warmup_epochs=1)

    calibration = {task["task_id"] for task in first if task["phase"] == "calibration"}
    evaluation = {task["task_id"] for task in first if task["phase"] == "longrun_eval"}
    assert first == second
    assert len(first) == 32
    assert calibration
    assert evaluation
    assert not calibration & evaluation


def test_policy_qualification_selects_only_improving_pairs(tmp_path: Path) -> None:
    qualify = _load_script("qualify_policy_catalog")
    config = _write_small_config(tmp_path)

    receipt = qualify.qualify_policy_catalog(
        config_path=config,
        out_dir=tmp_path / "qualification",
        mock_model=True,
    )

    qualified = read_json(tmp_path / "qualification" / "qualified_policy_catalog.json")
    assert receipt["status"] == "policy_catalog_qualified"
    assert qualified["qualified_pairs"]
    assert "set_action_grade" in qualified["forbidden_automatic_policies"]
    assert all(pair["debt_reduction_bps"] >= 1500 for pair in qualified["qualified_pairs"])


def test_trial_harness_emits_runner_backed_evidence(tmp_path: Path) -> None:
    harness = _load_script("oasg_decisive_trial_harness")
    generator = _load_script("generate_decisive_tasks")
    config = _write_small_config(tmp_path)
    tasks = generator.generate_decisive_tasks(seed=20260509, epoch_count=2, warmup_epochs=1)
    tasks_path = tmp_path / "tasks.jsonl"
    _write_jsonl(tasks_path, tasks)

    receipt = harness.run_trial_bundle(
        tasks_path=tasks_path,
        config_path=config,
        family="validator_receipt",
        policy_id="receipt_template_only",
        out_dir=tmp_path / "trial",
        mock_model=True,
    )

    assert receipt["status"] == "trial_improved"
    assert receipt["positive_evidence"]
    assert receipt["baseline_ledger_receipt"]["status"] == "ledger_prefix_valid"
    assert receipt["candidate_ledger_receipt"]["status"] == "ledger_prefix_valid"


def test_decisive_classifier_returns_controlled_outcomes() -> None:
    common = _load_script("decisive_common")
    config = {
        "confirmatory_min_active_seeds": 4,
        "minimum_meaningful_reduction_bps": 1500,
        "effect_confirmed_min_reduction_bps": 2000,
    }
    comparisons = {
        "oasg_adaptive_vs_baseline": {"bootstrap_ci": {"debt_auc_delta_ci": [-40, -20]}}
    }
    summaries = {
        "baseline_fixed": {"operational_debt_auc": 100, "unresolved_obligations": 10},
        "oasg_adaptive": {
            "operational_debt_auc": 70,
            "unresolved_obligations": 8,
            "hard_floor_regression_count": 0,
        },
    }

    assert (
        common.classify_decisive(
            summaries=summaries,
            comparisons=comparisons,
            policy_qualification={"status": "workload_not_sensitive"},
            promotion_qualification={"status": "promotion_mechanism_failure"},
            seed_count=5,
            config=config,
        )
        == "workload_not_sensitive"
    )
    assert (
        common.classify_decisive(
            summaries=summaries,
            comparisons=comparisons,
            policy_qualification={"status": "policy_catalog_qualified"},
            promotion_qualification={"status": "promotion_mechanism_failure"},
            seed_count=5,
            config=config,
        )
        == "promotion_mechanism_failure"
    )
    assert (
        common.classify_decisive(
            summaries=summaries,
            comparisons=comparisons,
            policy_qualification={"status": "policy_catalog_qualified"},
            promotion_qualification={
                "status": "promotion_mechanism_qualified",
                "active_seed_count": 5,
            },
            seed_count=5,
            config=config,
        )
        == "oasg_effect_confirmed"
    )


def test_decisive_mock_smoke_generates_required_outputs(tmp_path: Path) -> None:
    config = _write_small_config(tmp_path)

    completed = subprocess.run(
        [
            sys.executable,
            str(DECISIVE / "scripts" / "run_decisive_experiment.py"),
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
    latest = tmp_path / "runs" / "latest"
    metrics = read_json(latest / "metrics.json")
    assert metrics["classification"] == "oasg_effect_confirmed"
    assert (latest / "policy_catalog_qualification_receipt.json").exists()
    assert (latest / "promotion_qualification_receipt.json").exists()
    assert (latest / "report.md").exists()
    assert (latest / "paired_task_table.csv").exists()


def test_decisive_analysis_reports_invalid_pairing(tmp_path: Path) -> None:
    analyze = _load_script("analyze_decisive_results")
    run_dir = tmp_path / "run"
    write_json(
        run_dir / "config.json",
        {"replicate_seeds": [20260509], "confirmatory_min_active_seeds": 1},
    )
    write_json(
        run_dir / "policy_catalog_qualification_receipt.json",
        {"status": "policy_catalog_qualified", "qualified_pair_count": 1},
    )
    write_json(
        run_dir / "promotion_qualification_receipt.json",
        {
            "status": "promotion_mechanism_qualified",
            "active_seed_count": 1,
            "active_policies_by_seed": {"20260509": [{"mutation_id": "mut_x"}]},
        },
    )
    (run_dir / "seed_20260509" / "baseline_fixed").mkdir(parents=True)

    metrics = analyze.analyze_run(run_dir)

    assert metrics["classification"] == "invalid_run"
    assert "paired_comparison_missing" in metrics["verification"]["reasons"]


def _write_small_config(tmp_path: Path) -> Path:
    shutil.copyfile(DECISIVE / "policy_catalog.json", tmp_path / "policy_catalog.json")
    config = {
        "adaptive_initial_max_attempts": 1,
        "adaptive_promoted_max_attempts": 2,
        "baseline_max_attempts": 1,
        "condition_order": [
            "baseline_fixed",
            "oasg_observe_only",
            "forced_policy_positive_control",
            "oasg_adaptive",
        ],
        "confirmatory_min_active_seeds": 1,
        "effect_confirmed_min_reduction_bps": 2000,
        "epoch_count": 4,
        "forced_policy_max_attempts": 2,
        "minimum_meaningful_reduction_bps": 1500,
        "model": "gemma4:e4b",
        "ollama_endpoint": "http://127.0.0.1:11434",
        "ollama_timeout_seconds": 5,
        "policy_qualification_min_reduction_bps": 1500,
        "promotion_canary_count": 2,
        "replicate_seeds": [20260509],
        "results_dir": str(tmp_path / "results"),
        "runs_dir": str(tmp_path / "runs"),
        "task_generator_seed": 20260509,
        "tasks_path": str(tmp_path / "tasks.jsonl"),
        "temperature": 0,
        "timeout_seconds": 5,
        "warmup_epochs": 1,
    }
    path = tmp_path / "config.json"
    write_json(path, config)
    return path


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(__import__("json").dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
