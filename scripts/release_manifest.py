"""Bind qualified distribution hashes to the exact accepted source and contracts."""

import hashlib
import json
from pathlib import Path
import subprocess
import tomllib


def main():
    version = tomllib.loads(Path("pyproject.toml").read_text())["project"]["version"]
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    qualification = json.loads(Path("release-evidence/qualification.json").read_text())
    assert qualification["ok"] and not qualification["public_pypi"]
    artifacts = qualification["artifacts"]
    for row in artifacts:
        assert (
            hashlib.sha256((Path("dist") / row["filename"]).read_bytes()).hexdigest()
            == row["sha256"]
        )
    resources = Path("src/oasg/collective/resources")
    report = {
        "version": version,
        "source_commit": commit,
        "producer_workflow": "kadubon/oasg/.github/workflows/release.yml",
        "artifacts": artifacts,
        "resources": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(resources.glob("*.json"))
        },
        "claim": "Checksums and executed finite qualification; not source-build attestation or empirical AI evidence",
    }
    Path("release-evidence/manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    Path("release-evidence/SHA256SUMS").write_text(
        "".join(row["sha256"] + "  " + row["filename"] + "\n" for row in artifacts)
    )


if __name__ == "__main__":
    main()
