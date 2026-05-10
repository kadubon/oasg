"""Pydantic models for first-wave OASG v1.0 artifacts."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

HashStr = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
Grade = Literal["blocked", "critical", "degraded", "acceptable", "surplus"]
EffectClass = Literal[
    "pure",
    "simulated",
    "local_reversible",
    "local_irreversible",
    "network",
    "financial",
    "communication",
    "workflow_promotion",
    "secret_touching",
]
GateStatus = Literal[
    "safe_non_regression",
    "safe_promotion",
    "rejected_contaminated_comparison",
    "rejected_ledger_integrity",
    "inconclusive_klb_overflow",
    "rejected_effect_policy",
    "rejected_viability_regression",
    "rejected_floor_violation",
    "rejected_no_concrete_positive_evidence",
    "rejected_semantic_floor_missing",
    "rejected_secret_taint",
    "rejected_boundary",
    "rejected_trusted_base",
]
MutationState = Literal[
    "proposed",
    "shadowed",
    "leased",
    "safe_non_regression",
    "safe_promotion",
    "active_promoted",
    "rejected",
    "inconclusive",
    "quarantined",
    "retired",
]


class ExtensibleModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EventRecord(ExtensibleModel):
    record_type: Literal["event_record"] = "event_record"
    event_id: str
    append_index: int
    event_time: str | None = None
    collector_id: str = "local"
    ledger_profile: Literal["OASG-LEDGER-1"] = "OASG-LEDGER-1"
    ledger_profile_epoch: Literal["OASG-LEDGER-1:2026-05-08"] = "OASG-LEDGER-1:2026-05-08"
    schema_epoch: Literal["oasg.event_record.v1"] = "oasg.event_record.v1"
    policy_epoch: str = "oasg.policy.v1.0"
    workflow_id: str = "default"
    component_id: str = "unknown"
    parent_event_ids: list[str] = Field(default_factory=list)
    event_type: str = "observation"
    payload_hash: HashStr
    payload_pointer: str | None = None
    prev_integrity_hash: HashStr
    canonical_record_hash: HashStr
    integrity_hash: HashStr
    ledger_prefix_hash: HashStr
    coverage_scope: str = "default"
    authority_scope: str = "local"
    rejection_status: str | None = None
    supersedes_event_ids: list[str] = Field(default_factory=list)
    duplicate_policy: str = "reject_duplicate"
    payload: dict[str, Any] = Field(default_factory=dict)


class LedgerIntegrityReceipt(ExtensibleModel):
    receipt_type: Literal["ledger_integrity_receipt"] = "ledger_integrity_receipt"
    status: str
    ledger_prefix_hash: HashStr
    records_seen: int
    line_statuses: list[dict[str, Any]] = Field(default_factory=list)


class SchemaMigrationRecord(ExtensibleModel):
    record_type: Literal["schema_migration_record"] = "schema_migration_record"
    migration_id: str
    from_schema_epoch: str
    to_schema_epoch: str
    affected_record_types: list[str]
    migration_map: dict[str, Any]
    fixture_results: list[dict[str, Any]] = Field(default_factory=list)


class RejectionRecord(ExtensibleModel):
    record_type: str = "rejection_record"
    rejected_event_id: str
    reason_code: str
    affected_scope: str


class CoverageCertificate(ExtensibleModel):
    record_type: str = "coverage_certificate"
    coverage_id: str
    scope: str
    append_interval: tuple[int, int]
    collector_ids: list[str]
    observed_event_types: list[str]
    missingness_policy: str = "inconclusive"


class ReducerSnapshot(ExtensibleModel):
    artifact_type: Literal["reducer_snapshot"] = "reducer_snapshot"
    ledger_status: str
    ledger_prefix_hash: HashStr
    dimensions: dict[str, Grade]
    action_grades: dict[str, Grade]
    protected_debt: dict[str, Grade]
    positive_evidence: dict[str, list[str]]
    records_seen: int
    effect_classes: list[EffectClass] = Field(default_factory=list)
    semantic_scope: str = "none"
    claim_emitting: bool = False
    taint_level: Literal["public", "internal", "confidential", "secret", "unknown_secret"] = "public"
    boundary_status: str = "valid"
    trusted_base_status: str = "valid"
    workflow_promotion_authorized: bool = False


class ProofObligationReceipt(ExtensibleModel):
    receipt_type: str = "proof_obligation_receipt"
    obligation_id: str
    dimension_id: str
    status: Literal["receipt_valid", "receipt_rejected", "quarantine_dimension"]
    fixture_categories: list[str] = Field(default_factory=list)
    failure_status: str = "quarantine_dimension"
    evidence_hashes: list[str] = Field(default_factory=list)


class ProtectedDebtRecord(ExtensibleModel):
    record_type: str = "protected_debt_record"
    debt_id: str
    coordinate_id: str
    grade: Grade
    scope: str = "default"
    source_event_ids: list[str] = Field(default_factory=list)
    repair_receipt_hashes: list[str] = Field(default_factory=list)


class ObligationRecord(ExtensibleModel):
    record_type: str = "obligation_record"
    obligation_id: str
    state: Literal["created", "reserved", "closed", "expired", "held", "cancelled"]
    scope: str = "default"
    hard: bool = True
    created_by_event_id: str | None = None
    closed_by_event_id: str | None = None


class AbstractActionClass(ExtensibleModel):
    record_type: str = "abstract_action_class"
    action_class_id: str
    required_min_grade: Grade = "acceptable"
    effect_class: EffectClass = "pure"
    claim_emitting: bool = False
    semantic_scope: str = "none"
    authority_labels: list[str] = Field(default_factory=list)


class AbstractTraceReceipt(ExtensibleModel):
    receipt_type: str = "abstract_trace_receipt"
    trace_id: str
    action_class_ids: list[str]
    status: Literal["trace_viable", "trace_infeasible", "trace_inconclusive"]
    resulting_grades: dict[str, Grade] = Field(default_factory=dict)
    taint_grade: Grade = "blocked"


class KLBReceipt(ExtensibleModel):
    receipt_type: Literal["klb_receipt"] = "klb_receipt"
    status: Literal["ok", "inconclusive_klb_overflow"]
    horizon: int
    trace_count: int
    max_trace_classes: int
    action_order: list[str]
    klb: dict[str, Grade]
    ledger_prefix_hash: HashStr
    viable_trace_count: dict[str, int] = Field(default_factory=dict)
    abstract_trace_receipts: list[AbstractTraceReceipt] = Field(default_factory=list)


class PositiveEvidenceWitness(ExtensibleModel):
    receipt_type: Literal["positive_evidence_witness"] = "positive_evidence_witness"
    witness_id: str
    coordinate_id: str
    evidence_hashes: list[HashStr]
    required_receipt_types: list[str] = Field(default_factory=list)
    status: Literal["witness_valid"] = "witness_valid"
    ledger_prefix_hash: HashStr
    comparison_contract_hash: HashStr
    workload_manifest_hash: HashStr
    klb_receipt_hash: HashStr | None = None


class WorkloadManifest(ExtensibleModel):
    workload_id: str
    canonical_input_order: list[str] = Field(default_factory=list)
    input_hashes: list[HashStr] = Field(default_factory=list)
    baseline_snapshot_hash: HashStr | None = None
    candidate_snapshot_hash: HashStr | None = None
    replay_pairing_rule: Literal["same_input_hash"] = "same_input_hash"
    nondeterminism_seed_policy: Literal["fixed"] = "fixed"
    allowed_nondeterminism: Literal["none"] = "none"
    contamination_policy: Literal["reject"] = "reject"
    mismatch_status_policy: Literal["reject"] = "reject"
    ledger_prefix_hashes: list[HashStr] = Field(default_factory=list)


class PolicyActionRecord(ExtensibleModel):
    action_id: str
    requirements: list[str] = Field(default_factory=list)
    charges: list[str] = Field(default_factory=list)
    effect_class: EffectClass = "pure"
    claim_emitting: bool = False
    requires_semantic_floor: bool = False
    blocks_secret_taint: bool = False
    requires_workflow_promotion_authority: bool = False


class PolicyProfileRecord(ExtensibleModel):
    profile_id: str
    horizon: Literal[2] = 2
    max_trace_classes: int = Field(default=73, ge=0, le=73)
    actions: list[PolicyActionRecord] = Field(min_length=1, max_length=8)


class ComparisonContract(ExtensibleModel):
    comparison_contract_id: str
    workload_manifest_id: str
    baseline_workflow_id: str = "baseline"
    candidate_mutation_id: str = "candidate"
    epsilon_by_dimension: dict[str, int] = Field(default_factory=dict)
    promotion_requested: bool = False
    allow_workflow_promotion: bool = False


class MutationRecord(ExtensibleModel):
    record_type: Literal["mutation_record"] = "mutation_record"
    mutation_id: str
    target_component_id: str
    state: MutationState = "proposed"
    declared_improvement_coordinates: list[str] = Field(default_factory=list)
    effect_class: EffectClass = "pure"
    lease_caps: dict[str, int] = Field(default_factory=dict)
    patch: "MutationPatchRecord | None" = None


class ShadowReceipt(ExtensibleModel):
    receipt_type: Literal["shadow_receipt"] = "shadow_receipt"
    mutation_id: str
    status: Literal["shadow_passed", "shadow_rejected"]
    ledger_prefix_hash: HashStr
    observed_coordinates: dict[str, Grade] = Field(default_factory=dict)
    replayed_event_count: int = 0
    runner_type: str = "ledger-replay"
    workload_id: str = "candidate_replay"
    input_hashes: list[HashStr] = Field(default_factory=list)
    execution_receipt_hash: HashStr | None = None
    trial_ledger_path: str | None = None
    trial_ledger_prefix_hash: HashStr | None = None
    trial_reducer_snapshot_hash: HashStr | None = None


class LeaseReceipt(ExtensibleModel):
    receipt_type: Literal["lease_receipt"] = "lease_receipt"
    mutation_id: str
    status: Literal["lease_passed", "lease_rejected_cap_exceeded", "lease_rejected_effect"]
    ledger_prefix_hash: HashStr
    max_events: int = 0
    effect_counts: dict[str, int] = Field(default_factory=dict)
    executed_event_count: int = 0
    rollback_available: bool = True
    resources: dict[str, int] = Field(default_factory=dict)
    runner_type: str = "ledger-replay"
    workload_id: str = "candidate_replay"
    input_hashes: list[HashStr] = Field(default_factory=list)
    execution_receipt_hash: HashStr | None = None
    trial_ledger_path: str | None = None
    trial_ledger_prefix_hash: HashStr | None = None
    trial_reducer_snapshot_hash: HashStr | None = None


class EffectCounts(ExtensibleModel):
    pure: int = 0
    simulated: int = 0
    local_reversible: int = 0
    local_irreversible: int = 0
    network: int = 0
    financial: int = 0
    communication: int = 0
    workflow_promotion: int = 0
    secret_touching: int = 0
    external: int = 0


class ResourceUsage(ExtensibleModel):
    events: int = 0
    workload_inputs: int = 0
    duration_ms: int = 0
    stdout_bytes: int = 0
    stderr_bytes: int = 0
    return_code: int | None = None


class SchedulerState(ExtensibleModel):
    artifact_type: str = "scheduler_state"
    selected_component_id: str = "workflow_policy"
    selected_coordinates: list[str] = Field(default_factory=list)
    pressure_age: dict[str, int] = Field(default_factory=dict)
    selection_deadline: dict[str, int] = Field(default_factory=dict)
    exploration_debt: dict[str, int] = Field(default_factory=dict)
    starvation_violation: list[str] = Field(default_factory=list)


class PressureVector(ExtensibleModel):
    artifact_type: str = "pressure_vector"
    component_id: str
    coordinates: dict[str, Grade] = Field(default_factory=dict)
    reasons: dict[str, list[str]] = Field(default_factory=dict)
    attribution_receipt_hashes: list[str] = Field(default_factory=list)


class ScopeGraph(ExtensibleModel):
    artifact_type: str = "scope_graph"
    graph_epoch: str
    scopes: list[str] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    negative_edge_evidence: list[dict[str, Any]] = Field(default_factory=list)


class BoundaryCertificate(ExtensibleModel):
    receipt_type: str = "boundary_certificate"
    certificate_id: str
    graph_epoch: str
    source_scope: str
    excluded_scope: str
    status: str
    expires_at_event_index: int | None = None
    evidence_hashes: list[str] = Field(default_factory=list)


class TaintRecord(ExtensibleModel):
    record_type: str = "taint_record"
    taint_id: str
    taint_grade: Grade
    authority_label: str = "public"
    source_event_ids: list[str] = Field(default_factory=list)
    declassification_receipt_hashes: list[str] = Field(default_factory=list)


class SemanticFloorPolicy(ExtensibleModel):
    record_type: str = "semantic_floor_policy"
    policy_id: str
    semantic_scope: Literal["none", "operational_only", "validator", "external_review_required"]
    claim_emitting_allowed: bool = False
    validator_ids: list[str] = Field(default_factory=list)
    calibration_receipt_hashes: list[str] = Field(default_factory=list)


class TrustedBaseBridge(ExtensibleModel):
    receipt_type: str = "trusted_base_bridge"
    bridge_id: str
    from_trusted_base_epoch: str
    to_trusted_base_epoch: str
    migration_preorder: str = "claims_may_degrade_not_improve"
    coordinate_map: dict[str, Any] = Field(default_factory=dict)
    fixture_result_hashes: list[str] = Field(default_factory=list)


class DominanceGateReceipt(ExtensibleModel):
    receipt_type: Literal["dominance_gate_receipt"] = "dominance_gate_receipt"
    status: GateStatus
    baseline_ledger_prefix_hash: HashStr
    candidate_ledger_prefix_hash: HashStr
    improved_coordinates: list[str] = Field(default_factory=list)
    missing_witness_coordinates: list[str] = Field(default_factory=list)
    rejected_reasons: list[str] = Field(default_factory=list)
    positive_evidence_witness_hashes: list[HashStr] = Field(default_factory=list)


class ActivePromotionReceipt(ExtensibleModel):
    receipt_type: Literal["active_promotion_receipt"] = "active_promotion_receipt"
    status: Literal["active_promoted", "rejected_active_promotion"]
    baseline_ledger_prefix_hash: HashStr
    candidate_ledger_prefix_hash: HashStr
    improved_coordinates: list[str] = Field(default_factory=list)
    missing_witness_coordinates: list[str] = Field(default_factory=list)
    rejected_reasons: list[str] = Field(default_factory=list)
    positive_evidence_witness_hashes: list[HashStr] = Field(default_factory=list)
    mutation_id: str | None = None
    shadow_status: str
    lease_status: str
    shadow_runner_type: str = "ledger-replay"
    lease_runner_type: str = "ledger-replay"
    shadow_execution_receipt_hash: HashStr | None = None
    lease_execution_receipt_hash: HashStr | None = None
    shadow_trial_ledger_prefix_hash: HashStr | None = None
    lease_trial_ledger_prefix_hash: HashStr | None = None
    shadow_trial_reducer_snapshot_hash: HashStr | None = None
    lease_trial_reducer_snapshot_hash: HashStr | None = None


class MutatorProfile(ExtensibleModel):
    artifact_type: Literal["mutator_profile"] = "mutator_profile"
    profile_id: str = "OASG-REF-v1.0-mutators"
    enabled_mutators: list[str] = Field(default_factory=list)
    max_candidates: int = Field(default=4, ge=0, le=8)
    per_family_max_candidates: dict[str, int] = Field(default_factory=dict)
    cooldown_iterations: int = Field(default=3, ge=0, le=1000)
    unsafe_surface_allowlist: list[str] = Field(default_factory=list)
    retry_limit: int = Field(default=1, ge=0, le=100)


PatchOp = Literal[
    "set_action_grade",
    "adjust_charge",
    "add_requirement",
    "remove_requirement",
    "set_retry_policy",
    "set_validator_policy",
    "set_lease_cap",
    "set_semantic_floor",
    "retire_action",
    "set_routing_policy",
    "set_decomposition_depth",
    "set_context_compression",
    "set_rollback_requirement",
]


class MutationPatchRecord(ExtensibleModel):
    record_type: Literal["mutation_patch"] = "mutation_patch"
    mutation_id: str
    op: PatchOp
    target_surface: Literal["workflow_policy"] = "workflow_policy"
    target_action_id: str
    coordinate_id: str
    value: str | int | dict[str, Any]
    mutator_id: str
    precondition_policy_hash: HashStr | None = None
    resulting_policy_hash: HashStr | None = None


class MutationProposalRecord(ExtensibleModel):
    mutation_id: str
    coordinate: str
    action_id: str
    to_grade: Grade
    mutator_id: str
    reason: str
    patch: MutationPatchRecord


class MutationBatchRecord(ExtensibleModel):
    receipt_type: Literal["mutation_batch"] = "mutation_batch"
    proposals: list[MutationProposalRecord] = Field(default_factory=list)


class WorkflowPolicyStateRecord(ExtensibleModel):
    artifact_type: Literal["workflow_policy_state"] = "workflow_policy_state"
    state_id: str
    policy_profile: PolicyProfileRecord
    action_grades: dict[str, Grade] = Field(default_factory=dict)
    retry_policy: dict[str, str] = Field(default_factory=dict)
    validator_policy: dict[str, str] = Field(default_factory=dict)
    lease_caps: dict[str, dict[str, int]] = Field(default_factory=dict)
    semantic_policy: dict[str, str] = Field(default_factory=dict)
    routing_policy: dict[str, str] = Field(default_factory=dict)
    decomposition_policy: dict[str, int] = Field(default_factory=dict)
    context_policy: dict[str, str] = Field(default_factory=dict)
    rollback_policy: dict[str, str] = Field(default_factory=dict)
    requirement_policy: dict[str, list[str]] = Field(default_factory=dict)
    retired_actions: list[str] = Field(default_factory=list)


class ActiveMutationRecord(ExtensibleModel):
    mutation_id: str
    target_component_id: str | None = None
    declared_improvement_coordinates: list[str] = Field(default_factory=list)
    patch: MutationPatchRecord
    policy_state_hash: HashStr
    active_receipt_hash: HashStr


class CandidatePathRecord(ExtensibleModel):
    candidate: str | None = None
    mutation: str | None = None
    baseline_snapshot: str | None = None
    candidate_snapshot: str | None = None
    baseline_klb: str | None = None
    candidate_klb: str | None = None
    contract: str | None = None
    workload: str | None = None
    shadow: str | None = None
    lease: str | None = None
    trial_session: str | None = None
    trial_candidate: str | None = None
    trial_receipt: str | None = None
    execution: str | None = None


class QuarantinedLibraryEntry(ExtensibleModel):
    mutation_id: str
    reason: str


class MutationOutcomeRecord(ExtensibleModel):
    record_type: Literal["mutation_outcome_record"] = "mutation_outcome_record"
    mutation_id: str
    patch_hash: HashStr
    mutator_id: str
    status: Literal["accepted", "rejected", "inconclusive", "quarantined", "retired"]
    cooldown_until_iteration: int = 0
    gate_reason: str | None = None
    runner_reason: str | None = None
    receipt_hashes: list[HashStr] = Field(default_factory=list)


class WorkflowLibraryRecord(ExtensibleModel):
    artifact_type: Literal["workflow_library"] = "workflow_library"
    library_id: str
    active_policy_profile: PolicyProfileRecord
    policy_state: WorkflowPolicyStateRecord
    scheduler_state: SchedulerState | None = None
    active_mutations: list[ActiveMutationRecord] = Field(default_factory=list)
    quarantined: list[QuarantinedLibraryEntry] = Field(default_factory=list)
    retired: list[ActiveMutationRecord] = Field(default_factory=list)
    mutation_outcomes: list[MutationOutcomeRecord] = Field(default_factory=list)
    rollback_snapshots: list["RollbackSnapshotRecord"] = Field(default_factory=list)
    rollback_pointer: HashStr | None = None
    active_promotion_receipts: list[HashStr] = Field(default_factory=list)


class OptimizerRunReceipt(ExtensibleModel):
    receipt_type: Literal["optimizer_run_receipt"] = "optimizer_run_receipt"
    status: Literal[
        "active_promoted",
        "no_valid_candidate",
        "no_new_work",
        "checkpointed",
        "library_conflict",
        "stale_optimizer_state",
    ]
    baseline_ledger_prefix_hash: HashStr
    consumed_from_append_index: int = 0
    consumed_to_append_index: int = 0
    optimizer_state_hash: HashStr | None = None
    pressure_vector_hash: HashStr
    scheduler_state_hash: HashStr
    mutation_batch_hash: HashStr
    gate_receipt_hashes: list[HashStr] = Field(default_factory=list)
    active_promotion_receipt_hashes: list[HashStr] = Field(default_factory=list)
    runner_receipt_hashes: list[HashStr] = Field(default_factory=list)
    trial_ledger_prefix_hashes: list[HashStr] = Field(default_factory=list)
    trial_reducer_snapshot_hashes: list[HashStr] = Field(default_factory=list)
    library_hash: HashStr
    candidate_paths: list[CandidatePathRecord] = Field(default_factory=list)
    cycles_completed: int = 1


class TrialSessionRecord(ExtensibleModel):
    artifact_type: Literal["trial_session"] = "trial_session"
    trial_session_id: str
    mutation_id: str
    workload_id: str
    workload_manifest_hash: HashStr
    shadow_receipt_hash: HashStr
    lease_receipt_hash: HashStr
    shadow_trial_ledger_path: str
    lease_trial_ledger_path: str
    shadow_trial_ledger_prefix_hash: HashStr
    lease_trial_ledger_prefix_hash: HashStr
    shadow_trial_reducer_snapshot_hash: HashStr
    lease_trial_reducer_snapshot_hash: HashStr


class TrialBundleRecord(ExtensibleModel):
    artifact_type: Literal["trial_bundle"] = "trial_bundle"
    trial_session: TrialSessionRecord
    workload_execution_receipt_hash: HashStr
    trial_ledger_receipt_hash: HashStr
    shadow_receipt_hash: HashStr
    lease_receipt_hash: HashStr


class HarnessReceipt(ExtensibleModel):
    receipt_type: Literal["harness_receipt"] = "harness_receipt"
    status: Literal["harness_executed", "harness_rejected", "harness_timeout"]
    runner_type: Literal["local-command", "ledger-replay", "demo-replay"]
    workload_id: str
    mutation_id: str
    trial_ledger_path: str | None = None
    trial_ledger_prefix_hash: HashStr | None = None
    stdout_hash: HashStr | None = None
    stderr_hash: HashStr | None = None
    return_code: int | None = None


class PhaseReceipt(ExtensibleModel):
    receipt_type: Literal["phase_receipt"] = "phase_receipt"
    phase: Literal["shadow", "lease"]
    status: Literal["shadow_passed", "shadow_rejected", "lease_passed", "lease_rejected_cap_exceeded"]
    mutation_id: str
    trial_ledger_prefix_hash: HashStr
    receipt_hash: HashStr


class WorkloadExecutionReceipt(ExtensibleModel):
    receipt_type: Literal["workload_execution_receipt"] = "workload_execution_receipt"
    status: Literal["workload_executed", "workload_rejected"]
    runner_type: str
    workload_id: str
    mutation_id: str
    ledger_prefix_hash: HashStr
    executed_event_count: int
    effect_counts: EffectCounts = Field(default_factory=EffectCounts)
    resources: ResourceUsage = Field(default_factory=ResourceUsage)
    rollback_available: bool = True
    observed_coordinates: dict[str, Grade] = Field(default_factory=dict)
    trial_ledger_path: str | None = None
    trial_ledger_prefix_hash: HashStr | None = None
    trial_reducer_snapshot_hash: HashStr | None = None
    timeout_status: Literal["not_timed_out", "timed_out"] = "not_timed_out"
    stdout_hash: HashStr | None = None
    stderr_hash: HashStr | None = None
    return_code: int | None = None


class TrialLedgerReceipt(ExtensibleModel):
    receipt_type: Literal["trial_ledger_receipt"] = "trial_ledger_receipt"
    status: Literal["trial_observed", "trial_rejected"]
    runner_type: str
    workload_id: str
    mutation_id: str
    trial_ledger_path: str
    trial_ledger_prefix_hash: HashStr
    trial_reducer_snapshot_hash: HashStr
    effect_counts: EffectCounts = Field(default_factory=EffectCounts)
    resources: ResourceUsage = Field(default_factory=ResourceUsage)
    stdout_hash: HashStr | None = None
    stderr_hash: HashStr | None = None
    return_code: int | None = None
    timeout_status: Literal["not_timed_out", "timed_out"] = "not_timed_out"


class LedgerAppendReceipt(ExtensibleModel):
    receipt_type: Literal["ledger_append_receipt"] = "ledger_append_receipt"
    status: Literal[
        "appended",
        "append_rejected_invalid_ledger",
        "append_rejected_invalid_continuation",
        "stale_or_forked_ledger_prefix",
    ]
    ledger_path: str
    appended_records: int
    previous_ledger_prefix_hash: HashStr
    new_ledger_prefix_hash: HashStr
    previous_records_seen: int
    new_records_seen: int
    reason: str | None = None


class RunnerOutputReceipt(ExtensibleModel):
    receipt_type: Literal["runner_output_receipt"] = "runner_output_receipt"
    status: Literal["output_accepted", "output_rejected"]
    runner_type: str
    stdout_hash: HashStr | None = None
    stderr_hash: HashStr | None = None
    return_code: int | None = None
    timeout_status: Literal["not_timed_out", "timed_out"] = "not_timed_out"


class PolicyDiffRecord(ExtensibleModel):
    record_type: Literal["policy_diff"] = "policy_diff"
    mutation_id: str
    precondition_policy_hash: HashStr
    resulting_policy_hash: HashStr
    patch_hash: HashStr


class RollbackSnapshotRecord(ExtensibleModel):
    record_type: Literal["rollback_snapshot"] = "rollback_snapshot"
    snapshot_hash: HashStr
    policy_state: WorkflowPolicyStateRecord
    active_policy_profile: PolicyProfileRecord
    scheduler_state: SchedulerState | None = None
    active_mutations: list[ActiveMutationRecord] = Field(default_factory=list)
    active_promotion_receipts: list[HashStr] = Field(default_factory=list)
    rollback_pointer: HashStr | None = None


class OptimizerStateRecord(ExtensibleModel):
    artifact_type: Literal["optimizer_state"] = "optimizer_state"
    run_id: str
    iteration: int = 0
    last_observed_ledger_prefix_hash: HashStr | None = None
    last_append_index: int = 0
    scheduler_state: SchedulerState | None = None
    mutation_outcomes: list[MutationOutcomeRecord] = Field(default_factory=list)
    active_trial_ids: list[str] = Field(default_factory=list)
    quarantined_trial_ids: list[str] = Field(default_factory=list)
    trial_states: list[PendingTrial] = Field(default_factory=list)
    checkpoint_hash: HashStr | None = None
    last_library_hash: HashStr | None = None


class LibraryConflictReceipt(ExtensibleModel):
    receipt_type: Literal["library_conflict_receipt"] = "library_conflict_receipt"
    status: Literal["library_conflict"]
    expected_library_hash: HashStr
    observed_library_hash: HashStr


class LibraryHistoryReceipt(ExtensibleModel):
    receipt_type: Literal["library_history_receipt"] = "library_history_receipt"
    status: Literal["ok"]
    library_hash: HashStr
    active_mutation_count: int
    retired_mutation_count: int
    quarantined_mutation_count: int
    outcome_count: int


class RunnerProfile(ExtensibleModel):
    artifact_type: Literal["runner_profile"] = "runner_profile"
    runner_type: Literal["ledger-replay", "demo-replay", "local-command"] = "ledger-replay"
    command_argv: list[str] = Field(default_factory=list)
    timeout_seconds: int = Field(default=30, ge=1, le=3600)
    cwd: str | None = None
    env_allowlist: dict[str, str] = Field(default_factory=dict)


class RollbackReceipt(ExtensibleModel):
    receipt_type: Literal["rollback_receipt"] = "rollback_receipt"
    status: Literal["rolled_back", "rollback_noop"]
    library_hash: HashStr
    retired_mutation_id: str | None = None


class QuarantineRecord(ExtensibleModel):
    record_type: str = "quarantine_record"
    status: str
    reason: str
    affected_scope: str = "default"


class PendingTrial(ExtensibleModel):
    record_type: Literal["pending_trial"] = "pending_trial"
    trial_id: str
    status: Literal["pending", "shadowed", "leased", "gated", "promoted", "rejected", "quarantined"]
    receipt_hashes: list[HashStr] = Field(default_factory=list)


class SupervisorState(ExtensibleModel):
    artifact_type: Literal["supervisor_state"] = "supervisor_state"
    run_id: str
    lock_status: Literal["unlocked", "locked", "stale_lock_quarantined"] = "unlocked"
    pending_trials: list[PendingTrial] = Field(default_factory=list)
    optimizer_state_hash: HashStr | None = None


def schema_models() -> dict[str, type[BaseModel]]:
    return {
        "event_record": EventRecord,
        "active_mutation_record": ActiveMutationRecord,
        "candidate_path_record": CandidatePathRecord,
        "ledger_integrity_receipt": LedgerIntegrityReceipt,
        "schema_migration_record": SchemaMigrationRecord,
        "rejection_record": RejectionRecord,
        "coverage_certificate": CoverageCertificate,
        "reducer_snapshot": ReducerSnapshot,
        "proof_obligation_receipt": ProofObligationReceipt,
        "protected_debt_record": ProtectedDebtRecord,
        "obligation_record": ObligationRecord,
        "abstract_action_class": AbstractActionClass,
        "abstract_trace_receipt": AbstractTraceReceipt,
        "klb_receipt": KLBReceipt,
        "positive_evidence_witness": PositiveEvidenceWitness,
        "workload_manifest": WorkloadManifest,
        "comparison_contract": ComparisonContract,
        "policy_profile": PolicyProfileRecord,
        "workflow_policy_state": WorkflowPolicyStateRecord,
        "mutation_patch": MutationPatchRecord,
        "mutation_proposal": MutationProposalRecord,
        "mutation_record": MutationRecord,
        "shadow_receipt": ShadowReceipt,
        "lease_receipt": LeaseReceipt,
        "scheduler_state": SchedulerState,
        "pressure_vector": PressureVector,
        "scope_graph": ScopeGraph,
        "boundary_certificate": BoundaryCertificate,
        "taint_record": TaintRecord,
        "semantic_floor_policy": SemanticFloorPolicy,
        "trusted_base_bridge": TrustedBaseBridge,
        "dominance_gate_receipt": DominanceGateReceipt,
        "active_promotion_receipt": ActivePromotionReceipt,
        "mutator_profile": MutatorProfile,
        "mutation_outcome_record": MutationOutcomeRecord,
        "quarantined_library_entry": QuarantinedLibraryEntry,
        "mutation_batch": MutationBatchRecord,
        "workflow_library": WorkflowLibraryRecord,
        "effect_counts": EffectCounts,
        "resource_usage": ResourceUsage,
        "trial_session": TrialSessionRecord,
        "trial_bundle": TrialBundleRecord,
        "harness_receipt": HarnessReceipt,
        "phase_receipt": PhaseReceipt,
        "optimizer_run_receipt": OptimizerRunReceipt,
        "optimizer_state": OptimizerStateRecord,
        "workload_execution_receipt": WorkloadExecutionReceipt,
        "trial_ledger_receipt": TrialLedgerReceipt,
        "ledger_append_receipt": LedgerAppendReceipt,
        "runner_output_receipt": RunnerOutputReceipt,
        "policy_diff": PolicyDiffRecord,
        "rollback_snapshot": RollbackSnapshotRecord,
        "library_conflict_receipt": LibraryConflictReceipt,
        "library_history_receipt": LibraryHistoryReceipt,
        "runner_profile": RunnerProfile,
        "pending_trial": PendingTrial,
        "supervisor_state": SupervisorState,
        "rollback_receipt": RollbackReceipt,
        "quarantine_record": QuarantineRecord,
    }


__all__ = [
    "AbstractActionClass",
    "AbstractTraceReceipt",
    "ActivePromotionReceipt",
    "ActiveMutationRecord",
    "BoundaryCertificate",
    "CandidatePathRecord",
    "ComparisonContract",
    "CoverageCertificate",
    "DominanceGateReceipt",
    "EventRecord",
    "EffectClass",
    "EffectCounts",
    "GateStatus",
    "Grade",
    "HarnessReceipt",
    "KLBReceipt",
    "HashStr",
    "LedgerAppendReceipt",
    "LedgerIntegrityReceipt",
    "LeaseReceipt",
    "MutationRecord",
    "MutationPatchRecord",
    "MutationProposalRecord",
    "MutationState",
    "MutationBatchRecord",
    "MutationOutcomeRecord",
    "MutatorProfile",
    "ObligationRecord",
    "OptimizerRunReceipt",
    "OptimizerStateRecord",
    "PositiveEvidenceWitness",
    "PolicyActionRecord",
    "PolicyDiffRecord",
    "PendingTrial",
    "PolicyProfileRecord",
    "PressureVector",
    "ProofObligationReceipt",
    "ProtectedDebtRecord",
    "QuarantineRecord",
    "QuarantinedLibraryEntry",
    "ReducerSnapshot",
    "ResourceUsage",
    "RollbackReceipt",
    "RollbackSnapshotRecord",
    "RunnerProfile",
    "RunnerOutputReceipt",
    "SchedulerState",
    "SchemaMigrationRecord",
    "ScopeGraph",
    "SemanticFloorPolicy",
    "ShadowReceipt",
    "SupervisorState",
    "TaintRecord",
    "TrustedBaseBridge",
    "TrialLedgerReceipt",
    "TrialBundleRecord",
    "TrialSessionRecord",
    "WorkloadManifest",
    "WorkflowLibraryRecord",
    "WorkflowPolicyStateRecord",
    "WorkloadExecutionReceipt",
    "LibraryConflictReceipt",
    "LibraryHistoryReceipt",
    "schema_models",
]
