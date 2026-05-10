"""Small verification helpers for local OASG experiments."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from oasg.canonical import receipt_hash
from oasg.io import read_json
from oasg.ledger import verify_jsonl


def verify_longrun_run(run_dir: Path) -> dict[str, Any]:
    """Return deterministic integrity and readiness receipts for a longrun run."""

    replicate_dirs = _replicate_dirs(run_dir)
    if replicate_dirs:
        receipts = [verify_longrun_run(path) for path in replicate_dirs]
        status = (
            "ok"
            if all(str(item.get("status")) == "ok" for item in receipts)
            else "ledger_integrity_failed"
        )
        diagnostic = diagnose_promotion(run_dir)
        return {
            "receipt_type": "longrun_verification_receipt",
            "status": status,
            "run_dir": str(run_dir),
            "replicate_count": len(receipts),
            "replicate_receipt_hashes": [receipt_hash(item) for item in receipts],
            "adaptive_readiness": diagnostic["adaptive_readiness"],
            "diagnostic_hash": receipt_hash(diagnostic),
        }

    conditions = ("baseline_fixed", "oasg_observe_only", "oasg_adaptive")
    ledgers = {
        condition: _compact_ledger_receipt(verify_jsonl(run_dir / condition / "history.jsonl").to_dict())
        if (run_dir / condition / "history.jsonl").exists()
        else {"status": "missing"}
        for condition in conditions
    }
    diagnostic = diagnose_promotion(run_dir)
    status = (
        "ok"
        if all(str(item.get("status")) == "ledger_prefix_valid" for item in ledgers.values())
        else "ledger_integrity_failed"
    )
    return {
        "receipt_type": "longrun_verification_receipt",
        "status": status,
        "run_dir": str(run_dir),
        "ledger_receipts": ledgers,
        "adaptive_readiness": diagnostic["adaptive_readiness"],
        "diagnostic_hash": receipt_hash(diagnostic),
    }


def diagnose_promotion(run_dir: Path) -> dict[str, Any]:
    """Summarize why an adaptive run did or did not activate policy changes."""

    replicate_dirs = _replicate_dirs(run_dir)
    if replicate_dirs:
        diagnostics = [diagnose_promotion(path) for path in replicate_dirs]
        active_count = sum(
            int(item["adaptive_readiness"].get("active_promotion_count", 0))
            for item in diagnostics
        )
        active_ids = sorted(
            {
                str(mutation_id)
                for item in diagnostics
                for mutation_id in item["adaptive_readiness"].get("active_mutation_ids_used", [])
            }
        )
        readiness = {
            "receipt_type": "adaptive_readiness_receipt",
            "status": "active_policy_ready" if active_count and active_ids else "no_active_policy",
            "active_promotion_count": active_count,
            "active_mutation_ids_used": active_ids,
        }
        first_rejection = next(
            (
                item.get("first_rejected_candidate")
                for item in diagnostics
                if item.get("first_rejected_candidate") is not None
            ),
            None,
        )
        return {
            "receipt_type": "promotion_diagnostic_receipt",
            "status": "ok",
            "run_dir": str(run_dir),
            "replicate_count": len(diagnostics),
            "adaptive_readiness": readiness,
            "active_promotions": [
                receipt
                for item in diagnostics
                for receipt in item.get("active_promotions", [])
            ],
            "first_rejected_candidate": first_rejection,
            "rejected_or_inconclusive_count": sum(
                int(item.get("rejected_or_inconclusive_count", 0)) for item in diagnostics
            ),
            "rejected_or_inconclusive_status_counts": _merge_status_counts(
                [
                    item.get("rejected_or_inconclusive_status_counts", {})
                    for item in diagnostics
                ]
            ),
        }

    adaptive_dir = run_dir / "oasg_adaptive"
    active_receipts: list[dict[str, Any]] = []
    rejected_receipts: list[dict[str, Any]] = []
    for path in sorted(adaptive_dir.rglob("*.json")) if adaptive_dir.exists() else []:
        data = _read_json_dict(path)
        if not data:
            continue
        status = str(data.get("status", "unknown"))
        receipt_type = str(data.get("receipt_type", ""))
        item = {
            "path": str(path),
            "receipt_type": receipt_type,
            "status": status,
            "rejected_reasons": data.get("rejected_reasons", []),
        }
        if receipt_type == "active_promotion_receipt" and status == "active_promoted":
            active_receipts.append(item)
        elif _is_rejected_or_inconclusive(status):
            rejected_receipts.append(item)

    active_mutation_ids = sorted(_active_mutation_ids_from_results(adaptive_dir / "task_results.json"))
    readiness = {
        "receipt_type": "adaptive_readiness_receipt",
        "status": "active_policy_ready"
        if active_receipts and active_mutation_ids
        else "no_active_policy",
        "active_promotion_count": len(active_receipts),
        "active_mutation_ids_used": active_mutation_ids,
    }
    first_rejection = rejected_receipts[0] if rejected_receipts else None
    return {
        "receipt_type": "promotion_diagnostic_receipt",
        "status": "ok",
        "run_dir": str(run_dir),
        "adaptive_readiness": readiness,
        "active_promotions": active_receipts,
        "first_rejected_candidate": first_rejection,
        "rejected_or_inconclusive_count": len(rejected_receipts),
        "rejected_or_inconclusive_status_counts": _status_counts(rejected_receipts),
    }


def _read_json_dict(path: Path) -> dict[str, Any] | None:
    try:
        data = read_json(path)
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _compact_ledger_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    return {
        "receipt_type": receipt.get("receipt_type", "ledger_integrity_receipt"),
        "status": receipt.get("status", "unknown"),
        "ledger_prefix_hash": receipt.get("ledger_prefix_hash"),
        "records_seen": receipt.get("records_seen", 0),
    }


def _active_mutation_ids_from_results(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        rows = read_json(path)
    except (OSError, json.JSONDecodeError, ValueError):
        return set()
    if not isinstance(rows, list):
        return set()
    mutation_ids: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        for mutation_id in row.get("active_mutation_ids", []):
            mutation_ids.add(str(mutation_id))
    return mutation_ids


def _is_rejected_or_inconclusive(status: str) -> bool:
    return (
        status.startswith("rejected")
        or status.endswith("rejected")
        or status.startswith("inconclusive")
        or status
        in {
            "no_valid_candidate",
            "no_active_policy",
            "trial_rejected",
            "shadow_rejected",
            "lease_rejected_cap_exceeded",
            "workload_rejected",
        }
    )


def _status_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        status = str(item.get("status", "unknown"))
        counts[status] = counts.get(status, 0) + 1
    return counts


def _replicate_dirs(run_dir: Path) -> list[Path]:
    manifest = _read_json_dict(run_dir / "replicates.json")
    if not manifest:
        return []
    dirs: list[Path] = []
    for item in manifest.get("replicates", []):
        if not isinstance(item, dict):
            continue
        path = Path(str(item.get("run_dir", "")))
        if not path.is_absolute():
            path = run_dir / path
        if path.exists():
            dirs.append(path)
    return dirs


def _merge_status_counts(items: list[Any]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        for status, count in item.items():
            merged[str(status)] = merged.get(str(status), 0) + int(count)
    return merged


__all__ = ["diagnose_promotion", "verify_longrun_run"]
