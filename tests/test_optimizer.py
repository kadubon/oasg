from __future__ import annotations

from pathlib import Path
import sys

import pytest

from oasg.canonical import receipt_hash
from oasg.examples import quickstart_records
from oasg.harness import write_harness_template
from oasg.io import read_json, read_jsonl
from oasg.klb import calculate_klb
from oasg.library import (
    LibraryConflictError,
    load_library,
    quarantine_library_entry,
    rollback_library,
    write_library,
)
from oasg.ledger import seal_records
from oasg.lifecycle import shadow_candidate
from oasg.mutators import MutatorProfile, propose_mutations
from oasg.optimizer import run_optimizer
from oasg.optimizer import watch_optimizer
from oasg.operations import (
    write_mutation_candidate,
    write_observation_ledger,
    write_shadow_receipt,
    write_trial_ledger,
)
from oasg.pressure import compute_pressure
from oasg.reducers.core import reduce_records
from oasg.runners import default_runner
from oasg.scheduler import schedule_pressure


def _history(path: Path) -> Path:
    return write_observation_ledger(
        path,
        workflow_id="agent",
        component_id="planner",
        event_id="evt_history",
        dimensions={"budget": "acceptable"},
        action_grades={"pure_read": "acceptable"},
        effect_classes=["pure"],
        semantic_scope="none",
        claim_emitting=False,
        taint_level="public",
        assume_complete=True,
    )


def _harness_command(tmp_path: Path) -> tuple[str, ...]:
    harness = write_harness_template(tmp_path / "oasg_harness.py")
    return (
        sys.executable,
        str(harness),
        "--mutation",
        "{mutation}",
        "--candidate",
        "{candidate}",
    )


def test_pressure_and_scheduler_select_high_debt_component() -> None:
    records = quickstart_records(improved=False)
    records[0]["payload"]["dimensions"]["queue"] = "critical"
    snapshot = reduce_records(seal_records(records))
    pressure = compute_pressure(snapshot, calculate_klb(snapshot))
    scheduler = schedule_pressure(pressure, max_selected=4)
    assert pressure.coordinates["dimension.queue"] == "critical"
    assert "dimension.queue" in scheduler.selected_coordinates
    assert not scheduler.starvation_violation


def test_optimizer_promotes_witness_backed_local_policy_mutation(tmp_path: Path) -> None:
    history = _history(tmp_path / "history.jsonl")
    library = tmp_path / "workflow_library.json"
    result = run_optimizer(
        history=history,
        library_path=library,
        out_dir=tmp_path / "run",
        max_candidates=4,
        runner_type="local-command",
        runner_command=_harness_command(tmp_path),
    )
    assert result.receipt["status"] == "active_promoted"
    assert result.library.active_mutations
    assert result.library.rollback_pointer is not None
    assert library.exists()
    active = result.library.active_mutations[-1]
    patch = active["patch"]
    action_id = str(patch["target_action_id"])
    assert patch["op"] != "set_action_grade"
    policy_state = result.library.policy_state.to_dict()
    assert any(action_id in policy_state[surface] for surface in (
        "retry_policy",
        "validator_policy",
        "lease_caps",
        "semantic_policy",
        "routing_policy",
        "decomposition_policy",
        "context_policy",
        "rollback_policy",
    ))


def test_optimizer_does_not_promote_when_lease_does_not_execute(tmp_path: Path) -> None:
    history = _history(tmp_path / "history.jsonl")
    result = run_optimizer(
        history=history,
        library_path=tmp_path / "workflow_library.json",
        out_dir=tmp_path / "run",
        max_candidates=1,
        max_events=0,
    )
    assert result.receipt["status"] == "no_valid_candidate"
    assert not result.library.active_mutations


def test_optimizer_uses_active_policy_state_on_next_run(tmp_path: Path) -> None:
    history = _history(tmp_path / "history.jsonl")
    library = tmp_path / "workflow_library.json"
    first = run_optimizer(
        history=history,
        library_path=library,
        out_dir=tmp_path / "run1",
        max_candidates=4,
        runner_type="local-command",
        runner_command=_harness_command(tmp_path),
    )
    promoted_action = str(first.library.active_mutations[-1]["patch"]["target_action_id"])
    second = run_optimizer(
        history=history,
        library_path=library,
        out_dir=tmp_path / "run2",
        max_candidates=4,
        runner_type="local-command",
        runner_command=_harness_command(tmp_path),
    )
    proposals = read_json(second.paths["mutation_batch"])["proposals"]
    assert all(item["action_id"] != promoted_action for item in proposals)
    assert promoted_action in second.library.policy_state.to_dict()["retry_policy"] or any(
        promoted_action in second.library.policy_state.to_dict()[surface]
        for surface in (
            "validator_policy",
            "lease_caps",
            "semantic_policy",
            "routing_policy",
            "decomposition_policy",
            "context_policy",
            "rollback_policy",
        )
    )


def test_replay_runner_receipts_are_used_for_active_promotion(tmp_path: Path) -> None:
    history = _history(tmp_path / "history.jsonl")
    result = run_optimizer(
        history=history,
        library_path=tmp_path / "workflow_library.json",
        out_dir=tmp_path / "run",
        max_candidates=4,
        runner_type="local-command",
        runner_command=_harness_command(tmp_path),
    )
    mutation_id = str(result.library.active_mutations[-1]["mutation_id"])
    shadow = read_json(tmp_path / "run" / "cycle_001" / mutation_id / "comparison" / "shadow.json")
    lease = read_json(tmp_path / "run" / "cycle_001" / mutation_id / "comparison" / "lease.json")
    assert shadow["runner_type"] == "local-command"
    assert lease["runner_type"] == "local-command"
    assert shadow["workload_id"] == lease["workload_id"]
    assert result.receipt["runner_receipt_hashes"]
    assert result.receipt["trial_ledger_prefix_hashes"]
    assert shadow["trial_ledger_prefix_hash"] == lease["trial_ledger_prefix_hash"]


def test_optimizer_candidate_seed_has_no_self_evidence_and_gate_uses_trial(
    tmp_path: Path,
) -> None:
    history = _history(tmp_path / "history.jsonl")
    result = run_optimizer(
        history=history,
        library_path=tmp_path / "workflow_library.json",
        out_dir=tmp_path / "run",
        max_candidates=4,
        runner_type="local-command",
        runner_command=_harness_command(tmp_path),
    )
    assert result.receipt["status"] == "active_promoted"
    path_map = result.receipt["candidate_paths"][0]
    seed_snapshot = reduce_records(read_jsonl(Path(path_map["candidate"])))
    trial_snapshot = reduce_records(read_jsonl(Path(path_map["trial_candidate"])))
    assert seed_snapshot.positive_evidence == {}
    assert trial_snapshot.positive_evidence
    assert result.receipt["gate_receipt_hashes"]


def test_replay_runner_does_not_promote_candidate_self_evidence(tmp_path: Path) -> None:
    paths = write_mutation_candidate(
        tmp_path / "manual",
        mutation_id="mut_manual_grade",
        coordinate="KLB_2.pure_read",
        action_id="pure_read",
        to_grade="surplus",
    )
    seed = reduce_records(read_jsonl(paths["candidate"]))
    assert seed.positive_evidence
    trial = write_trial_ledger(
        paths["mutation"],
        paths["candidate"],
        tmp_path / "trial.jsonl",
        runner_type="ledger-replay",
    )
    assert trial.status == "trial_rejected"
    assert not trial.trial_snapshot.positive_evidence


def test_scheduler_state_persists_in_workflow_library(tmp_path: Path) -> None:
    history = _history(tmp_path / "history.jsonl")
    library = tmp_path / "workflow_library.json"
    first = run_optimizer(
        history=history,
        library_path=library,
        out_dir=tmp_path / "run1",
        max_candidates=1,
        max_events=0,
    )
    assert first.library.scheduler_state is not None
    first_age = dict(first.library.scheduler_state.pressure_age)
    second = run_optimizer(
        history=history,
        library_path=library,
        out_dir=tmp_path / "run2",
        max_candidates=1,
        max_events=0,
    )
    assert second.library.scheduler_state is not None
    assert max(second.library.scheduler_state.pressure_age.values()) >= max(first_age.values())


def test_rollback_restores_previous_policy_state(tmp_path: Path) -> None:
    history = _history(tmp_path / "history.jsonl")
    result = run_optimizer(
        history=history,
        library_path=tmp_path / "workflow_library.json",
        out_dir=tmp_path / "run",
        max_candidates=4,
        runner_type="local-command",
        runner_command=_harness_command(tmp_path),
    )
    before_hash = receipt_hash(result.library.policy_state.to_dict())
    restored = rollback_library(load_library(tmp_path / "workflow_library.json"))
    after_hash = receipt_hash(restored.policy_state.to_dict())
    assert before_hash != after_hash
    assert not restored.active_mutations
    assert not restored.active_promotion_receipts
    assert restored.retired


def test_optimize_watch_persists_state_and_skips_unchanged_history(tmp_path: Path) -> None:
    history = _history(tmp_path / "history.jsonl")
    library = tmp_path / "workflow_library.json"
    state = tmp_path / "optimizer_state.json"
    first = watch_optimizer(
        history=history,
        library_path=library,
        state_path=state,
        out_dir=tmp_path / "watch1",
        max_iterations=1,
        runner_type="local-command",
        runner_command=_harness_command(tmp_path),
    )
    assert first["status"] == "active_promoted"
    saved = read_json(state)
    assert saved["last_append_index"] == 1
    second = watch_optimizer(
        history=history,
        library_path=library,
        state_path=state,
        out_dir=tmp_path / "watch2",
        max_iterations=1,
        runner_type="local-command",
        runner_command=_harness_command(tmp_path),
    )
    assert second["status"] == "no_new_work"
    assert second["iterations_completed"] == 0


def test_optimize_watch_can_append_lease_observations(tmp_path: Path) -> None:
    history = _history(tmp_path / "history.jsonl")
    library = tmp_path / "workflow_library.json"
    state = tmp_path / "optimizer_state.json"
    first = watch_optimizer(
        history=history,
        library_path=library,
        state_path=state,
        out_dir=tmp_path / "watch",
        max_iterations=1,
        append_lease_observations=True,
        runner_type="local-command",
        runner_command=_harness_command(tmp_path),
    )
    assert first["status"] == "active_promoted"
    assert len(read_jsonl(history)) == 2
    saved = read_json(state)
    assert saved["last_append_index"] == 2


def test_local_command_runner_uses_argv_and_rejects_shell_string() -> None:
    with pytest.raises(ValueError):
        default_runner("local-command", command=("echo hello",))
    runner = default_runner(
        "local-command",
        command=(sys.executable, "-c", "print('oasg')"),
    )
    assert runner.runner_type == "local-command"


def test_local_command_runner_requires_trial_ledger_output(tmp_path: Path) -> None:
    paths = write_mutation_candidate(
        tmp_path / "mutation",
        mutation_id="mut_cmd",
        coordinate="KLB_2.pure_read",
        action_id="pure_read",
        to_grade="surplus",
    )
    shadow = tmp_path / "shadow.json"
    result = write_shadow_receipt(
        paths["mutation"],
        paths["candidate"],
        shadow,
        runner_type="local-command",
        runner_command=(sys.executable, "-c", "print('not-jsonl')"),
    )
    assert read_json(result)["status"] == "shadow_rejected"


def test_local_command_runner_accepts_stdout_oasg_jsonl(tmp_path: Path) -> None:
    paths = write_mutation_candidate(
        tmp_path / "mutation_stdout",
        mutation_id="mut_cmd_stdout",
        coordinate="KLB_2.pure_read",
        action_id="pure_read",
        to_grade="surplus",
    )
    ledger_text = Path(paths["candidate"]).read_text(encoding="utf-8")
    script = "import pathlib,sys; sys.stdout.write(pathlib.Path(sys.argv[1]).read_text())"
    shadow = tmp_path / "shadow_stdout.json"
    write_shadow_receipt(
        paths["mutation"],
        paths["candidate"],
        shadow,
        runner_type="local-command",
        runner_command=(sys.executable, "-c", script, str(paths["candidate"])),
    )
    assert ledger_text
    assert read_json(shadow)["status"] == "shadow_passed"


def test_mutator_profile_disables_unlisted_mutators(tmp_path: Path) -> None:
    history = _history(tmp_path / "history.jsonl")
    snapshot = reduce_records(seal_records(quickstart_records(improved=False)))
    pressure = compute_pressure(snapshot, calculate_klb(snapshot))
    scheduler = schedule_pressure(pressure, max_selected=4)
    batch = propose_mutations(
        snapshot,
        calculate_klb(snapshot),
        scheduler,
        load_library(None).policy,
        mutator_profile=MutatorProfile(enabled_mutators=("retry_backoff_v1_0",)),
    )
    assert all(proposal.mutator_id.startswith("retry_backoff_v1_") for proposal in batch.proposals)
    result = run_optimizer(
        history=history,
        library_path=tmp_path / "profile_library.json",
        out_dir=tmp_path / "profile_run",
        mutator_profile=MutatorProfile(enabled_mutators=("retry_backoff_v1_0",)),
        runner_type="local-command",
        runner_command=_harness_command(tmp_path),
    )
    assert result.receipt["status"] == "active_promoted"
    assert result.library.active_mutations[-1]["patch"]["mutator_id"].startswith("retry_backoff_v1_")


def test_mutation_outcome_memory_cools_down_failed_patch(tmp_path: Path) -> None:
    history = write_observation_ledger(
        tmp_path / "history.jsonl",
        workflow_id="agent",
        component_id="scheduler",
        event_id="evt_queue_pressure",
        dimensions={"queue": "critical"},
        action_grades={"close_obligation": "acceptable"},
        effect_classes=["pure"],
        semantic_scope="none",
        claim_emitting=False,
        taint_level="public",
        assume_complete=True,
    )
    library = tmp_path / "workflow_library.json"
    first = run_optimizer(
        history=history,
        library_path=library,
        out_dir=tmp_path / "run1",
        mutator_profile=MutatorProfile(enabled_mutators=("retry_backoff_v1_0",)),
        runner_type="local-command",
        runner_command=_harness_command(tmp_path),
    )
    assert first.library.mutation_outcomes
    second = run_optimizer(
        history=history,
        library_path=library,
        out_dir=tmp_path / "run2",
        mutator_profile=MutatorProfile(enabled_mutators=("retry_backoff_v1_0",)),
        runner_type="local-command",
        runner_command=_harness_command(tmp_path),
    )
    proposals = read_json(second.paths["mutation_batch"])["proposals"]
    assert proposals == []


def test_conflict_safe_library_write_rejects_stale_expected_hash(tmp_path: Path) -> None:
    library_path = tmp_path / "workflow_library.json"
    library = load_library(None)
    write_library(library_path, library)
    stale_hash = receipt_hash(library.to_dict())
    updated = quarantine_library_entry(library, mutation_id="mut_conflict", reason="test")
    write_library(library_path, updated)
    with pytest.raises(LibraryConflictError):
        write_library(library_path, library, expected_prior_hash=stale_hash)


def test_shadow_rejects_candidate_without_positive_evidence() -> None:
    shadow = shadow_candidate(
        {
            "mutation_id": "mut_missing",
            "declared_improvement_coordinates": ["KLB_2.pure_read"],
        },
        "sha256:" + "0" * 64,
        candidate_records_seen=1,
        candidate_positive_evidence={},
    )
    assert shadow.status == "shadow_rejected"


def test_klb_receipt_persists_trace_receipts() -> None:
    snapshot = reduce_records(seal_records(quickstart_records(improved=False)))
    klb = calculate_klb(snapshot)
    assert len(klb.abstract_trace_receipts) == 73
    assert klb.abstract_trace_receipts[0]["status"] == "trace_viable"
