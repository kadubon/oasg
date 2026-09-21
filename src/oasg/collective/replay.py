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
from oasg.collective.wire import Contract, Source, WorkflowExport, digest, encoded, loads, sha


def check_native_results(
    view: dict[str, Any],
    contract: Contract,
    run: dict[str, Any],
    public: bytes,
    expected: dict[str, tuple[str, int, bool]],
) -> None:
    """Independently verify original CCR signing bytes and bound work/source claims."""
    key_module = importlib.import_module("cryptography.hazmat.primitives.asymmetric.ed25519")
    key = key_module.Ed25519PublicKey.from_public_bytes(public)
    ids = importlib.import_module("ccr.ids")
    for operation, (source, work, accepted) in expected.items():
        row = next(r for r in view["entries"] if r["id"] == operation + ":ack")
        receipt = json.loads(row["data"]["original_result"])
        envelope = receipt["envelope"]
        result = envelope["result"]
        for signed in (envelope, result):
            body = {k: v for k, v in signed.items() if k != "signature_base64"}
            try:
                key.verify(
                    base64.b64decode(signed["signature_base64"], validate=True),
                    ids.canonical_bytes(body),
                )
            except Exception as exc:
                raise ValueError("original CCR host signature failed") from exc
        if (
            envelope["verifier_id"] != "host-checker"
            or result["verifier_id"] != "host-checker"
            or result["worker_id"] != contract.scope.worker
            or result["run_id"] != run["run_id"]
            or result["config_digest"] != run["config"]["config_digest"]
            or result["actual_resources"] != {"work": work}
            or result["accepted"] is not accepted
            or result["packet"]["provenance"]["content_sha256"] != source
        ):
            raise ValueError("signed CCR result does not bind the reconstructed source")
        trial = next(t for t in run["trials"] if t["trial_id"] == result["trial_id"])
        if any(
            result[k] != trial[k]
            for k in ("target_id", "input_digest", "fencing_token", "worker_id")
        ):
            raise ValueError("signed CCR result is not the assigned attempt")


def replay(root: Path) -> dict[str, Any]:
    view = Journal(root).inspect()
    if not view["entries"]:
        return {"status": "not_registered", "execution_authorization": False}
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
        return {
            "status": "unresolved_operation",
            "operations": view["unresolved"],
            "execution_authorization": False,
            "revision": view["revision"],
        }
    trial = loads((root / "trial.json").read_bytes())
    checked = check_trial(contract, trial, public)
    for source_name, report in zip(("baseline", "candidate"), trial["projections"], strict=True):
        original = Source.model_validate(loads((root / (source_name + ".json")).read_bytes()))
        if original.model_dump() != report["source"]:
            raise ValueError("original source replaced")
    mem = loads((root / "memory.json").read_bytes())
    WorkflowExport.model_validate(mem)
    if mem["contract"] != digest(contract):
        raise ValueError("memory export contract changed")
    from oasg.collective.memory import context, modules

    _, wire, native_memory = modules()
    q = wire.Qualification.model_validate(mem["qualification"])
    native_memory.reconstruct(q, q.valid_from)
    model = importlib.import_module("observable_agent_workflow_memory.core.models")
    memory = model.MemoryRecord.model_validate(mem["memory"])
    receipt = model.PromotionReceipt.model_validate(mem["receipt"])
    manifest = model.EvidenceManifest.model_validate(mem["manifest"])
    verifier = importlib.import_module("observable_agent_workflow_memory.adapters.receipt_verifier")
    if (
        not verifier.DefaultReceiptVerifier()
        .verify_receipt(receipt, manifest, {"candidate": memory})
        .passed
    ):
        raise ValueError("native memory receipt does not reconstruct")
    if (
        q.context != context(contract)
        or q.memory_id != memory.memory_id
        or q.update_id != memory.update_id
        or q.workflow_digest != memory.content_digest()
        or memory.metadata.get("oasg_source") != digest(trial)
        or memory.metadata.get("oasg_contract") != digest(contract)
        or mem["costs"] != [c.model_dump() for c in q.costs]
    ):
        raise ValueError("native memory source, scope, or cost substitution")
    accounting = loads((root / "accounting.json").read_bytes())
    accounting_ack = next(
        r
        for r in reversed(view["entries"])
        if r["id"].startswith("accounting:") and r["kind"] == "ack"
    )
    acknowledged = loads(accounting_ack["data"]["original_result"].encode())
    immutable_name = accounting_ack["id"].removesuffix(":ack").replace(":", "-") + ".json"
    immutable_snapshot = loads((root / immutable_name).read_bytes())
    if (
        digest(accounting) != acknowledged["snapshot_digest"]
        or digest(immutable_snapshot) != acknowledged["snapshot_digest"]
    ):
        raise ValueError("latest acknowledged accounting source changed")
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
    feedback = native.check_feedback(
        run, accounting["export"], accounting["report"], accounting["checked_at"]
    )
    if feedback != accounting["checked"]:
        raise ValueError("derived accounting changed")
    key_module = importlib.import_module("cryptography.hazmat.primitives.asymmetric.ed25519")
    key = key_module.Ed25519PublicKey.from_public_bytes(public)
    for withdrawal in view["withdrawn"]:
        body = {k: v for k, v in withdrawal.items() if k != "signature"}
        key.verify(base64.b64decode(withdrawal["signature"], validate=True), encoded(body))
        if body["contract"] != digest(contract) or body["memory"] != digest(mem):
            raise ValueError("unbound lifecycle evidence")
    # Tiny cost oracle uses ultimate work identities, not any aggregate report as input.
    costs: dict[str, int] = {}
    for report in trial["projections"]:
        e = Source.model_validate(report["source"]).execution()
        if e.cost_id in costs:
            raise ValueError("duplicate physical attempt")
        costs[e.cost_id] = e.work
    for cost in mem["costs"]:
        if cost["id"] in costs:
            raise ValueError("duplicate preparation/transfer cost")
        costs[cost["id"]] = int(cost["amount"])
    expected = {
        "trial-result": (digest(trial), sum(trial["work"].values()), True),
        "qualification-result": (digest(mem), sum(int(c["amount"]) for c in mem["costs"]), True),
    }
    for use in [r for r in view["entries"] if r["id"] in {"cycle-two-use:ack", "negative-use:ack"}]:
        outcome = loads(use["data"]["original_result"].encode())
        from oasg.collective.vek_bridge import verification_use

        verification_use(contract, outcome)
        if outcome["cost"]["id"] in costs:
            raise ValueError("duplicate receiver use")
        costs[outcome["cost"]["id"]] = outcome["applied"]["measurement"]["probes"]
        operation = "use-result" if use["id"] == "cycle-two-use:ack" else "negative-result"
        expected[operation] = (
            digest(outcome),
            outcome["applied"]["measurement"]["probes"],
            operation == "use-result",
        )
    if "use-result" not in expected or (
        contract.negative_control != "none" and "negative-result" not in expected
    ):
        raise ValueError("registered later use evidence missing")
    check_native_results(view, contract, run, public, expected)
    if sum(costs.values()) != feedback["costs"]["work"]:
        raise ValueError("source physical work does not reconcile with CCR")
    return {
        "status": "checked",
        "gate": checked["local_gate_status"],
        "source_costs": costs,
        "actual_registered_work": sum(costs.values()),
        "next_use_eligible": False,
        "requires_fresh_host_check": not bool(view["withdrawn"]),
        "historical_service": accounting["report"]["balances"],
        "reward_added": feedback["reward_added"],
        "asset_stock_added": feedback["asset_stock_added"],
        "execution_authorization": False,
        "evidence_class": contract.evidence_class,
        "revision": view["revision"],
    }
