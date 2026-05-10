"""OpenAI-compatible HTTP adapter example.

This module has no provider dependency and is never used by default tests. Calling it performs
network I/O by explicit user choice. The returned event is observation data only; it cannot promote
workflow mutations.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from oasg.adapters.contracts import ModelEvent
from oasg.canonical import canonical_json_dumps, domain_hash


@dataclass(frozen=True)
class OpenAICompatibleConfig:
    endpoint: str
    model: str
    api_key_env: str | None = None
    timeout_seconds: int = 30
    extra_headers: dict[str, str] = field(default_factory=dict)
    extra_body: dict[str, Any] = field(default_factory=dict)
    allow_insecure_http: bool = False
    allow_localhost: bool = False


def invoke_openai_compatible(
    prompt: str,
    config: OpenAICompatibleConfig,
    *,
    api_key: str | None = None,
) -> ModelEvent:
    _validate_endpoint(config)
    headers = {"Content-Type": "application/json", **config.extra_headers}
    resolved_key = api_key or (os.environ.get(config.api_key_env) if config.api_key_env else None)
    if resolved_key:
        headers.setdefault("Authorization", f"Bearer {resolved_key}")

    body = {
        "model": config.model,
        "messages": [{"role": "user", "content": prompt}],
        **config.extra_body,
    }
    body_bytes = canonical_json_dumps(body).encode("utf-8")
    request = Request(config.endpoint, data=body_bytes, headers=headers, method="POST")
    start = time.monotonic()
    with urlopen(request, timeout=config.timeout_seconds) as response:
        response_body = response.read()
        status = response.status
    latency_ms = int((time.monotonic() - start) * 1000)
    output_text = response_body.decode("utf-8", errors="replace")
    return ModelEvent(
        provider="openai_compatible_http",
        model=config.model,
        prompt_hash=domain_hash("OASG:v1.0:adapter_prompt", prompt),
        output_hash=domain_hash("OASG:v1.0:adapter_output", output_text),
        resources={"latency_ms": latency_ms, "http_status": status, "response_bytes": len(response_body)},
        metadata={"endpoint_hash": domain_hash("OASG:v1.0:adapter_endpoint", config.endpoint)},
    )


def parse_response_json(event_payload: str) -> Any:
    """Helper for caller-side parsing outside the trusted OASG gate."""

    return json.loads(event_payload)


def _validate_endpoint(config: OpenAICompatibleConfig) -> None:
    parsed = urlparse(config.endpoint)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise ValueError("endpoint must be an absolute HTTP(S) URL")
    if parsed.scheme == "http" and not config.allow_insecure_http:
        raise ValueError("plain HTTP endpoint requires allow_insecure_http=True")
    host = parsed.hostname.lower()
    if host in {"localhost", "127.0.0.1", "::1"} and not config.allow_localhost:
        raise ValueError("localhost endpoint requires allow_localhost=True")
    try:
        address = ip_address(host)
    except ValueError:
        return
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
    ) and not config.allow_localhost:
        raise ValueError("private or local IP endpoint requires allow_localhost=True")
