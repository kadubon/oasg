from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

from oasg.io import read_json
from oasg.ledger import verify_jsonl


ROOT = Path(__file__).resolve().parents[1]


def _run_script(script: Path, *args: str) -> None:
    subprocess.run(
        [sys.executable, str(script), *args],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )


def _load_module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_minimal_agent_integration_generates_expected_gate_outcomes(tmp_path: Path) -> None:
    out_dir = tmp_path / "minimal out"
    _run_script(
        ROOT / "examples" / "minimal_agent_integration" / "minimal_agent.py",
        "--out-dir",
        str(out_dir),
    )

    assert verify_jsonl(out_dir / "baseline.jsonl").status == "ledger_prefix_valid"
    assert (
        verify_jsonl(out_dir / "candidate_missing_witness.jsonl").status
        == "ledger_prefix_valid"
    )
    assert verify_jsonl(out_dir / "candidate_trial_backed.jsonl").status == "ledger_prefix_valid"

    missing_gate = read_json(out_dir / "gate_missing_witness.json")
    trial_gate = read_json(out_dir / "gate_trial_backed.json")
    assert missing_gate["status"] == "rejected_no_concrete_positive_evidence"
    assert missing_gate["missing_witness_coordinates"] == ["KLB_2.pure_read"]
    assert trial_gate["status"] == "safe_promotion"
    assert trial_gate["improved_coordinates"] == ["KLB_2.pure_read"]


def test_plain_python_adapter_example_emits_valid_ledger(tmp_path: Path) -> None:
    out = tmp_path / "plain python" / "ledger.jsonl"
    _run_script(
        ROOT / "examples" / "framework_adapters" / "plain_python_adapter.py",
        "--out",
        str(out),
    )
    receipt = verify_jsonl(out)
    assert receipt.status == "ledger_prefix_valid"
    assert receipt.records_seen == 1


def test_framework_adapter_examples_are_importable_without_optional_dependencies() -> None:
    langgraph = _load_module(
        ROOT / "examples" / "framework_adapters" / "langgraph_adapter.py"
    )
    crewai = _load_module(ROOT / "examples" / "framework_adapters" / "crewai_adapter.py")

    langgraph_event = langgraph.langgraph_state_to_oasg_event(
        {
            "prompt": "read state",
            "last_output": "ok",
            "model": "example",
            "node": "planner",
            "attempts": 1,
        },
        event_id="evt_langgraph_example",
    )
    crewai_event = crewai.crew_task_result_to_oasg_event(
        "task output",
        task_name="research_task",
        event_id="evt_crewai_example",
    )
    assert langgraph_event["payload"]["model_event"]["provider"] == "langgraph"
    assert crewai_event["payload"]["model_event"]["provider"] == "crewai"
