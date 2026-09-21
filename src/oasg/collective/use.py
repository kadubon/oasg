"""Fresh-process native retrieval and actual assigned work, never an import effect."""

from __future__ import annotations

import importlib
import json
import sys
import time
from pathlib import Path
from typing import Any

from oasg.canonical import receipt_hash
from oasg.collective.ccr_bridge import current_task, open_store
from oasg.collective.check import check_trial
from oasg.collective.journal import Journal
from oasg.collective.memory import context, modules, open_kernel
from oasg.collective.wire import Contract, digest, encoded, loads
from oasg.library import load_library


def execute_use(root: Path, operation: str = "cycle-two-use") -> dict[str, Any]:
    journal = Journal(root)
    view = journal.inspect()
    registration = view["entries"][0]["data"]
    contract = Contract.model_validate(registration["contract"])
    if operation not in {"cycle-two-use", "negative-use"} or (
        operation == "negative-use" and contract.negative_control != "second-use-output-loss"
    ):
        raise ValueError("unregistered use operation")
    public_key = bytes.fromhex(registration["public_key"])
    pending = next(row for row in view["entries"] if row["id"] == operation)
    expected = pending["data"]
    trial = loads((root / "trial.json").read_bytes())
    memory = loads((root / "memory.json").read_bytes())
    if digest(trial) != expected["trial"] or digest(memory) != expected["memory"]:
        raise ValueError("saved trial or memory changed")
    if check_trial(contract, trial, public_key)["local_gate_status"] != "safe_promotion":
        raise ValueError("current independent trial check failed")
    store = open_store(root / "ccr")

    def fresh() -> None:
        current = journal.inspect()
        if (
            current["revision"] != view["revision"]
            or current["unresolved"] != [operation]
            or current["withdrawn"]
        ):
            raise ValueError("host revision changed or unresolved work")
        library = load_library(root / "library.json")
        if receipt_hash(library.to_dict()) != expected["library"]:
            raise ValueError("active policy changed")
        if library.policy_state.routing_policy.get("local_reversible") != contract.candidate:
            raise ValueError("retrieved variant is not the active local policy")
        if not contract.cutoff < int(time.time()) < contract.expires_at:
            raise ValueError("use authority expired")
        original_config = json.loads(registration["ccr_config_original"])
        if digest(original_config) != contract.ccr_registration:
            raise ValueError("original CCR registration changed")
        current_task(
            store,
            expected["run"],
            expected["ccr_trial"],
            contract.scope.worker,
            expected["token"],
            expected_config=original_config,
        )

    fresh()
    kernel = open_kernel(
        root / "memory",
        contract,
        trial,
        public_key,
        before_use=fresh,
        negative_control=operation == "negative-use",
    )
    _, wire, _ = modules()
    runtime = importlib.import_module(
        "observable_agent_workflow_memory.qualified.runtime"
    ).ReceiverRuntime(
        kernel, root / "memory" / "oawm.sqlite", [context(contract), context(contract, "B")]
    )
    now = int(time.time()) - contract.registered_at
    text = contract.confirmation[0]
    retrieved = runtime.retrieve(contract.scope.receiver, text, now=now)
    other = runtime.retrieve("B", text, now=now)
    q = wire.Qualification.model_validate(memory["qualification"])
    chosen = [v for v in retrieved["views"] if v["qualification"] == wire.digest(q)]
    if len(chosen) != 1 or other["views"]:
        raise ValueError("receiver-local memory not eligible")
    # Native independent reconstruction is part of current use, not only promotion.
    checker = importlib.import_module("observable_agent_workflow_memory.qualified.checker")
    with runtime.store.readonly() as con:
        checker.check_view(con, chosen[0], context(contract), text, now)
    model = importlib.import_module("observable_agent_workflow_memory.core.models")
    intent = model.ActionIntent.model_validate(memory["intent"])
    cost = wire.Cost(
        id="cycle-two-work" if operation == "cycle-two-use" else "negative-use-work",
        stage="use",
        amount=str(len(text.splitlines())),
    )
    outcome = runtime.use(
        wire.digest(q),
        text,
        identity=operation,
        now=now,
        expected=runtime.store.inspect()["revision"],
        intent=intent,
        receipts=[memory["receipt"]["receipt_id"]],
        cost=cost,
    )
    if not outcome["service"] and operation != "negative-use":
        raise ValueError("native use did not verify")
    applied = loads((root / "memory" / "last-use.json").read_bytes())
    current = runtime.retrieve(contract.scope.receiver, text, now=now)
    return {
        "retrieved": chosen[0],
        "outcome": outcome,
        "applied": applied,
        "eligible_after_check": bool(current["views"]),
        "receiver_B_eligible": False,
        "receiver_C_supported": False,
        "cost": cost.model_dump(),
        "process_id": __import__("os").getpid(),
    }


if __name__ == "__main__":
    sys.stdout.buffer.write(
        encoded(
            execute_use(Path(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else "cycle-two-use")
        )
    )
