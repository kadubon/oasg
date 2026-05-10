"""Shared OASG v1.0 constants."""

from __future__ import annotations

THEORY_VERSION = "1.0"
CONFORMANCE_PROFILE = "OASG-REF-v1.0"
LEDGER_PROFILE = "OASG-LEDGER-1"
LEDGER_PROFILE_EPOCH = "OASG-LEDGER-1:2026-05-08"
CANONICAL_PROFILE = "OASG-CJ-1"

DOMAIN_RECORD = "OASG:v1.0:record"
DOMAIN_INTEGRITY = "OASG:v1.0:integrity"
DOMAIN_PREFIX = "OASG:v1.0:prefix"
DOMAIN_GENESIS = "OASG:v1.0:genesis"
DOMAIN_RECEIPT = "OASG:v1.0:receipt"
DOMAIN_PAYLOAD = "OASG:v1.0:payload"
DOMAIN_DUPLICATE_IDENTITY = "OASG:v1.0:duplicate_identity"

GRADES = ("blocked", "critical", "degraded", "acceptable", "surplus")
GRADE_RANK = {grade: rank for rank, grade in enumerate(GRADES)}

REQUIRED_DIMENSIONS = (
    "budget",
    "queue",
    "evidence",
    "replay",
    "rollback",
    "incident",
    "authority",
    "maintenance",
    "comparison",
    "boundary",
    "trusted_base",
    "taint",
)

ACTION_CLASSES = (
    "pure_read",
    "local_reversible",
    "validate_artifact",
    "close_obligation",
    "replay_artifact",
    "rollback_local_effect",
    "emit_claim",
    "promote_workflow",
)

MAX_ACTION_CLASSES = 8
MAX_TRACE_CLASSES = 73

ALLOWED_EFFECT_CLASSES = ("pure", "simulated", "local_reversible")

KNOWN_SCHEMA_EPOCHS = {
    "event_record": "oasg.event_record.v1",
    "schema_migration_record": "oasg.schema_migration_record.v1",
}

TAINT_LEVELS = ("public", "internal", "confidential", "secret", "unknown_secret")

REQUIRED_WITNESS_RECEIPTS = {
    "KLB_2": ("klb_receipt", "comparison_contract", "workload_manifest"),
    "dimension": ("proof_obligation_receipt", "comparison_contract", "workload_manifest"),
    "protected_debt": ("protected_debt_record", "comparison_contract", "workload_manifest"),
}

NON_POSITIVE_STATUSES = {
    "missing",
    "stale",
    "rejected",
    "conflicted",
    "untrusted",
    "overflowed",
    "taint_unknown",
    "prefix_invalid",
    "unbridged",
}


def grade_min(left: str, right: str) -> str:
    """Return the worse grade."""

    return left if GRADE_RANK[left] <= GRADE_RANK[right] else right


def grade_max(left: str, right: str) -> str:
    """Return the better grade."""

    return left if GRADE_RANK[left] >= GRADE_RANK[right] else right


def not_worse(candidate: str, baseline: str) -> bool:
    """Return whether candidate is at least as good as baseline."""

    return GRADE_RANK[candidate] >= GRADE_RANK[baseline]


def strictly_better(candidate: str, baseline: str) -> bool:
    """Return whether candidate is strictly better than baseline."""

    return GRADE_RANK[candidate] > GRADE_RANK[baseline]


def require_grade(value: str) -> str:
    """Validate and return a finite-chain grade."""

    if value not in GRADE_RANK:
        raise ValueError(f"unknown OASG grade: {value!r}")
    return value
