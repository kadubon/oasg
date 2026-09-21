"""Durable local CAS, original acknowledgment and malformed history checks."""

import pytest

from oasg.collective.journal import Journal
from oasg.collective.wire import digest, encoded
from test_collective import contract_key


def registered(tmp_path):
    contract, _, public = contract_key()
    journal = Journal(tmp_path)
    revision = journal.append("register", "registration", {"contract": contract.model_dump(),
        "public_key": public.hex()}, expected="0"*64)
    return journal, contract, revision


def test_idempotent_delivery_and_conflicts(tmp_path):
    journal, contract, revision = registered(tmp_path)
    assert journal.require_ready(contract, now=contract.registered_at)["revision"] == revision
    pending = journal.append("intent", "work", {"input": "inert"}, expected=revision)
    assert journal.append("intent", "work", {"input": "inert"}, expected=revision) == pending
    with pytest.raises(ValueError, match="conflicting"):
        journal.append("intent", "work", {"input": "other"}, expected=revision)
    with pytest.raises(ValueError, match="stale"):
        journal.append("intent", "other", {}, expected=revision)
    with pytest.raises(ValueError, match="unresolved"):
        journal.require_ready(contract, now=contract.registered_at)
    ack = {"intent": "work", "original_result": "{}", "result_sha256": digest({})}
    final = journal.append("ack", "work:ack", ack, expected=pending)
    assert journal.require_ready(contract, now=contract.registered_at)["revision"] == final
    with pytest.raises(ValueError, match="expired"):
        journal.require_ready(contract, now=contract.expires_at)
    with pytest.raises(ValueError, match="unregistered"):
        journal.require_ready(contract.model_copy(update={"pool": "other"}), now=contract.registered_at)
    with pytest.raises(ValueError, match="immutable"):
        journal.append("register", "replacement", {"contract": contract.model_dump()}, expected=final)
    with pytest.raises(ValueError, match="pending"):
        journal.append("ack", "extra:ack", ack, expected=final)
    with pytest.raises(ValueError, match="unsupported"):
        journal.append("grant", "extra", {}, expected=final)


def test_rejected_ack_never_changes_file(tmp_path):
    journal, _, revision = registered(tmp_path)
    before = journal.path.read_bytes()
    with pytest.raises(ValueError, match="acknowledgment"):
        journal.append("ack", "malformed", {"intent": "work"}, expected=revision)
    assert journal.path.read_bytes() == before


def test_requires_registration_and_bounds(tmp_path):
    journal = Journal(tmp_path)
    assert journal.inspect()["entries"] == []
    with pytest.raises(ValueError, match="registration"):
        journal.append("intent", "orphan", {}, expected="0"*64)
    journal, _, revision = registered(tmp_path)
    for i in range(127):
        revision = journal.append("intent", "item:"+str(i), {}, expected=revision)
    with pytest.raises(ValueError, match="full"):
        journal.append("intent", "overflow", {}, expected=revision)


def test_history_tampering(tmp_path):
    journal, _, _ = registered(tmp_path)
    original = journal.inspect()["entries"]
    for invalid in ({}, [], original*129):
        journal.path.write_bytes(encoded(invalid))
        with pytest.raises(ValueError):
            journal.inspect()
    row = original[0]
    for changes in ({"previous": "1"*64}, {"extra": 1}, {"data": []}):
        journal.path.write_bytes(encoded([row | changes]))
        with pytest.raises(ValueError):
            journal.inspect()
    for kind, data in [("ack", {"intent":"absent","original_result":"{}","result_sha256":digest({})}),
                       ("unknown", {}), ("intent", {})]:
        body = {k: row[k] for k in ("previous", "id", "kind", "data")}
        body.update(kind=kind, data=data)
        journal.path.write_bytes(encoded([body | {"digest":digest(body)}]))
        with pytest.raises(ValueError):
            journal.inspect()


def test_readonly_absence(tmp_path):
    root = tmp_path / "absent"
    assert Journal(root).inspect()["entries"] == []
    assert not root.exists()
