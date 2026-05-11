from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

from oasg.io import read_json, write_json


ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "experiment" / "ollama_gemma4_e4b_strong_baseline"


def _load_script(name: str) -> ModuleType:
    path = PROFILE / "scripts" / f"{name}.py"
    scripts_dir = str(PROFILE / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tiny_config(tmp_path: Path, *, seeds: list[int] | None = None) -> Path:
    config = read_json(PROFILE / "config_strong_baseline.json")
    config.update(
        {
            "epoch_count": 4,
            "warmup_epochs": 2,
            "replicate_seeds": seeds or [20260509],
            "runs_dir": str(tmp_path / "runs"),
            "results_dir": str(tmp_path / "results"),
            "tasks_path": str(tmp_path / "tasks.jsonl"),
            "confirmatory_min_active_seeds": 1,
        }
    )
    config_path = tmp_path / "config_strong_baseline.json"
    write_json(config_path, config)
    shutil.copy(PROFILE / "policy_catalog.json", tmp_path / "policy_catalog.json")
    return config_path


def test_strong_task_generator_has_disjoint_calibration_and_eval_ids() -> None:
    generator = _load_script("generate_strong_tasks")
    tasks = generator.generate_strong_tasks(seed=1, epoch_count=5, tasks_per_epoch=4, warmup_epochs=2)
    calibration = {task["task_id"] for task in tasks if task["phase"] == "calibration"}
    evaluation = {task["task_id"] for task in tasks if task["phase"] == "longrun_eval"}
    assert calibration
    assert evaluation
    assert calibration.isdisjoint(evaluation)


def test_strong_baseline_qualification_selects_policy_from_calibration_only(tmp_path: Path) -> None:
    config_path = _tiny_config(tmp_path)
    qualify = _load_script("qualify_strong_baseline")
    receipt = qualify.qualify_strong_baseline(
        config_path=config_path,
        out_dir=tmp_path / "qualification",
        mock_model=True,
    )
    policy_receipt = read_json(tmp_path / "qualification" / "strong_static_policy_receipt.json")
    manifest_tasks = read_json(tmp_path / "qualification" / "weak_rows.json")
    assert receipt["receipt_type"] == "strong_baseline_qualification_receipt"
    assert policy_receipt["receipt_type"] == "strong_static_policy_receipt"
    assert all(row["phase"] == "calibration" for row in manifest_tasks)


def test_strong_classifier_confirms_incremental_effect() -> None:
    common = _load_script("strong_common")
    summaries = {
        "strong_static_calibrated": {
            "operational_debt_auc": 1000,
            "unresolved_obligations": 100,
            "hard_floor_regression_count": 0,
            "rollback_failures": 0,
        },
        "strong_rule_adaptive_control": {"operational_debt_auc": 950},
        "oasg_adaptive_from_strong": {
            "operational_debt_auc": 850,
            "unresolved_obligations": 80,
            "hard_floor_regression_count": 0,
            "rollback_failures": 0,
        },
    }
    comparisons = {
        "oasg_vs_strong_static": {
            "debt_auc_delta": -150,
            "bootstrap_ci": {"debt_auc_delta_ci": [-180, -80]},
        },
        "oasg_vs_rule_adaptive": {"debt_auc_delta": -100},
    }
    assert (
        common.classify_strong_baseline(
            summaries=summaries,
            comparisons=comparisons,
            strong_qualification={"status": "strong_baseline_qualified"},
            readiness={"status": "adaptive_from_strong_ready", "active_seed_count": 5},
            seed_count=5,
            config={
                "confirmatory_min_active_seeds": 4,
                "minimum_incremental_reduction_bps": 500,
                "incremental_effect_confirmed_min_reduction_bps": 1000,
            },
            verification_status="ok",
        )
        == "oasg_incremental_effect_confirmed_vs_strong_baseline"
    )


def test_strong_classifier_detects_rule_baseline_sufficient() -> None:
    common = _load_script("strong_common")
    summaries = {
        "strong_static_calibrated": {
            "operational_debt_auc": 1000,
            "unresolved_obligations": 100,
            "hard_floor_regression_count": 0,
            "rollback_failures": 0,
        },
        "oasg_adaptive_from_strong": {
            "operational_debt_auc": 900,
            "unresolved_obligations": 90,
            "hard_floor_regression_count": 0,
            "rollback_failures": 0,
        },
    }
    comparisons = {
        "oasg_vs_strong_static": {
            "debt_auc_delta": -100,
            "bootstrap_ci": {"debt_auc_delta_ci": [-130, -80]},
        },
        "oasg_vs_rule_adaptive": {"debt_auc_delta": 0},
    }
    assert (
        common.classify_strong_baseline(
            summaries=summaries,
            comparisons=comparisons,
            strong_qualification={"status": "strong_baseline_qualified"},
            readiness={"status": "adaptive_from_strong_ready", "active_seed_count": 5},
            seed_count=5,
            config={
                "confirmatory_min_active_seeds": 4,
                "minimum_incremental_reduction_bps": 500,
                "incremental_effect_confirmed_min_reduction_bps": 1000,
            },
            verification_status="ok",
        )
        == "rule_baseline_sufficient"
    )


def test_strong_mock_run_writes_required_artifacts(tmp_path: Path) -> None:
    config_path = _tiny_config(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            str(PROFILE / "scripts" / "run_strong_baseline_experiment.py"),
            "--config",
            str(config_path),
            "--mock-model",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "run_dir" in result.stdout
    latest = tmp_path / "runs" / "latest"
    assert (latest / "metrics.json").exists()
    assert (latest / "strong_static_policy_receipt.json").exists()
    assert (latest / "adaptive_from_strong_readiness_receipt.json").exists()
    assert (latest / "final_strong_baseline_classification_receipt.json").exists()
