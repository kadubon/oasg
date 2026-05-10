from __future__ import annotations

from pathlib import Path

from oasg.examples import quickstart_records
from oasg.io import write_jsonl
from oasg.ledger import VALID_STATUS, append_jsonl, seal_records, verify_records


def test_sealed_ledger_verifies_prefix_chain() -> None:
    records = seal_records(quickstart_records(improved=False))
    receipt = verify_records(records)
    assert receipt.status == VALID_STATUS
    assert receipt.records_seen == 1
    assert receipt.line_statuses[0].status == VALID_STATUS


def test_tampered_record_hash_quarantines_chain() -> None:
    records = seal_records(quickstart_records(improved=False))
    records[0]["payload"]["dimensions"]["budget"] = "surplus"
    receipt = verify_records(records)
    assert receipt.status == "rejected_payload_hash_mismatch"


def test_duplicate_reject_policy_marks_duplicate_line() -> None:
    first = quickstart_records(improved=False)[0]
    second = dict(first)
    records = seal_records([first, second])
    receipt = verify_records(records)
    assert receipt.status == VALID_STATUS
    assert receipt.line_statuses[1].status == "rejected_duplicate_policy"


def test_unknown_schema_epoch_rejects_ledger() -> None:
    records = seal_records(quickstart_records(improved=False))
    records[0]["schema_epoch"] = "unknown"
    receipt = verify_records(records)
    assert receipt.status == "rejected_schema_migration_invalid"


def test_append_jsonl_seals_continuation(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    new_records = tmp_path / "new.jsonl"
    out = tmp_path / "ledger.jsonl"
    write_jsonl(ledger, seal_records(quickstart_records(improved=False)))
    write_jsonl(new_records, quickstart_records(improved=True))
    receipt = append_jsonl(ledger, new_records, out)
    assert receipt.status == "appended"
    assert receipt.previous_records_seen == 1
    assert receipt.new_records_seen == 2


def test_append_jsonl_rejects_prefix_mismatch(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    new_records = tmp_path / "new.jsonl"
    write_jsonl(ledger, seal_records(quickstart_records(improved=False)))
    write_jsonl(new_records, quickstart_records(improved=True))
    receipt = append_jsonl(
        ledger,
        new_records,
        ledger,
        expected_prefix_hash="sha256:" + "0" * 64,
    )
    assert receipt.status == "stale_or_forked_ledger_prefix"
