"""Real distributed companion lifecycle; optional locally, mandatory in native qualification."""

import os
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor

import pytest

from oasg.collective.feedback import reconcile
from oasg.collective.journal import Journal
from oasg.collective.native import PINS, require, support
from oasg.collective.replay import replay
from oasg.collective.runtime import example
from oasg.collective.use import execute_use
from oasg.collective.wire import Contract, encoded, loads, sha


@pytest.fixture(scope="module", autouse=True)
def native_installed():
    import importlib.metadata

    for name, (package, _) in PINS.items():
        try:
            importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            if os.environ.get("OASG_REQUIRE_NATIVE") == "1":
                pytest.fail("required native qualification package absent: " + package)
            pytest.skip("optional pinned native environment required")
        require(name)


@pytest.fixture(scope="module")
def completed(tmp_path_factory):
    root = tmp_path_factory.mktemp("native") / "runtime"
    report = example(root)
    return root, report


def test_real_two_cycle_and_reconciled_feedback(completed):
    root, report = completed
    assert report["gate"] == "safe_promotion"
    assert report["active"] == "active_promoted"
    assert report["work"] == {"baseline": 30, "candidate": 10}
    assert report["second_cycle"]["process_id"] != os.getpid()
    assert report["second_cycle"]["applied"]["policy"] == "indexed"
    assert report["second_cycle"]["applied"]["measurement"]["probes"] == 8
    assert not report["second_cycle"]["receiver_B_eligible"]
    assert not report["second_cycle"]["receiver_C_supported"]
    assert not report["withdrawal"]["memory_eligible"]
    assert report["accounting"]["status"] == "reconciled"
    assert not report["operationally_observed"]
    oracle = replay(root)
    assert oracle["actual_registered_work"] == 62
    assert not oracle["next_use_eligible"]
    assert oracle["reward_added"] == oracle["asset_stock_added"] == 0
    with pytest.raises(ValueError, match="revision"):
        execute_use(root)


def test_replay_never_runs_worker_opens_socket_or_writes(completed, monkeypatch):
    root, _ = completed
    before = {p.relative_to(root): sha(p.read_bytes()) for p in root.rglob("*") if p.is_file()}

    def prohibited(*args, **kwargs):
        raise AssertionError("read-only replay attempted a runtime effect")

    monkeypatch.setattr(subprocess, "run", prohibited)
    monkeypatch.setattr(socket, "socket", prohibited)
    result = replay(root)
    assert result["status"] == "checked"
    after = {p.relative_to(root): sha(p.read_bytes()) for p in root.rglob("*") if p.is_file()}
    assert before == after


def test_reconciliation_delivery_is_idempotent(completed):
    root, _ = completed
    before = Journal(root).inspect()
    assert reconcile(root)["idempotent"]
    assert Journal(root).inspect() == before


def test_fixed_native_manifest():
    result = support()
    assert all(r["content_verified"] for r in result["companions"])
    assert not result["execution_authorization"]


@pytest.mark.parametrize(
    "point,pending",
    [
        ("task-created", "trial-task-lease"),
        ("lease-acquired", "trial-task-lease"),
        ("execute-candidate", "execute-candidate"),
        ("trial-result", "trial-result"),
        ("memory-admission", "memory-admission"),
        ("local-promotion", "local-promotion"),
        ("cycle-two-use", "cycle-two-use"),
        ("memory-withdrawal", "withdrawal"),
        ("policy-rollback", "withdrawal"),
    ],
)
def test_uncertain_effects_stop_without_retry_or_erasure(tmp_path, point, pending):
    root = tmp_path / "runtime"
    with pytest.raises(RuntimeError, match="injected crash"):
        example(root, fail_after=point)
    journal = Journal(root)
    snapshot = journal.inspect()
    assert snapshot["unresolved"] == [pending]
    contract = Contract.model_validate(snapshot["entries"][0]["data"]["contract"])
    with pytest.raises(ValueError, match="unresolved"):
        journal.require_ready(contract, now=contract.registered_at)
    assert replay(root)["status"] == "unresolved_operation"
    assert reconcile(root)["status"] == "unresolved_operation"
    assert journal.inspect() == snapshot
    if pending == "withdrawal":
        assert snapshot["withdrawn"]


def test_single_winner_journal_cas(tmp_path, completed):
    original = Journal(completed[0]).inspect()["entries"][0]["data"]
    journal = Journal(tmp_path)
    revision = journal.append("register", "registration", original, expected="0" * 64)

    def append(i):
        try:
            journal.append("intent", "attempt:" + str(i), {}, expected=revision)
            return "committed"
        except ValueError:
            return "stale"

    with ThreadPoolExecutor(max_workers=4) as executor:
        outcomes = list(executor.map(append, range(4)))
    assert outcomes.count("committed") == 1
    assert outcomes.count("stale") == 3
    assert len(journal.inspect()["unresolved"]) == 1


def test_source_files_remain_original(completed):
    root, _ = completed
    trial = loads((root / "trial.json").read_bytes())
    for name, projection in zip(("baseline", "candidate"), trial["projections"], strict=True):
        assert (root / (name + ".json")).read_bytes() == encoded(projection["source"])


def test_actual_negative_after_success_preserves_cost_and_blocks_reuse(tmp_path):
    root = tmp_path / "fault-control"
    report = example(root, negative_control=True)
    assert report["second_cycle"]["outcome"]["service"]
    negative = report["negative_control"]
    assert negative["applied"]["negative_control"]
    assert negative["applied"]["measurement"]["output"] == ""
    assert negative["applied"]["measurement"]["probes"] == 8
    assert not negative["outcome"]["service"]
    assert not negative["eligible_after_check"]
    assert not report["withdrawal"]["memory_eligible"]
    checked = replay(root)
    assert checked["actual_registered_work"] == 70
    assert checked["source_costs"]["negative-use-work"] == 8
    assert checked["source_costs"]["cycle-two-work"] == 8
    assert checked["reward_added"] == checked["asset_stock_added"] == 0


def test_native_cli_execution_and_explicit_reconciliation(tmp_path, completed):
    from typer.testing import CliRunner
    from oasg.cli import app

    runner = CliRunner()
    result = runner.invoke(
        app, ["collective", "example", "--out", str(tmp_path / "cli"), "--execute"]
    )
    assert result.exit_code == 0, result.output
    value = loads(result.output.encode())
    assert value["second_cycle_policy"] == "indexed"
    assert not value["after_withdrawal_eligible"]
    reconciled = runner.invoke(app, ["collective", "reconcile", str(completed[0]), "--apply"])
    assert reconciled.exit_code == 0, reconciled.output
    assert loads(reconciled.output.encode())["idempotent"]
