from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from oasg.io import write_json

ROOT = Path(__file__).resolve().parents[1]
DEFINITIVE = ROOT / "experiment" / "ollama_gemma4_e4b_definitive"


def _load_script(name: str) -> ModuleType:
    path = DEFINITIVE / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_forced_positive_control_uses_adaptive_prompt_path() -> None:
    qualify = _load_script("qualify_mechanism")
    task = {
        "task_id": "warmup_sensitive_001",
        "epoch": 1,
        "phase": "warmup",
        "burst": "validator_failure_burst",
        "family": "json_schema_repair",
        "instruction": "Return {\"ok\": true}.",
        "validator": "json_equals",
        "expected": {"ok": True},
    }
    config = {"baseline_max_attempts": 1, "forced_policy_max_attempts": 2}

    baseline = qualify._run_calibration_condition(
        tasks=[task],
        config=config,
        condition="baseline_fixed",
        forced=False,
        mock_model=True,
        seed=20260509,
    )[0]
    forced = qualify._run_calibration_condition(
        tasks=[task],
        config=config,
        condition="forced_policy_positive_control",
        forced=True,
        mock_model=True,
        seed=20260509,
    )[0]

    assert baseline["closed"] is False
    assert forced["closed"] is True
    assert forced["condition"] == "forced_policy_positive_control"
    assert forced["prompt_template_ids"][0].startswith("longrun_promoted_")
    assert forced["active_mutation_ids"] == ["mut_forced_policy"]


def test_classification_distinguishes_mechanism_and_effect_outcomes() -> None:
    common = _load_script("definitive_common")
    summaries = {
        "baseline_fixed": {
            "operational_debt_auc": 100,
            "unresolved_obligations": 10,
        },
        "oasg_adaptive": {
            "operational_debt_auc": 100,
            "unresolved_obligations": 10,
            "hard_floor_regression_count": 0,
        },
    }
    comparisons = {
        "oasg_adaptive_vs_baseline": {
            "bootstrap_ci": {"debt_auc_delta_ci": [-2, 2]},
        }
    }

    assert (
        common.classify_effect(
            summaries=summaries,
            comparisons=comparisons,
            mechanism={"status": "workload_not_sensitive"},
            min_active_seeds=4,
            min_meaningful_bps=1500,
            confirmed_bps=2000,
        )
        == "workload_not_sensitive"
    )
    assert (
        common.classify_effect(
            summaries=summaries,
            comparisons=comparisons,
            mechanism={"status": "promotion_mechanism_failure"},
            min_active_seeds=4,
            min_meaningful_bps=1500,
            confirmed_bps=2000,
        )
        == "promotion_mechanism_failure"
    )
    assert (
        common.classify_effect(
            summaries=summaries,
            comparisons=comparisons,
            mechanism={"status": "mechanism_qualified", "active_seed_count": 4},
            min_active_seeds=4,
            min_meaningful_bps=1500,
            confirmed_bps=2000,
        )
        == "no_practical_oasg_effect"
    )


def test_classification_confirms_only_large_paired_effect_without_regression() -> None:
    common = _load_script("definitive_common")
    summaries = {
        "baseline_fixed": {
            "operational_debt_auc": 100,
            "unresolved_obligations": 10,
        },
        "oasg_adaptive": {
            "operational_debt_auc": 70,
            "unresolved_obligations": 8,
            "hard_floor_regression_count": 0,
        },
    }
    comparisons = {
        "oasg_adaptive_vs_baseline": {
            "bootstrap_ci": {"debt_auc_delta_ci": [-40, -20]},
        }
    }

    result = common.classify_effect(
        summaries=summaries,
        comparisons=comparisons,
        mechanism={"status": "mechanism_qualified", "active_seed_count": 5},
        min_active_seeds=4,
        min_meaningful_bps=1500,
        confirmed_bps=2000,
    )

    assert result == "oasg_effect_confirmed"


def test_classification_reports_regression_on_hard_floor_or_unresolved_growth() -> None:
    common = _load_script("definitive_common")
    comparisons = {
        "oasg_adaptive_vs_baseline": {
            "bootstrap_ci": {"debt_auc_delta_ci": [-40, -20]},
        }
    }

    assert (
        common.classify_effect(
            summaries={
                "baseline_fixed": {"operational_debt_auc": 100, "unresolved_obligations": 10},
                "oasg_adaptive": {
                    "operational_debt_auc": 70,
                    "unresolved_obligations": 8,
                    "hard_floor_regression_count": 1,
                },
            },
            comparisons=comparisons,
            mechanism={"status": "mechanism_qualified", "active_seed_count": 5},
            min_active_seeds=4,
            min_meaningful_bps=1500,
            confirmed_bps=2000,
        )
        == "regression_observed"
    )
    assert (
        common.classify_effect(
            summaries={
                "baseline_fixed": {"operational_debt_auc": 100, "unresolved_obligations": 10},
                "oasg_adaptive": {
                    "operational_debt_auc": 90,
                    "unresolved_obligations": 11,
                    "hard_floor_regression_count": 0,
                },
            },
            comparisons=comparisons,
            mechanism={"status": "mechanism_qualified", "active_seed_count": 5},
            min_active_seeds=4,
            min_meaningful_bps=1500,
            confirmed_bps=2000,
        )
        == "regression_observed"
    )


def test_analyze_definitive_fixture_produces_required_outputs(tmp_path: Path) -> None:
    analyze = _load_script("analyze_definitive_results")
    run_dir = tmp_path / "run"
    write_json(
        run_dir / "config.json",
        {
            "confirmatory_min_active_seeds": 1,
            "minimum_meaningful_reduction_bps": 1500,
            "effect_confirmed_min_reduction_bps": 2000,
        },
    )
    write_json(
        run_dir / "mechanism_qualification_receipt.json",
        {
            "receipt_type": "mechanism_qualification_receipt",
            "status": "mechanism_qualified",
            "active_seed_count": 1,
            "stage_b_allowed": True,
        },
    )
    seed_dir = run_dir / "seed_20260509"
    baseline_rows = [_row("task_001", "baseline_fixed", closed=False)]
    adaptive_rows = [
        {
            **_row("task_001", "oasg_adaptive", closed=True),
            "active_mutation_ids": ["mut_validator"],
        }
    ]
    forced_rows = [_row("task_001", "forced_policy_positive_control", closed=True)]
    observe_rows = [_row("task_001", "oasg_observe_only", closed=False)]
    for condition, rows in {
        "baseline_fixed": baseline_rows,
        "oasg_adaptive": adaptive_rows,
        "forced_policy_positive_control": forced_rows,
        "oasg_observe_only": observe_rows,
    }.items():
        write_json(seed_dir / condition / "task_results.json", rows)

    metrics = analyze.analyze_run(run_dir)

    assert "forced_policy_vs_baseline" in metrics["comparisons"]
    assert "oasg_adaptive_vs_baseline" in metrics["comparisons"]
    assert metrics["verification"]["status"] == "ok"
    assert metrics["promotion_diagnostic"]["status"] == "active_policy_observed"
    assert metrics["condition_summaries"]["baseline_fixed"]["task_count"] == 1
    assert metrics["paired_task_table"][0]["task_id"] == "task_001"


def _row(task_id: str, condition: str, *, closed: bool) -> dict[str, object]:
    return {
        "seed": "20260509",
        "task_id": task_id,
        "condition": condition,
        "epoch": 4,
        "phase": "longrun_eval",
        "burst": "validator_failure_burst",
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
        "active_policy_hash": "sha256:" + "1" * 64 if condition == "oasg_adaptive" else None,
        "active_mutation_ids": [],
    }
