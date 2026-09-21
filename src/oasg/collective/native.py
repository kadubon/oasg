"""Fixed optional companion imports; reports cannot select modules or packages."""

from __future__ import annotations

import importlib
import importlib.metadata
from importlib.resources import files
from pathlib import Path
from typing import Any

from oasg.collective.wire import loads, sha

PINS = {
    "ccr": ("collective-capability-runtime", "1.9.0"),
    "oawm": ("observable-agent-workflow-memory", "0.2.0b0"),
    "vek": ("verification-ecology-kit", "1.3.0"),
    "alt": ("alt-foundry-kernel", "0.5.0"),
    "cait": ("cait-certificate-schema", "0.2.0"),
}


def require(name: str) -> None:
    package, expected = PINS[name]
    try:
        actual = importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError as exc:
        raise ValueError(f"optional_dependency_required: {package}=={expected}") from exc
    if actual != expected:
        raise ValueError(f"unsupported_companion_version: {package} {actual}")
    pinned = manifest()[name]
    distribution = importlib.metadata.distribution(package)
    for relative, expected_hash in pinned["files"].items():
        path = Path(str(distribution.locate_file(relative)))
        if not path.is_file() or sha(path.read_bytes()) != expected_hash:
            raise ValueError(f"unsupported_companion_content: {package} {relative}")


def manifest() -> dict[str, Any]:
    value: dict[str, Any] = loads(
        files("oasg.collective").joinpath("resources/companions.json").read_bytes()
    )
    return value


def ccr() -> Any:
    require("ccr")
    return importlib.import_module("ccr.optimizer.engine")


def support() -> dict[str, Any]:
    rows = []
    pinned = manifest()
    for name, (package, expected) in PINS.items():
        try:
            actual = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            actual = None
        problem = None
        if actual == expected:
            try:
                require(name)
            except ValueError as exc:
                problem = str(exc)
        rows.append(
            {
                "companion": name,
                "package": package,
                "expected": expected,
                "installed": actual,
                "compatible_version": actual == expected,
                "content_verified": actual == expected and problem is None,
                "problem": problem,
                "pin": pinned[name],
            }
        )
    return {
        "schema_id": "oasg.collective.support.v1",
        "companions": rows,
        "profile": "finite-normalize-lines-v1",
        "classification": "Alpha",
        "unsupported": [
            "production execution",
            "arbitrary procedures",
            "cross-receiver authority",
            "OAWM qualified.native.ccr_proposal with CCR 1.9.0",
            "distributed OAWM writers",
        ],
        "tested_subset": "registered receiver A; formation-first CCR action order; UTC integer seconds",
        "operationally_observed": False,
        "execution_authorization": False,
        "mutates": False,
    }
