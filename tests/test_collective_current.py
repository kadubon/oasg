"""Current-state checks are repeated at actual tool use, after prior positive checks."""

import json
import shutil

import pytest

import test_collective_native as fixtures
from oasg.canonical import receipt_hash
from oasg.collective import memory, use
from oasg.collective.journal import Journal
from oasg.collective.runtime import example
from oasg.collective.wire import Contract, digest, encoded, loads
from oasg.library import load_library
from test_collective_replay_guards import rewrite_journal

native_installed = fixtures.native_installed


@pytest.fixture(scope="module")
def pending(tmp_path_factory):
    root = tmp_path_factory.mktemp("pending-use") / "host"
    with pytest.raises(RuntimeError, match="durable intent"):
        example(root, fail_after="cycle-two-use:intent")
    assert Journal(root).inspect()["unresolved"] == ["cycle-two-use"]
    assert not (root / "memory" / "last-use.json").exists()
    return root


def local_copy(tmp_path, pending):
    root = tmp_path / "copy"
    shutil.copytree(pending, root)
    return root


@pytest.mark.parametrize(
    "mode", ["operation", "source", "policy-hash", "policy", "expiry", "config", "version"]
)
def test_stale_or_substituted_use_is_refused(tmp_path, pending, monkeypatch, mode):
    root = local_copy(tmp_path, pending)
    if mode == "source":
        path = root / "memory.json"
        value = loads(path.read_bytes())
        value["revision"] = "0" * 64
        path.write_bytes(encoded(value))
    elif mode in {"policy-hash", "policy"}:
        path = root / "library.json"
        value = json.loads(path.read_text())
        value["policy_state"]["routing_policy"]["local_reversible"] = "scan"
        path.write_bytes(encoded(value))
        if mode == "policy":
            expected = receipt_hash(load_library(path).to_dict())
            rewrite_journal(
                root,
                lambda rows: next(r for r in rows if r["id"] == "cycle-two-use")["data"].update(
                    library=expected
                ),
            )
    elif mode == "expiry":
        contract = Contract.model_validate(
            Journal(root).inspect()["entries"][0]["data"]["contract"]
        )
        monkeypatch.setattr(use.time, "time", lambda: contract.expires_at + 1)
    elif mode == "config":

        def change(rows):
            original = json.loads(rows[0]["data"]["ccr_config_original"])
            original["growth"]["quota"]["allocation_ref"] = "replaced"
            rows[0]["data"]["ccr_config_original"] = encoded(original).decode()

        rewrite_journal(root, change)
    elif mode == "version":
        path = root / "memory.json"
        value = loads(path.read_bytes())
        value["qualification"]["memory_id"] = "other-memory"
        path.write_bytes(encoded(value))
        rewrite_journal(
            root,
            lambda rows: next(r for r in rows if r["id"] == "cycle-two-use")["data"].update(
                memory=digest(value)
            ),
        )
    with pytest.raises(ValueError):
        use.execute_use(root, "unregistered" if mode == "operation" else "cycle-two-use")
    assert not (root / "memory" / "last-use.json").exists()


def test_dependency_change_at_tool_boundary_is_not_success(tmp_path, pending, monkeypatch):
    root = local_copy(tmp_path, pending)
    monkeypatch.setattr(memory, "implementation_digest", lambda: "0" * 64)
    with pytest.raises(ValueError, match="did not verify"):
        use.execute_use(root)
    assert not (root / "memory" / "last-use.json").exists()


def test_readonly_memory_promotion_does_not_grant_tool_permission(tmp_path, pending):
    import importlib

    root = local_copy(tmp_path, pending)
    registration = Journal(root).inspect()["entries"][0]["data"]
    contract = Contract.model_validate(registration["contract"])
    trial = loads((root / "trial.json").read_bytes())
    mem = loads((root / "memory.json").read_bytes())
    kernel = memory.open_kernel(
        root / "memory", contract, trial, bytes.fromhex(registration["public_key"])
    )
    models = importlib.import_module("observable_agent_workflow_memory.core.models")
    tools = importlib.import_module("observable_agent_workflow_memory.ports.tools")
    intent = models.ActionIntent.model_validate(mem["intent"])
    result = kernel.invoke_tool(
        tools.ToolCall(
            name="normalize-lines-v1",
            arguments={"text": contract.confirmation[0]},
            external_effect=True,
        ),
        intent,
        [mem["receipt"]["receipt_id"]],
    )
    assert not result.ok
    assert "fresh host execution intent" in result.error
    assert not (root / "memory" / "last-use.json").exists()


def test_nonpromoting_check_cannot_be_used(tmp_path, pending, monkeypatch):
    root = local_copy(tmp_path, pending)
    monkeypatch.setattr(
        use, "check_trial", lambda *args: {"local_gate_status": "safe_non_regression"}
    )
    with pytest.raises(ValueError, match="independent trial"):
        use.execute_use(root)
