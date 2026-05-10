"""Local subprocess adapter example.

This adapter is not used by default tests. It is provided as a pattern for wrapping arbitrary
model or tool processes while keeping the trusted OASG core provider-neutral.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence

from oasg.adapters.contracts import ModelEvent
from oasg.canonical import domain_hash
from oasg.runners import validate_command_argv


def invoke_command(command: Sequence[str], prompt: str, *, timeout_seconds: int = 30) -> ModelEvent:
    argv = tuple(command)
    validate_command_argv(argv)
    completed = subprocess.run(
        list(argv),
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout_seconds,
        check=False,
    )
    return ModelEvent(
        provider="local_command",
        model=" ".join(command),
        prompt_hash=domain_hash("OASG:v1.0:adapter_prompt", prompt),
        output_hash=domain_hash("OASG:v1.0:adapter_output", completed.stdout),
        resources={"returncode": completed.returncode},
        metadata={"stderr_hash": domain_hash("OASG:v1.0:adapter_stderr", completed.stderr)},
    )
