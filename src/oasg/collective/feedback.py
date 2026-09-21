"""Authenticated scoped withdrawal, native reconciliation and preserved history."""

from __future__ import annotations

import base64
import importlib
import time
from pathlib import Path
from typing import Any

from oasg.canonical import receipt_hash
from oasg.collective import ccr_bridge, memory
from oasg.collective.journal import Journal
from oasg.collective.native import require
from oasg.collective.wire import Contract, digest, encoded, loads, sha
from oasg.library import load_library, rollback_library, write_library


def withdraw(root: Path, *, key: Any, reason: str, fail_after: str | None = None) -> dict[str, Any]:
    journal = Journal(root)
    view = journal.inspect()
    registration = view["entries"][0]["data"]
    contract = Contract.model_validate(registration["contract"])
    public = key.public_key().public_bytes_raw()
    if sha(public) != contract.verifier_key or not 1 <= len(reason) <= 256:
        raise ValueError("unregistered withdrawal signer or reason")
    journal.require_ready(contract,now=int(time.time()))
    trial = loads((root/"trial.json").read_bytes())
    mem = loads((root/"memory.json").read_bytes())
    body = {"contract":digest(contract),"memory":digest(mem),"reason":reason,"time":int(time.time())}
    signed = {**body,"signature":base64.b64encode(key.sign(encoded(body))).decode()}
    journal.append("intent","withdrawal",{"source":signed},expected=view["revision"])
    journal.append("withdraw","host-withdrawal",signed,expected=journal.inspect()["revision"])
    # Local eligibility is already blocked even if the next owning-system transition fails.
    kernel = memory.open_kernel(root/"memory",contract,trial,public)
    _, wire, native = memory.modules()
    runtime = importlib.import_module("observable_agent_workflow_memory.qualified.runtime").ReceiverRuntime(
        kernel,root/"memory"/"oawm.sqlite",[memory.context(contract)])
    runtime.record("withdraw","oasg-withdraw",{"dependency":native.IMPLEMENTATION,"reason":reason},
        now=int(time.time())-contract.registered_at,expected=runtime.store.inspect()["revision"])
    kernel.retire(mem["memory"]["memory_id"],reason)
    if fail_after == "memory-withdrawal":
        raise RuntimeError("injected crash after native withdrawal")
    engine = ccr_bridge.ccr()
    store = ccr_bridge.open_store(root/"ccr")
    use_row = next(r for r in view["entries"] if r["id"] == "cycle-two-use")
    run_id = use_row["data"]["run"]
    run = engine.load(store,run_id)
    asset = next(iter(run["config"]["growth"]["assets"]))
    event = dict(event_id="oasg-withdrawal",run_id=run_id,config_digest=run["config"]["config_digest"],
        asset=asset,state="withdrawn",reason=reason,observed_at=store.now(),
        verifier_id="host-checker",worker_id=contract.scope.worker)
    ids = importlib.import_module("ccr.ids")
    event["signature_base64"] = base64.b64encode(key.sign(ids.canonical_bytes(event))).decode()
    admitted = importlib.import_module("ccr.optimizer.growth_runtime").lifecycle(store,run_id,event)
    library = load_library(root/"library.json")
    reverted = rollback_library(library)
    write_library(root/"library.json",reverted,expected_prior_hash=receipt_hash(library.to_dict()))
    if fail_after == "policy-rollback":
        raise RuntimeError("injected crash after policy rollback")
    current = runtime.retrieve(contract.scope.receiver,contract.confirmation[0],now=int(time.time())-contract.registered_at)
    result = {"source":signed,"ccr_lifecycle":admitted,"memory_eligible":bool(current["views"]),
        "policy":reverted.policy_state.routing_policy,"historical_services":runtime.store.inspect()["services"]}
    if result["memory_eligible"]:
        raise ValueError("withdrawal failed to restrict future use")
    journal.append("ack","withdrawal:ack",{"intent":"withdrawal","original_result":encoded(result).decode(),
        "result_sha256":digest(result)},expected=journal.inspect()["revision"])
    return result


def reconcile(root: Path) -> dict[str, Any]:
    require("cait")
    journal = Journal(root)
    view = journal.inspect()
    if view["unresolved"]:
        return {"status":"unresolved_operation","operations":view["unresolved"],"execution_authorization":False}
    use_row = next(r for r in view["entries"] if r["id"] == "cycle-two-use")
    run_id = use_row["data"]["run"]
    store = ccr_bridge.open_store(root/"ccr")
    engine = ccr_bridge.ccr()
    accounting = importlib.import_module("ccr.optimizer.native_accounting")
    run = engine.load(store,run_id)
    previous = next((r for r in view["entries"] if r["id"] == "accounting:ack"),None)
    if previous is not None:
        saved = loads((root/"accounting.json").read_bytes())
        import json
        original = json.loads(saved["ccr_snapshot_original"])
        def source_rows(r: dict[str, Any]) -> list[Any]:
            return [x for x in r["growth_events"] if x["kind"] in {"outcome","lifecycle"}]
        if source_rows(original) != source_rows(run):
            raise ValueError("accounting source changed; explicit new reconciliation required")
        return {"status":"reconciled","idempotent":True,"checked":saved["checked"]}
    exported = accounting.export(run,store.now())
    report = importlib.import_module("cait_schema.accounting.report").analyze(exported["bundle"])
    (root/"accounting-candidate.json").write_bytes(encoded({"export":exported,"report":report}))
    checked = accounting.check_feedback(run,exported,report,store.now())
    revision = journal.append("intent","accounting",{"source_journal":checked["journal_digest"]},expected=view["revision"])
    admitted = accounting.reconcile(store,run_id,exported,report,expected_revision=run["revision"])
    (root/"accounting.json").write_bytes(encoded({"export":exported,"report":report,"checked":checked,
        "ccr_snapshot_original":encoded(run).decode(),"checked_at":store.now()}))
    journal.append("ack","accounting:ack",{"intent":"accounting","original_result":encoded(admitted).decode(),
        "result_sha256":digest(admitted)},expected=revision)
    return {"status":"reconciled","checked":checked,"admission":admitted}
