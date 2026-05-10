from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from oasg.events import event_record, observation_payload
from oasg.io import read_jsonl, write_json, write_jsonl
from oasg.ledger import seal_records, verify_jsonl
from oasg.policy_state import WorkflowPolicyState

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "experiment" / "ollama_gemma4_e4b_pilot"


def _load_script(name: str) -> ModuleType:
    path = PILOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_task_validator_marks_pass_and_fail() -> None:
    run_experiment = _load_script("run_experiment")
    task = {
        "validator": "json_equals",
        "expected": {"result": [2, 6, 8]},
    }

    assert run_experiment._validate_output(task, '{"result":[2,6,8]}') == (True, True, None)
    parsed, passed, reason = run_experiment._validate_output(task, '{"result":[6,8]}')

    assert parsed is True
    assert passed is False
    assert reason == "json_not_equal"


def test_effect_task_generator_is_deterministic() -> None:
    generator = _load_script("generate_effect_tasks")

    first = generator.generate_effect_tasks(20260508)
    second = generator.generate_effect_tasks(20260508)

    assert first == second
    assert len(first) == 60
    assert sum(1 for task in first if task["phase"] == "calibration") == 12
    assert sum(1 for task in first if task["phase"] == "evaluation") == 48
    assert {
        "strict_json_extraction",
        "schema_repair",
        "safe_python_expression",
        "code_transform",
        "validator_receipt",
    } == {task["family"] for task in first}


def test_preflight_reports_missing_model(monkeypatch: Any) -> None:
    run_experiment = _load_script("run_experiment")

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"models": [{"name": "other:model"}]}).encode("utf-8")

    monkeypatch.setattr(run_experiment, "urlopen", lambda *_args, **_kwargs: FakeResponse())
    result = run_experiment._preflight(
        {"ollama_endpoint": "http://127.0.0.1:11434", "model": "gemma4:e4b"}
    )

    assert result["status"] == "failed"
    assert result["reason"] == "model_missing"


def test_generated_observation_ledger_verifies(tmp_path: Path) -> None:
    run_experiment = _load_script("run_experiment")
    result = run_experiment.TaskResult(
        task_id="json_001",
        condition="baseline_fixed",
        batch_index=1,
        closed=True,
        parsed=True,
        validation_passed=True,
        attempts=1,
        retries=0,
        latency_ms=12,
        prompt_chars=20,
        output_chars=18,
        unresolved_obligations=0,
        error=None,
        output_hash="sha256:test",
    )
    ledger = tmp_path / "history.jsonl"
    run_experiment._write_history(
        ledger,
        [run_experiment._initial_event("baseline_fixed"), run_experiment._result_event(result)],
    )

    receipt = verify_jsonl(ledger)

    assert receipt.status == "ledger_prefix_valid"
    assert receipt.records_seen == 2


def test_effect_retry_prompt_requires_active_policy(monkeypatch: Any) -> None:
    run_experiment = _load_script("run_experiment")
    task = {
        "task_id": "effect_001",
        "phase": "evaluation",
        "family": "strict_json_extraction",
        "validator": "json_equals",
        "instruction": "Return result [2].",
        "expected": {"result": [2]},
    }
    policy = WorkflowPolicyState.default()
    policy = WorkflowPolicyState(
        state_id=policy.state_id,
        policy_profile=policy.policy_profile,
        retry_policy={"close_obligation": "bounded_exponential_backoff"},
    )

    baseline_prompt = run_experiment._prompt_for(
        task,
        attempt=1,
        last_error=None,
        effect_profile=True,
        policy_state=None,
        adaptive=False,
    )
    adaptive_prompt = run_experiment._prompt_for(
        task,
        attempt=1,
        last_error=None,
        effect_profile=True,
        policy_state=policy,
        adaptive=True,
    )

    assert "Answer the coding-operations request concisely" in baseline_prompt
    assert "Return exactly one minified JSON object" in adaptive_prompt

    monkeypatch.setattr(run_experiment, "_call_ollama", lambda _config, _prompt: ('{"result":[2]}', None))
    result = run_experiment._run_task(
        task=task,
        condition="oasg_adaptive",
        batch_index=3,
        config={"effect_profile": True, "timeout_seconds": 1},
        max_attempts=2,
        policy_state=policy,
        adaptive=True,
    )

    assert result.retry_policy_authorized is True
    assert result.active_policy_hash is not None
    assert result.prompt_template_ids == ("effect_promoted_strict_strict_json_extraction",)


def test_trial_harness_emits_valid_sealed_jsonl(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.jsonl"
    records = seal_records(
        [
            event_record(
                event_id="evt_seed",
                workflow_id="pilot",
                component_id="seed",
                event_type="observation",
                payload=observation_payload(),
            )
        ]
    )
    write_jsonl(candidate, records)
    mutation = tmp_path / "mutation.json"
    write_json(
        mutation,
        {
            "mutation_id": "mut_retry",
            "patch": {
                "mutation_id": "mut_retry",
                "op": "set_retry_policy",
                "target_surface": "workflow_policy",
                "target_action_id": "close_obligation",
                "coordinate_id": "KLB_2.close_obligation",
                "value": "bounded_retry",
                "mutator_id": "retry_backoff",
                "precondition_policy_hash": None,
                "resulting_policy_hash": None,
            },
        },
    )
    metrics = tmp_path / "metrics.json"
    write_json(
        metrics,
        {
            "validation_failures": 1,
            "unresolved_obligations": 1,
            "retry_count": 0,
            "mean_latency_ms": 10,
            "source_hash": "sha256:metrics",
        },
    )
    out = tmp_path / "trial.jsonl"

    completed = subprocess.run(
        [
            sys.executable,
            str(PILOT / "scripts" / "oasg_trial_harness.py"),
            "--mutation",
            str(mutation),
            "--candidate",
            str(candidate),
            "--metrics",
            str(metrics),
            "--out",
            str(out),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert verify_jsonl(out).status == "ledger_prefix_valid"
    payload = read_jsonl(out)[0]["payload"]
    assert payload["positive_evidence"]


def test_trial_harness_rejects_manual_grade_self_evidence(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.jsonl"
    write_jsonl(
        candidate,
        seal_records(
            [
                event_record(
                    event_id="evt_seed",
                    workflow_id="pilot",
                    component_id="seed",
                    event_type="observation",
                    payload=observation_payload(),
                )
            ]
        ),
    )
    mutation = tmp_path / "mutation.json"
    write_json(
        mutation,
        {
            "mutation_id": "mut_grade",
            "patch": {
                "mutation_id": "mut_grade",
                "op": "set_action_grade",
                "target_surface": "workflow_policy",
                "target_action_id": "close_obligation",
                "coordinate_id": "KLB_2.close_obligation",
                "value": "surplus",
                "mutator_id": "manual_grade",
                "precondition_policy_hash": None,
                "resulting_policy_hash": None,
            },
        },
    )
    metrics = tmp_path / "metrics.json"
    write_json(metrics, {"validation_failures": 2, "unresolved_obligations": 2})
    out = tmp_path / "trial.jsonl"

    completed = subprocess.run(
        [
            sys.executable,
            str(PILOT / "scripts" / "oasg_trial_harness.py"),
            "--mutation",
            str(mutation),
            "--candidate",
            str(candidate),
            "--metrics",
            str(metrics),
            "--out",
            str(out),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    payload = read_jsonl(out)[0]["payload"]
    assert payload["positive_evidence"] == []
    assert payload["model_event"]["rejection_reason"] == "manual_action_grade"


def test_analysis_reports_failed_and_rejected_cases(tmp_path: Path) -> None:
    analyze_results = _load_script("analyze_results")
    run_dir = tmp_path / "run"
    baseline = run_dir / "baseline_fixed"
    adaptive = run_dir / "oasg_adaptive"
    baseline.mkdir(parents=True)
    adaptive.mkdir(parents=True)
    write_json(run_dir / "config.json", {"model": "gemma4:e4b"})
    write_json(run_dir / "task_manifest.json", {"task_count": 1, "task_ids": ["t1"]})
    write_json(
        baseline / "task_results.json",
        [
            {
                "task_id": "t1",
                "closed": False,
                "parsed": False,
                "validation_passed": False,
                "attempts": 1,
                "retries": 0,
                "latency_ms": 10,
                "prompt_chars": 10,
                "output_chars": 0,
                "unresolved_obligations": 1,
                "error": "json_parse_failed",
            }
        ],
    )
    write_json(
        adaptive / "task_results.json",
        [
            {
                "task_id": "t1",
                "closed": False,
                "parsed": True,
                "validation_passed": False,
                "attempts": 2,
                "retries": 1,
                "latency_ms": 20,
                "prompt_chars": 12,
                "output_chars": 8,
                "unresolved_obligations": 1,
                "error": "json_not_equal",
            }
        ],
    )
    gate_dir = adaptive / "oasg_runs" / "batch_01"
    gate_dir.mkdir(parents=True)
    write_json(
        gate_dir / "gate.json",
        {"receipt_type": "dominance_gate_receipt", "status": "rejected_no_strict_improvement"},
    )

    metrics = analyze_results.analyze_run(run_dir)

    assert metrics["classification"] == "no_clear_effect"
    assert metrics["baseline_fixed"]["errors"] == ["json_parse_failed"]
    assert metrics["oasg_adaptive"]["errors"] == ["json_not_equal"]
    assert metrics["oasg_artifacts"]["rejected_gate_count"] == 1


def test_analysis_excludes_calibration_from_primary_metrics(tmp_path: Path) -> None:
    analyze_results = _load_script("analyze_results")
    run_dir = tmp_path / "run"
    baseline = run_dir / "baseline_fixed"
    adaptive = run_dir / "oasg_adaptive"
    baseline.mkdir(parents=True)
    adaptive.mkdir(parents=True)
    write_json(run_dir / "config.json", {"model": "gemma4:e4b", "effect_profile": True})
    write_json(run_dir / "task_manifest.json", {"task_count": 2})
    write_json(
        baseline / "task_results.json",
        [
            {
                "task_id": "cal_1",
                "phase": "calibration",
                "closed": False,
                "parsed": False,
                "validation_passed": False,
                "attempts": 1,
                "retries": 0,
                "latency_ms": 10,
                "prompt_chars": 10,
                "output_chars": 0,
                "unresolved_obligations": 1,
                "error": "json_parse_failed",
            },
            {
                "task_id": "eval_1",
                "phase": "evaluation",
                "closed": False,
                "parsed": True,
                "validation_passed": False,
                "attempts": 1,
                "retries": 0,
                "latency_ms": 10,
                "prompt_chars": 10,
                "output_chars": 4,
                "unresolved_obligations": 1,
                "error": "json_not_equal",
            },
        ],
    )
    write_json(
        adaptive / "task_results.json",
        [
            {
                "task_id": "cal_1",
                "phase": "calibration",
                "closed": False,
                "parsed": False,
                "validation_passed": False,
                "attempts": 1,
                "retries": 0,
                "latency_ms": 10,
                "prompt_chars": 10,
                "output_chars": 0,
                "unresolved_obligations": 1,
                "error": "json_parse_failed",
            },
            {
                "task_id": "eval_1",
                "phase": "evaluation",
                "closed": True,
                "parsed": True,
                "validation_passed": True,
                "attempts": 2,
                "retries": 1,
                "latency_ms": 20,
                "prompt_chars": 15,
                "output_chars": 10,
                "unresolved_obligations": 0,
                "error": None,
            },
        ],
    )

    metrics = analyze_results.analyze_run(run_dir)

    assert metrics["baseline_fixed"]["task_count"] == 1
    assert metrics["oasg_adaptive"]["task_count"] == 1
    assert metrics["calibration"]["baseline_fixed"]["task_count"] == 1
    assert metrics["paired_effects"]["closure_delta"] == 1
    assert metrics["classification"] == "improvement_observed"
