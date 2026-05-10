"""Plain Python adapter pattern for OASG.

Run with:
    uv run python examples/framework_adapters/plain_python_adapter.py --out out/plain.jsonl
"""

from __future__ import annotations

import argparse
from pathlib import Path

from oasg.adapters import invoke_function
from oasg.constants import ACTION_CLASSES, REQUIRED_DIMENSIONS
from oasg.ingest import model_event_record
from oasg.io import write_jsonl
from oasg.ledger import seal_records


def toy_model(prompt: str) -> str:
    return f"observed response for: {prompt}"


def build_event(prompt: str) -> dict[str, object]:
    model_event = invoke_function(toy_model, prompt, provider="plain_python", model="toy_model")
    action_grades = {action: "acceptable" for action in ACTION_CLASSES}
    action_grades["emit_claim"] = "blocked"
    action_grades["promote_workflow"] = "blocked"
    return model_event_record(
        model_event,
        event_id="evt_plain_python_model_call",
        workflow_id="plain_python_agent",
        component_id="model_call",
        dimensions={dimension: "acceptable" for dimension in REQUIRED_DIMENSIONS},
        action_grades=action_grades,
        protected_debt={dimension: "acceptable" for dimension in REQUIRED_DIMENSIONS},
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Write one OASG ledger from a plain Python call.")
    parser.add_argument("--out", type=Path, default=Path("examples/framework_adapters/out/plain.jsonl"))
    args = parser.parse_args()
    write_jsonl(args.out, seal_records([build_event("summarize local state")]))
    print(args.out)


if __name__ == "__main__":
    main()
