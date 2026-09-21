"""Project checked observations without changing the legacy reducer or gate."""

from __future__ import annotations

from typing import Any

from oasg.canonical import receipt_hash
from oasg.collective.evidence import checked_execution, eligibility
from oasg.collective.wire import Contract, Source, digest
from oasg.constants import ACTION_CLASSES, REQUIRED_DIMENSIONS
from oasg.events import event_record, observation_payload
from oasg.ledger import seal_records

FIELD_MAP = {"dimensions.budget": "execution.work,contract.efficient_work,contract.max_work",
             "protected_floors": "contract.scope,execution.binding,execution.measurements,execution.verification",
             "policy": "contract.effects,execution.external_effects",
             "positive_evidence": "original_source.sha256",
             "model_event": "execution.work,execution.variant,execution.cost_id"}


def project(contract: Contract, source: Source, public_key: bytes) -> dict[str, Any]:
    result = checked_execution(contract, source, public_key)
    support = eligibility(contract, result)
    grade = "blocked"
    if support["runner_execution_support"]:
        grade = "surplus" if result.work <= contract.efficient_work else "acceptable"
    protected = "acceptable" if support["runner_execution_support"] else "blocked"
    dimensions = dict.fromkeys(REQUIRED_DIMENSIONS, protected)
    dimensions["budget"] = grade
    actions = dict.fromkeys(ACTION_CLASSES, protected)
    actions["emit_claim"] = actions["promote_workflow"] = "blocked"
    coordinates = ["budget", *["KLB_2." + a for a in ACTION_CLASSES]]
    payload = observation_payload(
        dimensions=dimensions, action_grades=actions,
        protected_debt=dict.fromkeys(REQUIRED_DIMENSIONS, protected),
        proof_obligation_receipts=[{"coordinate": x, "status": "receipt_valid"} for x in coordinates]
        if support["runner_execution_support"] else [],
        positive_evidence=[{"coordinate": x, "evidence_hash": receipt_hash(source.model_dump())} for x in coordinates]
        if support["runner_execution_support"] else [],
        model_event={"source": source.sha256, "contract": digest(contract),
                     "cost_id": result.cost_id, "work": result.work,
                     "variant": result.variant, "evidence_class": result.evidence_class},
    )
    records = seal_records([event_record(event_id=result.binding.attempt,
        workflow_id=contract.scope.study, component_id=contract.scope.worker,
        event_type="observation", payload=payload)])
    return {"schema_id": "oasg.collective.projection.v1", "contract": digest(contract),
            "source": source.model_dump(), "records": records,
            "field_map": FIELD_MAP.copy(), "dimensions": support}
