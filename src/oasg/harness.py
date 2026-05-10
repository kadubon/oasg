"""Workflow harness scaffolding for local production trials."""

from __future__ import annotations

from pathlib import Path

HARNESS_TEMPLATE = r'''#!/usr/bin/env python
"""Example local OASG workflow harness.

This template is intentionally small.  Replace the metric deltas with values
measured from your agent workflow.  The harness must emit sealed OASG JSONL
records to stdout or to --out; it must not call an external evaluator.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from oasg.canonical import domain_hash
from oasg.constants import grade_max
from oasg.events import event_record, observation_payload
from oasg.io import read_json, read_jsonl, write_jsonl
from oasg.ledger import seal_records
from oasg.policy_state import MutationPatch
from oasg.reducers.core import reduce_records


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mutation", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--out")
    args = parser.parse_args()

    mutation = read_json(Path(args.mutation))
    patch = MutationPatch.from_dict(mutation["patch"])
    seed = reduce_records(read_jsonl(Path(args.candidate)))
    if patch.op == "set_action_grade":
        raise SystemExit("set_action_grade is manual/demo-only and cannot be trial-promoted")

    dimensions = dict(seed.dimensions)
    protected_debt = dict(seed.protected_debt)
    action_grades = dict(seed.action_grades)
    action_grades[patch.target_action_id] = grade_max(
        action_grades.get(patch.target_action_id, "blocked"),
        "surplus",
    )
    evidence_hash = domain_hash(
        "OASG:v1.0:harness_observation",
        str(mutation["mutation_id"]),
        patch.op,
        patch.target_action_id,
        patch.coordinate_id,
        seed.ledger_prefix_hash,
    )
    payload = observation_payload(
        dimensions=dimensions,
        action_grades=action_grades,
        protected_debt=protected_debt,
        proof_obligation_receipts=[
            {
                "receipt_type": "harness_metric_receipt",
                "coordinate": patch.coordinate_id,
                "status": "receipt_valid",
                "patch_op": patch.op,
                "target_action_id": patch.target_action_id,
            }
        ],
        positive_evidence=[{"coordinate": patch.coordinate_id, "evidence_hash": evidence_hash}],
        policy={
            "effect_classes": ["pure"],
            "semantic_scope": seed.semantic_scope,
            "claim_emitting": seed.claim_emitting,
            "taint_level": seed.taint_level,
            "boundary_status": seed.boundary_status,
            "trusted_base_status": seed.trusted_base_status,
            "workflow_promotion_authorized": False,
        },
        model_event={
            "runner_type": "local-command",
            "patch_op": patch.op,
            "target_action_id": patch.target_action_id,
            "observed_improvement_coordinate": patch.coordinate_id,
            "retry_delta": -1 if patch.op == "set_retry_policy" else 0,
            "queue_age_delta": -1 if patch.op in {"set_retry_policy", "set_decomposition_depth"} else 0,
            "pressure_delta": -1 if patch.op in {"set_routing_policy", "set_decomposition_depth", "remove_requirement"} else 0,
            "validation_debt_delta": -1 if patch.op == "set_validator_policy" else 0,
            "evidence_coverage_delta": 1 if patch.op == "set_validator_policy" else 0,
            "context_overflow_delta": -1 if patch.op == "set_context_compression" else 0,
            "budget_delta": -1 if patch.op in {"adjust_charge", "set_context_compression"} else 0,
            "rollback_receipt_delta": 1 if patch.op in {"set_rollback_requirement", "set_lease_cap"} else 0,
            "rollback_receipt_available": patch.op in {"set_rollback_requirement", "set_lease_cap"},
            "semantic_floor_delta": 1 if patch.op == "set_semantic_floor" else 0,
        },
    )
    records = seal_records(
        [
            event_record(
                event_id=f"evt_harness_{mutation['mutation_id']}",
                workflow_id="trial_workload",
                component_id="workflow_policy",
                event_type="observation",
                payload=payload,
            )
        ]
    )
    if args.out:
        write_jsonl(Path(args.out), records)
    else:
        for record in records:
            sys.stdout.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def write_harness_template(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(HARNESS_TEMPLATE, encoding="utf-8", newline="\n")
    return path


__all__ = ["write_harness_template"]
