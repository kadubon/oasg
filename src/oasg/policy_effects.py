"""Demo-only deterministic workflow-policy effect semantics for local OASG trials.

The production optimizer must use runner-produced trial ledgers.  This module is
kept for quickstart and conformance smoke tests under the explicit
``demo-replay`` runner; receipts produced here are not eligible for active
promotion.
"""

from __future__ import annotations

from dataclasses import dataclass
from oasg.canonical import domain_hash, receipt_hash
from oasg.constants import grade_max
from oasg.events import event_record, observation_payload
from oasg.ledger import seal_records
from oasg.policy import PolicyProfile
from oasg.policy_state import MutationPatch, WorkflowPolicyState
from oasg.reducers.core import ReducerSnapshot


@dataclass(frozen=True)
class PolicyEffectResult:
    status: str
    records: list[dict[str, object]]
    reason: str | None = None


def simulate_policy_trial_records(
    *,
    mutation: dict[str, object],
    candidate_seed: ReducerSnapshot,
    policy: PolicyProfile,
    runner_type: str,
) -> PolicyEffectResult:
    """Execute a supported policy patch against an observable snapshot.

    The resulting records may contain proof receipts and positive evidence, but
    those receipts are derived from the patch operation's executable effect rule
    and the resulting policy hash.  The mutation's declared coordinate is only
    used as a consistency check; it is not sufficient to create evidence.
    """

    patch_raw = mutation.get("patch")
    if not isinstance(patch_raw, dict):
        return _rejected(
            mutation=mutation,
            candidate_seed=candidate_seed,
            reason="missing_policy_patch",
            runner_type=runner_type,
        )
    patch = MutationPatch.from_dict(patch_raw)
    if patch.op == "set_action_grade":
        return _rejected(
            mutation=mutation,
            candidate_seed=candidate_seed,
            reason="manual_action_grade_patch_not_trial_executable",
            runner_type=runner_type,
        )
    try:
        starting_state = WorkflowPolicyState(
            state_id="trial_seed",
            policy_profile=policy.to_dict(),
        )
        resulting_state = starting_state.apply_patch(patch)
    except (KeyError, ValueError, TypeError) as exc:
        return _rejected(
            mutation=mutation,
            candidate_seed=candidate_seed,
            reason=f"policy_patch_rejected:{exc}",
            runner_type=runner_type,
        )

    coordinate = _coordinate_for_patch(patch, policy)
    raw_declared = mutation.get("declared_improvement_coordinates", [])
    declared = {str(item) for item in raw_declared} if isinstance(raw_declared, list) else set()
    if coordinate is None or coordinate not in declared:
        return _rejected(
            mutation=mutation,
            candidate_seed=candidate_seed,
            reason="patch_has_no_declared_executable_coordinate",
            runner_type=runner_type,
        )

    dimensions = dict(candidate_seed.dimensions)
    action_grades = {
        action: candidate_seed.action_grades.get(action, "blocked")
        for action in policy.action_ids
    }
    protected_debt = dict(candidate_seed.protected_debt)
    action_grades[patch.target_action_id] = grade_max(
        action_grades.get(patch.target_action_id, "blocked"),
        "surplus",
    )
    semantic_scope = candidate_seed.semantic_scope
    claim_emitting = candidate_seed.claim_emitting
    if patch.op == "set_semantic_floor":
        semantic_scope = "validator"
        claim_emitting = False

    resulting_policy_hash = receipt_hash(resulting_state.policy_profile)
    evidence_hash = domain_hash(
        "OASG:v1.0:trial_observation",
        str(mutation.get("mutation_id", "unknown")),
        patch.op,
        patch.target_action_id,
        coordinate,
        resulting_policy_hash,
        candidate_seed.ledger_prefix_hash,
        runner_type,
    )
    payload = observation_payload(
        dimensions=dimensions,
        action_grades=action_grades,
        protected_debt=protected_debt,
        proof_obligation_receipts=[
            {
                "receipt_type": "policy_effect_receipt",
                "coordinate": coordinate,
                "status": "receipt_valid",
                "patch_op": patch.op,
                "target_action_id": patch.target_action_id,
                "resulting_policy_hash": resulting_policy_hash,
            }
        ],
        positive_evidence=[{"coordinate": coordinate, "evidence_hash": evidence_hash}],
        policy={
            "effect_classes": ["pure"],
            "semantic_scope": semantic_scope,
            "claim_emitting": claim_emitting,
            "taint_level": candidate_seed.taint_level,
            "boundary_status": candidate_seed.boundary_status,
            "trusted_base_status": candidate_seed.trusted_base_status,
            "workflow_promotion_authorized": False,
        },
        model_event={
            "runner_type": runner_type,
            "trial_mode": "deterministic_policy_effect",
            "source_ledger_prefix_hash": candidate_seed.ledger_prefix_hash,
            "patch_op": patch.op,
            "target_action_id": patch.target_action_id,
        },
    )
    records = seal_records(
        [
            event_record(
                event_id=f"evt_trial_{mutation.get('mutation_id', 'unknown')}",
                workflow_id="trial_workload",
                component_id="workflow_policy",
                event_type="observation",
                payload=payload,
            )
        ]
    )
    return PolicyEffectResult(status="trial_observed", records=records)


def projected_policy_action_grades(
    snapshot: ReducerSnapshot,
    state: WorkflowPolicyState,
) -> dict[str, str]:
    """Project only explicit manual action-grade state into action viability.

    Broad policy surfaces affect executable workflow rules and runner behavior;
    they must not create KLB improvement by projection alone.
    """

    action_grades = dict(snapshot.action_grades)
    for action, grade in state.action_grades.items():
        action_grades[action] = grade
    for action in state.retired_actions:
        action_grades[action] = "blocked"
    return action_grades


def _coordinate_for_patch(patch: MutationPatch, policy: PolicyProfile) -> str | None:
    try:
        action = policy.action(patch.target_action_id)
    except KeyError:
        return None
    if action.requires_workflow_promotion_authority:
        return None
    if action.effect_class not in {"pure", "simulated", "local_reversible"}:
        return None
    if patch.op == "adjust_charge":
        if not isinstance(patch.value, dict):
            return None
        if str(patch.value.get("mode", "remove")) != "remove":
            return None
        if str(patch.value.get("dimension", "")) not in action.charges:
            return None
    elif patch.op == "set_lease_cap":
        if isinstance(patch.value, dict) and int(patch.value.get("max_external_effects", 0)) != 0:
            return None
    elif patch.op == "retire_action":
        return None
    elif patch.op not in {
        "remove_requirement",
        "set_retry_policy",
        "set_validator_policy",
        "set_semantic_floor",
        "set_routing_policy",
        "set_decomposition_depth",
        "set_context_compression",
        "set_rollback_requirement",
    }:
        return None
    return f"KLB_2.{patch.target_action_id}"


def _rejected(
    *,
    mutation: dict[str, object],
    candidate_seed: ReducerSnapshot,
    reason: str,
    runner_type: str,
) -> PolicyEffectResult:
    payload = observation_payload(
        dimensions=candidate_seed.dimensions,
        action_grades=candidate_seed.action_grades,
        protected_debt={**candidate_seed.protected_debt, "comparison": "critical"},
        policy={
            "effect_classes": ["pure"],
            "semantic_scope": "none",
            "claim_emitting": False,
            "taint_level": "public",
            "boundary_status": "valid",
            "trusted_base_status": "valid",
            "workflow_promotion_authorized": False,
        },
        model_event={"runner_type": runner_type, "rejection_reason": reason},
    )
    return PolicyEffectResult(
        status="trial_rejected",
        reason=reason,
        records=seal_records(
            [
                event_record(
                    event_id=f"evt_trial_rejected_{mutation.get('mutation_id', 'unknown')}",
                    workflow_id="trial_workload",
                    component_id="workflow_policy",
                    event_type="observation",
                    payload=payload,
                )
            ]
        ),
    )


__all__ = [
    "PolicyEffectResult",
    "projected_policy_action_grades",
    "simulate_policy_trial_records",
]
