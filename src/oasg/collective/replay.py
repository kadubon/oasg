"""Read-only reconstruction from original signed records, with no store opening."""

from __future__ import annotations

import base64
import importlib
import json
from pathlib import Path
from typing import Any

from oasg.collective.check import check_trial
from oasg.collective.journal import Journal
from oasg.collective.native import require
from oasg.collective.wire import Contract, Source, digest, encoded, loads, sha


def replay(root: Path) -> dict[str, Any]:
    view = Journal(root).inspect()
    if not view["entries"]:
        return {"status":"not_registered","execution_authorization":False}
    registration = view["entries"][0]["data"]
    contract = Contract.model_validate(registration["contract"])
    public = bytes.fromhex(registration["public_key"])
    if sha(public) != contract.verifier_key:
        raise ValueError("journal trust reference changed")
    for row in view["entries"]:
        if row["kind"] == "ack":
            if sha(row["data"]["original_result"].encode()) != row["data"]["result_sha256"]:
                raise ValueError("native acknowledgment bytes changed")
    if view["unresolved"]:
        return {"status":"unresolved_operation","operations":view["unresolved"],
                "execution_authorization":False,"revision":view["revision"]}
    trial = loads((root/"trial.json").read_bytes())
    checked = check_trial(contract,trial,public)
    for source_name, report in zip(("baseline","candidate"),trial["projections"],strict=True):
        original = Source.model_validate(loads((root/(source_name+".json")).read_bytes()))
        if original.model_dump() != report["source"]:
            raise ValueError("original source replaced")
    mem = loads((root/"memory.json").read_bytes())
    from oasg.collective.memory import context, modules
    _, wire, native_memory = modules()
    q = wire.Qualification.model_validate(mem["qualification"])
    native_memory.reconstruct(q, q.valid_from)
    model = importlib.import_module("observable_agent_workflow_memory.core.models")
    memory = model.MemoryRecord.model_validate(mem["memory"])
    receipt = model.PromotionReceipt.model_validate(mem["receipt"])
    manifest = model.EvidenceManifest.model_validate(mem["manifest"])
    verifier = importlib.import_module("observable_agent_workflow_memory.adapters.receipt_verifier")
    if not verifier.DefaultReceiptVerifier().verify_receipt(receipt, manifest, {"candidate":memory}).passed:
        raise ValueError("native memory receipt does not reconstruct")
    if (q.context != context(contract) or q.memory_id != memory.memory_id
            or q.update_id != memory.update_id or q.workflow_digest != memory.content_digest()
            or memory.metadata.get("oasg_source") != digest(trial)
            or memory.metadata.get("oasg_contract") != digest(contract)
            or mem["costs"] != [c.model_dump() for c in q.costs]):
        raise ValueError("native memory source, scope, or cost substitution")
    accounting = loads((root/"accounting.json").read_bytes())
    # Original CCR JSON (including legacy float spelling/signing semantics) is retained as text.
    run = json.loads(accounting["ccr_snapshot_original"])
    original_config = json.loads(registration["ccr_config_original"])
    if digest(original_config) != contract.ccr_registration:
        raise ValueError("original native configuration changed")
    require("ccr")
    require("cait")
    normalized = importlib.import_module("ccr.optimizer.growth_model").normalize(original_config)
    if run["config"] != normalized:
        raise ValueError("accounting configuration differs from registered contract")
    native = importlib.import_module("ccr.optimizer.native_accounting")
    feedback = native.check_feedback(run,accounting["export"],accounting["report"],accounting["checked_at"])
    if feedback != accounting["checked"]:
        raise ValueError("derived accounting changed")
    key_module = importlib.import_module("cryptography.hazmat.primitives.asymmetric.ed25519")
    key = key_module.Ed25519PublicKey.from_public_bytes(public)
    for withdrawal in view["withdrawn"]:
        body = {k:v for k,v in withdrawal.items() if k != "signature"}
        key.verify(base64.b64decode(withdrawal["signature"],validate=True),encoded(body))
        if body["contract"] != digest(contract) or body["memory"] != digest(mem):
            raise ValueError("unbound lifecycle evidence")
    # Tiny cost oracle uses ultimate work identities, not any aggregate report as input.
    costs: dict[str,int] = {}
    for report in trial["projections"]:
        e = Source.model_validate(report["source"]).execution()
        if e.cost_id in costs:
            raise ValueError("duplicate physical attempt")
        costs[e.cost_id] = e.work
    for cost in mem["costs"]:
        if cost["id"] in costs:
            raise ValueError("duplicate preparation/transfer cost")
        costs[cost["id"]] = int(cost["amount"])
    use = next(r for r in view["entries"] if r["id"] == "cycle-two-use:ack")
    outcome = loads(use["data"]["original_result"].encode())
    if outcome["cost"]["id"] in costs:
        raise ValueError("duplicate receiver use")
    costs[outcome["cost"]["id"]] = outcome["applied"]["measurement"]["probes"]
    if sum(costs.values()) != feedback["costs"]["work"]:
        raise ValueError("source physical work does not reconcile with CCR")
    return {"status":"checked","gate":checked["local_gate_status"],"source_costs":costs,
        "actual_registered_work":sum(costs.values()),"next_use_eligible":False,
        "requires_fresh_host_check":not bool(view["withdrawn"]),
        "historical_service":accounting["report"]["balances"],
        "reward_added":feedback["reward_added"],"asset_stock_added":feedback["asset_stock_added"],
        "execution_authorization":False,"evidence_class":contract.evidence_class,"revision":view["revision"]}
