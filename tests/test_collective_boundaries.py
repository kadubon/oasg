"""Counterexamples are re-signed/resealed where necessary, not just broken hashes."""

import base64
from copy import deepcopy

import pytest
from hypothesis import given, strategies as st

from oasg.collective.check import check_projection, check_trial
from oasg.collective.evidence import checked_execution, eligibility, reference
from oasg.collective.projection import project
from oasg.collective.trial import compare
from oasg.collective.wire import Contract, Source, digest, encoded, loads, sha
from oasg.collective.worker import execute
from oasg.ledger import seal_records
from test_collective import contract_key, sources


@pytest.fixture(scope="module")
def evidence():
    contract, key, public = contract_key()
    pair = sources(contract, key)
    return contract, key, public, pair


def signed(original, key, modify):
    value = original.execution().model_dump(exclude={"signature"})
    modify(value)
    value["signature"] = base64.b64encode(key.sign(encoded(value))).decode()
    raw = encoded(value)
    return Source(original=raw.decode(), sha256=sha(raw), producer_digest=digest(value))


@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'1.0', b'NaN', b'Infinity', b'1e3',
    b'"\xff"', b'9223372036854775808', b'['*26+b'0'+b']'*26, b'['*1100+b']'*1100,
    b'"'+b'x'*100001+b'"', b'['+b'0,'*50001+b'0]', b' '*2000001], ids=[str(i) for i in range(12)])
def test_bounded_parser(raw):
    with pytest.raises(ValueError):
        loads(raw)


@pytest.mark.parametrize("changes", [
    {"execute": 1}, {"execute": "true"}, {"execute": False}, {"new_authority": True},
    {"max_work": True}, {"max_work": 0}, {"max_work": 1000001}, {"efficient_work": 100},
    {"verification_budget": -1}, {"training": ["same", "same"]},
    {"training": ["z\ny\nx\nw\nv\nu\nt\ns", "other"]},
    {"confirmation": ["x\n"*65]}, {"expires_at": 0}, {"registered_at": 0},
    {"native_versions": "latest"}, {"effects": "external"}, {"candidate": "eval(user)"},
])
def test_contract_rejections(evidence, changes):
    with pytest.raises(ValueError):
        Contract.model_validate(evidence[0].model_dump() | changes)


@pytest.mark.parametrize("field,value", [
    ("contract", "0"*64), ("implementation", "0"*64), ("work", 0),
    ("external_effects", False), ("external_effects", 1), ("complete", False),
    ("observed_at", 0), ("received_at", 2**40), ("variant", "skip-last"),
    ("verification", "negative"), ("split", "training"),
])
def test_even_signed_invalid_execution_rejected(evidence, field, value):
    contract, key, public, pair = evidence
    source = signed(pair[1], key, lambda v: v.update({field: value}))
    with pytest.raises(ValueError):
        checked_execution(contract, source, public)


@pytest.mark.parametrize("field,value", [
    ("worker", "other"), ("receiver", "B"), ("policy_digest", "0"*64),
    ("input_digest", "0"*64), ("lease_end", 0), ("fencing_token", 0),
])
def test_binding_rejections(evidence, field, value):
    contract, key, public, pair = evidence
    source = signed(pair[1], key, lambda v: v["binding"].update({field: value}))
    with pytest.raises(ValueError):
        checked_execution(contract, source, public)


@pytest.mark.parametrize("alter", [
    lambda v: v["measurements"][0].update(output="forged output"),
    lambda v: v["measurements"][0].update(probes=0),
    lambda v: v["measurements"][0].update(trace=[0]),
    lambda v: v["measurements"][0].update(input="substituted"),
    lambda v: v.update(measurements=[]),
])
def test_exact_source_oracle(evidence, alter):
    contract, key, public, pair = evidence
    with pytest.raises(ValueError):
        checked_execution(contract, signed(pair[1], key, alter), public)


def test_source_authentication_and_bytes(evidence):
    contract, key, public, pair = evidence
    source = pair[1]
    with pytest.raises(ValueError, match="bytes"):
        source.model_copy(update={"original": source.original+" "}).execution()
    with pytest.raises(ValueError, match="producer"):
        source.model_copy(update={"producer_digest": "0"*64}).execution()
    with pytest.raises(ValueError, match="verifier"):
        checked_execution(contract, source, b'x'*32)
    altered = loads(source.original.encode())
    altered["signature"] = "unsigned"
    raw = encoded(altered)
    with pytest.raises(ValueError, match="signature"):
        checked_execution(contract, Source(original=raw.decode(), sha256=sha(raw), producer_digest=digest(altered)), public)
    other = contract.model_copy(update={"checker": "0"*64})
    modified = signed(source, key, lambda v: v.update(contract=digest(other)))
    with pytest.raises(ValueError, match="checker"):
        checked_execution(other, modified, public)


@pytest.mark.parametrize("status", ["timeout", "invalid", "inconclusive", "pending", "unavailable"])
def test_completed_nonpositive_work_never_positive_service(evidence, status):
    contract, key, public, pair = evidence
    source = signed(pair[1], key, lambda v: v.update(verification=status))
    checked = checked_execution(contract, source, public)
    assert checked.work == 10
    assert not eligibility(contract, checked)["runner_execution_support"]
    result = project(contract, source, public)
    assert check_projection(contract, result, public)["ok"]
    assert result["records"][0]["payload"]["dimensions"]["budget"] == "blocked"


@pytest.mark.parametrize("change", [
    lambda r: r.update(extra=True), lambda r: r.update(contract="0"*64),
    lambda r: r.update(records=[]), lambda r: r.update(field_map={}),
    lambda r: r["dimensions"].update(execution_authorization=True),
])
def test_projection_report_tampering(evidence, change):
    contract, _, public, pair = evidence
    result = project(contract, pair[1], public)
    change(result)
    with pytest.raises(ValueError):
        check_projection(contract, result, public)


@pytest.mark.parametrize("change", [
    lambda r: r.update(extra=True), lambda r: r.update(collector_id="remote"),
    lambda r: r.update(event_id="other-attempt"), lambda r: r.update(parent_event_ids=["foreign"]),
    lambda r: r["payload"].update(extra=True), lambda r: r["payload"].update(repair_receipts=[{}]),
    lambda r: r["payload"].update(proof_obligation_receipts=[]),
    lambda r: r["payload"].update(positive_evidence=[]),
    lambda r: r["payload"]["policy"].update(workflow_promotion_authorized=True),
    lambda r: r["payload"]["dimensions"].update(budget="blocked"),
    lambda r: r["payload"]["model_event"].update(work=0),
])
def test_validly_resealed_projection_cannot_invent_evidence(evidence, change):
    contract, _, public, pair = evidence
    result = project(contract, pair[1], public)
    change(result["records"][0])
    result["records"] = seal_records(result["records"])
    with pytest.raises(ValueError):
        check_projection(contract, result, public)


@pytest.mark.parametrize("change", [
    lambda t: t.update(extra=1), lambda t: t.update(execution_authorization=True),
    lambda t: t.update(collective_benefit=1), lambda t: t.update(contract="0"*64),
    lambda t: t["projections"].reverse(), lambda t: t["work"].update(candidate=0),
    lambda t: t["mutation"].update(action_id="external"),
    lambda t: t["active"].update(status="rejected_active_promotion"),
    lambda t: t["comparison"].update(candidate_mutation_id="other"),
    lambda t: t["workload"].update(input_hashes=[]),
])
def test_trial_reconstructs_legacy_decisions(evidence, change):
    contract, _, public, pair = evidence
    trial = compare(contract, *pair, public)
    assert check_trial(contract, trial, public)["ok"]
    changed = deepcopy(trial)
    change(changed)
    with pytest.raises(ValueError):
        check_trial(contract, changed, public)


@given(st.lists(st.text(alphabet="abcd", min_size=1, max_size=8), min_size=1, max_size=30))
def test_independent_reference_property(lines):
    text = "\n".join(lines)
    assert execute(text, "scan").output == execute(text, "indexed").output == reference(text)
    assert execute(text, "indexed").probes == len(lines)
