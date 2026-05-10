"""Custom Python callable adapter example."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from oasg.adapters.contracts import ModelEvent
from oasg.canonical import canonical_json_dumps, domain_hash


ModelFunction = Callable[[str], str | Mapping[str, Any]]


def invoke_function(
    function: ModelFunction,
    prompt: str,
    *,
    provider: str = "python_function",
    model: str = "callable",
) -> ModelEvent:
    """Invoke a Python callable and return only observable hashes and metadata.

    The callable output is not trusted as an evaluator. It is treated as data that can be
    recorded into an event ledger and checked later by ordinary OASG gates.
    """

    output = function(prompt)
    output_text = canonical_json_dumps(dict(output)) if isinstance(output, Mapping) else output
    return ModelEvent(
        provider=provider,
        model=model,
        prompt_hash=domain_hash("OASG:v1.0:adapter_prompt", prompt),
        output_hash=domain_hash("OASG:v1.0:adapter_output", output_text),
        resources={},
        metadata={"output_type": type(output).__name__},
    )
