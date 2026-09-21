"""Closed local contracts; original producer bytes never share a signing codec."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Name = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_:.-]+$")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
OASGDigest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
Count = Annotated[int, Field(strict=True, ge=0, le=1_000_000)]
Clock = Annotated[int, Field(strict=True, ge=0, le=2**53 - 1)]
Text = Annotated[str, Field(min_length=1, max_length=4096)]


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Scope(Closed):
    mission: Name
    study: Name
    worker: Name
    receiver: Name
    context: Name
    family: Literal["normalize-lines-v1"] = "normalize-lines-v1"
    evaluator: Literal["line-set-reference-v1"] = "line-set-reference-v1"
    namespace: Name


class Contract(Closed):
    schema_id: Literal["oasg.collective.contract.v1"] = "oasg.collective.contract.v1"
    scope: Scope
    training: Annotated[list[Text], Field(min_length=2, max_length=8)]
    confirmation: Annotated[list[Text], Field(min_length=1, max_length=8)]
    candidate: Literal["indexed", "scan", "skip-last"] = "indexed"
    baseline: Literal["scan"] = "scan"
    patch: Literal["set_routing_policy"] = "set_routing_policy"
    effects: Literal["pure"] = "pure"
    measurement_rule: Literal["membership-probe-plus-registered-control-work-v1"] = "membership-probe-plus-registered-control-work-v1"
    evidence_class: Literal["executed_finite_software", "synthetic"]
    clock: Literal["host-utc-seconds"] = "host-utc-seconds"
    registered_at: Clock
    cutoff: Clock
    expires_at: Clock
    max_work: Annotated[int, Field(strict=True, ge=1, le=1_000_000)]
    efficient_work: Count
    overhead: Count
    verification_budget: Count
    cleanup_budget: Count
    pool: Name
    ccr_registration: Digest
    ccr_revision: Count
    library_digest: OASGDigest
    implementation: Digest
    checker: Digest
    verifier_key: Digest
    execute: Literal[True]
    rollback: Literal["policy-only"] = "policy-only"
    native_versions: Literal["ccr-1.9.0/oawm-0.2.0b0/vek-1.3.0"]

    @field_validator("execute", mode="before")
    @classmethod
    def permission(cls, value: Any) -> Any:
        if type(value) is not bool:
            raise ValueError("explicit Boolean host permission required")
        return value

    @model_validator(mode="after")
    def consistent(self) -> Contract:
        if not self.registered_at <= self.cutoff < self.expires_at:
            raise ValueError("invalid clock interval")
        if self.expires_at - self.registered_at > 1_000_000:
            raise ValueError("native clock horizon exceeded")
        if self.efficient_work >= self.max_work:
            raise ValueError("grade thresholds must be ordered")
        if set(self.training) & set(self.confirmation):
            raise ValueError("confirmation inputs overlap training")
        for inputs in (self.training, self.confirmation):
            if len(inputs) != len(set(inputs)) or any(len(x.splitlines()) > 64 for x in inputs):
                raise ValueError("duplicate or excessive input domain")
        return self


class TaskBinding(Closed):
    run: Name
    task: Name
    trial: Name
    attempt: Name
    worker: Name
    receiver: Name
    arm: Literal["baseline", "candidate", "use", "negative"]
    fencing_token: Annotated[int, Field(strict=True, ge=1, le=1_000_000)]
    revision: Count
    reservation: Name
    input_digest: Digest
    policy_digest: Digest
    lease_start: Clock
    lease_end: Clock


class Measurement(Closed):
    input: Text
    output: Annotated[str, Field(max_length=4096)]
    probes: Count
    trace: Annotated[list[Count], Field(max_length=64)]


class Execution(Closed):
    schema_id: Literal["oasg.collective.execution.v1"] = "oasg.collective.execution.v1"
    contract: Digest
    binding: TaskBinding
    variant: Literal["scan", "indexed", "skip-last"]
    implementation: Digest
    evidence_class: Literal["executed_finite_software", "synthetic"]
    split: Literal["training", "confirmation", "use"]
    observed_at: Clock
    received_at: Clock
    measurements: Annotated[list[Measurement], Field(min_length=1, max_length=8)]
    external_effects: Literal[0]
    verification: Literal["positive", "negative", "timeout", "invalid", "inconclusive", "pending", "unavailable"]
    complete: bool
    cost_id: Name
    work: Count
    signature: Annotated[str, Field(max_length=256)]

    @field_validator("external_effects", mode="before")
    @classmethod
    def effects_count(cls, value: Any) -> Any:
        if type(value) is not int:
            raise ValueError("effect count must be an integer, not Boolean")
        return value


class Source(Closed):
    schema_id: Literal["oasg.collective.source.v1"] = "oasg.collective.source.v1"
    original: Annotated[str, Field(min_length=1, max_length=100_000)]
    sha256: Digest
    producer_digest: Digest

    def execution(self) -> Execution:
        if sha(self.original.encode()) != self.sha256:
            raise ValueError("source bytes changed")
        result = Execution.model_validate(loads(self.original.encode()))
        if digest(result) != self.producer_digest:
            raise ValueError("producer digest changed")
        return result


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def encoded(value: Any) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def digest(value: Any) -> str:
    return sha(encoded(value))


def loads(raw: bytes) -> Any:
    if len(raw) > 2_000_000:
        raise ValueError("input byte bound")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def number(value: str) -> Any:
        raise ValueError("only bounded integers supported")

    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                            parse_float=number, parse_constant=number)
    except (RecursionError, UnicodeError) as exc:
        raise ValueError("invalid encoding or nesting") from exc
    pending = [(result, 0)]
    count = 0
    while pending:
        value, depth = pending.pop()
        count += 1
        if depth > 24 or count > 50_000:
            raise ValueError("structural input bound")
        if isinstance(value, dict):
            pending.extend((v, depth + 1) for v in value.values())
        elif isinstance(value, list):
            pending.extend((v, depth + 1) for v in value)
        elif isinstance(value, str) and len(value) > 100_000:
            raise ValueError("string bound")
        elif type(value) is int and abs(value) > 2**63 - 1:
            raise ValueError("integer bound")
    return result
