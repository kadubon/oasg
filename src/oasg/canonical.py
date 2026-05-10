"""OASG-CJ-1 canonical JSON and SHA-256 domain hashing."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from oasg.constants import (
    CANONICAL_PROFILE,
    DOMAIN_GENESIS,
    DOMAIN_INTEGRITY,
    DOMAIN_DUPLICATE_IDENTITY,
    DOMAIN_PAYLOAD,
    DOMAIN_PREFIX,
    DOMAIN_RECEIPT,
    DOMAIN_RECORD,
)


HashPart = bytes | str


def _reject_non_canonical_numbers(value: Any) -> None:
    if isinstance(value, float):
        raise TypeError("OASG-CJ-1 hash-critical JSON does not allow floats")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("OASG-CJ-1 JSON object keys must be strings")
            _reject_non_canonical_numbers(item)
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for item in value:
            _reject_non_canonical_numbers(item)


def canonical_json_dumps(value: Any) -> str:
    """Return OASG-CJ-1 canonical JSON text."""

    _reject_non_canonical_numbers(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_json_bytes(value: Any) -> bytes:
    """Return OASG-CJ-1 canonical UTF-8 bytes without a terminal newline."""

    return canonical_json_dumps(value).encode("utf-8")


def _part_bytes(part: HashPart) -> bytes:
    return part if isinstance(part, bytes) else part.encode("utf-8")


def framed_bytes(parts: Iterable[HashPart]) -> bytes:
    """Return length-framed bytes for unambiguous cross-language hashing."""

    chunks: list[bytes] = []
    for part in parts:
        raw = _part_bytes(part)
        chunks.append(str(len(raw)).encode("ascii"))
        chunks.append(b":")
        chunks.append(raw)
        chunks.append(b";")
    return b"".join(chunks)


def domain_hash(domain: str, *parts: HashPart) -> str:
    """Return a prefixed SHA-256 hash over a domain and framed parts."""

    digest = hashlib.sha256(framed_bytes((domain, *parts))).hexdigest()
    return f"sha256:{digest}"


def genesis_hash(ledger_profile_epoch: str) -> str:
    return domain_hash(DOMAIN_GENESIS, ledger_profile_epoch)


def record_hash(
    record: Mapping[str, Any],
    *,
    ledger_profile_epoch: str,
    schema_epoch: str,
    record_type: str,
) -> str:
    redacted = {
        key: value
        for key, value in record.items()
        if key not in {"canonical_record_hash", "integrity_hash", "ledger_prefix_hash"}
    }
    return domain_hash(
        DOMAIN_RECORD,
        ledger_profile_epoch,
        schema_epoch,
        record_type,
        canonical_json_bytes(redacted),
    )


def payload_hash(payload: Any) -> str:
    return domain_hash(DOMAIN_PAYLOAD, canonical_json_bytes(payload))


def duplicate_identity_hash(record: Mapping[str, Any]) -> str:
    redacted = {
        key: value
        for key, value in record.items()
        if key
        not in {
            "append_index",
            "prev_integrity_hash",
            "canonical_record_hash",
            "integrity_hash",
            "ledger_prefix_hash",
        }
    }
    return domain_hash(DOMAIN_DUPLICATE_IDENTITY, canonical_json_bytes(redacted))


def integrity_hash(prev_integrity_hash: str, canonical_record_hash: str) -> str:
    return domain_hash(DOMAIN_INTEGRITY, prev_integrity_hash, canonical_record_hash)


def prefix_hash(previous_prefix_hash: str, current_integrity_hash: str) -> str:
    return domain_hash(DOMAIN_PREFIX, previous_prefix_hash, current_integrity_hash)


def receipt_hash(receipt: Mapping[str, Any]) -> str:
    return domain_hash(DOMAIN_RECEIPT, canonical_json_bytes(receipt))


__all__ = [
    "CANONICAL_PROFILE",
    "canonical_json_bytes",
    "canonical_json_dumps",
    "domain_hash",
    "duplicate_identity_hash",
    "framed_bytes",
    "genesis_hash",
    "integrity_hash",
    "payload_hash",
    "prefix_hash",
    "receipt_hash",
    "record_hash",
]
