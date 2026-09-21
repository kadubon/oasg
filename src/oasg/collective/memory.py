"""Native OAWM ports and receiver profile, with an additional host use boundary."""

from __future__ import annotations

import importlib
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from oasg.collective.check import check_trial
from oasg.collective.native import require
from oasg.collective.wire import Contract, WorkflowExport, digest, encoded
from oasg.collective.worker import execute, implementation_digest


def modules() -> tuple[Any, Any, Any]:
    require("oawm")
    require("alt")
    prefix = "observable_agent_workflow_memory."
    return (
        importlib.import_module(prefix + "runtime.kernel"),
        importlib.import_module(prefix + "qualified.wire"),
        importlib.import_module(prefix + "qualified.native"),
    )


def context(contract: Contract, receiver: str | None = None) -> Any:
    _, wire, native = modules()
    return wire.Context(
        workspace=contract.scope.namespace,
        receiver=receiver or contract.scope.receiver,
        mission=contract.scope.mission,
        task_family=contract.scope.family,
        context=contract.scope.context,
        inputs=contract.confirmation,
        clock="seconds-since-registration",
        dependencies=[native.IMPLEMENTATION],
        checks=["normalize-checker-v1"],
        expose=contract.execute,
    )


class DomainChecker:
    checker_name = "oasg-source-bound-finite-v1"

    def __init__(self, contract: Contract, trial: dict[str, Any], public_key: bytes):
        self.contract, self.trial, self.public_key = contract, trial, public_key

    def verify(self, candidate: Any, *, evidence: dict[str, Any], context: dict[str, Any]) -> Any:
        model = importlib.import_module("observable_agent_workflow_memory.core.models")
        try:
            checked = check_trial(self.contract, self.trial, self.public_key)
            if checked["local_gate_status"] != "safe_promotion":
                raise ValueError("no independently supported improvement")
            if candidate.metadata.get("oasg_source") != digest(self.trial):
                raise ValueError("memory source substitution")
            if candidate.metadata.get("oasg_contract") != digest(self.contract):
                raise ValueError("memory contract substitution")
            if set(candidate.source_event_ids) != set(context["actual_event_digests"]):
                raise ValueError("missing source observation")
            return model.CheckerResult(
                checker_name=self.checker_name,
                passed=True,
                evidence_refs=[digest(self.contract), digest(self.trial)],
                reason="Reconstructed finite sources and unchanged gate",
            )
        except (ValueError, KeyError) as exc:
            return model.CheckerResult(
                checker_name=self.checker_name, passed=False, reason=str(exc)
            )


class Proposer:
    proposer_name = "oasg-registered-procedural-v1"

    def __init__(self, contract: Contract, trial: dict[str, Any]):
        self.contract, self.trial = contract, trial

    def propose(self, events: list[Any], *, scope: str = "session") -> Any:
        native = importlib.import_module(
            "observable_agent_workflow_memory.adapters.deterministic_proposer"
        )
        candidate = native.DeterministicWorkflowProposer().propose(events, scope=scope)
        model = importlib.import_module("observable_agent_workflow_memory.core.models")
        return model.MemoryRecord.create(
            lane=candidate.lane,
            claim="Finite registered line-normalization routing",
            source_event_ids=list(candidate.source_event_ids),
            metadata={
                **candidate.metadata,
                "oasg_source": digest(self.trial),
                "oasg_contract": digest(self.contract),
                "variant": self.contract.candidate,
                "implementation": self.contract.implementation,
            },
        )


def open_kernel(
    root: Path,
    contract: Contract,
    trial: dict[str, Any],
    public_key: bytes,
    before_use: Callable[[], None] | None = None,
    *,
    negative_control: bool = False,
) -> Any:
    if negative_control and contract.negative_control != "second-use-output-loss":
        raise ValueError("fault control must be registered by the disposable host")
    kernel, _, _ = modules()
    defaults = importlib.import_module(
        "observable_agent_workflow_memory.adapters.jsonschema_checker"
    )
    tools = importlib.import_module(
        "observable_agent_workflow_memory.adapters.local_tools"
    ).LocalToolAdapter()

    def use(arguments: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
        if before_use is None:
            raise ValueError("fresh host execution intent required")
        before_use()
        if implementation_digest() != contract.implementation:
            raise ValueError("worker dependency changed")
        measurement = execute(arguments["text"], contract.candidate)
        if negative_control:
            # Actual bounded output loss is an explicit fault test, never a positive observation.
            measurement = measurement.model_copy(update={"output": ""})
        (root / "last-use.json").write_bytes(
            encoded(
                {
                    "measurement": measurement.model_dump(),
                    "policy": contract.candidate,
                    "implementation": contract.implementation,
                    "negative_control": negative_control,
                }
            )
        )
        return {
            "text": measurement.output,
            "work": measurement.probes,
            "policy": contract.candidate,
            "implementation": contract.implementation,
        }

    tools.register("normalize-lines-v1", use)
    return kernel.AgentKernel.open(
        root,
        plugins={
            "checkers": [
                *defaults.create_default_checkers(),
                DomainChecker(contract, trial, public_key),
            ],
            "proposer": Proposer(contract, trial),
            "tool_adapter": tools,
        },
    )


def observe(
    kernel: Any, contract: Contract, *, split: str, text: str, identity: str, now: int
) -> Any:
    _, wire, native = modules()
    ctx = context(contract)
    # This is separately executed OAWM verification work, not relabeled OASG evidence.
    output = native.normalize(text)
    operation = wire.Operation(
        implementation=native.IMPLEMENTATION,
        input=text,
        output=output,
        receiver=ctx.receiver,
        context_digest=wire.digest(ctx),
        time=now,
        split=split,
        outcome="success",
        cost=wire.Cost(
            id=identity,
            stage="formation" if split == "training" else "verification",
            amount=str(len(text.splitlines())),
        ),
    )
    raw = wire.encoded(operation)
    event = kernel.observe(
        "registered_operation", {"raw": raw}, run_id=contract.scope.study, index_as_raw=False
    )
    canonical = importlib.import_module("observable_agent_workflow_memory.core.canonical")
    return wire.Source(
        event_id=event.event_id,
        producer_digest=canonical.digest_json(operation),
        raw=raw,
        sha256=wire.sha(raw),
    )


def admit(
    root: Path, contract: Contract, trial: dict[str, Any], public_key: bytes
) -> dict[str, Any]:
    if check_trial(contract, trial, public_key)["local_gate_status"] != "safe_promotion":
        raise ValueError("memory proposal requires independently checked trial")
    kernel = open_kernel(root, contract, trial, public_key)
    _, wire, native = modules()
    start = int(time.time()) - contract.registered_at
    training = [
        observe(
            kernel,
            contract,
            split="training",
            text=text,
            identity="memory-train:" + str(i),
            now=start,
        )
        for i, text in enumerate(contract.training)
    ]
    candidate = kernel.propose_memory(
        contract.scope.study, tools=["normalize-lines-v1"], resource_caps={"max_steps": 4}
    )
    model = importlib.import_module("observable_agent_workflow_memory.core.models")
    intent = model.ActionIntent.create(
        tool_name="normalize-lines-v1",
        effect_class="local-external",
        arguments={"text": contract.confirmation[0]},
        resource_caps={"max_steps": 4},
    )
    receipt = kernel.verify(candidate.memory_id, action_intent=intent)
    if receipt.result != "passed":
        raise ValueError("OAWM native verification rejected")
    memory = kernel.promote(candidate.memory_id)
    # Integer clock boundary is real elapsed time, never a simulated promotion receipt.
    while int(time.time()) - contract.registered_at <= start:
        time.sleep(0.02)
    now = int(time.time()) - contract.registered_at
    evaluation = [
        observe(
            kernel,
            contract,
            split="evaluation",
            text=text,
            identity="memory-check:" + str(i),
            now=now,
        )
        for i, text in enumerate(contract.confirmation)
    ]
    q = native.propose(
        memory_id=memory.memory_id,
        update_id=memory.update_id,
        workflow_digest=memory.content_digest(),
        context=context(contract),
        training=training,
        evaluation=evaluation,
        cutoff=start,
        valid_from=now,
        valid_until=contract.expires_at - contract.registered_at,
        formation_cost=wire.Cost(id="memory-formation", stage="formation", amount="1"),
    )
    runtime = importlib.import_module(
        "observable_agent_workflow_memory.qualified.runtime"
    ).ReceiverRuntime(kernel, root / "oawm.sqlite", [context(contract), context(contract, "B")])
    runtime.store.initialize()
    revision = runtime.admit(q, now=now, expected=runtime.store.inspect()["revision"])
    manifest_id = next(ref for ref in receipt.evidence_refs if ref.startswith("evm_"))
    manifest = kernel.storage.get_evidence_manifest(manifest_id)
    return WorkflowExport.model_validate(
        {
            "contract": digest(contract),
            "qualification": q.model_dump(),
            "receipt": receipt.model_dump(mode="json"),
            "manifest": manifest.model_dump(mode="json"),
            "intent": intent.model_dump(mode="json"),
            "memory": memory.model_dump(mode="json"),
            "revision": revision,
            "costs": [c.model_dump() for c in q.costs],
        }
    ).model_dump()
