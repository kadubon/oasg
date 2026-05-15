from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

from oasg.io import read_json, write_json


ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "experiment" / "ollama_gemma4_e4b_nonstationary_confirmatory"


def _load_script(name: str) -> ModuleType:
    path = PROFILE / "scripts" / f"{name}.py"
    scripts_dir = str(PROFILE / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location(f"confirmatory_{name}", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tiny_config(tmp_path: Path) -> Path:
    config = read_json(PROFILE / "config_confirmatory_small.json")
    config.update(
        {
            "runs_dir": str(tmp_path / "runs"),
            "results_dir": str(tmp_path / "results"),
            "minimum_paired_task_count": 1,
        }
    )
    config_path = tmp_path / "config_confirmatory_small.json"
    write_json(config_path, config)
    shutil.copy(PROFILE / "policy_catalog.json", tmp_path / "policy_catalog.json")
    return config_path


def test_confirmatory_task_generation_is_deterministic_for_all_variants() -> None:
    generator = _load_script("generate_confirmatory_tasks")
    variants = {
        "full_drift_confirmatory": [
            "phase_a_calibration",
            "phase_b_mild_drift",
            "phase_c_structural_drift",
            "phase_d_mixed_reversion",
        ],
        "no_mixed_reversion_ablation": [
            "phase_a_calibration",
            "phase_b_mild_drift",
            "phase_c1_structural_drift",
            "phase_c2_structural_surface_shift",
        ],
        "mixed_reversion_only_probe": [
            "phase_a_calibration",
            "phase_d1_mixed_reversion",
            "phase_d2_mixed_ratio_shift",
        ],
        "delayed_drift_recovery": [
            "phase_a_calibration",
            "phase_a2_stable_continuation",
            "phase_c_structural_drift",
            "phase_d_partial_reversion",
        ],
    }
    for variant_id, phases in variants.items():
        first = generator.generate_confirmatory_tasks(
            seed=1, variant_id=variant_id, epochs_per_phase=1, tasks_per_epoch=2
        )
        second = generator.generate_confirmatory_tasks(
            seed=1, variant_id=variant_id, epochs_per_phase=1, tasks_per_epoch=2
        )
        assert first == second
        assert [phase["phase_id"] for phase in generator.phase_schedule(variant_id)] == phases
        assert {task["phase_id"] for task in first} == set(phases)
        assert all(task["canonical_input_hash"].startswith("sha256:") for task in first)


def test_confirmatory_no_leakage_phase_roles() -> None:
    generator = _load_script("generate_confirmatory_tasks")
    tasks = generator.generate_confirmatory_tasks(
        seed=20260509,
        variant_id="delayed_drift_recovery",
        epochs_per_phase=1,
        tasks_per_epoch=3,
    )
    calibration_ids = {task["task_id"] for task in tasks if task["phase_role"] == "calibration"}
    non_calibration_ids = {
        task["task_id"] for task in tasks if task["phase_role"] != "calibration"
    }
    assert calibration_ids
    assert non_calibration_ids
    assert not calibration_ids & non_calibration_ids
    primary_ids = {task["task_id"] for task in tasks if task["phase_role"] == "post_drift"}
    stable_ids = {task["task_id"] for task in tasks if task["phase_role"] == "stable_control"}
    assert primary_ids
    assert stable_ids
    assert not primary_ids & stable_ids


def test_confirmatory_classifier_core_statuses() -> None:
    common = _load_script("confirmatory_common")
    summaries = {
        "strong_static_calibrated": {
            "operational_debt_auc": 100,
            "cost_to_close_units": 1000,
            "hard_floor_regression_count": 0,
        },
        "oasg_adaptive_from_strong": {
            "operational_debt_auc": 80,
            "cost_to_close_units": 1050,
            "hard_floor_regression_count": 0,
        },
    }
    comparisons = {
        "oasg_vs_strong_static": {
            "paired_task_count": 100,
            "debt_auc_delta": -20,
            "baseline_cost_units": 1000,
            "cost_regression_bps": 0,
            "debt_bootstrap_ci": {"delta_ci": [-30, -5]},
            "cost_bootstrap_ci": {"delta_ci": [-20, 50]},
        },
        "oasg_vs_observe_only": {"debt_auc_delta": -5},
        "oasg_vs_rule_adaptive": {"debt_auc_delta": -5},
    }
    ablations = {
        "no_phase_d": {
            "debt_auc_delta": -5,
            "debt_reduction_bps": 500,
            "debt_bootstrap_ci": {"delta_ci": [-10, 0]},
        },
        "structural_only": {
            "debt_auc_delta": -5,
            "debt_reduction_bps": 500,
            "debt_bootstrap_ci": {"delta_ci": [-10, 0]},
        },
        "mixed_only": {
            "debt_auc_delta": -10,
            "debt_reduction_bps": 500,
            "debt_bootstrap_ci": {"delta_ci": [-12, -1]},
        },
        "mild_only": {
            "debt_auc_delta": 0,
            "debt_reduction_bps": 0,
            "debt_bootstrap_ci": {"delta_ci": [0, 0]},
        },
    }
    config = {
        "allow_effect_claim": True,
        "minimum_paired_task_count": 100,
        "required_variants": list(common.REQUIRED_VARIANTS),
        "post_drift_effect_min_reduction_bps": 1500,
        "control_support_min_reduction_bps": 500,
        "cost_regression_tolerance_bps": 1000,
        "confirmatory_min_active_seeds": 4,
    }
    assert (
        common.classify_confirmatory(
            summaries=summaries,
            comparisons=comparisons,
            ablations=ablations,
            oracle_headroom={
                "status": "oracle_headroom_present",
                "oracle_headroom_by_drift_class": {
                    "structural": {"status": "oracle_headroom_present"},
                    "mixed": {"status": "oracle_headroom_present"},
                    "mild": {"status": "oracle_headroom_absent"},
                },
            },
            active_seed_count=4,
            stable_a2_active_mutations=0,
            verification_status="ok",
            completed_variants=set(common.REQUIRED_VARIANTS),
            config=config,
            interrupted=False,
        )
        == "oasg_nonstationary_confirmed"
    )
    assert (
        common.classify_confirmatory(
            summaries=summaries,
            comparisons={**comparisons, "oasg_vs_rule_adaptive": {"debt_auc_delta": 0}},
            ablations=ablations,
            oracle_headroom={
                "status": "oracle_headroom_present",
                "oracle_headroom_by_drift_class": {
                    "structural": {"status": "oracle_headroom_present"},
                    "mixed": {"status": "oracle_headroom_present"},
                },
            },
            active_seed_count=4,
            stable_a2_active_mutations=0,
            verification_status="ok",
            completed_variants=set(common.REQUIRED_VARIANTS),
            config=config,
            interrupted=False,
        )
        == "rule_adaptive_explains_effect"
    )
    assert (
        common.classify_confirmatory(
            summaries=summaries,
            comparisons=comparisons,
            ablations=ablations,
            oracle_headroom={"status": "oracle_headroom_absent"},
            active_seed_count=4,
            stable_a2_active_mutations=0,
            verification_status="ok",
            completed_variants=set(common.REQUIRED_VARIANTS),
            config=config,
            interrupted=False,
        )
        == "oracle_headroom_absent"
    )


def test_confirmatory_classifier_ablation_and_cost_statuses() -> None:
    common = _load_script("confirmatory_common")
    base_config = {
        "allow_effect_claim": True,
        "minimum_paired_task_count": 10,
        "required_variants": list(common.REQUIRED_VARIANTS),
        "post_drift_effect_min_reduction_bps": 1500,
        "control_support_min_reduction_bps": 500,
        "cost_regression_tolerance_bps": 1000,
        "confirmatory_min_active_seeds": 4,
    }
    comparisons = {
        "oasg_vs_strong_static": {
            "paired_task_count": 10,
            "debt_auc_delta": -20,
            "baseline_cost_units": 1000,
            "debt_bootstrap_ci": {"delta_ci": [-30, -5]},
            "cost_bootstrap_ci": {"delta_ci": [250, 400]},
        },
        "oasg_vs_observe_only": {"debt_auc_delta": -5},
        "oasg_vs_rule_adaptive": {"debt_auc_delta": -5},
    }
    summaries = {
        "strong_static_calibrated": {
            "operational_debt_auc": 100,
            "cost_to_close_units": 1000,
            "hard_floor_regression_count": 0,
        },
        "oasg_adaptive_from_strong": {
            "operational_debt_auc": 80,
            "cost_to_close_units": 1300,
            "hard_floor_regression_count": 0,
        },
    }
    assert (
        common.classify_confirmatory(
            summaries=summaries,
            comparisons=comparisons,
            ablations={},
            oracle_headroom={"status": "oracle_headroom_present"},
            active_seed_count=4,
            stable_a2_active_mutations=0,
            verification_status="ok",
            completed_variants=set(common.REQUIRED_VARIANTS),
            config=base_config,
            interrupted=False,
        )
        == "inconclusive_cost_regression"
    )
    summaries["oasg_adaptive_from_strong"]["cost_to_close_units"] = 1000
    assert (
        common.classify_confirmatory(
            summaries=summaries,
            comparisons={**comparisons, "oasg_vs_strong_static": {"paired_task_count": 0}},
            ablations={},
            oracle_headroom={"status": "oracle_headroom_present"},
            active_seed_count=4,
            stable_a2_active_mutations=0,
            verification_status="ok",
            completed_variants=set(common.REQUIRED_VARIANTS),
            config=base_config,
            interrupted=False,
        )
        == "interrupted_before_primary_evaluation"
    )


def test_confirmatory_bootstrap_shape_and_determinism() -> None:
    common = _load_script("confirmatory_common")
    first = common.bootstrap_delta_ci([1, -2, 3, -4], samples=20, seed=7)
    second = common.bootstrap_delta_ci([1, -2, 3, -4], samples=20, seed=7)
    assert first == second
    assert first["samples"] == 20
    assert len(first["delta_ci"]) == 2


def test_confirmatory_retirement_changes_are_counted_separately() -> None:
    common = _load_script("confirmatory_common")
    summary = common.condition_summary(
        [
            {
                "closed": True,
                "parsed": True,
                "validation_passed": True,
                "active_mutation_ids": ["mut_policy_retirement_validator_receipt_phase_d"],
                "attempts": 1,
                "prompt_chars": 10,
                "output_chars": 10,
                "latency_ms": 10,
            }
        ]
    )
    assert summary["active_mutation_count"] == 1
    assert summary["retirement_count"] == 1
    assert summary["active_retirement_ids"] == [
        "mut_policy_retirement_validator_receipt_phase_d"
    ]


def test_confirmatory_ablation_denominators_are_subset_local() -> None:
    analyzer = _load_script("analyze_confirmatory_results")

    def row(
        condition: str,
        *,
        variant_id: str,
        phase_category: str,
        task_id: str,
        debt: int,
    ) -> dict[str, object]:
        parsed = debt == 0
        validation_passed = debt <= 1
        return {
            "variant_id": variant_id,
            "seed": "1",
            "task_id": task_id,
            "condition": condition,
            "phase_id": f"phase_{phase_category}",
            "phase_category": phase_category,
            "phase_role": "post_drift",
            "epoch": 1,
            "closed": debt == 0,
            "parsed": parsed,
            "validation_passed": validation_passed,
            "unresolved_obligations": max(0, debt - 2),
            "retries": 0,
            "queue_pressure": 0,
            "rollback_gap": 0,
            "evidence_gap": 0,
            "attempts": 1,
            "prompt_chars": 10,
            "output_chars": 10,
            "latency_ms": 10,
        }

    rows = [
        row(
            "strong_static_calibrated",
            variant_id="no_mixed_reversion_ablation",
            phase_category="structural",
            task_id="s1",
            debt=2,
        ),
        row(
            "oasg_adaptive_from_strong",
            variant_id="no_mixed_reversion_ablation",
            phase_category="structural",
            task_id="s1",
            debt=1,
        ),
        row(
            "strong_static_calibrated",
            variant_id="mixed_reversion_only_probe",
            phase_category="mixed",
            task_id="m1",
            debt=10,
        ),
        row(
            "oasg_adaptive_from_strong",
            variant_id="mixed_reversion_only_probe",
            phase_category="mixed",
            task_id="m1",
            debt=10,
        ),
    ]
    ablations = analyzer._ablation_comparisons(rows, bootstrap_count=20, seed=7)
    assert ablations["structural_only"]["baseline_debt_auc"] == 2
    assert ablations["structural_only"]["candidate_debt_auc"] == 1
    assert ablations["structural_only"]["debt_reduction_bps"] == 5000


def test_confirmatory_drift_label_uses_support_threshold() -> None:
    analyzer = _load_script("analyze_confirmatory_results")
    effects = {
        "mild": {
            "debt_reduction_bps": 1562,
            "debt_bootstrap_ci": {"delta_ci": [-76, -27]},
        },
        "mixed": {
            "debt_reduction_bps": 1639,
            "debt_bootstrap_ci": {"delta_ci": [-160, -80]},
        },
        "structural": {
            "debt_reduction_bps": 83,
            "debt_bootstrap_ci": {"delta_ci": [-12, 0]},
        },
    }
    assert (
        analyzer._drift_interpretation_label(effects, support_threshold_bps=500)
        == "mixed_reversion_or_retirement_specific_support"
    )


def test_confirmatory_structural_support_required_for_confirmation() -> None:
    common = _load_script("confirmatory_common")
    summaries = {
        "strong_static_calibrated": {
            "operational_debt_auc": 100,
            "cost_to_close_units": 1000,
            "hard_floor_regression_count": 0,
        },
        "oasg_adaptive_from_strong": {
            "operational_debt_auc": 80,
            "cost_to_close_units": 1000,
            "hard_floor_regression_count": 0,
        },
    }
    comparisons = {
        "oasg_vs_strong_static": {
            "paired_task_count": 100,
            "debt_auc_delta": -20,
            "baseline_cost_units": 1000,
            "debt_bootstrap_ci": {"delta_ci": [-30, -5]},
            "cost_bootstrap_ci": {"delta_ci": [-10, 50]},
        },
        "oasg_vs_observe_only": {"debt_auc_delta": -5},
        "oasg_vs_rule_adaptive": {"debt_auc_delta": -5},
    }
    ablations = {
        "no_phase_d": {
            "debt_reduction_bps": 0,
            "debt_bootstrap_ci": {"delta_ci": [0, 0]},
        },
        "structural_only": {
            "debt_reduction_bps": 0,
            "debt_bootstrap_ci": {"delta_ci": [0, 0]},
        },
        "mixed_only": {
            "debt_reduction_bps": 2000,
            "debt_bootstrap_ci": {"delta_ci": [-20, -1]},
        },
    }
    classification = common.classify_confirmatory(
        summaries=summaries,
        comparisons=comparisons,
        ablations=ablations,
        oracle_headroom={
            "status": "oracle_headroom_present",
            "oracle_headroom_by_drift_class": {
                "structural": {"status": "oracle_headroom_present"},
                "mixed": {"status": "oracle_headroom_present"},
            },
        },
        active_seed_count=4,
        stable_a2_active_mutations=0,
        verification_status="ok",
        completed_variants=set(common.REQUIRED_VARIANTS),
        config={
            "allow_effect_claim": True,
            "minimum_paired_task_count": 100,
            "required_variants": list(common.REQUIRED_VARIANTS),
            "post_drift_effect_min_reduction_bps": 1500,
            "control_support_min_reduction_bps": 500,
            "cost_regression_tolerance_bps": 1000,
            "confirmatory_min_active_seeds": 4,
        },
        interrupted=False,
    )
    assert classification in {
        "mixed_reversion_only_effect",
        "oasg_nonstationary_phase_specific_support",
    }


def test_confirmatory_mock_run_creates_required_artifacts(tmp_path: Path) -> None:
    config_path = _tiny_config(tmp_path)
    subprocess.run(
        [
            sys.executable,
            str(PROFILE / "scripts" / "run_confirmatory_experiment.py"),
            "--config",
            str(config_path),
            "--mock-model",
            "--all-variants",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    latest = tmp_path / "runs" / "latest"
    metrics = read_json(latest / "metrics.json")
    assert metrics["verification"]["status"] == "ok"
    assert metrics["classification"] == "inconclusive_insufficient_power"
    assert set(metrics["completed_variants"]) == {
        "full_drift_confirmatory",
        "no_mixed_reversion_ablation",
        "mixed_reversion_only_probe",
        "delayed_drift_recovery",
    }
    assert any(
        receipt["calibration"]["status"] == "strong_baseline_calibrated_phase_a_ceiling"
        for receipt in metrics["variant_receipts"].values()
    )
    for name in [
        "classification_receipt.json",
        "no_leakage_receipt.json",
        "oracle_headroom_receipt.json",
        "adaptation_lag_receipt.json",
        "ablation_receipt.json",
        "drift_class_effect_receipt.json",
        "retirement_effect_receipt.json",
        "report.md",
    ]:
        assert (latest / name).exists()


def test_confirmatory_interruption_receipt_writer(tmp_path: Path) -> None:
    runner = _load_script("run_confirmatory_experiment")
    runner._write_interruption(tmp_path, "interrupted_before_primary_evaluation", {"reason": "test"})
    receipt = read_json(tmp_path / "interruption_receipt.json")
    assert receipt["status"] == "interrupted_before_primary_evaluation"
    assert receipt["detail_hash"].startswith("sha256:")
