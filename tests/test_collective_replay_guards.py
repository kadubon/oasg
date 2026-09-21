"""Independent replay rejects internally rehashed but unauthenticated substitutions."""

import json
import shutil
from copy import deepcopy

import pytest

import test_collective_native as fixtures
from oasg.collective.journal import Journal
from oasg.collective.replay import replay
from oasg.collective.wire import digest, encoded, loads, sha

completed = fixtures.completed
native_installed = fixtures.native_installed


def copy_run(tmp_path, completed):
    root = tmp_path / "copy"
    shutil.copytree(completed[0], root)
    return root


def rewrite_journal(root, change):
    """Rechain local hashes; this deliberately cannot forge a host signature."""
    rows = loads((root / "collective.json").read_bytes())
    change(rows)
    previous = "0" * 64
    for row in rows:
        row["previous"] = previous
        row["digest"] = digest({k: v for k, v in row.items() if k != "digest"})
        previous = row["digest"]
    (root / "collective.json").write_bytes(encoded(rows))


@pytest.mark.parametrize(
    "filename,change",
    [
        ("baseline.json", lambda d: d.update(producer_digest="0" * 64)),
        ("memory.json", lambda d: d.update(contract="0" * 64)),
        ("memory.json", lambda d: d["receipt"].update(receipt_digest="0" * 64)),
        ("memory.json", lambda d: d["memory"]["metadata"].update(oasg_source="0" * 64)),
        ("memory.json", lambda d: d["costs"][0].update(amount="900")),
        ("accounting.json", lambda d: d["checked"].update(reward_added=1)),
    ],
)
def test_untrusted_derived_files(completed, tmp_path, filename, change):
    root = copy_run(tmp_path, completed)
    path = root / filename
    raw = loads(path.read_bytes())
    change(raw)
    path.write_bytes(encoded(raw))
    with pytest.raises(ValueError):
        replay(root)


def test_changed_journal_trust_root(completed, tmp_path):
    root = copy_run(tmp_path, completed)
    rewrite_journal(root, lambda rows: rows[0]["data"].update(public_key="00" * 32))
    with pytest.raises(ValueError, match="trust"):
        replay(root)


def test_original_native_config_cannot_be_replaced(completed, tmp_path):
    root = copy_run(tmp_path, completed)

    def change(rows):
        data = rows[0]["data"]
        config = json.loads(data["ccr_config_original"])
        config["growth"]["quota"]["allocation_ref"] = "new-namespace"
        data["ccr_config_original"] = encoded(config).decode()

    rewrite_journal(root, change)
    with pytest.raises(ValueError, match="configuration"):
        replay(root)


def test_modified_result_with_fresh_local_hash_still_requires_host_signature(completed, tmp_path):
    root = copy_run(tmp_path, completed)

    def change(rows):
        row = next(r for r in rows if r["id"] == "use-result:ack")
        result = json.loads(row["data"]["original_result"])
        result["envelope"]["result"]["actual_resources"]["work"] = 0
        original = encoded(result).decode()
        row["data"].update(original_result=original, result_sha256=sha(original.encode()))

    rewrite_journal(root, change)
    with pytest.raises(ValueError, match="signature"):
        replay(root)


def test_signed_result_wrong_ultimate_source_is_rejected(completed):
    from oasg.collective.replay import check_native_results
    from oasg.collective.wire import Contract

    root, _ = completed
    view = Journal(root).inspect()
    registration = view["entries"][0]["data"]
    accounting = loads((root / "accounting.json").read_bytes())
    run = json.loads(accounting["ccr_snapshot_original"])
    contract = Contract.model_validate(registration["contract"])
    public = bytes.fromhex(registration["public_key"])
    trial = loads((root / "trial.json").read_bytes())
    with pytest.raises(ValueError, match="reconstructed source"):
        check_native_results(view, contract, run, public, {"trial-result": ("0" * 64, 40, True)})
    changed = deepcopy(run)
    changed["trials"][0]["fencing_token"] += 1
    with pytest.raises(ValueError, match="assigned attempt"):
        check_native_results(
            view, contract, changed, public, {"trial-result": (digest(trial), 40, True)}
        )


def rewrite_snapshot(root, change):
    value = loads((root / "accounting.json").read_bytes())
    change(value)
    (root / "accounting.json").write_bytes(encoded(value))

    def update(rows):
        row = next(
            r for r in reversed(rows) if r["id"].startswith("accounting:") and r["kind"] == "ack"
        )
        acknowledged = loads(row["data"]["original_result"].encode())
        acknowledged["snapshot_digest"] = digest(value)
        original = encoded(acknowledged).decode()
        row["data"].update(original_result=original, result_sha256=sha(original.encode()))
        name = row["id"].removesuffix(":ack").replace(":", "-") + ".json"
        (root / name).write_bytes(encoded(value))

    rewrite_journal(root, update)


@pytest.mark.parametrize("mode", ["config", "derived", "cost"])
def test_rehashed_accounting_still_needs_independent_source_check(
    completed, tmp_path, monkeypatch, mode
):
    root = copy_run(tmp_path, completed)

    def change(value):
        if mode == "config":
            run = json.loads(value["ccr_snapshot_original"])
            run["config"]["mission"] = "substituted"
            value["ccr_snapshot_original"] = json.dumps(run)
        else:
            value["checked"]["costs"]["work"] += 1

    rewrite_snapshot(root, change)
    if mode == "cost":
        # Selected faulty native checker: the independent physical-event oracle must still reject.
        import ccr.optimizer.native_accounting as native

        changed = loads((root / "accounting.json").read_bytes())["checked"]
        monkeypatch.setattr(native, "check_feedback", lambda *args: changed)
    with pytest.raises(
        ValueError,
        match={"config": "configuration", "derived": "derived accounting", "cost": "physical work"}[
            mode
        ],
    ):
        replay(root)


def test_removing_later_use_cannot_turn_partial_history_into_completion(completed, tmp_path):
    root = copy_run(tmp_path, completed)
    rewrite_journal(
        root,
        lambda rows: rows.__setitem__(
            slice(None), [r for r in rows if r["id"] not in {"cycle-two-use", "cycle-two-use:ack"}]
        ),
    )
    with pytest.raises(ValueError, match="later use evidence missing"):
        replay(root)
