"""OASG command line interface."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Callable

import typer
from pydantic import ValidationError
from rich.console import Console

from oasg.conformance import run_conformance
from oasg.examples import write_quickstart
from oasg.experiment_tools import diagnose_promotion, verify_longrun_run
from oasg.gate import evaluate_gate
from oasg.canonical import receipt_hash
from oasg.harness import write_harness_template
from oasg.io import read_json, write_json
from oasg.klb import calculate_klb
from oasg.ledger import append_jsonl, verify_jsonl
from oasg.library import (
    LibraryConflictError,
    load_library,
    quarantine_library_entry,
    rollback_library,
    write_library,
)
from oasg.models import ComparisonContract, PositiveEvidenceWitness, WorkloadManifest
from oasg.mutators import load_mutator_profile
from oasg.mutators import MutatorProfile
from oasg.optimizer import plan_optimizer, run_optimizer, supervise_optimizer, watch_optimizer
from oasg.optimizer_state import load_optimizer_state
from oasg.operations import (
    build_klb_witness,
    write_active_promotion,
    write_comparison_bundle,
    write_lease_receipt,
    write_mutation_candidate,
    write_observation_ledger,
    write_shadow_receipt,
    write_trial_bundle,
)
from oasg.policy import load_policy, write_default_policy
from oasg.pressure import compute_pressure
from oasg.reducers.core import ReducerSnapshot, reduce_ledger
from oasg.scheduler import SchedulerResult, schedule_pressure
from oasg.schemas import export_schemas

app = typer.Typer(help="OASG local-first workflow self-improvement toolkit.")
ledger_app = typer.Typer(help="Ledger operations.")
schema_app = typer.Typer(help="JSON Schema operations.")
demo_app = typer.Typer(help="Demo generators.")
conformance_app = typer.Typer(help="Conformance fixtures.")
mutate_app = typer.Typer(help="Mutation planning operations.")
mutator_app = typer.Typer(help="Mutator profile operations.")
mutator_profile_app = typer.Typer(help="Mutator profile helpers.")
library_app = typer.Typer(help="Workflow library operations.")
optimize_app = typer.Typer(help="Autonomic optimization operations.")
workload_app = typer.Typer(help="Workload manifest and runner helpers.")
harness_app = typer.Typer(help="Workflow harness helpers.")
trial_app = typer.Typer(help="Trial session helpers.")
experiment_app = typer.Typer(help="Experiment verification helpers.")
app.add_typer(ledger_app, name="ledger")
app.add_typer(schema_app, name="schema")
app.add_typer(demo_app, name="demo")
app.add_typer(conformance_app, name="conformance")
app.add_typer(mutate_app, name="mutate")
app.add_typer(mutator_app, name="mutator")
mutator_app.add_typer(mutator_profile_app, name="profile")
app.add_typer(library_app, name="library")
app.add_typer(optimize_app, name="optimize")
app.add_typer(workload_app, name="workload")
app.add_typer(harness_app, name="harness")
app.add_typer(trial_app, name="trial")
app.add_typer(experiment_app, name="experiment")
console = Console()


@app.command()
def init(path: Annotated[Path, typer.Argument()] = Path(".oasg")) -> None:
    """Create a local OASG working directory."""

    def _init() -> dict[str, object]:
        path.mkdir(parents=True, exist_ok=True)
        (path / "receipts").mkdir(exist_ok=True)
        (path / "snapshots").mkdir(exist_ok=True)
        return {"receipt_type": "init_receipt", "status": "ok", "path": str(path)}

    _guard(_init, None)


@app.command("observe")
def observe_command(
    out: Annotated[Path, typer.Option("--out")],
    workflow_id: Annotated[str, typer.Option("--workflow-id")] = "default",
    component_id: Annotated[str, typer.Option("--component-id")] = "agent",
    event_id: Annotated[str, typer.Option("--event-id")] = "evt_observation",
    dimension: Annotated[list[str] | None, typer.Option("--dimension")] = None,
    action: Annotated[list[str] | None, typer.Option("--action")] = None,
    effect: Annotated[list[str] | None, typer.Option("--effect")] = None,
    semantic_scope: Annotated[str, typer.Option("--semantic-scope")] = "none",
    claim_emitting: Annotated[bool, typer.Option("--claim-emitting")] = False,
    taint_level: Annotated[str, typer.Option("--taint-level")] = "public",
    policy: Annotated[Path | None, typer.Option("--policy")] = None,
    assume_complete: Annotated[
        bool,
        typer.Option(
            "--assume-complete",
            help="Demo shortcut: treat omitted dimensions/actions as acceptable.",
        ),
    ] = False,
) -> None:
    """Create a sealed observation ledger from CLI key=value inputs."""

    _guard(
        lambda: {
            "receipt_type": "observe_receipt",
            "status": "ok",
            "ledger": str(
                write_observation_ledger(
                    out,
                    workflow_id=workflow_id,
                    component_id=component_id,
                    event_id=event_id,
                    dimensions=_parse_pairs(dimension),
                    action_grades=_parse_pairs(action),
                    effect_classes=effect or ["pure"],
                    semantic_scope=semantic_scope,
                    claim_emitting=claim_emitting,
                    taint_level=taint_level,
                    policy=load_policy(policy),
                    assume_complete=assume_complete,
                )
            ),
        },
        None,
    )


@app.command()
def doctor() -> None:
    """Print a local environment health summary."""

    _emit(
        {
            "receipt_type": "doctor_receipt",
            "status": "ok",
            "network_default": "disabled",
        },
        None,
    )


@app.command("compare")
def compare_command(
    baseline: Annotated[Path, typer.Option("--baseline")],
    candidate: Annotated[Path, typer.Option("--candidate")],
    out_dir: Annotated[Path, typer.Option("--out-dir")],
    policy: Annotated[Path | None, typer.Option("--policy")] = None,
) -> None:
    """Build deterministic comparison artifacts for a baseline/candidate pair."""

    _guard(
        lambda: _paths_receipt(
            "compare_receipt",
            write_comparison_bundle(
                out_dir,
                baseline=baseline,
                candidate=candidate,
                policy=load_policy(policy),
            ),
        ),
        None,
    )


@app.command("witness")
def witness_command(
    coordinate: Annotated[str, typer.Option("--coordinate")],
    candidate_snapshot: Annotated[Path, typer.Option("--candidate-snapshot")],
    candidate_klb: Annotated[Path, typer.Option("--candidate-klb")],
    contract: Annotated[Path, typer.Option("--contract")],
    workload: Annotated[Path, typer.Option("--workload")],
    out: Annotated[Path, typer.Option("--out")],
) -> None:
    """Create a sidecar positive evidence witness for a KLB coordinate."""

    _guard(
        lambda: {
            "receipt_type": "witness_build_receipt",
            "status": "ok",
            "witnesses": str(
                build_klb_witness(
                    coordinate=coordinate,
                    candidate_snapshot_path=candidate_snapshot,
                    candidate_klb_path=candidate_klb,
                    contract_path=contract,
                    workload_path=workload,
                    output=out,
                )
            ),
        },
        None,
    )


@demo_app.command("quickstart")
def demo_quickstart(
    out: Annotated[Path, typer.Option("--out")] = Path("examples/quickstart"),
) -> None:
    """Generate a complete local quickstart example."""

    _guard(lambda: _paths_receipt("quickstart_receipt", write_quickstart(out)), None)


@schema_app.command("export")
def schema_export(out: Annotated[Path, typer.Option("--out")] = Path("schemas")) -> None:
    """Export JSON Schemas."""

    _guard(
        lambda: {
            "receipt_type": "schema_export_receipt",
            "status": "ok",
            "schemas": [str(path) for path in export_schemas(out)],
        },
        None,
    )


@schema_app.command("policy")
def schema_policy(out: Annotated[Path, typer.Option("--out")] = Path("policy_profile.json")) -> None:
    """Export the built-in v1.0 policy profile."""

    _guard(
        lambda: {
            "receipt_type": "policy_export_receipt",
            "status": "ok",
            "policy": str(_write_policy(out)),
        },
        None,
    )


@ledger_app.command("verify")
def ledger_verify(
    path: Annotated[Path, typer.Argument()],
    out: Annotated[Path | None, typer.Option("--out")] = None,
) -> None:
    """Verify an OASG JSONL ledger."""

    _guard(lambda: verify_jsonl(path).to_dict(), out)


@ledger_app.command("append")
def ledger_append_command(
    ledger: Annotated[Path, typer.Option("--ledger")],
    records: Annotated[Path, typer.Option("--records")],
    out: Annotated[Path, typer.Option("--out")],
    expected_prefix: Annotated[str | None, typer.Option("--expected-prefix")] = None,
) -> None:
    """Append records to an OASG JSONL ledger with prefix verification."""

    _guard(
        lambda: append_jsonl(
            ledger,
            records,
            out,
            expected_prefix_hash=expected_prefix,
        ).to_dict(),
        None,
    )


@app.command("reduce")
def reduce_command(
    ledger: Annotated[Path, typer.Argument()],
    out: Annotated[Path | None, typer.Option("--out")] = None,
) -> None:
    """Reduce a JSONL ledger into a deterministic snapshot."""

    _guard(lambda: reduce_ledger(ledger).to_dict(), out)


@app.command("klb")
def klb_command(
    snapshot: Annotated[Path, typer.Argument()],
    policy: Annotated[Path | None, typer.Option("--policy")] = None,
    out: Annotated[Path | None, typer.Option("--out")] = None,
) -> None:
    """Compute a bounded KLB_2 receipt from a reducer snapshot."""

    _guard(
        lambda: calculate_klb(
            ReducerSnapshot.from_dict(read_json(snapshot)),
            load_policy(policy),
        ).to_dict(),
        out,
    )


@app.command("pressure")
def pressure_command(
    ledger: Annotated[Path, typer.Argument()],
    policy: Annotated[Path | None, typer.Option("--policy")] = None,
    out: Annotated[Path | None, typer.Option("--out")] = None,
) -> None:
    """Compute a typed pressure vector from an observable ledger."""

    def _pressure() -> dict[str, object]:
        snapshot = reduce_ledger(ledger)
        return compute_pressure(snapshot, calculate_klb(snapshot, load_policy(policy))).to_dict()

    _guard(_pressure, out)


@app.command("scheduler")
def scheduler_command(
    ledger: Annotated[Path, typer.Argument()],
    policy: Annotated[Path | None, typer.Option("--policy")] = None,
    max_selected: Annotated[int, typer.Option("--max-selected")] = 4,
    out: Annotated[Path | None, typer.Option("--out")] = None,
) -> None:
    """Schedule mutation targets from a typed pressure vector."""

    def _schedule() -> dict[str, object]:
        snapshot = reduce_ledger(ledger)
        pressure = compute_pressure(snapshot, calculate_klb(snapshot, load_policy(policy)))
        return schedule_pressure(pressure, max_selected=max_selected).to_dict()

    _guard(_schedule, out)


@app.command("gate")
def gate_command(
    baseline: Annotated[Path, typer.Option("--baseline")],
    candidate: Annotated[Path, typer.Option("--candidate")],
    contract: Annotated[Path, typer.Option("--contract")],
    workload: Annotated[Path, typer.Option("--workload")],
    witnesses: Annotated[Path | None, typer.Option("--witnesses")] = None,
    policy: Annotated[Path | None, typer.Option("--policy")] = None,
    out: Annotated[Path | None, typer.Option("--out")] = None,
) -> None:
    """Evaluate the no-meta dominance gate."""

    _guard(lambda: _gate_receipt(baseline, candidate, contract, workload, witnesses, policy), out)


@optimize_app.command("plan")
def optimize_plan_command(
    history: Annotated[Path, typer.Option("--history")],
    out_dir: Annotated[Path, typer.Option("--out-dir")],
    library: Annotated[Path | None, typer.Option("--library")] = None,
    policy: Annotated[Path | None, typer.Option("--policy")] = None,
    previous_scheduler: Annotated[Path | None, typer.Option("--previous-scheduler")] = None,
    mutator_profile: Annotated[Path | None, typer.Option("--mutator-profile")] = None,
    max_candidates: Annotated[int, typer.Option("--max-candidates")] = 4,
) -> None:
    """Plan a deterministic optimizer pass without promotion."""

    _guard(
        lambda: _paths_receipt(
            "optimizer_plan_receipt",
            plan_optimizer(
                history=history,
                out_dir=out_dir,
                library_path=library,
                policy=load_policy(policy) if policy is not None else None,
                previous_scheduler=_read_scheduler(previous_scheduler),
                mutator_profile=load_mutator_profile(mutator_profile),
                max_candidates=max_candidates,
            ),
        ),
        None,
    )


@optimize_app.command("run")
def optimize_run_command(
    history: Annotated[Path, typer.Option("--history")],
    library: Annotated[Path, typer.Option("--library")],
    out_dir: Annotated[Path, typer.Option("--out-dir")],
    policy: Annotated[Path | None, typer.Option("--policy")] = None,
    previous_scheduler: Annotated[Path | None, typer.Option("--previous-scheduler")] = None,
    save_scheduler: Annotated[Path | None, typer.Option("--save-scheduler")] = None,
    mutator_profile: Annotated[Path | None, typer.Option("--mutator-profile")] = None,
    max_candidates: Annotated[int, typer.Option("--max-candidates")] = 4,
    cycles: Annotated[int, typer.Option("--cycles")] = 1,
    runner: Annotated[str, typer.Option("--runner")] = "ledger-replay",
    runner_arg: Annotated[list[str] | None, typer.Option("--runner-arg")] = None,
    max_events: Annotated[int, typer.Option("--max-events")] = 1,
) -> None:
    """Run one conservative local OASG optimization cycle."""

    def _run() -> dict[str, object]:
        result = run_optimizer(
            history=history,
            library_path=library,
            out_dir=out_dir,
            policy=load_policy(policy) if policy is not None else None,
            max_candidates=max_candidates,
            max_events=max_events,
            cycles=cycles,
            runner_type=runner,
            runner_command=tuple(runner_arg or ()) if runner_arg else None,
            previous_scheduler=_read_scheduler(previous_scheduler),
            mutator_profile=load_mutator_profile(mutator_profile),
        )
        if save_scheduler is not None and result.library.scheduler_state is not None:
            write_json(save_scheduler, result.library.scheduler_state.to_dict())
        return {
            "receipt_type": "optimizer_cli_receipt",
            "status": str(result.receipt["status"]),
            "paths": {name: str(path) for name, path in result.paths.items()},
            "optimizer_run_receipt": result.receipt,
        }

    _guard(_run, None)


@optimize_app.command("watch")
def optimize_watch_command(
    history: Annotated[Path, typer.Option("--history")],
    library: Annotated[Path, typer.Option("--library")],
    state: Annotated[Path, typer.Option("--state")],
    out_dir: Annotated[Path, typer.Option("--out-dir")],
    policy: Annotated[Path | None, typer.Option("--policy")] = None,
    mutator_profile: Annotated[Path | None, typer.Option("--mutator-profile")] = None,
    max_candidates: Annotated[int, typer.Option("--max-candidates")] = 4,
    max_iterations: Annotated[int, typer.Option("--max-iterations")] = 1,
    interval_seconds: Annotated[float, typer.Option("--interval-seconds")] = 0.0,
    runner: Annotated[str, typer.Option("--runner")] = "ledger-replay",
    runner_arg: Annotated[list[str] | None, typer.Option("--runner-arg")] = None,
    max_events: Annotated[int, typer.Option("--max-events")] = 1,
    append_lease_observations: Annotated[
        bool,
        typer.Option("--append-lease-observations"),
    ] = False,
) -> None:
    """Run a resumable local optimizer loop over an append-only history ledger."""

    _guard(
        lambda: watch_optimizer(
            history=history,
            library_path=library,
            state_path=state,
            out_dir=out_dir,
            policy=load_policy(policy) if policy is not None else None,
            mutator_profile=load_mutator_profile(mutator_profile),
            max_candidates=max_candidates,
            max_events=max_events,
            max_iterations=max_iterations,
            interval_seconds=interval_seconds,
            runner_type=runner,
            runner_command=tuple(runner_arg or ()) if runner_arg else None,
            append_lease_observations=append_lease_observations,
        ),
        None,
    )


@optimize_app.command("supervise")
def optimize_supervise_command(
    history: Annotated[Path, typer.Option("--history")],
    library: Annotated[Path, typer.Option("--library")],
    state: Annotated[Path, typer.Option("--state")],
    out_dir: Annotated[Path, typer.Option("--out-dir")],
    policy: Annotated[Path | None, typer.Option("--policy")] = None,
    mutator_profile: Annotated[Path | None, typer.Option("--mutator-profile")] = None,
    max_candidates: Annotated[int, typer.Option("--max-candidates")] = 4,
    max_iterations: Annotated[int, typer.Option("--max-iterations")] = 1,
    interval_seconds: Annotated[float, typer.Option("--interval-seconds")] = 0.0,
    runner: Annotated[str, typer.Option("--runner")] = "ledger-replay",
    runner_arg: Annotated[list[str] | None, typer.Option("--runner-arg")] = None,
    max_events: Annotated[int, typer.Option("--max-events")] = 1,
    append_lease_observations: Annotated[
        bool,
        typer.Option("--append-lease-observations"),
    ] = False,
    require_active_by_epoch: Annotated[int | None, typer.Option("--require-active-by-epoch")] = None,
) -> None:
    """Run the durable supervisor state machine for long-running optimization."""

    _guard(
        lambda: supervise_optimizer(
            history=history,
            library_path=library,
            state_path=state,
            out_dir=out_dir,
            policy=load_policy(policy) if policy is not None else None,
            mutator_profile=load_mutator_profile(mutator_profile),
            max_candidates=max_candidates,
            max_events=max_events,
            max_iterations=max_iterations,
            interval_seconds=interval_seconds,
            runner_type=runner,
            runner_command=tuple(runner_arg or ()) if runner_arg else None,
            append_lease_observations=append_lease_observations,
            require_active_by_epoch=require_active_by_epoch,
        ),
        None,
    )


@experiment_app.command("verify-longrun")
def experiment_verify_longrun_command(
    run_dir: Annotated[Path, typer.Option("--run-dir")],
    out: Annotated[Path | None, typer.Option("--out")] = None,
) -> None:
    """Verify longrun ledgers and adaptive-readiness status."""

    _guard(lambda: verify_longrun_run(run_dir), out)


@experiment_app.command("diagnose-promotion")
def experiment_diagnose_promotion_command(
    run_dir: Annotated[Path, typer.Option("--run-dir")],
    out: Annotated[Path | None, typer.Option("--out")] = None,
) -> None:
    """Summarize promotion failures and first rejected candidate receipts."""

    _guard(lambda: diagnose_promotion(run_dir), out)


@mutate_app.command("profile-init")
def mutator_profile_init_command(
    out: Annotated[Path, typer.Option("--out")],
) -> None:
    """Write the default local mutator profile."""

    _guard(
        lambda: {
            "receipt_type": "mutator_profile_init_receipt",
            "status": "ok",
            "profile": str(_write_mutator_profile(out)),
        },
        None,
    )


@mutator_profile_app.command("init")
def mutator_profile_init_alias(
    out: Annotated[Path, typer.Option("--out")],
) -> None:
    """Write the default local mutator profile."""

    mutator_profile_init_command(out)


@optimize_app.command("state")
def optimize_state_command(
    state: Annotated[Path, typer.Option("--state")],
    out: Annotated[Path | None, typer.Option("--out")] = None,
) -> None:
    """Show durable optimizer checkpoint state."""

    _guard(lambda: load_optimizer_state(state).to_dict(), out)


@mutate_app.command("plan")
def mutate_plan_command(
    out_dir: Annotated[Path, typer.Option("--out-dir")],
    mutation_id: Annotated[str, typer.Option("--mutation-id")] = "mut_001",
    coordinate: Annotated[str, typer.Option("--coordinate")] = "KLB_2.pure_read",
    action_id: Annotated[str, typer.Option("--action-id")] = "pure_read",
    to_grade: Annotated[str, typer.Option("--to-grade")] = "surplus",
    policy: Annotated[Path | None, typer.Option("--policy")] = None,
) -> None:
    """Create a bounded local workflow-policy mutation candidate."""

    _guard(
        lambda: _paths_receipt(
            "mutation_plan_receipt",
            write_mutation_candidate(
                out_dir,
                mutation_id=mutation_id,
                coordinate=coordinate,
                action_id=action_id,
                to_grade=to_grade,
                policy=load_policy(policy),
            ),
        ),
        None,
    )


@app.command("shadow")
def shadow_command(
    mutation: Annotated[Path, typer.Option("--mutation")],
    candidate: Annotated[Path, typer.Option("--candidate")],
    out: Annotated[Path, typer.Option("--out")],
    workload: Annotated[Path | None, typer.Option("--workload")] = None,
    runner: Annotated[str, typer.Option("--runner")] = "ledger-replay",
    runner_arg: Annotated[list[str] | None, typer.Option("--runner-arg")] = None,
) -> None:
    """Produce a conservative local shadow receipt."""

    _guard(
        lambda: {
            "receipt_type": "shadow_run_receipt",
            "status": "ok",
            "shadow": str(
                write_shadow_receipt(
                    mutation,
                    candidate,
                    out,
                    workload,
                    runner_type=runner,
                    runner_command=tuple(runner_arg or ()) if runner_arg else None,
                )
            ),
        },
        None,
    )


@app.command("lease")
def lease_command(
    mutation: Annotated[Path, typer.Option("--mutation")],
    candidate: Annotated[Path, typer.Option("--candidate")],
    out: Annotated[Path, typer.Option("--out")],
    max_events: Annotated[int, typer.Option("--max-events")] = 1,
    workload: Annotated[Path | None, typer.Option("--workload")] = None,
    runner: Annotated[str, typer.Option("--runner")] = "ledger-replay",
    runner_arg: Annotated[list[str] | None, typer.Option("--runner-arg")] = None,
) -> None:
    """Produce a bounded local lease receipt."""

    _guard(
        lambda: {
            "receipt_type": "lease_run_receipt",
            "status": "ok",
            "lease": str(
                write_lease_receipt(
                    mutation,
                    candidate,
                    out,
                    max_events,
                    workload,
                    runner_type=runner,
                    runner_command=tuple(runner_arg or ()) if runner_arg else None,
                )
            ),
        },
        None,
    )


@library_app.command("status")
def library_status_command(
    library: Annotated[Path, typer.Option("--library")],
    out: Annotated[Path | None, typer.Option("--out")] = None,
) -> None:
    """Show workflow library state."""

    _guard(lambda: load_library(library).to_dict(), out)


@library_app.command("history")
def library_history_command(
    library: Annotated[Path, typer.Option("--library")],
    out: Annotated[Path | None, typer.Option("--out")] = None,
) -> None:
    """Show concise workflow library history counts."""

    def _history() -> dict[str, object]:
        state = load_library(library)
        return {
            "receipt_type": "library_history_receipt",
            "status": "ok",
            "library_hash": receipt_hash(state.to_dict()),
            "active_mutation_count": len(state.active_mutations),
            "retired_mutation_count": len(state.retired),
            "quarantined_mutation_count": len(state.quarantined),
            "outcome_count": len(state.mutation_outcomes),
        }

    _guard(_history, out)


@library_app.command("rollback")
def library_rollback_command(
    library: Annotated[Path, typer.Option("--library")],
    out: Annotated[Path | None, typer.Option("--out")] = None,
) -> None:
    """Retire the newest active mutation in a workflow library."""

    def _rollback() -> dict[str, object]:
        current = load_library(library)
        updated = rollback_library(current)
        write_library(library, updated)
        return {
            "receipt_type": "rollback_receipt",
            "status": "rolled_back" if len(updated.retired) > len(current.retired) else "rollback_noop",
            "library_hash": receipt_hash(updated.to_dict()),
            "retired_mutation_id": str(updated.retired[-1].get("mutation_id"))
            if len(updated.retired) > len(current.retired)
            else None,
        }

    _guard(_rollback, out)


@library_app.command("quarantine")
def library_quarantine_command(
    library: Annotated[Path, typer.Option("--library")],
    mutation_id: Annotated[str, typer.Option("--mutation-id")],
    reason: Annotated[str, typer.Option("--reason")] = "manual_quarantine",
    out: Annotated[Path | None, typer.Option("--out")] = None,
) -> None:
    """Append a quarantine entry to a workflow library."""

    def _quarantine() -> dict[str, object]:
        updated = quarantine_library_entry(
            load_library(library),
            mutation_id=mutation_id,
            reason=reason,
        )
        write_library(library, updated)
        return {
            "record_type": "quarantine_record",
            "status": "quarantined",
            "reason": f"{mutation_id}:{reason}",
            "affected_scope": mutation_id,
        }

    _guard(_quarantine, out)


@workload_app.command("manifest")
def workload_manifest_command(
    baseline: Annotated[Path, typer.Option("--baseline")],
    candidate: Annotated[Path, typer.Option("--candidate")],
    out_dir: Annotated[Path, typer.Option("--out-dir")],
    policy: Annotated[Path | None, typer.Option("--policy")] = None,
) -> None:
    """Create a paired deterministic workload manifest."""

    _guard(
        lambda: _paths_receipt(
            "workload_manifest_build_receipt",
            write_comparison_bundle(
                out_dir,
                baseline=baseline,
                candidate=candidate,
                policy=load_policy(policy),
            ),
        ),
        None,
    )


@workload_app.command("run")
def workload_run_command(
    mutation: Annotated[Path, typer.Option("--mutation")],
    candidate: Annotated[Path, typer.Option("--candidate")],
    workload: Annotated[Path, typer.Option("--workload")],
    out_dir: Annotated[Path, typer.Option("--out-dir")],
    runner: Annotated[str, typer.Option("--runner")] = "ledger-replay",
    runner_arg: Annotated[list[str] | None, typer.Option("--runner-arg")] = None,
    max_events: Annotated[int, typer.Option("--max-events")] = 1,
    trial_ledger_out: Annotated[Path | None, typer.Option("--trial-ledger-out")] = None,
) -> None:
    """Run shadow and lease workload receipts through an explicit local runner."""

    def _run() -> dict[str, object]:
        command = tuple(runner_arg or ()) if runner_arg else None
        paths = write_trial_bundle(
            mutation,
            candidate,
            out_dir,
            workload,
            runner_type=runner,
            runner_command=command,
            max_events=max_events,
            trial_ledger_out=trial_ledger_out,
        )
        return {
            "receipt_type": "workload_run_receipt",
            "status": "ok",
            "paths": {name: str(path) for name, path in paths.items()},
        }

    _guard(_run, None)


@trial_app.command("run")
def trial_run_command(
    phase: Annotated[str, typer.Option("--phase")] = "shadow",
    mutation: Annotated[Path, typer.Option("--mutation")] = Path("mutation_record.json"),
    candidate: Annotated[Path, typer.Option("--candidate")] = Path("candidate.jsonl"),
    workload: Annotated[Path | None, typer.Option("--workload")] = None,
    out_dir: Annotated[Path, typer.Option("--out-dir")] = Path(".oasg/trial"),
    runner: Annotated[str, typer.Option("--runner")] = "ledger-replay",
    runner_arg: Annotated[list[str] | None, typer.Option("--runner-arg")] = None,
    max_events: Annotated[int, typer.Option("--max-events")] = 1,
    trial_ledger_out: Annotated[Path | None, typer.Option("--trial-ledger-out")] = None,
) -> None:
    """Execute or verify one trial bundle and return the requested phase receipt."""

    def _run() -> dict[str, object]:
        if phase not in {"shadow", "lease"}:
            raise ValueError("--phase must be shadow or lease")
        paths = write_trial_bundle(
            mutation,
            candidate,
            out_dir,
            workload,
            runner_type=runner,
            runner_command=tuple(runner_arg or ()) if runner_arg else None,
            max_events=max_events,
            trial_ledger_out=trial_ledger_out,
        )
        return {
            "receipt_type": "trial_run_receipt",
            "status": "ok",
            "phase": phase,
            "phase_receipt": str(paths[phase]),
            "paths": {name: str(path) for name, path in paths.items()},
        }

    _guard(_run, None)


@harness_app.command("init")
def harness_init_command(
    out: Annotated[Path, typer.Option("--out")] = Path("oasg_harness.py"),
) -> None:
    """Scaffold a local command workflow harness template."""

    _guard(
        lambda: {
            "receipt_type": "harness_init_receipt",
            "status": "ok",
            "harness": str(write_harness_template(out)),
        },
        None,
    )


@library_app.command("promote")
def library_promote_command(
    safe_gate: Annotated[Path, typer.Option("--gate")],
    shadow: Annotated[Path, typer.Option("--shadow")],
    lease: Annotated[Path, typer.Option("--lease")],
    mutation: Annotated[Path, typer.Option("--mutation")],
    out: Annotated[Path, typer.Option("--out")],
) -> None:
    """Convert a safe promotion into active promotion only with shadow and lease receipts."""

    _guard(
        lambda: read_json(
            write_active_promotion(
                safe_gate_receipt=read_json(safe_gate),
                shadow_path=shadow,
                lease_path=lease,
                mutation_path=mutation,
                output=out,
            )
        ),
        None,
    )


@conformance_app.command("run")
def conformance_run(path: Annotated[Path, typer.Argument()] = Path("examples/conformance")) -> None:
    """Run bundled conformance checks."""

    results = run_conformance(path)
    passed = all(result.passed for result in results)
    _emit(
        {
            "receipt_type": "conformance_receipt",
            "status": "ok" if passed else "failed",
            "results": [result.to_dict() for result in results],
        },
        None,
    )
    raise typer.Exit(0 if passed else 1)


def _emit(value: dict[str, object], out: Path | None) -> None:
    if out is None:
        console.print_json(data=value)
    else:
        write_json(out, value)
        console.print(out)


def _read_witnesses(path: Path | None) -> list[PositiveEvidenceWitness]:
    if path is None:
        return []
    raw = read_json(path)
    items = raw if isinstance(raw, list) else [raw]
    return [PositiveEvidenceWitness.model_validate(item) for item in items]


def _guard(factory: Callable[[], dict[str, object]], out: Path | None) -> None:
    try:
        value = factory()
    except (OSError, ValueError, ValidationError, KeyError, LibraryConflictError) as exc:
        _emit(
            {
                "receipt_type": "cli_error_receipt",
                "status": "error",
                "error_type": type(exc).__name__,
                "message": str(exc),
            },
            out,
        )
        raise typer.Exit(1) from exc
    _emit(value, out)


def _parse_pairs(items: list[str] | None) -> dict[str, str]:
    output: dict[str, str] = {}
    for item in items or []:
        if "=" not in item:
            raise ValueError(f"expected key=value, got {item!r}")
        key, value = item.split("=", 1)
        output[key] = value
    return output


def _paths_receipt(receipt_type: str, paths: dict[str, Path]) -> dict[str, object]:
    return {
        "receipt_type": receipt_type,
        "status": "ok",
        "paths": {name: str(path) for name, path in paths.items()},
    }


def _write_policy(path: Path) -> Path:
    write_default_policy(path)
    return path


def _write_mutator_profile(path: Path) -> Path:
    write_json(path, MutatorProfile().to_dict())
    return path


def _read_scheduler(path: Path | None) -> SchedulerResult | None:
    if path is None:
        return None
    return SchedulerResult.from_dict(read_json(path))


def _gate_receipt(
    baseline: Path,
    candidate: Path,
    contract: Path,
    workload: Path,
    witnesses: Path | None,
    policy: Path | None,
) -> dict[str, object]:
    profile = load_policy(policy)
    baseline_snapshot = reduce_ledger(baseline)
    candidate_snapshot = reduce_ledger(candidate)
    return evaluate_gate(
        baseline_snapshot,
        candidate_snapshot,
        calculate_klb(baseline_snapshot, profile),
        calculate_klb(candidate_snapshot, profile),
        ComparisonContract.model_validate(read_json(contract)),
        WorkloadManifest.model_validate(read_json(workload)),
        _read_witnesses(witnesses),
    ).to_dict()
