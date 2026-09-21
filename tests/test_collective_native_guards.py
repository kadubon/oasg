"""Negative host boundaries around the separately tested real native lifecycle."""

import importlib
import json
import time
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor

import pytest

from oasg.collective import ccr_bridge, native, vek_bridge
from oasg.collective.journal import Journal
from oasg.collective.wire import Contract, digest
from test_collective import contract_key, sources
import test_collective_native as native_fixtures

completed = native_fixtures.completed
native_installed = native_fixtures.native_installed


@pytest.mark.parametrize(
    "change",
    [
        {"ccr_registration": "0" * 64},
        {"verifier_key": "0" * 64},
        {"cutoff": 0},
        {"ccr_revision": 1},
        {"pool": "other"},
        {"cleanup_budget": 0},
        {"verification_budget": 1},
        {"max_work": 501},
        {"candidate": "scan"},
        {"evidence_class": "synthetic"},
        {"implementation": "0" * 64},
        {"checker": "0" * 64},
    ],
)
def test_registration_constraints(completed, change):
    registration = Journal(completed[0]).inspect()["entries"][0]["data"]
    contract = Contract.model_validate(registration["contract"])
    config = json.loads(registration["ccr_config_original"])
    with pytest.raises(ValueError):
        ccr_bridge.check_registration(
            contract.model_copy(update=change),
            config,
            bytes.fromhex(registration["public_key"]),
            now=contract.registered_at,
        )


def test_registration_cannot_widen_native_authority(completed):
    registration = Journal(completed[0]).inspect()["entries"][0]["data"]
    contract = Contract.model_validate(registration["contract"])
    config = json.loads(registration["ccr_config_original"])
    public = bytes.fromhex(registration["public_key"])
    changed = deepcopy(config)
    changed["growth"]["receivers"]["A"]["cross_mission_allowed"] = True
    altered = contract.model_copy(update={"ccr_registration": digest(changed)})
    with pytest.raises(ValueError, match="authority"):
        ccr_bridge.check_registration(altered, changed, public, now=contract.registered_at)
    earlier = deepcopy(config)
    earlier["base"]["deadline"] = "2000-01-01T00:00:00+00:00"
    with pytest.raises(ValueError, match="deadline"):
        ccr_bridge.check_registration(
            contract.model_copy(update={"ccr_registration": digest(earlier)}),
            earlier,
            public,
            now=contract.registered_at,
        )


def test_ccr_real_lease_contention_and_stale_fence(tmp_path):
    _, _, public = contract_key()
    config = ccr_bridge.registration(
        public, ["z\na"], study="contended", worker="worker", context="finite", artifact="1" * 64
    )
    store = ccr_bridge.open_store(tmp_path / "ccr")
    engine = ccr_bridge.ccr()
    run_id = engine.initialize(store, mission="contended", config=config)["run_id"]
    plan = engine.plan(store, run_id)
    trial = engine.step(store, run_id, apply=True, expected_revision=plan["revision"])["trial"]

    def claim(_):
        try:
            return engine.claim(store, run_id, trial["trial_id"], worker="worker", ttl_seconds=30)[
                "ok"
            ]
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=4) as executor:
        attempts = list(executor.map(claim, range(4)))
    assert attempts.count(True) == 1
    current = engine.load(store, run_id)["trials"][0]
    token = current["fencing_token"]
    assert ccr_bridge.current_task(
        store, run_id, trial["trial_id"], "worker", token, expected_config=config
    )
    with pytest.raises(ValueError):
        ccr_bridge.current_task(store, run_id, trial["trial_id"], "worker", token + 1)
    changed = deepcopy(config)
    changed["growth"]["quota"]["allocation_ref"] = "different-allocation"
    with pytest.raises(ValueError, match="registration"):
        ccr_bridge.current_task(
            store, run_id, trial["trial_id"], "worker", token, expected_config=changed
        )


def test_verification_bottleneck_and_nonpositive_statuses():
    contract, key, public = contract_key(verification_budget=1)
    assert not vek_bridge.capacity(contract)["feasible"]
    contract, key, public = contract_key(candidate="skip-last")
    report = vek_bridge.verification(contract, sources(contract, key)[1], public)
    assert report["verification_work_status"] == "negative"
    assert not report["positive_service"]


def test_missing_wrong_and_changed_companion(monkeypatch, tmp_path):
    real = importlib.metadata.version
    monkeypatch.setattr(importlib.metadata, "version", lambda _: "unregistered")
    with pytest.raises(ValueError, match="unsupported_companion_version"):
        native.require("vek")
    monkeypatch.setattr(importlib.metadata, "version", real)
    original = native.manifest
    altered = original()
    first = next(iter(altered["vek"]["files"]))
    altered["vek"]["files"][first] = "0" * 64
    monkeypatch.setattr(native, "manifest", lambda: altered)
    with pytest.raises(ValueError, match="unsupported_companion_content"):
        native.require("vek")
    assert next(r for r in native.support()["companions"] if r["companion"] == "vek")["problem"]
    monkeypatch.setattr(native, "manifest", original)

    def absent(_):
        raise importlib.metadata.PackageNotFoundError("absent")

    monkeypatch.setattr(importlib.metadata, "version", absent)
    with pytest.raises(ValueError, match="optional_dependency_required"):
        native.require("vek")
    assert all(r["installed"] is None for r in native.support()["companions"])


def test_rejected_memory_candidate_sources(completed):
    from oasg.collective.memory import DomainChecker
    from oasg.collective.wire import loads

    root, _ = completed
    registration = Journal(root).inspect()["entries"][0]["data"]
    contract = Contract.model_validate(registration["contract"])
    public = bytes.fromhex(registration["public_key"])
    trial = loads((root / "trial.json").read_bytes())
    raw = loads((root / "memory.json").read_bytes())["memory"]
    model = importlib.import_module("observable_agent_workflow_memory.core.models")
    candidate = model.MemoryRecord.model_validate(raw)
    checker = DomainChecker(contract, trial, public)
    context = {"actual_event_digests": dict.fromkeys(candidate.source_event_ids, "source")}
    assert checker.verify(candidate, evidence={}, context=context).passed
    for field in ("oasg_source", "oasg_contract"):
        changed = candidate.model_copy(deep=True)
        changed.metadata[field] = "0" * 64
        assert not checker.verify(changed, evidence={}, context=context).passed
    assert not checker.verify(candidate, evidence={}, context={"actual_event_digests": {}}).passed


def test_result_pending_is_not_a_new_execution_lease(tmp_path):
    _, _, public = contract_key()
    config = ccr_bridge.registration(
        public, ["z\na"], study="pending", worker="worker", context="finite", artifact="1" * 64
    )
    store = ccr_bridge.open_store(tmp_path / "ccr")
    engine = ccr_bridge.ccr()
    run_id = engine.initialize(store, mission="pending", config=config)["run_id"]
    task = ccr_bridge.next_task(store, run_id, "worker")
    engine.task_transition(
        store,
        run_id,
        task["trial_id"],
        worker="worker",
        token=task["fencing_token"],
        result={"source": "awaiting-admission"},
        idempotency_key="work-done",
    )
    with pytest.raises(ValueError, match="no longer executable"):
        ccr_bridge.current_task(store, run_id, task["trial_id"], "worker", task["fencing_token"])
    assert ccr_bridge.current_task(
        store, run_id, task["trial_id"], "worker", task["fencing_token"], for_execution=False
    )


def test_completed_run_does_not_manufacture_more_work(completed):
    root, _ = completed
    view = Journal(root).inspect()
    run_id = next(r for r in view["entries"] if r["id"] == "cycle-two-use")["data"]["run"]
    with pytest.raises(ValueError, match="no funded"):
        ccr_bridge.next_task(ccr_bridge.open_store(root / "ccr"), run_id, "finite-worker")


def test_native_shared_pool_cannot_be_reserved_twice(tmp_path):
    _, _, public = contract_key()
    config = ccr_bridge.registration(
        public, ["z\na"], study="shared", worker="worker", context="finite", artifact="1" * 64
    )
    store = ccr_bridge.open_store(tmp_path / "ccr")
    engine = ccr_bridge.ccr()

    def register(i):
        own_config = deepcopy(config)
        own_config["growth"]["study_id"] = "shared:" + str(i)
        try:
            return engine.initialize(store, mission="mission:" + str(i), config=own_config)["ok"]
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(register, range(2)))
    assert results.count(True) == 1
    assert results.count(False) == 1


def test_expired_or_changed_worker_never_executes(monkeypatch):
    from oasg.collective.trial import run_worker

    contract, key, _ = contract_key()
    binding = sources(contract, key)[1].execution().binding
    with pytest.raises(ValueError, match="registered"):
        run_worker(
            contract.model_copy(update={"implementation": "0" * 64}),
            binding,
            split="confirmation",
            key=key,
            now=int(time.time()),
        )
    with pytest.raises(ValueError, match="expired"):
        run_worker(contract, binding, split="confirmation", key=key, now=binding.lease_end)
    with pytest.raises(ValueError, match="policy"):
        run_worker(
            contract,
            binding.model_copy(update={"policy_digest": "0" * 64}),
            split="confirmation",
            key=key,
            now=int(time.time()),
        )


def test_native_core_rejection_is_not_a_pass(monkeypatch):
    from types import SimpleNamespace

    core = importlib.import_module("verification_ecology_kit.model.conformance")
    monkeypatch.setattr(
        core.ConformanceEngine,
        "run",
        lambda *args: SimpleNamespace(decision=SimpleNamespace(value="reject")),
    )
    contract, key, public = contract_key()
    with pytest.raises(ValueError, match="conformance rejected"):
        vek_bridge.verification(contract, sources(contract, key)[1], public)


def test_use_verification_reconstructs_counters_and_status(completed):
    root, report = completed
    contract = Contract.model_validate(Journal(root).inspect()["entries"][0]["data"]["contract"])
    for change in (
        lambda r: r["applied"]["measurement"].update(probes=0),
        lambda r: r["outcome"].update(service=False),
    ):
        source = deepcopy(report["second_cycle"])
        change(source)
        with pytest.raises(ValueError):
            vek_bridge.verification_use(contract, source)


def test_nonpromoting_memory_and_unregistered_fault_are_rejected(tmp_path):
    from oasg.collective import memory
    from oasg.collective.trial import compare

    contract, key, public = contract_key(candidate="scan")
    trial = compare(contract, *sources(contract, key), public)
    assert (
        not memory.DomainChecker(contract, trial, public)
        .verify(None, evidence={}, context={})
        .passed
    )
    with pytest.raises(ValueError, match="checked trial"):
        memory.admit(tmp_path / "none", contract, trial, public)
    with pytest.raises(ValueError, match="fault control"):
        memory.open_kernel(tmp_path / "none", contract, trial, public, negative_control=True)
    assert not (tmp_path / "none").exists()


def test_native_memory_checker_rejection_is_preserved(tmp_path, monkeypatch):
    from oasg.collective import memory
    from oasg.collective.trial import compare

    models = importlib.import_module("observable_agent_workflow_memory.core.models")
    monkeypatch.setattr(
        memory.DomainChecker,
        "verify",
        lambda *args, **kwargs: models.CheckerResult(
            checker_name="selected-negative-control",
            passed=False,
            reason="Finite checker fault test",
        ),
    )
    contract, key, public = contract_key()
    trial = compare(contract, *sources(contract, key), public)
    with pytest.raises(ValueError, match="native verification rejected"):
        memory.admit(tmp_path / "rejected", contract, trial, public)
