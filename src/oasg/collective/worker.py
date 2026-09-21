"""Finite built-in executor. No code, plugin, path or argv comes from evidence."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from oasg.collective.wire import Measurement, encoded, loads, sha


def implementation_digest() -> str:
    return sha(Path(__file__).read_bytes().replace(b"\r\n", b"\n"))


def execute(text: str, variant: str) -> Measurement:
    if not isinstance(text, str) or not 1 <= len(text) <= 4096:
        raise ValueError("bounded nonempty input required")
    lines = text.splitlines()
    if len(lines) > 64 or variant not in {"scan", "indexed", "skip-last"}:
        raise ValueError("unsupported work")
    seen: list[str] = []
    index: set[str] = set()
    trace = []
    for line in lines[:-1] if variant == "skip-last" else lines:
        probes = 0
        present = False
        if variant == "indexed":
            probes += 1
            present = line in index
        else:
            for previous in seen:
                probes += 1
                if previous == line:
                    present = True
                    break
        if not present:
            seen.append(line)
            index.add(line)
        trace.append(probes)
    return Measurement(input=text, output="\n".join(sorted(seen)), probes=sum(trace), trace=trace)


def main() -> None:
    request: Any = loads(sys.stdin.buffer.read(100_001))
    if not isinstance(request, dict) or set(request) != {"inputs", "variant"}:
        raise ValueError("invalid worker request")
    if not isinstance(request["inputs"], list) or not 1 <= len(request["inputs"]) <= 8:
        raise ValueError("bounded work list required")
    rows = [execute(text, request["variant"]).model_dump() for text in request["inputs"]]
    sys.stdout.buffer.write(encoded({"implementation": implementation_digest(), "rows": rows}))


if __name__ == "__main__":
    main()
