from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

from oasg.io import read_json, write_json


ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "experiment" / "ollama_gemma4_e4b_nonstationary_strong_baseline"


def _load_script(name: str) -> ModuleType:
    path = PROFILE / "scripts" / f"{name}.py"
    scripts_dir = str(PROFILE / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location(f"nonstationary_{name}", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tiny_config(tmp_path: Path) -> Path:
    config = read_json(PROFILE / "config_nonstationary.json")
    config.update(
        {
            "epochs_per_phase": 1,
            "tasks_per_epoch": 3,
            "replicate_seeds": [20260509],
            "runs_dir": str(tmp_path / "runs"),
            "results_dir": str(tmp_path / "results"),
            "confirmatory_min_active_seeds": 1,
        }
    )
    config_path = tmp_path / "config_nonstationary.json"
    write_json(config_path, config)
    shutil.copy(PROFILE / "policy_catalog.json", tmp_path / "policy_catalog.json")
    return config_path


def test_nonstationary_task_generator_is_deterministic_and_phased() -> None:
    generator = _load_script("generate_nonstationary_tasks")
    first = generator.generate_nonstationary_tasks(seed=1, epochs_per_phase=2, tasks_per_epoch=4)
    second = generator.generate_nonstationary_tasks(seed=1, epochs_per_phase=2, tasks_per_epoch=4)
    assert first == second
    assert len(first) == 32
    phases = {task["phase_id"] for task in first}
    assert phases == {
        "phase_a_calibration",
        "phase_b_mild_drift",
        "phase_c_structural_drift",
        "phase_d_mixed_reversion",
    }
    assert all(task["canonical_input_hash"].startswith("sha256:") for task in first)


def test_nonstationary_classifier_returns_core_statuses() -> None:
    common = _load_script("nonstationary_common")
    strong = {
        "operational_debt_auc": 100,
        "cost_to_close_units": 1000,
        "hard_floor_regression_count": 0,
    }
    adaptive = {
        "operational_debt_auc": 80,
        "cost_to_close_units": 1050,
        "hard_floor_regression_count": 0,
    }
    comparisons = {
        "oasg_vs_strong_static": {
            "paired_task_count": 10,
            "debt_auc_delta": -20,
            "debt_bootstrap_ci": {"delta_ci": [-30, -5]},
            "cost_to_close_delta": 50,
        },
        "oasg_vs_rule_adaptive": {"debt_auc_delta": -1},
    }
    assert (
        common.classify_nonstationary(
            summaries={
                "strong_static_calibrated": strong,
                "oasg_adaptive_from_strong": adaptive,
            },
            comparisons=comparisons,
            oracle_headroom={"status": "oracle_headroom_present"},
            readiness={"status": "adaptive_readiness_passed"},
            verification_status="ok",
            config={
                "post_drift_effect_min_reduction_bps": 1500,
                "minimum_partial_debt_reduction_bps": 500,
                "cost_regression_tolerance_bps": 1000,
            },
        )
        == "oasg_nonstationary_effect_confirmed_timeboxed"
    )
    assert (
        common.classify_nonstationary(
            summaries={},
            comparisons=comparisons,
            oracle_headroom={"status": "oracle_headroom_absent"},
            readiness={"status": "adaptive_readiness_passed"},
            verification_status="ok",
            config={},
        )
        == "oracle_headroom_absent"
    )
    assert (
        common.classify_nonstationary(
            summaries={},
            comparisons=comparisons,
            oracle_headroom={"status": "oracle_headroom_present"},
            readiness={"status": "adaptive_readiness_failed"},
            verification_status="ok",
            config={},
        )
        == "adaptive_readiness_failed"
    )


def test_nonstationary_mock_run_generates_valid_post_drift_report(tmp_path: Path) -> None:
    config_path = _tiny_config(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            str(PROFILE / "scripts" / "run_nonstationary_experiment.py"),
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
    metrics = read_json(latest / "metrics.json")
    assert metrics["verification"]["status"] == "ok"
    assert metrics["verification"]["paired_task_count"] == 9
    assert metrics["strong_baseline_calibration"]["phase_scope"] == "phase_a_calibration_only"
    assert "phase_a_calibration" not in {
        row["phase_id"] for row in metrics["paired_task_table"]
    }
    assert (latest / "drift_schedule_receipt.json").exists()
    assert (latest / "final_nonstationary_classification_receipt.json").exists()


def test_nonstationary_interruption_receipt_writer(tmp_path: Path) -> None:
    runner = _load_script("run_nonstationary_experiment")
    runner._write_interruption(tmp_path, "interrupted_before_primary_evaluation", {"reason": "test"})
    receipt = read_json(tmp_path / "interruption_receipt.json")
    assert receipt["status"] == "interrupted_before_primary_evaluation"
    assert receipt["detail_hash"].startswith("sha256:")
