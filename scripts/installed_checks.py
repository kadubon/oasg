"""Offline checks executed by the installed interpreter outside the checkout."""

import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--checkout", type=Path, required=True)
    args = parser.parse_args()
    import oasg
    from oasg.collective.feedback import reconcile
    from oasg.collective.native import support
    from oasg.collective.replay import replay
    from oasg.collective.runtime import example

    assert importlib.metadata.version("oasg") == args.version
    assert not Path(oasg.__file__).resolve().is_relative_to(args.checkout.resolve())
    assert os.environ["OASG_OFFLINE_CHECK"] == "1"
    import socket

    try:
        socket.create_connection(("example.invalid", 443))
    except RuntimeError as exc:
        assert "offline" in str(exc)
    else:
        raise AssertionError("runtime network blocker absent")
    executable = Path(sys.executable).parent / ("oasg.exe" if os.name == "nt" else "oasg")
    for command in (
        ["doctor"],
        ["demo", "quickstart", "--out", "legacy"],
        ["conformance", "run", "conformance"],
        ["collective", "support"],
    ):
        result = subprocess.run(
            [str(executable), *command], capture_output=True, text=True, timeout=60
        )
        if result.returncode:
            raise RuntimeError(result.stdout[-4000:] + result.stderr[-8000:])
    assert all(row["content_verified"] for row in support()["companions"])
    rows = []
    for negative, expected in ((False, 62), (True, 70)):
        root = Path("negative" if negative else "positive")
        report = example(root, negative_control=negative)
        assert report["gate"] == "safe_promotion"
        assert report["active"] == "active_promoted"
        assert report["second_cycle"]["process_id"] != os.getpid()
        assert report["second_cycle"]["applied"]["policy"] == "indexed"
        assert not report["second_cycle"]["receiver_B_eligible"]
        assert not report["withdrawal"]["memory_eligible"]
        checked = replay(root)
        assert checked["actual_registered_work"] == expected
        assert checked["reward_added"] == checked["asset_stock_added"] == 0
        assert not checked["execution_authorization"]
        assert reconcile(root)["idempotent"]
        if negative:
            assert not report["negative_control"]["outcome"]["service"]
            assert not report["negative_control"]["eligible_after_check"]
        rows.append({"negative_control": negative, "physical_work": expected})
    print(
        json.dumps(
            {
                "ok": True,
                "version": args.version,
                "offline": True,
                "installed_outside_checkout": True,
                "cycles": rows,
            }
        )
    )


if __name__ == "__main__":
    main()
