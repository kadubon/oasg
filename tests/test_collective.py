"""Independent finite measurements and admission counterexamples."""

from __future__ import annotations

import importlib
import time

import pytest

from oasg.canonical import receipt_hash
from oasg.collective.evidence import checker_digest
from oasg.collective.trial import compare, run_worker
from oasg.collective.wire import Contract, Scope, TaskBinding, digest, sha
from oasg.collective.worker import implementation_digest
from oasg.policy_state import WorkflowPolicyState


def contract_key(**changes):
    ed = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ed25519")
    key = ed.Ed25519PrivateKey.generate()
    serialization = importlib.import_module("cryptography.hazmat.primitives.serialization")
    public = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    now = int(time.time())
    raw = dict(
        scope=Scope(
            mission="finite",
            study="study",
            worker="worker",
            receiver="A",
            context="finite",
            namespace="disposable",
        ),
        training=["z\na", "c\nb"],
        confirmation=["z\ny\nx\nw\nv\nu\nt\ns"],
        evidence_class="executed_finite_software",
        registered_at=now - 2,
        cutoff=now - 1,
        expires_at=now + 600,
        max_work=100,
        efficient_work=12,
        overhead=2,
        verification_budget=4,
        cleanup_budget=1,
        pool="pool",
        ccr_registration="0" * 64,
        ccr_revision=0,
        library_digest=receipt_hash(WorkflowPolicyState.default().to_dict()),
        implementation=implementation_digest(),
        checker=checker_digest(),
        verifier_key=sha(public),
        execute=True,
        native_versions="ccr-1.9.0/oawm-0.2.0b0/vek-1.3.0",
    )
    return Contract(**(raw | changes)), key, public


def sources(contract, key):
    now = int(time.time())
    result = []
    for arm, variant in [("baseline", "scan"), ("candidate", contract.candidate)]:
        binding = TaskBinding(
            run="run",
            task="task",
            trial="trial",
            attempt=arm,
            worker="worker",
            receiver="A",
            arm=arm,
            fencing_token=1,
            revision=1,
            reservation="reserve",
            input_digest=digest(contract.confirmation),
            policy_digest=digest({"variant": variant}),
            lease_start=now,
            lease_end=now + 300,
        )
        result.append(run_worker(contract, binding, split="confirmation", key=key, now=now))
    return result


def test_executed_gate_and_lifecycle():
    contract, key, public = contract_key()
    report = compare(contract, *sources(contract, key), public)
    assert report["work"] == {"baseline": 30, "candidate": 10}
    assert report["gate"]["status"] == "safe_promotion"
    assert report["active"]["status"] == "active_promoted"


@pytest.mark.parametrize(
    "changes",
    [
        {"evidence_class": "synthetic"},
        {"candidate": "scan"},
        {"candidate": "skip-last"},
        {"overhead": 90},
        {"efficient_work": 5},
    ],
)
def test_no_manufactured_improvement(changes):
    contract, key, public = contract_key(**changes)
    report = compare(contract, *sources(contract, key), public)
    assert report["active"]["status"] == "rejected_active_promotion"
