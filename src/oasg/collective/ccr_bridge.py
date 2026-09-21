"""CCR owns all reservations, tasks, fencing and signed result admission."""

from __future__ import annotations

import base64
import importlib
from contextlib import contextmanager
from collections.abc import Iterator
from datetime import timedelta
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from oasg.collective.native import ccr
from oasg.collective.wire import Contract, digest, sha


def registration(
    public_key: bytes,
    inputs: list[str],
    *,
    study: str,
    worker: str,
    context: str,
    artifact: str,
    budget: int = 10000,
    negative_control: bool = False,
) -> dict[str, Any]:
    ccr()
    expiry = (
        datetime.now(timezone.utc).replace(microsecond=0) + timedelta(seconds=600)
    ).isoformat()
    mapping = {
        "formation": "distillation",
        "qualify": "verification",
        "use": "independent_proposal",
    }
    kinds = {"formation": "formation", "qualify": "transfer_validation", "use": "reuse"}
    actions = {}
    for name in mapping:
        actions[name] = dict(
            kind=kinds[name],
            intervention_id=name,
            target_id="target:" + name,
            receiver="A",
            requires=[] if name == "formation" else [artifact],
            produces=artifact if name == "formation" else None,
            gains={"task": int(name == "use"), "research": int(name == "use")},
            duration_seconds=60,
            cleanup_seconds=1,
            cleanup_cost={"work": 1},
            capacity={"worker": 1},
            service_measurement={"check": 0},
            verification_work={"check": 1},
            authority="local_only",
            evidence_refs=["finite-software-observations"],
        )
    # A disjoint frozen holdout is registered but never used to train this profile.
    holdout = dict(actions["use"], intervention_id="holdout", target_id="target:holdout")
    actions["holdout"] = holdout
    mapping["holdout"] = "independent_proposal"
    if negative_control:
        actions["verify-use"] = dict(
            actions["use"], intervention_id="verify-use", target_id="target:verify-use"
        )
        mapping["verify-use"] = "independent_proposal"
    base = dict(
        schema_version="ccr.optimizer_config.v1",
        policy_version=1,
        seed=17,
        deadline=expiry,
        epsilon=0.2,
        diagnostic_reserve=0.2,
        resource_limits={"work": budget},
        effort_resource="work",
        max_inflight=1,
        trusted_verifiers={"host-checker": base64.b64encode(public_key).decode()},
        task_manifest=[
            dict(
                target_id=a["target_id"],
                input_ref="registered:" + n,
                input_sha256=digest(inputs if n != "holdout" else ["held-out-not-executed"]),
                acceptance_criteria="Exact finite line-set output and current scoped host evidence; no production claim",
            )
            for n, a in actions.items()
        ],
        interventions=[
            dict(
                intervention_id=n,
                kind=mapping[n],
                resource_upper_bound={"work": 1000},
                producer_ids=[worker],
            )
            for n in actions
        ],
        evaluation=dict(
            holdout_tasks=["target:holdout"],
            horizon=1,
            alpha=0.05,
            resource_envelope={"work": 1001},
            baseline_intervention="use",
        ),
    )
    bundles = {"workflow": ["formation", "qualify", "use"], "holdout": ["holdout"]}
    if negative_control:
        bundles["workflow"].append("verify-use")
    growth = dict(
        study_id=study,
        checkpoint_digest=digest({"packets": [], "residuals": []}),
        evidence_mode="observational",
        targets={"task": 2 if negative_control else 1, "research": 2 if negative_control else 1},
        units={
            "task": "finite_completed_task",
            "research": "finite_verification_result",
            "costs": {"work": "registered_work_unit"},
        },
        horizon_seconds=300,
        max_steps=4,
        candidate_limit=32,
        attribution_seconds=3600,
        window_end=expiry,
        receivers={
            "A": dict(
                mission_id=study,
                context_sha256=digest(context),
                domain="finite_software",
                protocol="oasg-finite-v1",
                evaluator="line-set-reference-v1",
                quality="exact",
                cross_mission_allowed=False,
            )
        },
        assets={
            artifact: dict(
                version="1",
                source_mission=study,
                receivers=["A"],
                parents=[],
                external_inputs=["registered-finite-policy"],
                expires_at=expiry,
            )
        },
        actions=actions,
        bundles=bundles,
        scenarios={"declared-finite": dict.fromkeys(actions, True)},
        verifier_stages={
            "check": dict(
                domains=["finite_software"],
                quality="exact",
                service_units_per_second=1,
                fresh_until=expiry,
                independence_groups=["host-reference"],
                exposure_groups=["same-finite-domain"],
                dependence="shared",
            )
        },
        quota=dict(
            pool_id="pool:" + study,
            pool_budget={"work": budget},
            pool_capacity={"worker": 1},
            budget={"work": budget},
            capacity={"worker": 1},
            allocation_ref="host-disposable-budget",
        ),
        cost_order=["work"],
        diagnostic_budget={"work": 1},
        comparison=dict(
            restricted_bundles=list(bundles),
            independent_unit="finite-study",
            uncertainty_method="unresolved",
        ),
    )
    return {
        "schema_version": "ccr.growth_profile.v1",
        "policy": "verified_growth_v1",
        "base": base,
        "growth": growth,
    }


def check_registration(
    contract: Contract, config: dict[str, Any], public: bytes, *, now: int
) -> None:
    """Enforce the host sidecar against the exact supported native registration."""
    from oasg.collective.evidence import checker_digest
    from oasg.collective.worker import implementation_digest

    if digest(config) != contract.ccr_registration or sha(public) != contract.verifier_key:
        raise ValueError("native registration or host key changed")
    if not contract.registered_at <= now <= contract.cutoff < contract.expires_at:
        raise ValueError("registration must precede confirmation and expiry")
    if (
        contract.scope.receiver != "A"
        or contract.scope.mission != contract.scope.study
        or contract.ccr_revision != 0
        or contract.pool != "pool:" + contract.scope.study
        or contract.cleanup_budget != 1
        or contract.verification_budget < 2
        or len(contract.confirmation) != 1
        or 2 * contract.max_work > 1000
        or contract.evidence_class != "executed_finite_software"
        or contract.candidate != "indexed"
    ):
        raise ValueError("unsupported registered host profile")
    if contract.implementation != implementation_digest() or contract.checker != checker_digest():
        raise ValueError("unregistered executing implementation")
    artifact = digest(
        {
            "variant": contract.candidate,
            "implementation": contract.implementation,
            "inputs": contract.confirmation,
        }
    )
    expected = registration(
        public,
        contract.confirmation,
        study=contract.scope.study,
        worker=contract.scope.worker,
        context=contract.scope.context,
        artifact=artifact,
        negative_control=contract.negative_control == "second-use-output-loss",
    )
    expiry = config["base"]["deadline"]
    if utc_seconds(expiry) < contract.expires_at:
        raise ValueError("CCR deadline precedes host expiry")
    expected["base"]["deadline"] = expiry
    expected["growth"]["window_end"] = expiry
    expected["growth"]["assets"][artifact]["expires_at"] = expiry
    expected["growth"]["verifier_stages"]["check"]["fresh_until"] = expiry
    if config != expected:
        raise ValueError("unsupported native allocation or authority configuration")


def open_store(root: Path) -> Any:
    ccr()
    base: Any = importlib.import_module("ccr.storage.control").ControlStore

    class IntegerSecondStore(base):
        """Explicit test-host UTC-second clock; real DB transactions, no simulated advancement."""

        def now(self) -> str:
            return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

        @contextmanager
        def edit_many(self, keys: list[str], **kwargs: Any) -> Iterator[Any]:
            with super().edit_many(keys, **kwargs) as (objects, database_time):
                current = datetime.fromisoformat(database_time.replace("Z", "+00:00"))
                yield objects, current.replace(microsecond=0).isoformat()

    return IntegerSecondStore(root, "")


def next_task(
    store: Any, run_id: str, worker: str, *, fail_after: str | None = None
) -> dict[str, Any]:
    engine = ccr()
    plan = engine.plan(store, run_id)
    if plan["chosen"] is None:
        raise ValueError("CCR has no funded eligible task")
    trial = engine.step(store, run_id, apply=True, expected_revision=plan["revision"])["trial"]
    if fail_after == "task-created":
        raise RuntimeError("injected crash after task creation")
    receipt = engine.claim(store, run_id, trial["trial_id"], worker=worker, ttl_seconds=300)
    if not receipt["ok"]:
        raise ValueError("CCR lease unavailable")
    if fail_after == "lease-acquired":
        raise RuntimeError("injected crash after lease acquisition")
    return current_task(store, run_id, trial["trial_id"], worker, receipt["fencing_token"])


def current_task(
    store: Any,
    run_id: str,
    trial_id: str,
    worker: str,
    token: int,
    *,
    expected_config: dict[str, Any] | None = None,
    for_execution: bool = True,
) -> dict[str, Any]:
    engine = ccr()
    run = engine.load(store, run_id)
    if expected_config is not None:
        normalized = importlib.import_module("ccr.optimizer.growth_model").normalize(
            expected_config
        )
        if run["config"] != normalized:
            raise ValueError("current CCR registration differs from host commitment")
    trial = next(t for t in run["trials"] if t["trial_id"] == trial_id)
    engine.check_lease(trial, store.now(), worker, token)
    allowed = (
        {"leased"} if for_execution else {"leased", "awaiting_result", "awaiting_verification"}
    )
    if trial["state"] not in allowed:
        raise ValueError("CCR work no longer executable")
    return trial


def admit_result(
    store: Any,
    run_id: str,
    trial: dict[str, Any],
    *,
    key: Any,
    source_digest: str,
    artifact: str,
    work: int,
    accepted: bool,
) -> dict[str, Any]:
    engine = ccr()
    current_task(
        store,
        run_id,
        trial["trial_id"],
        trial["worker_id"],
        trial["fencing_token"],
        for_execution=False,
    )
    engine.task_transition(
        store,
        run_id,
        trial["trial_id"],
        worker=trial["worker_id"],
        token=trial["fencing_token"],
        result={"source": source_digest},
        idempotency_key=trial["trial_id"],
    )
    # A packet is not a credential. The host signature below attests only this exact result.
    from importlib.resources import files
    import json

    packet = json.loads(
        files("ccr.data").joinpath("examples/verified_growth/packet.json").read_text()
    )
    packet["packet_id"] = "packet:" + source_digest[:24]
    packet["created_at"] = store.now()
    packet["issuer"]["actor_id"] = trial["worker_id"]
    packet["issuer"]["display_name"] = "Registered finite worker"
    packet["artifacts"][0].update(
        content_sha256=artifact,
        description="Finite checked workflow output",
        uri_or_path="source:" + source_digest,
        artifact_id="artifact:" + artifact[:24],
        kind="json",
        mime_type="application/json",
    )
    packet["summary"] = "Executed finite software check; no cross-context or empirical claim"
    packet["provenance"].update(
        content_sha256=source_digest,
        lineage_note="Scoped host attestation",
        source_refs=["source:" + source_digest],
        origin_kind="verifier",
    )
    packet["evidence"] = [
        dict(
            evidence_id="finite-reference",
            checker="line-set-reference-v1",
            evidence_type="test_result",
            ref="source:" + source_digest,
            status="accepted" if accepted else "rejected",
        )
    ]
    packet["verifier_reports"] = [
        dict(
            report_id="report:" + source_digest[:24],
            provider="host-checker",
            ref="source:" + source_digest,
            accepted=accepted,
            settled=False,
            blocking_residuals=[],
        )
    ]
    packet["pic_interop"]["enabled"] = False
    packet["pic_interop"]["recommended_commands"] = []
    packet["verifiers"] = [
        dict(
            verifier_id="host-checker",
            provider="custom",
            purpose="evidence_route",
            required=True,
            acceptance_criteria=["Exact registered line-set output"],
            command_hint="oasg collective check",
        )
    ]
    packet["metrics"] = dict(reuse_score=0, residual_load=0, hazard_load=0, queue_load=0)
    packet["intent"] = "Record exact finite software output with retained source evidence"
    packet["lineage"] = dict(parents=[], children=[], revision=0, supersedes=[])
    packet["claims"][0].update(
        claim_id="finite-output",
        claim_text=packet["summary"],
        domain="registered finite software domain",
        receiver_family=["registered-worker"],
        claim_type="implementation",
        must_not_be_read_as=["production evidence", "authority grant", "new capability stock"],
    )
    packet["execution_availability"] = dict(
        claim="This result grants no subsequent execution authority",
        mode="analysis_only",
        gates=["fresh host intent", "current scoped lease"],
        side_effect_policy="none",
        rollback="Only local policy state can be restored",
    )
    packet["reuse"].update(
        deprecation_conditions=["expiry", "dependency withdrawal"],
        intended_downstream_uses=["source-bound accounting reconciliation"],
        transport_limits=["receiver A in the registered finite context only; not a credential"],
    )
    packet["risk"]["mitigations"] = [
        "Bounded pure worker",
        "independent exact-output reference",
        "scoped host signature",
    ]
    packet["scope"].update(
        validity_domain="Registered finite line-normalization inputs",
        refresh_conditions=["revalidate inputs, policy, dependencies, expiry and current lease"],
        out_of_scope=[
            "production execution",
            "empirical agent generalization",
            "cross-receiver qualification",
        ],
    )
    ids = importlib.import_module("ccr.ids")

    def sign(value: dict[str, Any]) -> dict[str, Any]:
        return {
            **value,
            "signature_base64": base64.b64encode(key.sign(ids.canonical_bytes(value))).decode(),
        }

    result = sign(
        dict(
            schema_version="ccr.optimizer_result.v1",
            **{
                k: trial[k]
                for k in (
                    "run_id",
                    "trial_id",
                    "target_id",
                    "config_digest",
                    "input_digest",
                    "worker_id",
                    "fencing_token",
                )
            },
            observed_at=store.now(),
            verifier_id="host-checker",
            actual_resources={"work": work},
            accepted=accepted,
            residuals=[],
            packet=packet,
            artifact_sha256=artifact,
        )
    )
    run = engine.load(store, run_id)
    action = run["config"]["growth"]["actions"][trial["growth_action"]]
    receiver = run["config"]["growth"]["receivers"]["A"]
    observation = dict(
        study_id=run["config"]["growth"]["study_id"],
        evidence_mode="observational",
        action_id=trial["growth_action"],
        receiver="A",
        context_sha256=receiver["context_sha256"],
        protocol=receiver["protocol"],
        evaluator=receiver["evaluator"],
        artifact_version="1",
        parents=action["requires"],
        external_inputs=["registered-finite-policy"],
        status="success" if accepted else "failed",
        measured_service={"check": 0},
    )
    envelope = sign(
        dict(
            schema_version="ccr.growth_result.v1",
            result=result,
            observation=observation,
            verifier_id="host-checker",
            worker_id=trial["worker_id"],
        )
    )
    receipt = engine.ingest(store, run_id, envelope)
    return {"envelope": envelope, "admission": receipt}


def utc_seconds(value: str) -> int:
    return int(
        datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()
    )
