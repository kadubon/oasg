from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

from oasg.io import read_json, write_json


ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "experiment" / "ollama_gemma4_e4b_strong_baseline_v2"


def _load_script(name: str) -> ModuleType:
    path = PROFILE / "scripts" / f"{name}.py"
    scripts_dir = str(PROFILE / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location(f"strong_v2_{name}", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tiny_config(tmp_path: Path, *, seeds: list[int] | None = None) -> Path:
    config = read_json(PROFILE / "config_strong_baseline_v2.json")
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
    config_path = tmp_path / "config_strong_baseline_v2.json"
    write_json(config_path, config)
    shutil.copy(PROFILE / "policy_catalog.json", tmp_path / "policy_catalog.json")
    return config_path


def test_v2_task_generator_has_disjoint_calibration_and_eval_ids() -> None:
    generator = _load_script("generate_strong_v2_tasks")
    tasks = generator.generate_strong_tasks(seed=1, epoch_count=5, tasks_per_epoch=4, warmup_epochs=2)
    calibration = {task["task_id"] for task in tasks if task["phase"] == "calibration"}
    evaluation = {task["task_id"] for task in tasks if task["phase"] == "longrun_eval"}
    assert calibration
    assert evaluation
    assert calibration.isdisjoint(evaluation)


def test_v2_headroom_canary_selection_prefers_debt_rows() -> None:
    headroom = _load_script("qualify_incremental_headroom")
    rows = [
        {"task_id": "ok", "closed": True, "parsed": True, "validation_passed": True},
        {
            "task_id": "debt",
            "closed": False,
            "parsed": True,
            "validation_passed": False,
            "unresolved_obligations": 1,
        },
    ]
    assert headroom._select_canaries(baseline_rows=rows, max_count=1) == ["debt"]


def test_v2_classifier_distinguishes_no_headroom() -> None:
    common = _load_script("strong_v2_common")
    assert (
        common.classify_strong_v2(
            summaries={},
            comparisons={},
            strong_qualification={"status": "strong_baseline_qualified"},
            headroom={"status": "no_incremental_headroom"},
            readiness={"status": "promotion_mechanism_failure_vs_strong_baseline"},
            seed_count=5,
            config={"confirmatory_min_active_seeds": 4},
            verification_status="ok",
        )
        == "strong_baseline_ceiling_no_headroom"
    )


def test_v2_classifier_confirms_debt_effect() -> None:
    common = _load_script("strong_v2_common")
    summaries = {
        "strong_static_calibrated": {
            "operational_debt_auc": 1000,
            "cost_to_close_units": 10000,
            "closed": 100,
            "hard_floor_regression_count": 0,
            "rollback_failures": 0,
        },
        "oasg_adaptive_from_strong": {
            "operational_debt_auc": 850,
            "cost_to_close_units": 10000,
            "closed": 100,
            "hard_floor_regression_count": 0,
            "rollback_failures": 0,
        },
    }
    comparisons = {
        "oasg_vs_strong_static": {
            "debt_bootstrap_ci": {"debt_auc_delta_ci": [-180, -80]},
            "cost_bootstrap_ci": {"debt_auc_delta_ci": [0, 0]},
        }
    }
    assert (
        common.classify_strong_v2(
            summaries=summaries,
            comparisons=comparisons,
            strong_qualification={"status": "strong_baseline_qualified"},
            headroom={"status": "debt_headroom_exists"},
            readiness={"status": "adaptive_from_strong_ready", "active_seed_count": 5},
            seed_count=5,
            config={
                "confirmatory_min_active_seeds": 4,
                "minimum_incremental_reduction_bps": 500,
                "debt_effect_confirmed_min_reduction_bps": 1000,
            },
            verification_status="ok",
        )
        == "oasg_debt_effect_confirmed_vs_strong_baseline"
    )


def test_v2_classifier_confirms_efficiency_effect() -> None:
    common = _load_script("strong_v2_common")
    summaries = {
        "strong_static_calibrated": {
            "operational_debt_auc": 0,
            "cost_to_close_units": 10000,
            "closed": 100,
            "hard_floor_regression_count": 0,
            "rollback_failures": 0,
        },
        "oasg_adaptive_from_strong": {
            "operational_debt_auc": 0,
            "cost_to_close_units": 8500,
            "closed": 100,
            "hard_floor_regression_count": 0,
            "rollback_failures": 0,
        },
    }
    comparisons = {
        "oasg_vs_strong_static": {
            "debt_bootstrap_ci": {"debt_auc_delta_ci": [0, 0]},
            "cost_bootstrap_ci": {"debt_auc_delta_ci": [-1800, -800]},
        }
    }
    assert (
        common.classify_strong_v2(
            summaries=summaries,
            comparisons=comparisons,
            strong_qualification={"status": "strong_baseline_qualified"},
            headroom={"status": "efficiency_headroom_exists"},
            readiness={"status": "adaptive_from_strong_ready", "active_seed_count": 5},
            seed_count=5,
            config={
                "confirmatory_min_active_seeds": 4,
                "minimum_incremental_reduction_bps": 500,
                "cost_effect_confirmed_min_reduction_bps": 1000,
            },
            verification_status="ok",
        )
        == "oasg_efficiency_effect_confirmed_vs_strong_baseline"
    )


def test_v2_mock_run_early_stops_with_no_headroom(tmp_path: Path) -> None:
    config_path = _tiny_config(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            str(PROFILE / "scripts" / "run_strong_baseline_v2_experiment.py"),
            "--config",
            str(config_path),
            "--mock-model",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "strong_baseline_ceiling_no_headroom" in result.stdout
    latest = tmp_path / "runs" / "latest"
    metrics = read_json(latest / "metrics.json")
    assert metrics["classification"] == "strong_baseline_ceiling_no_headroom"
    assert (latest / "incremental_headroom_receipt.json").exists()
    assert (latest / "interruption_or_stop_receipt.json").exists()
