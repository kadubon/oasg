"""Runner protocols for shadow and lease execution receipts."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from oasg.canonical import domain_hash
from oasg.canonical import receipt_hash
from oasg.events import event_record, observation_payload
from oasg.io import read_jsonl, write_jsonl
from oasg.ledger import seal_records, verify_records
from oasg.lifecycle import LeaseResult, ShadowResult
from oasg.models import WorkloadManifest
from oasg.policy import PolicyProfile, default_policy
from oasg.policy_effects import simulate_policy_trial_records
from oasg.reducers.core import ReducerSnapshot
from oasg.reducers.core import reduce_records


@dataclass(frozen=True)
class TrialResult:
    status: str
    runner_type: str
    workload_id: str
    mutation_id: str
    trial_ledger_path: Path
    trial_snapshot: ReducerSnapshot
    trial_ledger_prefix_hash: str
    trial_reducer_snapshot_hash: str
    effect_counts: dict[str, int]
    resources: dict[str, int]
    stdout_hash: str | None = None
    stderr_hash: str | None = None
    return_code: int | None = None
    timeout_status: str = "not_timed_out"

    def to_execution_receipt(self) -> dict[str, object]:
        return {
            "receipt_type": "workload_execution_receipt",
            "status": "workload_executed" if self.status == "trial_observed" else "workload_rejected",
            "runner_type": self.runner_type,
            "workload_id": self.workload_id,
            "mutation_id": self.mutation_id,
            "ledger_prefix_hash": self.trial_ledger_prefix_hash,
            "trial_ledger_path": str(self.trial_ledger_path),
            "trial_ledger_prefix_hash": self.trial_ledger_prefix_hash,
            "trial_reducer_snapshot_hash": self.trial_reducer_snapshot_hash,
            "executed_event_count": self.trial_snapshot.records_seen
            if self.status == "trial_observed"
            else 0,
            "effect_counts": self.effect_counts,
            "resources": self.resources,
            "rollback_available": self.effect_counts.get("external", 0) == 0,
            "observed_coordinates": {
                coordinate: "acceptable"
                for coordinate in self.trial_snapshot.positive_evidence
            },
            "stdout_hash": self.stdout_hash,
            "stderr_hash": self.stderr_hash,
            "return_code": self.return_code,
            "timeout_status": self.timeout_status,
        }

    def to_trial_receipt(self) -> dict[str, object]:
        return {
            "receipt_type": "trial_ledger_receipt",
            "status": self.status,
            "runner_type": self.runner_type,
            "workload_id": self.workload_id,
            "mutation_id": self.mutation_id,
            "trial_ledger_path": str(self.trial_ledger_path),
            "trial_ledger_prefix_hash": self.trial_ledger_prefix_hash,
            "trial_reducer_snapshot_hash": self.trial_reducer_snapshot_hash,
            "effect_counts": self.effect_counts,
            "resources": self.resources,
            "stdout_hash": self.stdout_hash,
            "stderr_hash": self.stderr_hash,
            "return_code": self.return_code,
            "timeout_status": self.timeout_status,
        }


class ShadowRunner(Protocol):
    runner_type: str

    def run_shadow(
        self,
        *,
        mutation: dict[str, object],
        candidate: ReducerSnapshot,
        workload: WorkloadManifest,
    ) -> ShadowResult:
        """Execute or replay a shadow workload and return a shadow receipt."""


class LeaseRunner(Protocol):
    runner_type: str

    def run_lease(
        self,
        *,
        mutation: dict[str, object],
        candidate: ReducerSnapshot,
        workload: WorkloadManifest,
        max_events: int,
    ) -> LeaseResult:
        """Execute or replay a bounded lease workload and return a lease receipt."""


class WorkloadRunner(ShadowRunner, LeaseRunner, Protocol):
    """Runner that can back both shadow and lease receipts with workload execution."""

    def run_trial(
        self,
        *,
        mutation: dict[str, object],
        candidate_seed: ReducerSnapshot,
        workload: WorkloadManifest,
        trial_ledger_path: Path,
        policy: PolicyProfile | None = None,
    ) -> TrialResult:
        """Execute a candidate workflow and emit an observed trial ledger."""


class LedgerReplayRunner:
    """Verify an existing local trial ledger and reduce it.

    Production replay is intentionally only a verifier.  It does not create
    protected-coordinate evidence, because active promotion must be backed by a
    workload harness or another runner-produced trial ledger.
    """

    runner_type = "ledger-replay"

    def run_trial(
        self,
        *,
        mutation: dict[str, object],
        candidate_seed: ReducerSnapshot,
        workload: WorkloadManifest,
        trial_ledger_path: Path,
        policy: PolicyProfile | None = None,
    ) -> TrialResult:
        policy = policy or default_policy()
        if trial_ledger_path.exists():
            records = read_jsonl(trial_ledger_path)
            verification = verify_records(records)
            trial_snapshot = reduce_records(records, verification)
            status = (
                "trial_observed"
                if verification.status == "ledger_prefix_valid"
                and trial_snapshot.records_seen > 0
                and candidate_seed.ledger_status == "ledger_prefix_valid"
                and _workload_matches_candidate(candidate_seed, workload)
                else "trial_rejected"
            )
            if status != "trial_observed":
                records = _rejected_trial_records(
                    mutation=mutation,
                    candidate_seed=candidate_seed,
                    reason=verification.status,
                    runner_type=self.runner_type,
                )
                write_jsonl(trial_ledger_path, records)
                trial_snapshot = reduce_records(records)
        elif candidate_seed.ledger_status != "ledger_prefix_valid":
            records = _rejected_trial_records(
                mutation=mutation,
                candidate_seed=candidate_seed,
                reason=candidate_seed.ledger_status,
                runner_type=self.runner_type,
            )
        elif not _workload_matches_candidate(candidate_seed, workload):
            records = _rejected_trial_records(
                mutation=mutation,
                candidate_seed=candidate_seed,
                reason="workload_mismatch",
                runner_type=self.runner_type,
            )
        else:
            records = _rejected_trial_records(
                mutation=mutation,
                candidate_seed=candidate_seed,
                reason="trial_ledger_required",
                runner_type=self.runner_type,
            )
        if not trial_ledger_path.exists():
            write_jsonl(trial_ledger_path, records)
            trial_snapshot = reduce_records(records)
            status = (
                "trial_observed"
                if trial_snapshot.ledger_status == "ledger_prefix_valid"
                and trial_snapshot.records_seen > 0
                and candidate_seed.ledger_status == "ledger_prefix_valid"
                and _workload_matches_candidate(candidate_seed, workload)
                and trial_snapshot.positive_evidence
                else "trial_rejected"
            )
        return TrialResult(
            status=status,
            runner_type=self.runner_type,
            workload_id=workload.workload_id,
            mutation_id=str(mutation["mutation_id"]),
            trial_ledger_path=trial_ledger_path,
            trial_snapshot=trial_snapshot,
            trial_ledger_prefix_hash=trial_snapshot.ledger_prefix_hash,
            trial_reducer_snapshot_hash=receipt_hash(trial_snapshot.to_dict()),
            effect_counts={"workflow_promotion": 0, "external": 0},
            resources={"events": trial_snapshot.records_seen, "workload_inputs": len(workload.input_hashes)},
        )

    def run_shadow(
        self,
        *,
        mutation: dict[str, object],
        candidate: ReducerSnapshot,
        workload: WorkloadManifest,
    ) -> ShadowResult:
        execution = _execution_receipt(
            runner_type=self.runner_type,
            workload=workload,
            mutation_id=str(mutation["mutation_id"]),
            candidate=candidate,
            status="workload_executed" if _workload_matches_candidate(candidate, workload) else "workload_rejected",
        )
        raw_declared = mutation.get("declared_improvement_coordinates", [])
        declared = tuple(str(item) for item in raw_declared) if isinstance(raw_declared, list) else ()
        missing = [coordinate for coordinate in declared if not candidate.positive_evidence.get(coordinate)]
        workload_ok = _workload_matches_candidate(candidate, workload)
        status = (
            "shadow_passed"
            if declared
            and not missing
            and candidate.records_seen > 0
            and candidate.ledger_status == "ledger_prefix_valid"
            and workload_ok
            else "shadow_rejected"
        )
        return ShadowResult(
            mutation_id=str(mutation["mutation_id"]),
            status=status,
            ledger_prefix_hash=candidate.ledger_prefix_hash,
            observed_coordinates={
                coordinate: "acceptable"
                for coordinate in declared
                if coordinate not in missing
            },
            replayed_event_count=candidate.records_seen if workload_ok else 0,
            runner_type=self.runner_type,
            workload_id=workload.workload_id,
            input_hashes=tuple(workload.input_hashes),
            execution_receipt_hash=receipt_hash(execution),
        )

    def run_lease(
        self,
        *,
        mutation: dict[str, object],
        candidate: ReducerSnapshot,
        workload: WorkloadManifest,
        max_events: int,
    ) -> LeaseResult:
        execution = _execution_receipt(
            runner_type=self.runner_type,
            workload=workload,
            mutation_id=str(mutation["mutation_id"]),
            candidate=candidate,
            status="workload_executed" if _workload_matches_candidate(candidate, workload) else "workload_rejected",
        )
        caps = mutation.get("lease_caps", {})
        caps = caps if isinstance(caps, dict) else {}
        cap_events = int(caps.get("max_events", max_events))
        external_cap = int(caps.get("max_external_effects", 0))
        workload_ok = _workload_matches_candidate(candidate, workload)
        status = (
            "lease_passed"
            if max_events <= cap_events
            and candidate.records_seen <= max_events
            and external_cap == 0
            and candidate.ledger_status == "ledger_prefix_valid"
            and workload_ok
            else "lease_rejected_cap_exceeded"
        )
        return LeaseResult(
            mutation_id=str(mutation["mutation_id"]),
            status=status,
            ledger_prefix_hash=candidate.ledger_prefix_hash,
            max_events=max_events,
            effect_counts={"workflow_promotion": 1, "external": 0},
            executed_event_count=candidate.records_seen if workload_ok else 0,
            rollback_available=True,
            resources={
                "events": candidate.records_seen if workload_ok else 0,
                "workload_inputs": len(workload.input_hashes),
            },
            runner_type=self.runner_type,
            workload_id=workload.workload_id,
            input_hashes=tuple(workload.input_hashes),
            execution_receipt_hash=receipt_hash(execution),
        )


class DemoReplayRunner(LedgerReplayRunner):
    """Demo-only deterministic policy-effect runner.

    This runner is useful for quickstart and conformance smoke tests, but its
    receipts are intentionally ineligible for active production promotion.
    """

    runner_type = "demo-replay"

    def run_trial(
        self,
        *,
        mutation: dict[str, object],
        candidate_seed: ReducerSnapshot,
        workload: WorkloadManifest,
        trial_ledger_path: Path,
        policy: PolicyProfile | None = None,
    ) -> TrialResult:
        if trial_ledger_path.exists() or candidate_seed.ledger_status != "ledger_prefix_valid":
            return super().run_trial(
                mutation=mutation,
                candidate_seed=candidate_seed,
                workload=workload,
                trial_ledger_path=trial_ledger_path,
                policy=policy,
            )
        if not _workload_matches_candidate(candidate_seed, workload):
            return super().run_trial(
                mutation=mutation,
                candidate_seed=candidate_seed,
                workload=workload,
                trial_ledger_path=trial_ledger_path,
                policy=policy,
            )
        policy = policy or default_policy()
        simulation = simulate_policy_trial_records(
            mutation=mutation,
            candidate_seed=candidate_seed,
            policy=policy,
            runner_type=self.runner_type,
        )
        write_jsonl(trial_ledger_path, simulation.records)
        trial_snapshot = reduce_records(simulation.records)
        status = (
            "trial_observed"
            if simulation.status == "trial_observed"
            and trial_snapshot.ledger_status == "ledger_prefix_valid"
            and bool(trial_snapshot.positive_evidence)
            else "trial_rejected"
        )
        return TrialResult(
            status=status,
            runner_type=self.runner_type,
            workload_id=workload.workload_id,
            mutation_id=str(mutation["mutation_id"]),
            trial_ledger_path=trial_ledger_path,
            trial_snapshot=trial_snapshot,
            trial_ledger_prefix_hash=trial_snapshot.ledger_prefix_hash,
            trial_reducer_snapshot_hash=receipt_hash(trial_snapshot.to_dict()),
            effect_counts={"workflow_promotion": 0, "external": 0},
            resources={
                "events": trial_snapshot.records_seen,
                "workload_inputs": len(workload.input_hashes),
            },
        )


class ReplayRunner(LedgerReplayRunner):
    """Backward-compatible name for the production ledger replay verifier."""


class LocalCommandRunner:
    """Explicit local command runner using argv lists and no shell."""

    runner_type = "local-command"

    def __init__(
        self,
        command: tuple[str, ...],
        *,
        timeout_seconds: int = 30,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        validate_command_argv(command)
        self.command = command
        self.timeout_seconds = timeout_seconds
        self.cwd = cwd
        self.env = env

    def run_trial(
        self,
        *,
        mutation: dict[str, object],
        candidate_seed: ReducerSnapshot,
        workload: WorkloadManifest,
        trial_ledger_path: Path,
        policy: PolicyProfile | None = None,
    ) -> TrialResult:
        start = time.perf_counter()
        stdout = b""
        stderr = b""
        return_code = -1
        timeout_status = "not_timed_out"
        if trial_ledger_path.exists():
            trial_ledger_path.unlink()
        try:
            completed = subprocess.run(
                self.command,
                cwd=self.cwd,
                env=self.env,
                shell=False,
                capture_output=True,
                text=False,
                timeout=self.timeout_seconds,
                check=False,
            )
            stdout = completed.stdout
            stderr = completed.stderr
            return_code = completed.returncode
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout if isinstance(exc.stdout, bytes) else b""
            stderr = exc.stderr if isinstance(exc.stderr, bytes) else b"timeout"
            timeout_status = "timed_out"
        duration_ms = int((time.perf_counter() - start) * 1000)
        stdout_hash = domain_hash("OASG:v1.0:runner_stdout", stdout)
        stderr_hash = domain_hash("OASG:v1.0:runner_stderr", stderr)

        records: list[dict[str, object]] = []
        if return_code == 0 and timeout_status == "not_timed_out":
            try:
                records = _jsonl_bytes(stdout)
            except ValueError:
                if trial_ledger_path.exists():
                    records = read_jsonl(trial_ledger_path)
        verification = verify_records(records)
        if verification.status == "ledger_prefix_valid":
            write_jsonl(trial_ledger_path, records)
        else:
            fallback = _rejected_trial_records(
                mutation=mutation,
                candidate_seed=candidate_seed,
                reason=verification.status,
                runner_type=self.runner_type,
            )
            write_jsonl(trial_ledger_path, fallback)
            records = fallback
        trial_snapshot = reduce_records(records)
        status = (
            "trial_observed"
            if return_code == 0
            and timeout_status == "not_timed_out"
            and verification.status == "ledger_prefix_valid"
            and candidate_seed.ledger_status == "ledger_prefix_valid"
            and _workload_matches_candidate(candidate_seed, workload)
            else "trial_rejected"
        )
        return TrialResult(
            status=status,
            runner_type=self.runner_type,
            workload_id=workload.workload_id,
            mutation_id=str(mutation["mutation_id"]),
            trial_ledger_path=trial_ledger_path,
            trial_snapshot=trial_snapshot,
            trial_ledger_prefix_hash=trial_snapshot.ledger_prefix_hash,
            trial_reducer_snapshot_hash=receipt_hash(trial_snapshot.to_dict()),
            effect_counts={"workflow_promotion": 0, "external": 0},
            resources={
                "duration_ms": duration_ms,
                "stdout_bytes": len(stdout),
                "stderr_bytes": len(stderr),
                "events": trial_snapshot.records_seen,
            },
            stdout_hash=stdout_hash,
            stderr_hash=stderr_hash,
            return_code=return_code,
            timeout_status=timeout_status,
        )

    def run_shadow(
        self,
        *,
        mutation: dict[str, object],
        candidate: ReducerSnapshot,
        workload: WorkloadManifest,
    ) -> ShadowResult:
        execution = self._execute(mutation=mutation, candidate=candidate, workload=workload)
        raw_declared = mutation.get("declared_improvement_coordinates", [])
        declared = tuple(str(item) for item in raw_declared) if isinstance(raw_declared, list) else ()
        workload_ok = _workload_matches_candidate(candidate, workload)
        missing = [coordinate for coordinate in declared if not candidate.positive_evidence.get(coordinate)]
        status = (
            "shadow_passed"
            if execution["status"] == "workload_executed"
            and workload_ok
            and declared
            and not missing
            and candidate.ledger_status == "ledger_prefix_valid"
            else "shadow_rejected"
        )
        return ShadowResult(
            mutation_id=str(mutation["mutation_id"]),
            status=status,
            ledger_prefix_hash=candidate.ledger_prefix_hash,
            observed_coordinates={
                coordinate: "acceptable" for coordinate in declared if coordinate not in missing
            },
            replayed_event_count=candidate.records_seen if workload_ok else 0,
            runner_type=self.runner_type,
            workload_id=workload.workload_id,
            input_hashes=tuple(workload.input_hashes),
            execution_receipt_hash=receipt_hash(execution),
        )

    def run_lease(
        self,
        *,
        mutation: dict[str, object],
        candidate: ReducerSnapshot,
        workload: WorkloadManifest,
        max_events: int,
    ) -> LeaseResult:
        execution = self._execute(mutation=mutation, candidate=candidate, workload=workload)
        caps = mutation.get("lease_caps", {})
        caps = caps if isinstance(caps, dict) else {}
        cap_events = int(caps.get("max_events", max_events))
        external_cap = int(caps.get("max_external_effects", 0))
        workload_ok = _workload_matches_candidate(candidate, workload)
        status = (
            "lease_passed"
            if execution["status"] == "workload_executed"
            and max_events <= cap_events
            and candidate.records_seen <= max_events
            and external_cap == 0
            and candidate.ledger_status == "ledger_prefix_valid"
            and workload_ok
            else "lease_rejected_cap_exceeded"
        )
        execution_resources = execution.get("resources", {})
        resources = execution_resources if isinstance(execution_resources, dict) else {}
        return_code_raw = execution.get("return_code", -1)
        return LeaseResult(
            mutation_id=str(mutation["mutation_id"]),
            status=status,
            ledger_prefix_hash=candidate.ledger_prefix_hash,
            max_events=max_events,
            effect_counts={"workflow_promotion": 1, "external": 0},
            executed_event_count=candidate.records_seen if workload_ok else 0,
            rollback_available=True,
            resources={
                "events": candidate.records_seen if workload_ok else 0,
                "duration_ms": _int_from_object(resources.get("duration_ms", 0)),
                "return_code": _int_from_object(return_code_raw)
                if return_code_raw is not None
                else -1,
            },
            runner_type=self.runner_type,
            workload_id=workload.workload_id,
            input_hashes=tuple(workload.input_hashes),
            execution_receipt_hash=receipt_hash(execution),
        )

    def _execute(
        self,
        *,
        mutation: dict[str, object],
        candidate: ReducerSnapshot,
        workload: WorkloadManifest,
    ) -> dict[str, object]:
        start = time.perf_counter()
        try:
            completed = subprocess.run(
                self.command,
                cwd=self.cwd,
                env=self.env,
                shell=False,
                capture_output=True,
                text=False,
                timeout=self.timeout_seconds,
                check=False,
            )
            status = "workload_executed" if completed.returncode == 0 else "workload_rejected"
            stdout = completed.stdout
            stderr = completed.stderr
            return_code = completed.returncode
        except subprocess.TimeoutExpired as exc:
            status = "workload_rejected"
            stdout = exc.stdout if isinstance(exc.stdout, bytes) else b""
            stderr = exc.stderr if isinstance(exc.stderr, bytes) else b"timeout"
            return_code = -1
        duration_ms = int((time.perf_counter() - start) * 1000)
        return _execution_receipt(
            runner_type=self.runner_type,
            workload=workload,
            mutation_id=str(mutation["mutation_id"]),
            candidate=candidate,
            status=status,
            resources={"duration_ms": duration_ms, "stdout_bytes": len(stdout), "stderr_bytes": len(stderr)},
            stdout_hash=domain_hash("OASG:v1.0:runner_stdout", stdout),
            stderr_hash=domain_hash("OASG:v1.0:runner_stderr", stderr),
            return_code=return_code,
        )


def default_runner(
    runner_type: str = "ledger-replay",
    *,
    command: tuple[str, ...] | None = None,
    timeout_seconds: int = 30,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> WorkloadRunner:
    if runner_type in {"replay", "ledger-replay"}:
        return LedgerReplayRunner()
    if runner_type == "demo-replay":
        return DemoReplayRunner()
    if runner_type == "local-command":
        if command is None:
            raise ValueError("local-command runner requires explicit argv")
        return LocalCommandRunner(
            command,
            timeout_seconds=timeout_seconds,
            cwd=cwd,
            env=env,
        )
    raise ValueError(f"unsupported local runner: {runner_type!r}")


def runner_receipt_hash(seed: str, *parts: str) -> str:
    return domain_hash("OASG:v1.0:runner_receipt", seed, *parts)


def _workload_matches_candidate(candidate: ReducerSnapshot, workload: WorkloadManifest) -> bool:
    return candidate.ledger_prefix_hash in set(workload.ledger_prefix_hashes)


def _execution_receipt(
    *,
    runner_type: str,
    workload: WorkloadManifest,
    mutation_id: str,
    candidate: ReducerSnapshot,
    status: str,
    resources: dict[str, int] | None = None,
    stdout_hash: str | None = None,
    stderr_hash: str | None = None,
    return_code: int | None = None,
) -> dict[str, object]:
    return {
        "receipt_type": "workload_execution_receipt",
        "status": status,
        "runner_type": runner_type,
        "workload_id": workload.workload_id,
        "mutation_id": mutation_id,
        "ledger_prefix_hash": candidate.ledger_prefix_hash,
        "executed_event_count": candidate.records_seen
        if _workload_matches_candidate(candidate, workload)
        else 0,
        "effect_counts": {"external": 0, "workflow_promotion": 1},
        "resources": resources or {"events": candidate.records_seen},
        "rollback_available": True,
        "observed_coordinates": {},
        "stdout_hash": stdout_hash,
        "stderr_hash": stderr_hash,
        "return_code": return_code,
    }


def validate_command_argv(command: tuple[str, ...]) -> None:
    if not command:
        raise ValueError("local-command runner requires at least one argv item")
    if len(command) == 1 and any(char.isspace() for char in command[0]):
        raise ValueError("local-command runner requires argv list, not a shell command string")
    executable = Path(command[0]).name.lower()
    if executable in {"sh", "bash", "zsh", "cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
        raise ValueError("local-command runner refuses shell executables")


def _rejected_trial_records(
    *,
    mutation: dict[str, object],
    candidate_seed: ReducerSnapshot,
    reason: str,
    runner_type: str,
) -> list[dict[str, object]]:
    payload = observation_payload(
        dimensions=candidate_seed.dimensions,
        action_grades=candidate_seed.action_grades,
        protected_debt={**candidate_seed.protected_debt, "comparison": "critical"},
        policy={
            "effect_classes": ["pure"],
            "semantic_scope": "none",
            "claim_emitting": False,
            "taint_level": "public",
            "boundary_status": "valid",
            "trusted_base_status": "valid",
            "workflow_promotion_authorized": False,
        },
        model_event={"runner_type": runner_type, "rejection_reason": reason},
    )
    return seal_records(
        [
            event_record(
                event_id=f"evt_trial_rejected_{mutation.get('mutation_id', 'unknown')}",
                workflow_id="trial_workload",
                component_id="workflow_policy",
                event_type="observation",
                payload=payload,
            )
        ]
    )


def _jsonl_bytes(content: bytes) -> list[dict[str, object]]:
    import json

    if not content.strip():
        raise ValueError("local-command runner did not emit an OASG JSONL ledger")
    records: list[dict[str, object]] = []
    for line in content.splitlines():
        if not line.strip():
            continue
        item = json.loads(line.decode("utf-8"))
        if not isinstance(item, dict):
            raise ValueError("local-command runner emitted a non-object JSONL line")
        records.append(item)
    if not records:
        raise ValueError("local-command runner did not emit an OASG JSONL ledger")
    return records


def _int_from_object(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value)
    return 0
