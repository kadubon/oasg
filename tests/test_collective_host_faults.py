"""Selected fail-closed host tests; mutated responses are explicitly fault controls."""

import os

import pytest

import test_collective_native as fixtures
from test_collective_host import registered_host
from oasg.collective import runtime
from oasg.collective.journal import Journal
from oasg.collective.wire import encoded, loads

native_installed = fixtures.native_installed


def test_cutoff_crossed_during_validation_never_registers(tmp_path, monkeypatch):
    contract, config, key = registered_host()
    clock = [contract.registered_at]
    actual = runtime.vek_bridge.capacity

    def capacity(c):
        result = actual(c)
        clock[0] = contract.cutoff + 1
        return result

    monkeypatch.setattr(runtime.vek_bridge, "capacity", capacity)
    monkeypatch.setattr(runtime.time, "time", lambda: clock[0])
    root = tmp_path / "host"
    with pytest.raises(ValueError, match="cutoff passed"):
        runtime.execute_registered(root, contract, config, key=key)
    assert not (root / "collective.json").exists()


@pytest.mark.parametrize(
    "action,reason",
    [("formation", "local activation"), ("qualify", "receiver checks"), ("use", "receiver use")],
)
def test_rejected_native_admission_stops_next_transition(tmp_path, monkeypatch, action, reason):
    real = runtime.ccr_bridge.admit_result

    def declined(store, run_id, task, **kwargs):
        result = real(store, run_id, task, **kwargs)
        if task["growth_action"] == action:
            result["admission"]["blockers"] = ["selected-admission-response-fault"]
        return result

    monkeypatch.setattr(runtime.ccr_bridge, "admit_result", declined)
    root = tmp_path / "host"
    with pytest.raises(ValueError, match=reason):
        runtime.example(root)
    assert not (root / "report.json").exists()
    assert Journal(root).inspect()["entries"]


def test_fake_fresh_process_claim_is_rejected(tmp_path, monkeypatch):
    real = runtime.subprocess.run
    parent = os.getpid()

    def changed(argv, **kwargs):
        result = real(argv, **kwargs)
        if "oasg.collective.use" in argv:
            value = loads(result.stdout)
            value["process_id"] = parent
            result.stdout = encoded(value)
        return result

    monkeypatch.setattr(runtime.subprocess, "run", changed)
    with pytest.raises(ValueError, match="fresh-process"):
        runtime.example(tmp_path / "host")
