"""OASG local-command trial harness for the Ollama pilot.

The harness converts recent observed pilot metrics into a sealed trial ledger.
It is deliberately conservative: without observed failures/pressure it emits no
positive evidence for promotion.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for import_path in (SRC, ROOT):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from oasg.canonical import domain_hash, receipt_hash  # noqa: E402
from oasg.constants import grade_max  # noqa: E402
from oasg.events import event_record, observation_payload  # noqa: E402
from oasg.io import read_json, read_jsonl, write_jsonl  # noqa: E402
from oasg.ledger import seal_records  # noqa: E402
from oasg.policy_state import MutationPatch  # noqa: E402
from oasg.reducers.core import reduce_records  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mutation", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--metrics", required=True)
    parser.add_argument("--out")
    args = parser.parse_args()

    mutation = read_json(Path(args.mutation))
    patch = MutationPatch.from_dict(mutation["patch"])
    metrics = read_json(Path(args.metrics))
    seed = reduce_records(read_jsonl(Path(args.candidate)))
    if patch.op == "set_action_grade":
        return _emit_rejection(args.out, mutation, seed, "manual_action_grade")
    if not _metrics_support_patch(metrics, patch):
        return _emit_rejection(args.out, mutation, seed, "insufficient_observed_pressure")

    coordinate = patch.coordinate_id
    action_grades = dict(seed.action_grades)
    action_grades[patch.target_action_id] = grade_max(
        action_grades.get(patch.target_action_id, "blocked"),
        "surplus",
    )
    evidence_hash = domain_hash(
        "OASG:v1.0:ollama_pilot_trial",
        str(mutation["mutation_id"]),
        patch.op,
        patch.target_action_id,
        coordinate,
        str(metrics.get("source_hash")),
    )
    records = seal_records(
        [
            event_record(
                event_id=f"evt_trial_{mutation['mutation_id']}",
                workflow_id="ollama_gemma4_e4b_pilot_trial",
                component_id="workflow_policy",
                event_type="observation",
                payload=observation_payload(
                    dimensions=dict(seed.dimensions),
                    action_grades=action_grades,
                    protected_debt=dict(seed.protected_debt),
                    proof_obligation_receipts=[
                        {
                            "receipt_type": "pilot_metric_receipt",
                            "coordinate": coordinate,
                            "status": "receipt_valid",
                            "patch_op": patch.op,
                            "target_action_id": patch.target_action_id,
                            "metrics_hash": receipt_hash(metrics),
                        }
                    ],
                    positive_evidence=[{"coordinate": coordinate, "evidence_hash": evidence_hash}],
                    policy={
                        "effect_classes": ["pure"],
                        "semantic_scope": seed.semantic_scope,
                        "claim_emitting": seed.claim_emitting,
                        "taint_level": seed.taint_level,
                        "boundary_status": seed.boundary_status,
                        "trusted_base_status": seed.trusted_base_status,
                        "workflow_promotion_authorized": False,
                    },
                    model_event=_metric_event(metrics, patch),
                ),
            )
        ]
    )
    _emit_records(args.out, records)
    return 0


def _metrics_support_patch(metrics: dict[str, Any], patch: MutationPatch) -> bool:
    failures = int(metrics.get("validation_failures", 0))
    parse_failures = int(metrics.get("parse_failures", 0))
    unresolved = int(metrics.get("unresolved_obligations", 0))
    error_classes = metrics.get("error_classes", {})
    unsafe_expr = int(error_classes.get("expr_disallowed_node", 0)) if isinstance(error_classes, dict) else 0
    if patch.op == "set_retry_policy":
        return failures > 0 or unresolved > 0
    if patch.op == "set_validator_policy":
        return failures > 0 or parse_failures > 0 or unsafe_expr > 0
    if patch.op in {"set_context_compression", "adjust_charge"}:
        return int(metrics.get("mean_latency_ms", 0)) > 0
    if patch.op in {"set_rollback_requirement", "set_lease_cap"}:
        return unresolved > 0
    if patch.op in {"set_routing_policy", "set_decomposition_depth", "remove_requirement"}:
        return failures > 0 or unresolved > 0
    if patch.op == "set_semantic_floor":
        return failures > 0
    return False


def _metric_event(metrics: dict[str, Any], patch: MutationPatch) -> dict[str, Any]:
    failures = int(metrics.get("validation_failures", 0))
    parse_failures = int(metrics.get("parse_failures", 0))
    unresolved = int(metrics.get("unresolved_obligations", 0))
    error_classes = metrics.get("error_classes", {})
    unsafe_expr = int(error_classes.get("expr_disallowed_node", 0)) if isinstance(error_classes, dict) else 0
    return {
        "runner_type": "local-command",
        "trial_mode": "ollama_pilot_metric_trial",
        "patch_op": patch.op,
        "target_action_id": patch.target_action_id,
        "observed_improvement_coordinate": patch.coordinate_id,
        "retry_delta": -1 if patch.op == "set_retry_policy" and failures > 0 else 0,
        "queue_age_delta": -1 if unresolved > 0 else 0,
        "pressure_delta": -1 if failures > 0 or unresolved > 0 else 0,
        "parse_failure_delta": -1 if patch.op == "set_validator_policy" and parse_failures > 0 else 0,
        "validation_debt_delta": -1 if patch.op == "set_validator_policy" and failures > 0 else 0,
        "unsafe_expression_delta": -1 if patch.op == "set_validator_policy" and unsafe_expr > 0 else 0,
        "evidence_coverage_delta": 1 if patch.op == "set_validator_policy" and failures > 0 else 0,
        "context_overflow_delta": -1 if patch.op == "set_context_compression" else 0,
        "budget_delta": -1 if patch.op in {"adjust_charge", "set_context_compression"} else 0,
        "rollback_receipt_delta": 1 if patch.op in {"set_rollback_requirement", "set_lease_cap"} else 0,
        "rollback_receipt_available": patch.op in {"set_rollback_requirement", "set_lease_cap"},
        "semantic_floor_delta": 1 if patch.op == "set_semantic_floor" else 0,
        "metrics_hash": receipt_hash(metrics),
    }


def _emit_rejection(
    out: str | None,
    mutation: dict[str, Any],
    seed: Any,
    reason: str,
) -> int:
    records = seal_records(
        [
            event_record(
                event_id=f"evt_trial_rejected_{mutation.get('mutation_id', 'unknown')}",
                workflow_id="ollama_gemma4_e4b_pilot_trial",
                component_id="workflow_policy",
                event_type="observation",
                payload=observation_payload(
                    dimensions=dict(seed.dimensions),
                    action_grades=dict(seed.action_grades),
                    protected_debt={**dict(seed.protected_debt), "comparison": "critical"},
                    model_event={"runner_type": "local-command", "rejection_reason": reason},
                ),
            )
        ]
    )
    _emit_records(out, records)
    return 0


def _emit_records(out: str | None, records: list[dict[str, Any]]) -> None:
    if out:
        write_jsonl(Path(out), records)
        return
    for record in records:
        sys.stdout.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
