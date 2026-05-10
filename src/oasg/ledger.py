"""Append-only JSONL ledger sealing and verification."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from oasg.canonical import (
    duplicate_identity_hash,
    genesis_hash,
    integrity_hash,
    payload_hash,
    prefix_hash,
    record_hash,
)
from oasg.constants import KNOWN_SCHEMA_EPOCHS, LEDGER_PROFILE, LEDGER_PROFILE_EPOCH
from oasg.io import read_jsonl, write_jsonl


VALID_STATUS = "ledger_prefix_valid"


@dataclass(frozen=True)
class LineStatus:
    append_index: int
    event_id: str
    status: str
    reason: str | None = None


@dataclass(frozen=True)
class LedgerVerification:
    status: str
    ledger_prefix_hash: str
    line_statuses: tuple[LineStatus, ...] = field(default_factory=tuple)
    records_seen: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt_type": "ledger_integrity_receipt",
            "status": self.status,
            "ledger_prefix_hash": self.ledger_prefix_hash,
            "records_seen": self.records_seen,
            "line_statuses": [status.__dict__ for status in self.line_statuses],
        }


@dataclass(frozen=True)
class LedgerAppendReceipt:
    status: str
    ledger_path: str
    appended_records: int
    previous_ledger_prefix_hash: str
    new_ledger_prefix_hash: str
    previous_records_seen: int
    new_records_seen: int
    reason: str | None = None
    receipt_type: str = "ledger_append_receipt"

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt_type": self.receipt_type,
            "status": self.status,
            "ledger_path": self.ledger_path,
            "appended_records": self.appended_records,
            "previous_ledger_prefix_hash": self.previous_ledger_prefix_hash,
            "new_ledger_prefix_hash": self.new_ledger_prefix_hash,
            "previous_records_seen": self.previous_records_seen,
            "new_records_seen": self.new_records_seen,
            "reason": self.reason,
        }


def _base_record(record: dict[str, Any], append_index: int) -> dict[str, Any]:
    output = dict(record)
    output.setdefault("record_type", "event_record")
    output.setdefault("event_id", f"evt_{append_index:06d}")
    output["append_index"] = append_index
    record_type = str(output["record_type"])
    output.setdefault("ledger_profile", LEDGER_PROFILE)
    output.setdefault("ledger_profile_epoch", LEDGER_PROFILE_EPOCH)
    output.setdefault("schema_epoch", KNOWN_SCHEMA_EPOCHS.get(record_type, "oasg.event_record.v1"))
    output.setdefault("policy_epoch", "oasg.policy.v1.0")
    output.setdefault("workflow_id", "default")
    output.setdefault("component_id", "unknown")
    output.setdefault("parent_event_ids", [])
    output.setdefault("event_type", "observation")
    output.setdefault("payload", {})
    output["payload_hash"] = payload_hash(output["payload"])
    output.setdefault("payload_pointer", None)
    output.setdefault("coverage_scope", "default")
    output.setdefault("authority_scope", "local")
    output.setdefault("rejection_status", None)
    output.setdefault("supersedes_event_ids", [])
    output.setdefault("duplicate_policy", "reject_duplicate")
    return output


def seal_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return records with canonical record, integrity, and prefix hashes."""

    sealed: list[dict[str, Any]] = []
    previous_integrity = genesis_hash(LEDGER_PROFILE_EPOCH)
    previous_prefix = genesis_hash(LEDGER_PROFILE_EPOCH)
    for index, record in enumerate(records, start=1):
        item = _base_record(record, index)
        item["prev_integrity_hash"] = previous_integrity
        item["canonical_record_hash"] = record_hash(
            item,
            ledger_profile_epoch=item["ledger_profile_epoch"],
            schema_epoch=item["schema_epoch"],
            record_type=item["record_type"],
        )
        item["integrity_hash"] = integrity_hash(previous_integrity, item["canonical_record_hash"])
        item["ledger_prefix_hash"] = prefix_hash(previous_prefix, item["integrity_hash"])
        previous_integrity = item["integrity_hash"]
        previous_prefix = item["ledger_prefix_hash"]
        sealed.append(item)
    return sealed


def seal_record_continuation(
    existing_records: list[dict[str, Any]],
    new_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Seal new records as a hash-chain continuation of an already valid ledger."""

    verification = verify_records(existing_records)
    if verification.status != VALID_STATUS:
        raise ValueError(f"cannot append to invalid ledger: {verification.status}")
    sealed: list[dict[str, Any]] = []
    previous_integrity = (
        str(existing_records[-1]["integrity_hash"])
        if existing_records
        else genesis_hash(LEDGER_PROFILE_EPOCH)
    )
    previous_prefix = verification.ledger_prefix_hash
    start_index = len(existing_records) + 1
    for offset, record in enumerate(new_records):
        item = _base_record(record, start_index + offset)
        item["prev_integrity_hash"] = previous_integrity
        item["canonical_record_hash"] = record_hash(
            item,
            ledger_profile_epoch=item["ledger_profile_epoch"],
            schema_epoch=item["schema_epoch"],
            record_type=item["record_type"],
        )
        item["integrity_hash"] = integrity_hash(previous_integrity, item["canonical_record_hash"])
        item["ledger_prefix_hash"] = prefix_hash(previous_prefix, item["integrity_hash"])
        previous_integrity = item["integrity_hash"]
        previous_prefix = item["ledger_prefix_hash"]
        sealed.append(item)
    return sealed


def append_jsonl(
    ledger_path: Path,
    records_path: Path,
    out_path: Path,
    *,
    expected_prefix_hash: str | None = None,
) -> LedgerAppendReceipt:
    """Append raw or sealed records to a ledger with prefix verification."""

    existing = read_jsonl(ledger_path) if ledger_path.exists() else []
    existing_verification = verify_records(existing)
    if existing_verification.status != VALID_STATUS:
        return LedgerAppendReceipt(
            status="append_rejected_invalid_ledger",
            ledger_path=str(out_path),
            appended_records=0,
            previous_ledger_prefix_hash=existing_verification.ledger_prefix_hash,
            new_ledger_prefix_hash=existing_verification.ledger_prefix_hash,
            previous_records_seen=existing_verification.records_seen,
            new_records_seen=existing_verification.records_seen,
            reason=existing_verification.status,
        )
    if (
        expected_prefix_hash is not None
        and existing_verification.ledger_prefix_hash != expected_prefix_hash
    ):
        return LedgerAppendReceipt(
            status="stale_or_forked_ledger_prefix",
            ledger_path=str(out_path),
            appended_records=0,
            previous_ledger_prefix_hash=existing_verification.ledger_prefix_hash,
            new_ledger_prefix_hash=existing_verification.ledger_prefix_hash,
            previous_records_seen=existing_verification.records_seen,
            new_records_seen=existing_verification.records_seen,
            reason="expected_prefix_mismatch",
        )
    incoming = _strip_chain_fields(read_jsonl(records_path))
    sealed_new = seal_record_continuation(existing, incoming)
    combined = [*existing, *sealed_new]
    combined_verification = verify_records(combined)
    if combined_verification.status != VALID_STATUS:
        return LedgerAppendReceipt(
            status="append_rejected_invalid_continuation",
            ledger_path=str(out_path),
            appended_records=0,
            previous_ledger_prefix_hash=existing_verification.ledger_prefix_hash,
            new_ledger_prefix_hash=combined_verification.ledger_prefix_hash,
            previous_records_seen=existing_verification.records_seen,
            new_records_seen=combined_verification.records_seen,
            reason=combined_verification.status,
        )
    write_jsonl(out_path, combined)
    return LedgerAppendReceipt(
        status="appended",
        ledger_path=str(out_path),
        appended_records=len(sealed_new),
        previous_ledger_prefix_hash=existing_verification.ledger_prefix_hash,
        new_ledger_prefix_hash=combined_verification.ledger_prefix_hash,
        previous_records_seen=existing_verification.records_seen,
        new_records_seen=combined_verification.records_seen,
    )


def _strip_chain_fields(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chain_fields = {
        "append_index",
        "payload_hash",
        "prev_integrity_hash",
        "canonical_record_hash",
        "integrity_hash",
        "ledger_prefix_hash",
    }
    return [{key: value for key, value in record.items() if key not in chain_fields} for record in records]


def seal_jsonl(input_records: list[dict[str, Any]], output_path: Path) -> None:
    write_jsonl(output_path, seal_records(input_records))


def verify_records(records: list[dict[str, Any]]) -> LedgerVerification:
    previous_integrity = genesis_hash(LEDGER_PROFILE_EPOCH)
    previous_prefix = genesis_hash(LEDGER_PROFILE_EPOCH)
    seen: dict[str, str] = {}
    line_statuses: list[LineStatus] = []

    for expected_index, record in enumerate(records, start=1):
        event_id = str(record.get("event_id", f"line_{expected_index}"))
        append_index = int(record.get("append_index", -1))
        if append_index != expected_index:
            return LedgerVerification(
                "quarantined_prefix_gap",
                previous_prefix,
                tuple(line_statuses),
                len(records),
            )

        schema_status = _schema_status(record)
        if schema_status != VALID_STATUS:
            return LedgerVerification(
                schema_status,
                previous_prefix,
                tuple(line_statuses),
                len(records),
            )

        if record.get("payload_pointer") is not None:
            return LedgerVerification(
                "rejected_external_payload_unsupported",
                previous_prefix,
                tuple(line_statuses),
                len(records),
            )

        expected_payload_hash = payload_hash(record.get("payload", {}))
        if record.get("payload_hash") != expected_payload_hash:
            return LedgerVerification(
                "rejected_payload_hash_mismatch",
                previous_prefix,
                tuple(line_statuses),
                len(records),
            )

        expected_record_hash = record_hash(
            record,
            ledger_profile_epoch=str(record.get("ledger_profile_epoch", LEDGER_PROFILE_EPOCH)),
            schema_epoch=str(record.get("schema_epoch", "")),
            record_type=str(record.get("record_type", "")),
        )
        if record.get("canonical_record_hash") != expected_record_hash:
            return LedgerVerification(
                "rejected_canonical_hash_mismatch",
                previous_prefix,
                tuple(line_statuses),
                len(records),
            )

        if record.get("prev_integrity_hash") != previous_integrity:
            return LedgerVerification(
                "quarantined_hash_chain_mismatch",
                previous_prefix,
                tuple(line_statuses),
                len(records),
            )

        expected_integrity = integrity_hash(previous_integrity, expected_record_hash)
        if record.get("integrity_hash") != expected_integrity:
            return LedgerVerification(
                "quarantined_hash_chain_mismatch",
                previous_prefix,
                tuple(line_statuses),
                len(records),
            )

        expected_prefix = prefix_hash(previous_prefix, expected_integrity)
        if record.get("ledger_prefix_hash") != expected_prefix:
            return LedgerVerification(
                "quarantined_hash_chain_mismatch",
                previous_prefix,
                tuple(line_statuses),
                len(records),
            )

        duplicate_status = _duplicate_status(record, seen)
        line_statuses.append(LineStatus(append_index, event_id, duplicate_status))
        if duplicate_status in {"rejected_duplicate_policy", "quarantined_duplicate"}:
            if duplicate_status == "quarantined_duplicate":
                return LedgerVerification(
                    "quarantined_duplicate",
                    expected_prefix,
                    tuple(line_statuses),
                    len(records),
                )
        else:
            seen[event_id] = duplicate_identity_hash(record)

        previous_integrity = expected_integrity
        previous_prefix = expected_prefix

    return LedgerVerification(VALID_STATUS, previous_prefix, tuple(line_statuses), len(records))


def _schema_status(record: dict[str, Any]) -> str:
    record_type = str(record.get("record_type", ""))
    expected_schema = KNOWN_SCHEMA_EPOCHS.get(record_type)
    if expected_schema is None:
        return "rejected_schema_epoch_missing"
    if record.get("schema_epoch") != expected_schema:
        return "rejected_schema_migration_invalid"
    if record_type == "schema_migration_record":
        fixture_results = record.get("fixture_results", [])
        if not isinstance(fixture_results, list) or not fixture_results:
            return "rejected_schema_migration_invalid"
        if any(item.get("status") != "passed" for item in fixture_results if isinstance(item, dict)):
            return "rejected_schema_migration_invalid"
    if record.get("ledger_profile") != LEDGER_PROFILE:
        return "quarantined_unknown_genesis"
    if record.get("ledger_profile_epoch") != LEDGER_PROFILE_EPOCH:
        return "quarantined_unknown_genesis"
    return VALID_STATUS


def _duplicate_status(record: dict[str, Any], seen: dict[str, str]) -> str:
    event_id = str(record.get("event_id"))
    if event_id not in seen:
        return VALID_STATUS
    policy = str(record.get("duplicate_policy", "reject_duplicate"))
    identity_hash = duplicate_identity_hash(record)
    if policy == "idempotent_same_hash" and seen[event_id] == identity_hash:
        return VALID_STATUS
    if policy == "supersede_by_record" and record.get("supersedes_event_ids"):
        return VALID_STATUS
    if policy == "quarantine_duplicate":
        return "quarantined_duplicate"
    return "rejected_duplicate_policy"


def verify_jsonl(path: Path) -> LedgerVerification:
    return verify_records(read_jsonl(path))
