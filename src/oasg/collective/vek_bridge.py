"""Native verification objects and declared capacity; never observed capacity."""

from __future__ import annotations

import importlib
from datetime import datetime, timezone
from typing import Any

from oasg.collective.evidence import checked_execution, reference
from oasg.collective.native import require
from oasg.collective.wire import Contract, Source, Measurement, digest


def verification(contract: Contract, source: Source, public_key: bytes) -> dict[str, Any]:
    require("vek")
    result = checked_execution(contract, source, public_key)
    return packet_check(
        contract,
        source.model_dump(),
        source.sha256,
        result.binding.policy_digest,
        result.binding.input_digest,
        result.verification,
        "scoped_host_attestation",
    )


def verification_use(contract: Contract, source: dict[str, Any]) -> dict[str, Any]:
    """Recheck captured native execution, retaining its unadmitted-source status.

    A later separate CCR host signature binds this observation. This function alone
    neither authenticates a caller's dictionary nor authorizes lifecycle mutation.
    """
    measured = Measurement.model_validate(source["applied"]["measurement"])
    if (
        measured.input != contract.confirmation[0]
        or source["applied"]["policy"] != contract.candidate
        or source["applied"]["implementation"] != contract.implementation
        or measured.trace != [1] * len(measured.input.splitlines())
        or measured.probes != sum(measured.trace)
        or source["cost"]["amount"] != str(measured.probes)
    ):
        raise ValueError("native use measurement or scope changed")
    positive = measured.output == reference(measured.input)
    if source["outcome"]["service"] is not positive:
        raise ValueError("native use status disagrees with independent output check")
    return packet_check(
        contract,
        source,
        digest(source),
        digest({"variant": contract.candidate}),
        digest(contract.confirmation),
        "positive" if positive else "negative",
        "unadmitted_native_observation",
    )


def packet_check(
    contract: Contract,
    original: dict[str, Any],
    source_digest: str,
    subject: str,
    input_digest: str,
    status: str,
    authentication: str,
) -> dict[str, Any]:
    require("vek")
    packets = importlib.import_module("verification_ecology_kit.model.packets")
    records = importlib.import_module("verification_ecology_kit.model.records")
    packet = packets.VerifierPacket.minimal(
        created_from=records.OriginKind.SUCCESS
        if status == "positive"
        else records.OriginKind.RESIDUAL
    )
    packet.packet_id = "oasg:" + source_digest[:24]
    packet.origin.traces = [source_digest]
    packet.scope.applies_to = [digest(contract), contract.scope.receiver, contract.scope.evaluator]
    packet.scope.excludes = ["production-generalization", "execution-authority"]
    packet.transformation_class.allowed = ["source-preserving-projection"]
    packet.transformation_class.forbidden = ["automatic-reward", "grade-edit"]
    packet.verifier_procedure.steps = [
        "exact-output-reference",
        "independent-counter-reconstruction",
    ]
    packet.verifier_procedure.evaluator_versions = [contract.checker]
    packet.certification_condition.pass_conditions = ["complete registered finite inputs"]
    packet.certification_condition.fail_conditions = ["output mismatch", "source mismatch"]
    packet.update_profile.revalidation_triggers = [
        "expiry",
        "dependency withdrawal",
        "negative evidence",
    ]
    packet.update_profile.rollback_hooks = ["policy-only"]
    packet.extension = {
        "oasg_contract": digest(contract),
        "source": original,
        "subject": subject,
        "input": input_digest,
        "outcome": status,
        "execution_authorization": False,
    }
    packet.ensure_core_accountability()
    packet.ensure_semantic_accountability()
    checks = packet.validate()
    refs = importlib.import_module("verification_ecology_kit.references")
    core = importlib.import_module("verification_ecology_kit.model.conformance")
    records = importlib.import_module("verification_ecology_kit.model.records")
    obj = refs.ObjectEnvelope(packet.packet_id, "oasg-verification-packet", "1", packet.to_dict())
    obj.refresh_digest()
    bundle = core.VetBundle(
        "oasg-trial",
        "1",
        records.ConformanceProfile.CORE,
        refs.SchemaCatalogue("oasg-local", {"oasg-verification-packet": ("1",)}),
        objects=[obj],
    )
    conformance = core.ConformanceEngine().run(bundle)
    if conformance.decision.value != "accept":
        raise ValueError("VEK native core conformance rejected")
    return {
        "packet": packet.to_dict(),
        "native_checks": [c.to_dict() for c in checks],
        "conformance": conformance.to_dict(),
        "verification_work_status": status,
        "positive_service": False,
        "source_authentication": authentication,
        "source": source_digest,
    }


def capacity(contract: Contract) -> dict[str, Any]:
    require("vek")
    model = importlib.import_module("verification_ecology_kit.capacity.model")
    selector = importlib.import_module("verification_ecology_kit.capacity.selector")
    checker = importlib.import_module("verification_ecology_kit.capacity.checker")
    report_module = importlib.import_module("verification_ecology_kit.capacity.report")
    raw = dict(
        contract_id=contract.scope.study,
        scope=contract.scope.context,
        time_origin=datetime.fromtimestamp(contract.registered_at, timezone.utc).isoformat(),
        slot_seconds="1",
        horizon=2,
        max_candidates=64,
        max_events=16,
        resources=[
            dict(resource_id=contract.pool, unit="checker-slot", kind="pool", capacity=[1, 1]),
            dict(
                resource_id="verification-budget",
                unit="check-unit",
                kind="budget",
                capacity=[contract.verification_budget],
            ),
        ],
        services=[
            dict(
                service_id="reference",
                version="1",
                domain=contract.scope.family,
                checks=[contract.scope.evaluator],
                interface="inert-json-v1",
                valid_until=2,
                exposures=["host-finite-domain"],
                dependence_known=True,
                support_refs=[contract.checker],
                assumptions=["finite declared model; no observed or guaranteed capacity"],
                evidence_basis="declared-model",
            )
        ],
        work=[
            dict(
                work_id=arm,
                residual_id="residual:" + arm,
                subject_digest=digest(contract),
                input_digest=digest(contract.confirmation),
                rule_version=contract.scope.evaluator,
                check=contract.scope.evaluator,
                domain=contract.scope.family,
                bundle="paired",
                arrival=0,
                deadline=2,
                protected=True,
                required=True,
                predecessors=[],
                separate_from=[],
            )
            for arm in ("baseline", "candidate")
        ],
        actions=[
            dict(
                action_id=arm,
                work_id=arm,
                service_id="reference",
                kind="check",
                duration=1,
                costs=[1, 1],
                requires_success=[],
                requires_negative=[],
            )
            for arm in ("baseline", "candidate")
        ],
        scenarios=[
            dict(
                scenario_id="model-positive",
                outcomes=["positive", "positive"],
                assumption="declared joint finite outcome; no empirical independence",
            )
        ],
        schema_version="vek.capacity.contract.v1",
        semantics="nonpreemptive-integer-slots",
        work_unit="registered-check",
        observation_policy="replan-after-admitted-result",
    )
    native = model.Contract.from_dict(raw)
    snapshot = checker.Snapshot(spent=[0, 0])
    plan = selector.plan(native, snapshot)
    checker.check_plan(native, snapshot, plan)
    report = report_module.capacity_report(native, snapshot, plan)
    return {
        "contract": native.to_dict(),
        "plan": plan,
        "report": report,
        "feasible": bool(plan["checked"]["mandatory_met"]),
        "host_reservation": False,
    }
