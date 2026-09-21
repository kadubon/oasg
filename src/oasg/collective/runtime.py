"""Explicit disposable two-cycle host. Every companion owns its own transitions."""

from __future__ import annotations

import importlib
from copy import deepcopy
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from oasg.canonical import receipt_hash
from oasg.collective import ccr_bridge, memory, vek_bridge
from oasg.collective.feedback import withdraw, reconcile
from oasg.collective.check import check_trial
from oasg.collective.evidence import checker_digest
from oasg.collective.journal import Journal
from oasg.collective.trial import compare, run_worker
from oasg.collective.wire import Contract, Scope, TaskBinding, digest, encoded, loads, sha
from oasg.collective.worker import implementation_digest
from oasg.library import apply_active_promotion, load_library, write_library


def example(
    root: Path, *, fail_after: str | None = None, negative_control: bool = False
) -> dict[str, Any]:
    ed = importlib.import_module("cryptography.hazmat.primitives.asymmetric.ed25519")
    key = ed.Ed25519PrivateKey.generate()  # Host verifier only; never passed to worker processes.
    public = key.public_key().public_bytes_raw()
    inputs = ["z\ny\nx\nw\nv\nu\nt\ns"]
    artifact = digest(
        {"variant": "indexed", "implementation": implementation_digest(), "inputs": inputs}
    )
    registration = ccr_bridge.registration(
        public,
        inputs,
        study="study:finite",
        worker="finite-worker",
        context="line-context",
        artifact=artifact,
        negative_control=negative_control,
    )
    library = load_library(None)
    now = int(time.time())
    contract = Contract(
        scope=Scope(
            mission="study:finite",
            study="study:finite",
            worker="finite-worker",
            receiver="A",
            context="line-context",
            namespace="disposable-software",
        ),
        training=["z\na", "c\nb\nc"],
        confirmation=inputs,
        evidence_class="executed_finite_software",
        negative_control="second-use-output-loss" if negative_control else "none",
        registered_at=now,
        cutoff=now + 2,
        expires_at=ccr_bridge.utc_seconds(registration["base"]["deadline"]),
        max_work=100,
        efficient_work=12,
        overhead=2,
        verification_budget=4,
        cleanup_budget=1,
        pool="pool:study:finite",
        ccr_registration=digest(registration),
        ccr_revision=0,
        library_digest=receipt_hash(library.policy_state.to_dict()),
        implementation=implementation_digest(),
        checker=checker_digest(),
        verifier_key=sha(public),
        execute=True,
        native_versions="ccr-1.9.0/oawm-0.2.0b0/vek-1.3.0",
    )
    return execute_registered(
        root, contract, registration, key=key, withdraw_after=True, fail_after=fail_after
    )


def execute_registered(
    root: Path,
    contract: Contract,
    registration: dict[str, Any],
    *,
    key: Any,
    withdraw_after: bool = False,
    fail_after: str | None = None,
) -> dict[str, Any]:
    """Execute a host-authorized finite study and later task in an empty disposable root.

    Inputs and thresholds are supplied by the host before either arm executes. The
    caller retains the private verifier key for later scoped withdrawal. No key is
    persisted or sent to a worker. An interrupted run is inspected, never retried
    implicitly; unresolved owning-system effects require reconciliation.
    """
    contract = Contract.model_validate(loads(encoded(contract)))
    registration = deepcopy(
        registration
    )  # Native CCR config retains its own float-bearing wire domain.
    public = key.public_key().public_bytes_raw()
    ccr_bridge.check_registration(contract, registration, public, now=int(time.time()))
    capacity = vek_bridge.capacity(contract)
    if not capacity["feasible"]:
        raise ValueError("registered VEK verification work cannot fit")
    if root.exists() and any(root.iterdir()):
        raise ValueError(
            "explicit empty disposable output root required; inspect/reconcile existing work"
        )
    library = load_library(None)
    if contract.library_digest != receipt_hash(library.policy_state.to_dict()):
        raise ValueError(
            "unsupported initial policy; explicit default-policy disposable host required"
        )
    root.mkdir(parents=True, exist_ok=True)
    inputs = contract.confirmation
    artifact = next(iter(registration["growth"]["assets"]))
    journal = Journal(root)
    if int(time.time()) > contract.cutoff:
        raise ValueError("registration cutoff passed during validation")
    journal.append(
        "register",
        "registration",
        {
            "contract": contract.model_dump(),
            "public_key": public.hex(),
            "ccr_config_original": encoded(registration).decode(),
        },
        expected="0" * 64,
    )

    def perform(
        identity: str, action: Callable[[], Any], detail: dict[str, Any] | None = None
    ) -> Any:
        revision = journal.require_ready(contract, now=int(time.time()))["revision"]
        journal.append("intent", identity, detail or {}, expected=revision)
        if fail_after == identity + ":intent":
            raise RuntimeError("injected crash after durable intent for " + identity)
        result = action()
        if fail_after == identity:
            raise RuntimeError("injected crash after " + identity)
        journal.append(
            "ack",
            identity + ":ack",
            {
                "intent": identity,
                "original_result": encoded(result).decode(),
                "result_sha256": sha(encoded(result)),
            },
            expected=journal.inspect()["revision"],
        )
        return result

    store = ccr_bridge.open_store(root / "ccr")
    engine = ccr_bridge.ccr()
    initialized = perform(
        "ccr-registration",
        lambda: engine.initialize(store, mission=contract.scope.mission, config=registration),
    )
    run_id = initialized["run_id"]
    task = perform(
        "trial-task-lease",
        lambda: ccr_bridge.next_task(store, run_id, contract.scope.worker, fail_after=fail_after),
    )
    while int(time.time()) <= contract.cutoff:
        time.sleep(0.02)
    sources = []
    for arm in ("baseline", "candidate"):
        variant = "scan" if arm == "baseline" else contract.candidate
        binding = TaskBinding(
            run=run_id,
            task=task["task"]["task_id"],
            trial=task["trial_id"],
            attempt=task["trial_id"] + ":" + arm,
            worker=contract.scope.worker,
            receiver="A",
            arm=arm,
            fencing_token=task["fencing_token"],
            revision=engine.load(store, run_id)["revision"],
            reservation=task["trial_id"],
            input_digest=digest(inputs),
            policy_digest=digest({"variant": variant}),
            lease_start=int(time.time()),
            lease_end=ccr_bridge.utc_seconds(task["lease_expires_at"]),
        )

        def execute() -> Any:
            ccr_bridge.current_task(
                store,
                run_id,
                task["trial_id"],
                contract.scope.worker,
                task["fencing_token"],
                expected_config=registration,
            )
            source = run_worker(
                contract, binding, split="confirmation", key=key, now=int(time.time())
            )
            (root / (arm + ".json")).write_bytes(encoded(source))
            return source.model_dump()

        raw = perform("execute-" + arm, execute)
        from oasg.collective.wire import Source

        sources.append(Source.model_validate(raw))
    trial = compare(contract, sources[0], sources[1], public)
    check_trial(contract, trial, public)
    verification = [vek_bridge.verification(contract, source, public) for source in sources]
    (root / "trial.json").write_bytes(encoded(trial))
    admitted = perform(
        "trial-result",
        lambda: ccr_bridge.admit_result(
            store,
            run_id,
            task,
            key=key,
            source_digest=digest(trial),
            artifact=artifact,
            work=sum(s.execution().work for s in sources),
            accepted=trial["active"]["status"] == "active_promoted",
        ),
    )
    if admitted["admission"]["blockers"] or trial["active"]["status"] != "active_promoted":
        raise ValueError("trial not eligible for local activation")

    def promote() -> Any:
        active = apply_active_promotion(
            library, mutation=trial["mutation"], active_receipt=trial["active"]
        )
        write_library(root / "library.json", active)
        return {
            "library": receipt_hash(active.to_dict()),
            "policy": receipt_hash(active.policy_state.to_dict()),
        }

    promotion = perform("local-promotion", promote)
    qualification_task = perform(
        "qualification-task-lease",
        lambda: ccr_bridge.next_task(store, run_id, contract.scope.worker),
    )

    def form_memory() -> Any:
        result = memory.admit(root / "memory", contract, trial, public)
        (root / "memory.json").write_bytes(encoded(result))
        return result

    mem = perform("memory-admission", form_memory)
    memory_work = sum(int(c["amount"]) for c in mem["costs"])
    qualification_result = perform(
        "qualification-result",
        lambda: ccr_bridge.admit_result(
            store,
            run_id,
            qualification_task,
            key=key,
            source_digest=digest(mem),
            artifact=artifact,
            work=memory_work,
            accepted=True,
        ),
    )
    if qualification_result["admission"]["blockers"]:
        raise ValueError("receiver checks not admitted by CCR")
    use_task = perform(
        "use-task-lease", lambda: ccr_bridge.next_task(store, run_id, contract.scope.worker)
    )
    detail = {
        "trial": digest(trial),
        "memory": digest(mem),
        "library": promotion["library"],
        "run": run_id,
        "ccr_trial": use_task["trial_id"],
        "token": use_task["fencing_token"],
    }

    def later(operation: str = "cycle-two-use") -> Any:
        child = subprocess.run(
            [sys.executable, "-m", "oasg.collective.use", str(root.resolve()), operation],
            capture_output=True,
            timeout=30,
            check=True,
            shell=False,
        )
        return loads(child.stdout)

    used = perform("cycle-two-use", later, detail)
    use_verification = vek_bridge.verification_use(contract, used)
    if used["process_id"] == os.getpid():
        raise ValueError("fresh-process retrieval required")
    use_result = perform(
        "use-result",
        lambda: ccr_bridge.admit_result(
            store,
            run_id,
            use_task,
            key=key,
            source_digest=digest(used),
            artifact=artifact,
            work=used["applied"]["measurement"]["probes"],
            accepted=True,
        ),
    )
    if use_result["admission"]["blockers"]:
        raise ValueError("executed receiver use not admitted")
    negative = None
    if contract.negative_control == "second-use-output-loss":
        negative_task = perform(
            "negative-task-lease",
            lambda: ccr_bridge.next_task(store, run_id, contract.scope.worker),
        )
        negative_detail = {
            **detail,
            "ccr_trial": negative_task["trial_id"],
            "token": negative_task["fencing_token"],
        }
        negative = perform("negative-use", lambda: later("negative-use"), negative_detail)
        negative_verification = vek_bridge.verification_use(contract, negative)
        (root / "negative-verification.json").write_bytes(encoded(negative_verification))
        if negative["outcome"]["service"] or negative["eligible_after_check"]:
            raise ValueError("actual fault incorrectly credited or left eligible")
        perform(
            "negative-result",
            lambda: ccr_bridge.admit_result(
                store,
                run_id,
                negative_task,
                key=key,
                source_digest=digest(negative),
                artifact=artifact,
                work=negative["applied"]["measurement"]["probes"],
                accepted=False,
            ),
        )
    withdrawal = (
        withdraw(
            root,
            key=key,
            reason="Host withdrew this finite test dependency after scoped use",
            fail_after=fail_after,
        )
        if withdraw_after
        else None
    )
    accounting = reconcile(root)
    report = {
        "ok": True,
        "contract": contract.model_dump(),
        "gate": trial["gate"]["status"],
        "active": trial["active"]["status"],
        "work": trial["work"],
        "capacity": capacity,
        "verification": verification,
        "use_verification": use_verification,
        "memory": mem,
        "second_cycle": used,
        "negative_control": negative,
        "ccr_original": encoded(engine.report(store, run_id)).decode(),
        "withdrawal": withdrawal,
        "accounting": accounting,
        "journal": journal.inspect()["revision"],
        "evidence_class": "executed_finite_software",
        "operationally_observed": False,
    }
    (root / "report.json").write_bytes(encoded(report))
    return report
