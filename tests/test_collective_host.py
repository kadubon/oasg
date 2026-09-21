"""Caller-owned registered execution and subsequent admitted lifecycle feedback."""

import time

import pytest

import test_collective_native as fixtures
from oasg.collective import ccr_bridge
from oasg.collective.feedback import reconcile, withdraw
from oasg.collective.journal import Journal
from oasg.collective.replay import replay
from oasg.collective.runtime import execute_registered
from oasg.collective.wire import Scope, digest
from test_collective import contract_key

native_installed = fixtures.native_installed


def registered_host(**changes):
    scope = Scope(
        mission="finite",
        study="finite",
        worker="worker",
        receiver="A",
        context="finite",
        namespace="host-test",
    )
    contract, key, public = contract_key(scope=scope, pool="pool:finite", **changes)
    artifact = digest(
        {
            "variant": contract.candidate,
            "implementation": contract.implementation,
            "inputs": contract.confirmation,
        }
    )
    config = ccr_bridge.registration(
        public,
        contract.confirmation,
        study="finite",
        worker="worker",
        context="finite",
        artifact=artifact,
    )
    now = int(time.time())
    contract = contract.model_copy(
        update={
            "registered_at": now,
            "cutoff": now + 2,
            "expires_at": ccr_bridge.utc_seconds(config["base"]["deadline"]),
            "ccr_registration": digest(config),
        }
    )
    return contract, config, key


def test_separate_later_withdrawal_reconciles_new_source_once(tmp_path):
    contract, config, key = registered_host()
    root = tmp_path / "host"
    result = execute_registered(root, contract, config, key=key)
    assert result["withdrawal"] is None
    assert result["second_cycle"]["eligible_after_check"]
    previous = (root / "accounting.json").read_bytes()
    assert replay(root)["requires_fresh_host_check"]
    withdraw(
        root, key=key, reason="Host admitted scoped dependency withdrawal after successful use"
    )
    assert reconcile(root)["status"] == "reconciled"
    assert reconcile(root)["idempotent"]
    preserved = list(root.glob("accounting-*.json"))
    assert len(preserved) == 3  # two immutable snapshots plus the latest candidate export
    assert any(p.read_bytes() == previous for p in preserved)
    assert (
        replay(root)["actual_registered_work"] == 61
    )  # This host registered one fewer training line.
    assert not replay(root)["requires_fresh_host_check"]


def test_unknown_signer_cannot_withdraw(tmp_path):
    contract, config, key = registered_host()
    root = tmp_path / "host"
    execute_registered(root, contract, config, key=key)
    _, _, other = registered_host()
    before = Journal(root).inspect()
    with pytest.raises(ValueError, match="signer"):
        withdraw(root, key=other, reason="unauthenticated allegation")
    assert Journal(root).inspect() == before


@pytest.mark.parametrize("failure", ["budget", "existing", "policy"])
def test_host_rejections_before_execution(tmp_path, monkeypatch, failure):
    import oasg.collective.runtime as runtime

    contract, config, key = registered_host()
    root = tmp_path / "host"
    if failure == "budget":
        monkeypatch.setattr(runtime.vek_bridge, "capacity", lambda _: {"feasible": False})
    elif failure == "existing":
        root.mkdir()
        (root / "unrelated.txt").write_text("preserve", encoding="utf-8")
    else:
        contract = contract.model_copy(update={"library_digest": "sha256:" + "0" * 64})
    with pytest.raises(ValueError):
        execute_registered(root, contract, config, key=key)
    assert not (root / "collective.json").exists()
