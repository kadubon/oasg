from __future__ import annotations

import pytest

from oasg.adapters import invoke_function
from oasg.adapters.local_command import invoke_command
from oasg.adapters.openai_compatible import OpenAICompatibleConfig, invoke_openai_compatible


def test_python_function_adapter_emits_hash_only_event() -> None:
    event = invoke_function(lambda prompt: {"echo": prompt}, "hello", model="echo")
    payload = event.to_payload()
    assert payload["provider"] == "python_function"
    assert payload["model"] == "echo"
    assert payload["prompt_hash"].startswith("sha256:")
    assert payload["output_hash"].startswith("sha256:")


def test_openai_compatible_adapter_rejects_localhost_by_default() -> None:
    with pytest.raises(ValueError, match="localhost"):
        invoke_openai_compatible(
            "hello",
            OpenAICompatibleConfig(endpoint="https://localhost:8000/v1/chat/completions", model="x"),
        )


def test_local_command_adapter_reuses_runner_safety_policy() -> None:
    with pytest.raises(ValueError):
        invoke_command(("echo hello",), "prompt")
