"""Independent reconstruction of finite work and scoped host attestations."""

from __future__ import annotations

import base64
import importlib
from pathlib import Path
from typing import Any

from oasg.collective.wire import Contract, Execution, Source, digest, encoded, sha


def checker_digest() -> str:
    # Bind the whole installed checking/lifecycle implementation, including its schemas.
    root = Path(__file__).parent.parent
    return digest(
        {
            path.relative_to(root).as_posix(): sha(path.read_bytes().replace(b"\r\n", b"\n"))
            for path in sorted(root.rglob("*"))
            if path.is_file() and path.suffix in {".py", ".json"}
        }
    )


def reference(text: str) -> str:
    # Separate invariant implementation: sorted adjacent-group elimination.
    ordered = sorted(text.splitlines())
    return "\n".join(x for i, x in enumerate(ordered) if i == 0 or x != ordered[i - 1])


def checked_execution(contract: Contract, source: Source, public_key: bytes) -> Execution:
    result = source.execution()
    if sha(public_key) != contract.verifier_key:
        raise ValueError("unregistered verifier")
    payload = result.model_dump(exclude={"signature"})
    ed = importlib.import_module("cryptography.hazmat.primitives.asymmetric.ed25519")
    try:
        ed.Ed25519PublicKey.from_public_bytes(public_key).verify(
            base64.b64decode(result.signature, validate=True), encoded(payload)
        )
    except Exception as exc:
        raise ValueError("invalid scoped host signature") from exc
    if result.contract != digest(contract) or result.implementation != contract.implementation:
        raise ValueError("contract or implementation binding mismatch")
    if contract.checker != checker_digest():
        raise ValueError("unregistered checker implementation")
    binding = result.binding
    if binding.worker != contract.scope.worker or binding.receiver != contract.scope.receiver:
        raise ValueError("worker or receiver mismatch")
    if binding.policy_digest != digest({"variant": result.variant}):
        raise ValueError("policy substitution")
    if (
        not contract.registered_at
        <= binding.lease_start
        <= result.observed_at
        <= result.received_at
        < min(binding.lease_end, contract.expires_at)
    ):
        raise ValueError("expired evidence or incompatible source clocks")
    if result.split == "training":
        inputs = contract.training
        if result.observed_at > contract.cutoff:
            raise ValueError("post-cutoff training")
    else:
        inputs = contract.confirmation
        if result.observed_at <= contract.cutoff:
            raise ValueError("confirmation before freeze")
    if [m.input for m in result.measurements] != inputs or binding.input_digest != digest(inputs):
        raise ValueError("missing, reordered or substituted input coverage")
    expected_variant = "scan" if binding.arm == "baseline" else contract.candidate
    if result.variant != expected_variant:
        raise ValueError("unregistered variant")
    total = 0
    correct = True
    for measurement in result.measurements:
        lines = measurement.input.splitlines()
        visited: list[str] = []
        expected = []
        limit = len(lines) - (result.variant == "skip-last")
        for line in lines[:limit]:
            if result.variant == "indexed":
                expected.append(1)
            else:
                expected.append(visited.index(line) + 1 if line in visited else len(visited))
            if line not in visited:
                visited.append(line)
        if measurement.trace != expected or measurement.probes != sum(expected):
            raise ValueError("forged physical work counters")
        total += sum(expected)
        correct &= measurement.output == reference(measurement.input)
    if result.work != total + contract.overhead:
        raise ValueError("missing or repeated overhead costs")
    if result.verification == "positive" and (not correct or not result.complete):
        raise ValueError("false positive or partial workload")
    if result.verification == "negative" and correct:
        raise ValueError("unsubstantiated contradiction")
    return result


def eligibility(contract: Contract, result: Execution) -> dict[str, Any]:
    supported = (
        contract.evidence_class == result.evidence_class == "executed_finite_software"
        and result.verification == "positive"
        and result.complete
        and result.work <= contract.max_work
    )
    return {
        "runner_execution_support": supported,
        "evidence_class": result.evidence_class,
        "source_authentication": "scoped_host_attestation",
        "verification_work_status": result.verification,
        "execution_authorization": False,
        "statistical_support": None,
    }
