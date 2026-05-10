from __future__ import annotations

import pytest

from oasg.canonical import canonical_json_dumps, domain_hash, framed_bytes


def test_canonical_json_orders_keys_and_uses_no_spaces() -> None:
    assert canonical_json_dumps({"b": 2, "a": ["x", True]}) == '{"a":["x",true],"b":2}'


def test_canonical_json_rejects_float_values() -> None:
    with pytest.raises(TypeError):
        canonical_json_dumps({"value": 0.1})


def test_domain_hash_uses_length_framing() -> None:
    assert framed_bytes(("ab", "c")) != framed_bytes(("a", "bc"))
    assert domain_hash("domain", "payload") == domain_hash("domain", "payload")
    assert domain_hash("domain", "payload") != domain_hash("other", "payload")
