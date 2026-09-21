"""Reject obvious secrets/private workstation paths and unexpected release contents."""

import json
from pathlib import Path
import re
import subprocess


def main():
    paths = subprocess.check_output(["git", "ls-files", "-z"], text=True).split("\0")
    patterns = [
        re.compile(rb"(?:ghp_|github_pat_)[A-Za-z0-9_]{30,}"),
        re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        re.compile(rb"[A-Za-z]:[\\/]Users[\\/][^\s\"']+"),
        re.compile(rb"/(?:home|Users)/[^\s\"']+"),
    ]
    violations = []
    inspected = 0
    for name in paths:
        if not name:
            continue
        path = Path(name)
        if not path.is_file():
            continue
        data = path.read_bytes()
        inspected += 1
        if any(p.search(data) for p in patterns):
            violations.append(name)
    print(json.dumps({"ok": not violations, "files_checked": inspected,
                      "violations": violations,
                      "scope": "Obvious token/key/workstation patterns; not exhaustive secret detection"}))
    if violations:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
