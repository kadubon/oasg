"""Typed event payload helpers for OASG ledgers."""

from __future__ import annotations

from typing import Any

from oasg.constants import ACTION_CLASSES, REQUIRED_DIMENSIONS


def observation_payload(
    *,
    dimensions: dict[str, str] | None = None,
    action_grades: dict[str, str] | None = None,
    protected_debt: dict[str, str] | None = None,
    policy: dict[str, Any] | None = None,
    proof_obligation_receipts: list[dict[str, Any]] | None = None,
    repair_receipts: list[dict[str, Any]] | None = None,
    positive_evidence: list[dict[str, str]] | None = None,
    model_event: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "payload_type": "observation",
        "dimensions": dimensions or {dimension: "blocked" for dimension in REQUIRED_DIMENSIONS},
        "action_grades": action_grades or {action: "blocked" for action in ACTION_CLASSES},
        "protected_debt": protected_debt
        or {dimension: "blocked" for dimension in REQUIRED_DIMENSIONS},
        "proof_obligation_receipts": proof_obligation_receipts or [],
        "repair_receipts": repair_receipts or [],
        "positive_evidence": positive_evidence or [],
        "policy": policy
        or {
            "effect_classes": ["pure"],
            "semantic_scope": "none",
            "claim_emitting": False,
            "taint_level": "public",
            "boundary_status": "valid",
            "trusted_base_status": "valid",
            "workflow_promotion_authorized": False,
        },
        "model_event": model_event,
    }


def event_record(
    *,
    event_id: str,
    workflow_id: str,
    component_id: str,
    event_type: str,
    payload: dict[str, Any],
    collector_id: str = "local",
    coverage_scope: str = "default",
    authority_scope: str = "local",
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "collector_id": collector_id,
        "workflow_id": workflow_id,
        "component_id": component_id,
        "event_type": event_type,
        "payload": payload,
        "coverage_scope": coverage_scope,
        "authority_scope": authority_scope,
    }
