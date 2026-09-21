"""Qualify exact archives in fresh external environments; never rebuild an artifact."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

BLOCK_NETWORK = """import os, socket
if os.environ.get("OASG_OFFLINE_CHECK") == "1":
    def denied(*args, **kwargs):
        raise RuntimeError("offline qualification blocks runtime network")
    for name in ("connect", "connect_ex", "sendto"):
        setattr(socket.socket, name, denied)
    for name in ("create_connection", "getaddrinfo"):
        setattr(socket, name, denied)
"""


def run(argv, **kwargs):
    return subprocess.run(argv, check=True, text=True, capture_output=True, **kwargs).stdout


def archive_check(path):
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            assert all(n.startswith(("oasg/", "oasg-")) for n in names)
    else:
        with tarfile.open(path) as archive:
            names = archive.getnames()
    forbidden = {".git", ".tmp", ".venv", "__pycache__", ".env"}
    assert not any(forbidden.intersection(Path(n).parts) for n in names)
    assert any("LICENSE" in n for n in names)
    assert any(n.endswith("collective/resources/companions.json") for n in names)
    assert (
        sum("collective/resources/collective-" in n and n.endswith(".schema.json") for n in names)
        == 8
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    parser.add_argument("--requirements", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--public", action="store_true")
    args = parser.parse_args()
    checkout = Path(__file__).resolve().parent.parent
    artifacts = sorted(args.dist.resolve().glob("*"))
    artifacts = [p for p in artifacts if p.suffix == ".whl" or p.name.endswith(".tar.gz")]
    assert len(artifacts) == 2
    rows = []
    for artifact in artifacts:
        archive_check(artifact)
        expected_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory(prefix="oasg-installed-") as temp:
            root = Path(temp)
            venv = root / "env"
            run(["uv", "venv", "--seed", "--python", sys.executable, str(venv)], cwd=root)
            python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            run(
                [
                    "uv",
                    "pip",
                    "install",
                    "--python",
                    str(python),
                    "--no-cache",
                    "--require-hashes",
                    "-r",
                    str(args.requirements.resolve()),
                ],
                cwd=root,
            )
            selected = artifact
            if args.public:
                downloaded = root / "download"
                command = [
                    str(python),
                    "-m",
                    "pip",
                    "download",
                    "--no-cache-dir",
                    "--no-deps",
                    "--index-url",
                    "https://pypi.org/simple",
                    "--dest",
                    str(downloaded),
                ]
                command += (
                    ["--only-binary=:all:"] if artifact.suffix == ".whl" else ["--no-binary=:all:"]
                )
                run([*command, "oasg==" + args.version], cwd=root)
                selected = downloaded / artifact.name
                assert hashlib.sha256(selected.read_bytes()).hexdigest() == expected_hash
            run(
                [str(python), "-m", "pip", "install", "--no-cache-dir", "--no-deps", str(selected)],
                cwd=root,
            )
            run([str(python), "-m", "pip", "check"], cwd=root)
            site = Path(
                run(
                    [str(python), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
                    cwd=root,
                ).strip()
            )
            (site / "sitecustomize.py").write_text(BLOCK_NETWORK, encoding="utf-8")
            script = root / "installed_checks.py"
            shutil.copyfile(checkout / "scripts/installed_checks.py", script)
            env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "VIRTUAL_ENV"}}
            env["OASG_OFFLINE_CHECK"] = "1"
            output = run(
                [str(python), str(script), "--version", args.version, "--checkout", str(checkout)],
                cwd=root,
                env=env,
            )
            checks = json.loads(output.strip().splitlines()[-1])
            rows.append({"filename": artifact.name, "sha256": expected_hash, "checks": checks})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps({"ok": True, "public_pypi": args.public, "artifacts": rows}, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
