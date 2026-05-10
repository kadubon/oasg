from __future__ import annotations

from pathlib import Path
import sys

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from oasg.cli import app
from oasg.conformance import run_conformance
from oasg.harness import write_harness_template
from oasg.io import read_json, write_json
from oasg.models import PositiveEvidenceWitness
from oasg.schemas.export import schema_documents


def test_schema_export_includes_first_wave_artifacts() -> None:
    schemas = schema_documents()
    expected = {
        "event_record",
        "candidate_path_record",
        "ledger_integrity_receipt",
        "schema_migration_record",
        "coverage_certificate",
        "rejection_record",
        "reducer_snapshot",
        "proof_obligation_receipt",
        "protected_debt_record",
        "abstract_action_class",
        "abstract_trace_receipt",
        "klb_receipt",
        "positive_evidence_witness",
        "comparison_contract",
        "workload_manifest",
        "dominance_gate_receipt",
        "active_promotion_receipt",
        "mutator_profile",
        "mutation_batch",
        "mutation_outcome_record",
        "workflow_library",
        "trial_session",
        "optimizer_run_receipt",
        "optimizer_state",
        "workload_execution_receipt",
        "trial_ledger_receipt",
        "ledger_append_receipt",
        "runner_output_receipt",
        "policy_diff",
        "rollback_snapshot",
        "library_conflict_receipt",
        "library_history_receipt",
        "runner_profile",
        "trial_bundle",
        "harness_receipt",
        "phase_receipt",
        "effect_counts",
        "resource_usage",
        "pending_trial",
        "supervisor_state",
        "rollback_receipt",
        "quarantine_record",
        "quarantined_library_entry",
    }
    assert expected <= set(schemas)


def _runner_args(tmp_path: Path) -> list[str]:
    harness = write_harness_template(tmp_path / "oasg_harness.py")
    return [
        "--runner",
        "local-command",
        "--runner-arg",
        sys.executable,
        "--runner-arg",
        str(harness),
        "--runner-arg",
        "--mutation",
        "--runner-arg",
        "{mutation}",
        "--runner-arg",
        "--candidate",
        "--runner-arg",
        "{candidate}",
    ]


def test_cli_quickstart_and_gate(tmp_path: Path) -> None:
    runner = CliRunner()
    example_dir = tmp_path / "quickstart"
    result = runner.invoke(app, ["demo", "quickstart", "--out", str(example_dir)])
    assert result.exit_code == 0, result.output

    out = tmp_path / "gate.json"
    result = runner.invoke(
        app,
        [
            "gate",
            "--baseline",
            str(example_dir / "baseline.jsonl"),
            "--candidate",
            str(example_dir / "candidate.jsonl"),
            "--contract",
            str(example_dir / "comparison_contract.json"),
            "--workload",
            str(example_dir / "workload_manifest.json"),
            "--witnesses",
            str(example_dir / "positive_evidence_witnesses.json"),
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    assert read_json(out)["status"] == "safe_promotion"


def test_cli_doctor() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert '"network_default": "disabled"' in result.output


def test_conformance_runner_passes(tmp_path: Path) -> None:
    results = run_conformance(tmp_path)
    assert all(result.passed for result in results)


def test_cli_practical_loop_reaches_active_promotion(tmp_path: Path) -> None:
    runner = CliRunner()
    baseline = tmp_path / "baseline.jsonl"
    mutation_dir = tmp_path / "mutation"
    comparison = tmp_path / "comparison"

    result = runner.invoke(
        app,
        [
            "observe",
            "--out",
            str(baseline),
            "--dimension",
            "budget=acceptable",
            "--action",
            "pure_read=acceptable",
            "--assume-complete",
        ],
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(
        app,
        [
            "mutate",
            "plan",
            "--out-dir",
            str(mutation_dir),
            "--mutation-id",
            "mut_loop",
            "--coordinate",
            "KLB_2.pure_read",
            "--action-id",
            "pure_read",
        ],
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(
        app,
        [
            "compare",
            "--baseline",
            str(baseline),
            "--candidate",
            str(mutation_dir / "candidate.jsonl"),
            "--out-dir",
            str(comparison),
        ],
    )
    assert result.exit_code == 0, result.output

    witnesses = comparison / "positive_evidence_witnesses.json"
    result = runner.invoke(
        app,
        [
            "witness",
            "--coordinate",
            "KLB_2.pure_read",
            "--candidate-snapshot",
            str(comparison / "candidate_snapshot.json"),
            "--candidate-klb",
            str(comparison / "candidate_klb_receipt.json"),
            "--contract",
            str(comparison / "comparison_contract.json"),
            "--workload",
            str(comparison / "workload_manifest.json"),
            "--out",
            str(witnesses),
        ],
    )
    assert result.exit_code == 0, result.output

    gate = comparison / "gate.json"
    result = runner.invoke(
        app,
        [
            "gate",
            "--baseline",
            str(baseline),
            "--candidate",
            str(mutation_dir / "candidate.jsonl"),
            "--contract",
            str(comparison / "comparison_contract.json"),
            "--workload",
            str(comparison / "workload_manifest.json"),
            "--witnesses",
            str(witnesses),
            "--out",
            str(gate),
        ],
    )
    assert result.exit_code == 0, result.output
    gate_receipt = read_json(gate)
    assert gate_receipt["status"] == "safe_promotion"
    assert gate_receipt["improved_coordinates"] == ["KLB_2.pure_read"]

    shadow = comparison / "shadow.json"
    lease = comparison / "lease.json"
    active = comparison / "active.json"
    result = runner.invoke(
        app,
        [
            "shadow",
            "--mutation",
            str(mutation_dir / "mutation_record.json"),
            "--candidate",
            str(mutation_dir / "candidate.jsonl"),
            "--out",
            str(shadow),
        ],
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(
        app,
        [
            "lease",
            "--mutation",
            str(mutation_dir / "mutation_record.json"),
            "--candidate",
            str(mutation_dir / "candidate.jsonl"),
            "--out",
            str(lease),
        ],
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(
        app,
        [
            "library",
            "promote",
            "--gate",
            str(gate),
            "--shadow",
            str(shadow),
            "--lease",
            str(lease),
            "--mutation",
            str(mutation_dir / "mutation_record.json"),
            "--out",
            str(active),
        ],
    )
    assert result.exit_code == 0, result.output
    active_receipt = read_json(active)
    assert active_receipt["receipt_type"] == "active_promotion_receipt"
    assert active_receipt["status"] == "rejected_active_promotion"
    assert "manual_action_grade_patch_not_active_promotable" in active_receipt["rejected_reasons"]


def test_cli_optimizer_run_updates_workflow_library(tmp_path: Path) -> None:
    runner = CliRunner()
    history = tmp_path / "history.jsonl"
    library = tmp_path / "workflow_library.json"
    run_dir = tmp_path / "run"

    result = runner.invoke(
        app,
        [
            "observe",
            "--out",
            str(history),
            "--workflow-id",
            "optimizer_agent",
            "--component-id",
            "planner",
            "--dimension",
            "budget=acceptable",
            "--action",
            "pure_read=acceptable",
            "--assume-complete",
        ],
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(
        app,
        [
            "optimize",
            "run",
            "--history",
            str(history),
            "--library",
            str(library),
            "--out-dir",
            str(run_dir),
            *_runner_args(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    receipt = read_json(run_dir / "optimizer_run_receipt.json")
    assert receipt["status"] == "active_promoted"
    library_state = read_json(library)
    assert library_state["active_mutations"]

    result = runner.invoke(app, ["library", "status", "--library", str(library)])
    assert result.exit_code == 0, result.output
    assert "workflow_library" in result.output


def test_cli_optimize_supervise_alias(tmp_path: Path) -> None:
    runner = CliRunner()
    history = tmp_path / "history.jsonl"
    library = tmp_path / "workflow_library.json"
    state = tmp_path / "optimizer_state.json"
    out_dir = tmp_path / "supervise"
    result = runner.invoke(
        app,
        [
            "observe",
            "--out",
            str(history),
            "--dimension",
            "budget=acceptable",
            "--action",
            "pure_read=acceptable",
            "--assume-complete",
        ],
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(
        app,
        [
            "optimize",
            "supervise",
            "--history",
            str(history),
            "--library",
            str(library),
            "--state",
            str(state),
            "--out-dir",
            str(out_dir),
            "--max-iterations",
            "1",
            *_runner_args(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert read_json(out_dir / "optimizer_watch_receipt.json")["status"] == "active_promoted"


def test_cli_longrun_experiment_verification_helpers(tmp_path: Path) -> None:
    runner = CliRunner()
    run_dir = tmp_path / "run"
    for condition in ("baseline_fixed", "oasg_observe_only", "oasg_adaptive"):
        condition_dir = run_dir / condition
        condition_dir.mkdir(parents=True)
        result = runner.invoke(
            app,
            [
                "observe",
                "--out",
                str(condition_dir / "history.jsonl"),
                "--workflow-id",
                condition,
                "--dimension",
                "budget=acceptable",
                "--action",
                "pure_read=acceptable",
                "--assume-complete",
            ],
        )
        assert result.exit_code == 0, result.output
        write_json(condition_dir / "task_results.json", [])

    verify_out = tmp_path / "verification.json"
    result = runner.invoke(
        app,
        [
            "experiment",
            "verify-longrun",
            "--run-dir",
            str(run_dir),
            "--out",
            str(verify_out),
        ],
    )
    assert result.exit_code == 0, result.output
    assert read_json(verify_out)["status"] == "ok"

    diagnostic_out = tmp_path / "diagnostic.json"
    result = runner.invoke(
        app,
        [
            "experiment",
            "diagnose-promotion",
            "--run-dir",
            str(run_dir),
            "--out",
            str(diagnostic_out),
        ],
    )
    assert result.exit_code == 0, result.output
    diagnostic = read_json(diagnostic_out)
    assert diagnostic["adaptive_readiness"]["status"] == "no_active_policy"


def test_schema_model_rejects_malformed_hash() -> None:
    with pytest.raises(ValidationError):
        PositiveEvidenceWitness(
            witness_id="bad",
            coordinate_id="KLB_2.pure_read",
            evidence_hashes=["sha256:not-a-real-hash"],
            ledger_prefix_hash="sha256:not-a-real-hash",
            comparison_contract_hash="sha256:not-a-real-hash",
            workload_manifest_hash="sha256:not-a-real-hash",
        )


def test_policy_loader_rejects_unknown_fields(tmp_path: Path) -> None:
    from oasg.io import write_json
    from oasg.policy import load_policy

    policy = tmp_path / "policy.json"
    write_json(
        policy,
        {
            "profile_id": "bad",
            "horizon": 2,
            "max_trace_classes": 73,
            "unexpected": True,
            "actions": [
                {
                    "action_id": "pure_read",
                    "requirements": ["budget"],
                }
            ],
        },
    )
    with pytest.raises(ValidationError):
        load_policy(policy)
