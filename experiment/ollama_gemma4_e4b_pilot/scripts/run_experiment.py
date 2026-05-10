"""Run the OASG x Ollama gemma4:e4b pilot experiment.

This script intentionally measures operational workflow behavior. It does not
use an LLM judge and does not claim semantic truth beyond deterministic local
validators.
"""

from __future__ import annotations

import argparse
import ast
import json
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
SCRIPTS = Path(__file__).resolve().parent
for import_path in (SCRIPTS, SRC, ROOT):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from oasg.canonical import domain_hash, receipt_hash  # noqa: E402
from oasg.events import event_record, observation_payload  # noqa: E402
from oasg.io import read_json, read_jsonl, write_json, write_jsonl  # noqa: E402
from oasg.ledger import seal_records, verify_jsonl  # noqa: E402
from oasg.optimizer import supervise_optimizer  # noqa: E402
from oasg.policy_state import WorkflowPolicyState  # noqa: E402
from oasg.reducers.core import reduce_ledger  # noqa: E402
from generate_effect_tasks import generate_effect_tasks  # noqa: E402

ALL_ACTIONS = (
    "pure_read",
    "local_reversible",
    "validate_artifact",
    "close_obligation",
    "replay_artifact",
    "rollback_local_effect",
    "emit_claim",
    "promote_workflow",
)
ALL_DIMENSIONS = (
    "budget",
    "queue",
    "evidence",
    "replay",
    "rollback",
    "incident",
    "authority",
    "maintenance",
    "comparison",
    "boundary",
    "trusted_base",
    "taint",
)


@dataclass(frozen=True)
class TaskResult:
    task_id: str
    condition: str
    batch_index: int
    closed: bool
    parsed: bool
    validation_passed: bool
    attempts: int
    retries: int
    latency_ms: int
    prompt_chars: int
    output_chars: int
    unresolved_obligations: int
    error: str | None
    output_hash: str
    phase: str = "evaluation"
    family: str = "legacy"
    validator_error_class: str = "none"
    prompt_template_ids: tuple[str, ...] = ()
    active_policy_hash: str | None = None
    retry_policy_authorized: bool = False
    attempt_records: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--skip-preflight", action="store_true")
    args = parser.parse_args()

    config = read_json(Path(args.config))
    tasks = _load_tasks(config)
    run_dir = _new_run_dir(ROOT / str(config["runs_dir"]))
    write_json(run_dir / "config.json", config)
    write_json(run_dir / "task_manifest.json", _task_manifest(tasks))

    preflight = _preflight(config) if not args.skip_preflight else {"status": "skipped"}
    write_json(run_dir / "preflight.json", preflight)
    if preflight["status"] != "ok" and not args.skip_preflight:
        print(json.dumps({"status": "preflight_failed", "run_dir": str(run_dir)}, indent=2))
        return 2

    all_results: list[dict[str, Any]] = []
    baseline = _run_condition(
        condition="baseline_fixed",
        tasks=tasks,
        config=config,
        run_dir=run_dir / "baseline_fixed",
        adaptive=False,
    )
    adaptive = _run_condition(
        condition="oasg_adaptive",
        tasks=tasks,
        config=config,
        run_dir=run_dir / "oasg_adaptive",
        adaptive=True,
    )
    all_results.extend(baseline)
    all_results.extend(adaptive)
    write_json(run_dir / "task_results.json", all_results)
    _write_latest_pointer(ROOT / str(config["runs_dir"]), run_dir)
    print(json.dumps({"status": "ok", "run_dir": str(run_dir)}, indent=2))
    return 0


def _load_tasks(config: dict[str, Any]) -> list[dict[str, Any]]:
    path = ROOT / str(config["tasks_path"])
    if path.exists():
        return read_jsonl(path)
    if config.get("effect_profile") is True:
        return generate_effect_tasks(int(config.get("task_generator_seed", 20260508)))
    raise FileNotFoundError(path)


def _preflight(config: dict[str, Any]) -> dict[str, Any]:
    try:
        with urlopen(f"{config['ollama_endpoint'].rstrip('/')}/api/tags", timeout=5) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError) as exc:
        return {"status": "failed", "reason": f"ollama_unreachable:{exc}"}
    names = [str(item.get("name", "")) for item in raw.get("models", [])]
    if str(config["model"]) not in names:
        return {"status": "failed", "reason": "model_missing", "available_models": names}
    return {"status": "ok", "model": config["model"], "available_models": names}


def _run_condition(
    *,
    condition: str,
    tasks: list[dict[str, Any]],
    config: dict[str, Any],
    run_dir: Path,
    adaptive: bool,
) -> list[dict[str, Any]]:
    run_dir.mkdir(parents=True, exist_ok=True)
    raw_events: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    batch_size = int(config["batch_size"])
    history = run_dir / "history.jsonl"
    library = run_dir / "workflow_library.json"
    state = run_dir / "optimizer_state.json"
    metrics_path = run_dir / "recent_metrics.json"
    raw_events.append(_initial_event(condition))
    _write_history(history, raw_events)

    for offset in range(0, len(tasks), batch_size):
        batch = tasks[offset : offset + batch_size]
        batch_index = offset // batch_size + 1
        policy_state = _active_policy_state(library) if adaptive else None
        max_attempts = _max_attempts(config, policy_state, adaptive)
        batch_results: list[dict[str, Any]] = []
        for task in batch:
            result = _run_task(
                task=task,
                condition=condition,
                batch_index=batch_index,
                config=config,
                max_attempts=max_attempts,
                policy_state=policy_state,
                adaptive=adaptive,
            )
            raw_events.append(_result_event(result))
            batch_results.append(result.to_dict())
            results.append(result.to_dict())
        _write_history(history, raw_events)
        _write_recent_metrics(metrics_path, batch_results, condition, batch_index)
        if adaptive and _should_supervise_batch(config, batch_results):
            supervise_optimizer(
                history=history,
                library_path=library,
                state_path=state,
                out_dir=run_dir / "oasg_runs" / f"batch_{batch_index:02d}",
                max_candidates=int(config["optimizer_max_candidates"]),
                max_iterations=int(config["optimizer_max_iterations"]),
                runner_type="local-command",
                runner_command=(
                    sys.executable,
                    str(Path(__file__).with_name("oasg_trial_harness.py")),
                    "--mutation",
                    "{mutation}",
                    "--candidate",
                    "{candidate}",
                    "--metrics",
                    str(metrics_path),
                ),
                append_lease_observations=bool(config["append_lease_observations"]),
            )
    write_json(run_dir / "task_results.json", results)
    write_json(run_dir / "history_receipt.json", verify_jsonl(history).to_dict())
    write_json(run_dir / "final_snapshot.json", reduce_ledger(history).to_dict())
    return results


def _should_supervise_batch(config: dict[str, Any], batch_results: list[dict[str, Any]]) -> bool:
    if not config.get("effect_profile"):
        return True
    return any(item.get("phase") == "calibration" for item in batch_results)


def _run_task(
    *,
    task: dict[str, Any],
    condition: str,
    batch_index: int,
    config: dict[str, Any],
    max_attempts: int,
    policy_state: WorkflowPolicyState | None = None,
    adaptive: bool = False,
) -> TaskResult:
    effect_profile = bool(config.get("effect_profile"))
    prompt = _prompt_for(
        task,
        attempt=1,
        last_error=None,
        effect_profile=effect_profile,
        policy_state=policy_state,
        adaptive=adaptive,
    )
    attempts = 0
    latency_ms = 0
    output = ""
    parsed = False
    passed = False
    error: str | None = None
    prompt_template_ids: list[str] = []
    attempt_records: list[dict[str, Any]] = []
    for attempt in range(1, max_attempts + 1):
        attempts = attempt
        prompt = _prompt_for(
            task,
            attempt=attempt,
            last_error=error,
            effect_profile=effect_profile,
            policy_state=policy_state,
            adaptive=adaptive,
        )
        prompt_template_id = _prompt_template_id(
            task,
            attempt=attempt,
            effect_profile=effect_profile,
            policy_state=policy_state,
            adaptive=adaptive,
        )
        prompt_template_ids.append(prompt_template_id)
        start = time.monotonic()
        output, call_error = _call_ollama(config, prompt)
        latency_ms += int((time.monotonic() - start) * 1000)
        if call_error is not None:
            error = call_error
            attempt_records.append(
                {
                    "attempt": attempt,
                    "prompt_template_id": prompt_template_id,
                    "parsed": False,
                    "validation_passed": False,
                    "error": error,
                }
            )
            continue
        parsed, passed, error = _validate_output(task, output)
        attempt_records.append(
            {
                "attempt": attempt,
                "prompt_template_id": prompt_template_id,
                "parsed": parsed,
                "validation_passed": passed,
                "error": error,
            }
        )
        if passed:
            break
    closed = parsed and passed
    active_policy_hash = receipt_hash(policy_state.to_dict()) if policy_state is not None else None
    return TaskResult(
        task_id=str(task["task_id"]),
        condition=condition,
        batch_index=batch_index,
        closed=closed,
        parsed=parsed,
        validation_passed=passed,
        attempts=attempts,
        retries=max(0, attempts - 1),
        latency_ms=latency_ms,
        prompt_chars=len(prompt),
        output_chars=len(output),
        unresolved_obligations=0 if closed else 1,
        error=error,
        output_hash=domain_hash("OASG:v1.0:experiment_output", output),
        phase=str(task.get("phase", "evaluation")),
        family=str(task.get("family", "legacy")),
        validator_error_class=_error_class(error),
        prompt_template_ids=tuple(prompt_template_ids),
        active_policy_hash=active_policy_hash,
        retry_policy_authorized=bool(policy_state and policy_state.retry_policy),
        attempt_records=tuple(attempt_records),
    )


def _call_ollama(config: dict[str, Any], prompt: str) -> tuple[str, str | None]:
    body = {
        "model": config["model"],
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": config.get("temperature", 0)},
    }
    data = json.dumps(body).encode("utf-8")
    request = Request(
        f"{str(config['ollama_endpoint']).rstrip('/')}/api/generate",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=int(config["timeout_seconds"])) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError) as exc:
        return "", f"ollama_call_failed:{exc}"
    return str(payload.get("response", "")), None


def _prompt_for(
    task: dict[str, Any],
    *,
    attempt: int,
    last_error: str | None,
    effect_profile: bool = False,
    policy_state: WorkflowPolicyState | None = None,
    adaptive: bool = False,
) -> str:
    if not effect_profile:
        retry_note = "" if attempt == 1 else f"\nPrevious validation error: {last_error}\n"
        return (
            "You are executing a deterministic coding-operations task.\n"
            "Return only a single JSON object. Do not use Markdown fences.\n"
            f"{retry_note}"
            f"Task: {task['instruction']}\n"
        )
    has_policy = adaptive and policy_state is not None and (
        bool(policy_state.retry_policy)
        or bool(policy_state.validator_policy)
        or bool(policy_state.context_policy)
    )
    if attempt == 1 and not has_policy:
        return (
            "Answer the coding-operations request concisely.\n"
            f"Request: {task['instruction']}\n"
        )
    repair_note = "" if attempt == 1 else f"\nPrevious validator error: {last_error}\n"
    family_rule = _family_prompt_rule(str(task.get("family", "legacy")))
    return (
        "You are executing a deterministic coding-operations task.\n"
        "Return exactly one minified JSON object. Do not use Markdown fences or prose.\n"
        f"{family_rule}\n"
        f"{repair_note}"
        f"Task: {task['instruction']}\n"
    )


def _prompt_template_id(
    task: dict[str, Any],
    *,
    attempt: int,
    effect_profile: bool,
    policy_state: WorkflowPolicyState | None,
    adaptive: bool,
) -> str:
    if not effect_profile:
        return "legacy_json_strict" if attempt == 1 else "legacy_validator_retry"
    has_policy = adaptive and policy_state is not None and (
        bool(policy_state.retry_policy)
        or bool(policy_state.validator_policy)
        or bool(policy_state.context_policy)
    )
    if not has_policy and attempt == 1:
        return "effect_initial_weak"
    if attempt > 1:
        return f"effect_validator_repair_{task.get('family', 'legacy')}"
    return f"effect_promoted_strict_{task.get('family', 'legacy')}"


def _family_prompt_rule(family: str) -> str:
    if family == "safe_python_expression":
        return "For expression tasks, use only literals, operators, tuples, lists, dicts, and parentheses."
    if family == "schema_repair":
        return "For schema tasks, include every required key with the requested JSON value types."
    if family == "validator_receipt":
        return "For receipt tasks, use booleans as JSON booleans and failures as an integer."
    if family == "code_transform":
        return "For transform tasks, compute the identifier exactly and include the requested style."
    return "For extraction tasks, compute the requested value exactly."


def _validate_output(task: dict[str, Any], output: str) -> tuple[bool, bool, str | None]:
    try:
        parsed = json.loads(_extract_json_object(output))
    except (json.JSONDecodeError, ValueError) as exc:
        return False, False, f"json_parse_failed:{exc}"
    validator = str(task["validator"])
    if validator == "json_equals":
        passed = parsed == task["expected"]
        return True, passed, None if passed else "json_not_equal"
    if validator == "json_schema":
        passed, reason = _validate_schema_subset(parsed, task["schema"])
        return True, passed, reason
    if validator == "python_expr":
        if not isinstance(parsed, dict) or "expression" not in parsed:
            return True, False, "missing_expression"
        passed, reason = _validate_python_expr(str(parsed["expression"]), task["expected_value"])
        return True, passed, reason
    return True, False, f"unknown_validator:{validator}"


def _extract_json_object(output: str) -> str:
    stripped = output.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object found")
    return stripped[start : end + 1]


def _validate_schema_subset(value: Any, schema: dict[str, Any]) -> tuple[bool, str | None]:
    if not isinstance(value, dict):
        return False, "schema_expected_object"
    for key in schema.get("required", []):
        if key not in value:
            return False, f"schema_missing:{key}"
    for key, rule in schema.get("properties", {}).items():
        if key not in value:
            continue
        if "const" in rule and value[key] != rule["const"]:
            return False, f"schema_const:{key}"
        if rule.get("type") == "integer" and not isinstance(value[key], int):
            return False, f"schema_type:{key}"
        if "maximum" in rule and isinstance(value[key], int) and value[key] > int(rule["maximum"]):
            return False, f"schema_max:{key}"
    return True, None


def _validate_python_expr(expression: str, expected: Any) -> tuple[bool, str | None]:
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        return False, f"expr_syntax:{exc}"
    for node in ast.walk(tree):
        if isinstance(node, (ast.Call, ast.Attribute, ast.Subscript, ast.Import, ast.ImportFrom)):
            return False, "expr_disallowed_node"
    try:
        value = eval(compile(tree, "<oasg-experiment>", "eval"), {"__builtins__": {}}, {})
    except Exception as exc:  # noqa: BLE001
        return False, f"expr_eval:{exc}"
    return value == expected, None if value == expected else "expr_value_mismatch"


def _max_attempts(
    config: dict[str, Any],
    policy_state: WorkflowPolicyState | None,
    adaptive: bool,
) -> int:
    if not adaptive or policy_state is None:
        return int(config["baseline_max_attempts"])
    if policy_state.retry_policy:
        return int(config["adaptive_promoted_max_attempts"])
    return int(config["adaptive_initial_max_attempts"])


def _active_policy_state(library_path: Path) -> WorkflowPolicyState | None:
    if not library_path.exists():
        return None
    raw = read_json(library_path)
    return WorkflowPolicyState.from_dict(raw.get("policy_state"))


def _error_class(error: str | None) -> str:
    if error is None:
        return "none"
    return error.split(":", 1)[0]


def _initial_event(condition: str) -> dict[str, Any]:
    return event_record(
        event_id=f"evt_{condition}_initial",
        workflow_id=condition,
        component_id="experiment",
        event_type="observation",
        payload=observation_payload(
            dimensions={dimension: "acceptable" for dimension in ALL_DIMENSIONS},
            action_grades={action: "acceptable" for action in ALL_ACTIONS},
            protected_debt={dimension: "acceptable" for dimension in ALL_DIMENSIONS},
            policy={
                "effect_classes": ["pure"],
                "semantic_scope": "none",
                "claim_emitting": False,
                "taint_level": "public",
                "boundary_status": "valid",
                "trusted_base_status": "valid",
                "workflow_promotion_authorized": False,
            },
        ),
    )


def _result_event(result: TaskResult) -> dict[str, Any]:
    evidence_grade = "acceptable" if result.validation_passed else "degraded"
    queue_grade = "acceptable" if result.closed else "critical"
    budget_grade = "acceptable" if result.latency_ms < 60000 else "degraded"
    dimensions = {dimension: "acceptable" for dimension in ALL_DIMENSIONS}
    dimensions.update({"budget": budget_grade, "queue": queue_grade, "evidence": evidence_grade})
    protected_debt = {dimension: "acceptable" for dimension in ALL_DIMENSIONS}
    if not result.closed:
        protected_debt.update({"queue": "critical", "evidence": "degraded"})
    action_grades = {action: "acceptable" for action in ALL_ACTIONS}
    action_grades["validate_artifact"] = "surplus" if result.validation_passed else "degraded"
    action_grades["close_obligation"] = "surplus" if result.closed else "critical"
    return event_record(
        event_id=f"evt_{result.condition}_{result.task_id}",
        workflow_id=result.condition,
        component_id="ollama_gemma4_e4b",
        event_type="observation",
        payload=observation_payload(
            dimensions=dimensions,
            action_grades=action_grades,
            protected_debt=protected_debt,
            policy={
                "effect_classes": ["pure"],
                "semantic_scope": "operational_only",
                "claim_emitting": False,
                "taint_level": "public",
                "boundary_status": "valid",
                "trusted_base_status": "valid",
                "workflow_promotion_authorized": False,
            },
            model_event=result.to_dict(),
        ),
    )


def _write_recent_metrics(
    path: Path,
    batch_results: list[dict[str, Any]],
    condition: str,
    batch_index: int,
) -> None:
    failures = [item for item in batch_results if not item["validation_passed"]]
    parse_failures = [item for item in batch_results if not item["parsed"]]
    unresolved = sum(int(item["unresolved_obligations"]) for item in batch_results)
    retries = sum(int(item["retries"]) for item in batch_results)
    error_classes: dict[str, int] = {}
    for item in batch_results:
        key = str(item.get("validator_error_class", "none"))
        error_classes[key] = error_classes.get(key, 0) + 1
    write_json(
        path,
        {
            "condition": condition,
            "batch_index": batch_index,
            "phases": sorted({str(item.get("phase", "evaluation")) for item in batch_results}),
            "task_count": len(batch_results),
            "validation_failures": len(failures),
            "parse_failures": len(parse_failures),
            "unresolved_obligations": unresolved,
            "retry_count": retries,
            "error_classes": error_classes,
            "mean_latency_ms": int(
                sum(int(item["latency_ms"]) for item in batch_results) / max(1, len(batch_results))
            ),
            "source_hash": receipt_hash({"batch_results": batch_results}),
        },
    )


def _write_history(path: Path, raw_events: list[dict[str, Any]]) -> None:
    write_jsonl(path, seal_records(raw_events))


def _task_manifest(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    phases: dict[str, int] = {}
    families: dict[str, int] = {}
    for task in tasks:
        phase = str(task.get("phase", "evaluation"))
        family = str(task.get("family", "legacy"))
        phases[phase] = phases.get(phase, 0) + 1
        families[family] = families.get(family, 0) + 1
    return {
        "task_count": len(tasks),
        "task_ids": [task["task_id"] for task in tasks],
        "phase_counts": phases,
        "family_counts": families,
        "task_list_hash": receipt_hash({"tasks": tasks}),
    }


def _new_run_dir(raw_runs_dir: str) -> Path:
    runs_dir = ROOT / raw_runs_dir
    runs_dir.mkdir(parents=True, exist_ok=True)
    name = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = runs_dir / name
    suffix = 0
    while path.exists():
        suffix += 1
        path = runs_dir / f"{name}_{suffix:02d}"
    path.mkdir(parents=True)
    return path


def _write_latest_pointer(raw_runs_dir: str, run_dir: Path) -> None:
    runs_dir = ROOT / raw_runs_dir
    latest = runs_dir / "latest"
    if latest.exists() or latest.is_symlink():
        if latest.is_dir() and not latest.is_symlink():
            shutil.rmtree(latest)
        else:
            latest.unlink()
    shutil.copytree(run_dir, latest)
    write_json(runs_dir / "latest_pointer.json", {"latest_run_dir": run_dir.name})


if __name__ == "__main__":
    raise SystemExit(main())
