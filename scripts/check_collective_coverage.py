"""Enforce requested statement and branch gates separately for every new module."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    raw = json.loads(args.report.read_text(encoding="utf-8"))
    summaries = {
        Path(name.replace("\\", "/")).name: value["summary"]
        for name, value in raw["files"].items()
        if "/oasg/collective/" in "/" + name.replace("\\", "/")
    }
    rows = []
    for path in sorted(Path("src/oasg/collective").glob("*.py")):
        summary = summaries.get(path.name)
        if summary is None:
            rows.append({"module": path.name, "ok": False, "reason": "missing coverage"})
            continue
        statements = summary["num_statements"]
        branches = summary["num_branches"]
        statement_percent = 100 * summary["covered_lines"] / statements if statements else 100
        branch_percent = 100 * summary["covered_branches"] / branches if branches else 100
        rows.append(
            {
                "module": path.name,
                "statements": statements,
                "branches": branches,
                "statement_percent": statement_percent,
                "branch_percent": branch_percent,
                "combined_percent": summary["percent_covered"],
                "ok": statement_percent >= 95 and branch_percent >= 90,
            }
        )
    report = {
        "statement_minimum": 95,
        "branch_minimum": 90,
        "modules": rows,
        "ok": bool(rows) and all(row["ok"] for row in rows),
    }
    text = json.dumps(report, indent=2) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(text, end="")
    raise SystemExit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
