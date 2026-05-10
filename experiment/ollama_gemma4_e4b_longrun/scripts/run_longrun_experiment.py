"""Run the long-running OASG/Ollama workflow-operation experiment."""

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

from generate_longrun_tasks import generate_longrun_tasks  # noqa: E402
from oasg.canonical import receipt_hash  # noqa: E402
from oasg.constants import ACTION_CLASSES, REQUIRED_DIMENSIONS  # noqa: E402
from oasg.events import event_record, observation_payload  # noqa: E402
from oasg.io import read_json, read_jsonl, write_json, write_jsonl  # noqa: E402
from oasg.ledger import seal_records, verify_jsonl  # noqa: E402
from oasg.optimizer import supervise_optimizer  # noqa: E402
from oasg.policy_state import WorkflowPolicyState  # noqa: E402
from oasg.reducers.core import reduce_ledger  # noqa: E402


@dataclass(frozen=True)
class AttemptResult:
    task_id: str
    condition: str
    epoch: int
    phase: str
    burst: str
    family: str
    closed: bool
    parsed: bool
    validation_passed: bool
    attempts: int
    retries: int
    latency_ms: int
    prompt_chars: int
    output_chars: int
    unresolved_obligations: int
    validator_error_class: str
    prompt_template_ids: tuple[str, ...]
    active_policy_hash: str | None
    retry_policy_authorized: bool
    active_mutation_ids: tuple[str, ...]
    attempt_records: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "condition": self.condition,
            "epoch": self.epoch,
            "phase": self.phase,
            "burst": self.burst,
            "family": self.family,
            "closed": self.closed,
            "parsed": self.parsed,
            "validation_passed": self.validation_passed,
            "attempts": self.attempts,
            "retries": self.retries,
            "latency_ms": self.latency_ms,
            "prompt_chars": self.prompt_chars,
            "output_chars": self.output_chars,
            "unresolved_obligations": self.unresolved_obligations,
            "validator_error_class": self.validator_error_class,
            "prompt_template_ids": list(self.prompt_template_ids),
            "active_policy_hash": self.active_policy_hash,
            "retry_policy_authorized": self.retry_policy_authorized,
            "active_mutation_ids": list(self.active_mutation_ids),
            "attempt_records": list(self.attempt_records),
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--skip-preflight", action="store_true")
    parser.add_argument("--mock-model", action="store_true")
    args = parser.parse_args()

    config = read_json(Path(args.config))
    run_dir = _new_run_dir(ROOT / str(config["runs_dir"]))
    write_json(run_dir / "config.json", config)
    preflight = (
        {"status": "mocked"}
        if args.mock_model or args.skip_preflight
        else _preflight(config)
    )
    write_json(run_dir / "preflight.json", preflight)
    if preflight["status"] not in {"ok", "mocked"}:
        print(json.dumps({"status": "preflight_failed", "run_dir": str(run_dir)}, indent=2))
        return 2

    replicate_seeds = [int(seed) for seed in config.get("replicate_seeds", [])]
    if replicate_seeds:
        replicate_receipts: list[dict[str, Any]] = []
        for seed in replicate_seeds:
            seed_dir = run_dir / f"seed_{seed}"
            seed_config = {
                **config,
                "task_generator_seed": seed,
                "tasks_path": str(seed_dir / "tasks_longrun.jsonl"),
                "runs_dir": str(run_dir),
            }
            tasks = _load_or_generate_tasks(seed_config)
            write_json(seed_dir / "config.json", seed_config)
            write_json(seed_dir / "preflight.json", preflight)
            write_json(seed_dir / "task_manifest.json", _task_manifest(tasks, seed=seed))
            replicate_receipts.append(
                _run_seed_conditions(
                    config=seed_config,
                    tasks=tasks,
                    run_dir=seed_dir,
                    mock_model=args.mock_model,
                    seed=seed,
                )
            )
        write_json(
            run_dir / "replicates.json",
            {
                "receipt_type": "replicate_run_receipt",
                "status": "ok",
                "replicate_seeds": replicate_seeds,
                "replicates": replicate_receipts,
            },
        )
        _write_latest_pointer(ROOT / str(config["runs_dir"]), run_dir)
        print(json.dumps({"status": "ok", "run_dir": str(run_dir)}, indent=2))
        return 0

    tasks = _load_or_generate_tasks(config)
    write_json(
        run_dir / "task_manifest.json",
        _task_manifest(tasks, seed=int(config.get("task_generator_seed", 20260508))),
    )
    _run_seed_conditions(
        config=config,
        tasks=tasks,
        run_dir=run_dir,
        mock_model=args.mock_model,
        seed=int(config.get("task_generator_seed", 20260508)),
    )
    _write_latest_pointer(ROOT / str(config["runs_dir"]), run_dir)
    print(json.dumps({"status": "ok", "run_dir": str(run_dir)}, indent=2))
    return 0


def _run_seed_conditions(
    *,
    config: dict[str, Any],
    tasks: list[dict[str, Any]],
    run_dir: Path,
    mock_model: bool,
    seed: int,
) -> dict[str, Any]:
    all_results: list[dict[str, Any]] = []
    for condition in config.get("condition_order", []):
        results = _run_condition(
            condition=str(condition),
            tasks=tasks,
            config=config,
            run_dir=run_dir / str(condition),
            mock_model=mock_model,
        )
        all_results.extend(results)
    write_json(run_dir / "task_results.json", all_results)
    return {
        "seed": seed,
        "run_dir": str(run_dir),
        "task_manifest_hash": receipt_hash(_task_manifest(tasks, seed=seed)),
        "result_count": len(all_results),
    }


def _load_or_generate_tasks(config: dict[str, Any]) -> list[dict[str, Any]]:
    path = _config_path(config["tasks_path"])
    if not path.exists():
        tasks = generate_longrun_tasks(
            seed=int(config.get("task_generator_seed", 20260508)),
            epoch_count=int(config.get("epoch_count", 20)),
            tasks_per_epoch=8,
            warmup_epochs=int(config.get("warmup_epochs", 3)),
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        write_jsonl(path, tasks)
    return read_jsonl(path)


def _config_path(value: Any) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else ROOT / path


def _preflight(config: dict[str, Any]) -> dict[str, Any]:
    endpoint = str(config["ollama_endpoint"]).rstrip("/")
    if endpoint not in {"http://127.0.0.1:11434", "http://localhost:11434"}:
        return {"status": "failed", "reason": "non_localhost_ollama_endpoint"}
    try:
        with urlopen(f"{endpoint}/api/tags", timeout=5) as response:
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
    mock_model: bool,
) -> list[dict[str, Any]]:
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(run_dir / "config.json", config)
    history = run_dir / "history.jsonl"
    library = run_dir / "workflow_library.json"
    state = run_dir / "optimizer_state.json"
    metrics_path = run_dir / "recent_epoch_metrics.json"
    raw_events = [_initial_event(condition)]
    _write_history(history, raw_events)
    results: list[dict[str, Any]] = []
    by_epoch: dict[int, list[dict[str, Any]]] = {}
    for task in tasks:
        by_epoch.setdefault(int(task["epoch"]), []).append(task)

    for epoch in sorted(by_epoch):
        policy_state = _active_policy_state(library) if condition == "oasg_adaptive" else None
        max_attempts = _max_attempts(config, policy_state, condition)
        epoch_results: list[dict[str, Any]] = []
        for task in by_epoch[epoch]:
            result = _run_task(
                task=task,
                condition=condition,
                config=config,
                max_attempts=max_attempts,
                policy_state=policy_state,
                mock_model=mock_model,
            )
            raw_events.append(_result_event(result))
            row = result.to_dict()
            epoch_results.append(row)
            results.append(row)
        _write_history(history, raw_events)
        _write_epoch_metrics(metrics_path, epoch_results, condition, epoch)
        if condition == "oasg_observe_only":
            write_json(
                run_dir / "observe_snapshots" / f"epoch_{epoch:02d}.json",
                reduce_ledger(history).to_dict(),
            )
        if condition == "oasg_adaptive":
            iterations = _optimizer_iterations_for_epoch(config, epoch)
            supervise_optimizer(
                history=history,
                library_path=library,
                state_path=state,
                out_dir=run_dir / "oasg_supervisor" / f"epoch_{epoch:02d}",
                max_candidates=int(config["optimizer_max_candidates"]),
                max_iterations=iterations,
                runner_type="local-command",
                runner_command=(
                    sys.executable,
                    str(Path(__file__).with_name("oasg_longrun_trial_harness.py")),
                    "--mutation",
                    "{mutation}",
                    "--candidate",
                    "{candidate}",
                    "--trial-ledger-out",
                    "{trial_ledger_out}",
                    "--tasks",
                    str(_config_path(config["tasks_path"])),
                    "--config",
                    str(run_dir / "config.json"),
                    "--recent-metrics",
                    str(metrics_path),
                    *(("--mock-model",) if mock_model else ()),
                ),
                runner_timeout_seconds=_runner_timeout_seconds(config),
                append_lease_observations=bool(config["append_lease_observations"]),
                require_active_by_epoch=int(config.get("require_active_promotion_by_epoch", 0))
                or None,
            )
            readiness = _adaptive_readiness(
                library=library,
                run_dir=run_dir,
                epoch=epoch,
                warmup_epochs=int(config.get("warmup_epochs", 3)),
            )
            write_json(run_dir / "adaptive_readiness_receipt.json", readiness)
            if _should_stop_for_no_active_policy(config, readiness):
                break
    write_json(run_dir / "task_results.json", results)
    write_json(run_dir / "history_receipt.json", verify_jsonl(history).to_dict())
    write_json(run_dir / "final_snapshot.json", reduce_ledger(history).to_dict())
    return results


def _run_task(
    *,
    task: dict[str, Any],
    condition: str,
    config: dict[str, Any],
    max_attempts: int,
    policy_state: WorkflowPolicyState | None,
    mock_model: bool,
) -> AttemptResult:
    active_policy_hash = receipt_hash(policy_state.to_dict()) if policy_state is not None else None
    active_mutations = _active_mutation_ids(policy_state)
    prompt_ids: list[str] = []
    attempt_records: list[dict[str, Any]] = []
    last_error: str | None = None
    prompt_chars = 0
    output_chars = 0
    started = time.perf_counter()
    parsed = False
    valid = False
    for attempt in range(1, max_attempts + 1):
        prompt_id = _prompt_template_id(task, attempt, policy_state, condition)
        prompt_ids.append(prompt_id)
        prompt = _prompt_for(task, attempt=attempt, last_error=last_error, prompt_id=prompt_id)
        prompt_chars += len(prompt)
        if mock_model:
            output, call_error = _mock_output(task, prompt_id, attempt)
        else:
            output, call_error = _call_ollama(config, prompt)
        output_chars += len(output)
        if call_error:
            last_error = call_error
        else:
            parsed, valid, last_error = _validate_output(task, output)
        attempt_records.append(
            {
                "attempt": attempt,
                "prompt_template_id": prompt_id,
                "parsed": parsed,
                "validation_passed": valid,
                "error": last_error,
                "output_hash": receipt_hash({"output": output}),
            }
        )
        if parsed and valid:
            break
    closed = parsed and valid
    return AttemptResult(
        task_id=str(task["task_id"]),
        condition=condition,
        epoch=int(task["epoch"]),
        phase=str(task["phase"]),
        burst=str(task["burst"]),
        family=str(task["family"]),
        closed=closed,
        parsed=parsed,
        validation_passed=valid,
        attempts=len(attempt_records),
        retries=max(0, len(attempt_records) - 1),
        latency_ms=int((time.perf_counter() - started) * 1000),
        prompt_chars=prompt_chars,
        output_chars=output_chars,
        unresolved_obligations=0 if closed else 1,
        validator_error_class=_error_class(last_error),
        prompt_template_ids=tuple(prompt_ids),
        active_policy_hash=active_policy_hash,
        retry_policy_authorized=max_attempts > 1,
        active_mutation_ids=active_mutations,
        attempt_records=tuple(attempt_records),
    )


def _prompt_template_id(
    task: dict[str, Any],
    attempt: int,
    policy_state: WorkflowPolicyState | None,
    condition: str,
) -> str:
    has_policy = policy_state is not None and (
        bool(policy_state.retry_policy)
        or bool(policy_state.validator_policy)
        or bool(policy_state.context_policy)
        or bool(policy_state.rollback_policy)
    )
    if condition == "oasg_adaptive" and has_policy:
        return f"longrun_promoted_{task['family']}" if attempt == 1 else "longrun_repair"
    return "longrun_fixed_weak"


def _prompt_for(
    task: dict[str, Any],
    *,
    attempt: int,
    last_error: str | None,
    prompt_id: str,
) -> str:
    if prompt_id == "longrun_fixed_weak":
        return f"Answer the request concisely.\nRequest: {task['instruction']}\n"
    repair = "" if attempt == 1 else f"\nPrevious validator error: {last_error}\n"
    return (
        "Return exactly one minified JSON object. No Markdown or prose.\n"
        f"{_family_rule(str(task['family']))}\n"
        f"{repair}Task: {task['instruction']}\n"
    )


def _call_ollama(config: dict[str, Any], prompt: str) -> tuple[str, str | None]:
    body = {
        "model": config["model"],
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": int(config.get("temperature", 0))},
    }
    request = Request(
        f"{str(config['ollama_endpoint']).rstrip('/')}/api/generate",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(
            request,
            timeout=int(config.get("ollama_timeout_seconds", config["timeout_seconds"])),
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError) as exc:
        return "", f"ollama_call_failed:{exc}"
    return str(payload.get("response", "")), None


def _mock_output(task: dict[str, Any], prompt_id: str, attempt: int) -> tuple[str, str | None]:
    if prompt_id == "longrun_fixed_weak":
        if task["burst"] in {"validator_failure_burst", "stale_format_drift"}:
            return "not-json", None
        if task["family"] in {"safe_python_expression", "validator_receipt"}:
            return json.dumps({"wrong": True}), None
    if task["validator"] == "python_expr":
        return json.dumps({"expression": str(task["expected_value"])}), None
    if "expected" in task:
        return json.dumps(task["expected"], sort_keys=True), None
    return json.dumps({"status": "ok", "attempt": attempt}), None


def _validate_output(task: dict[str, Any], output: str) -> tuple[bool, bool, str | None]:
    try:
        parsed = json.loads(_extract_json(output))
    except (json.JSONDecodeError, ValueError) as exc:
        return False, False, f"json_parse_failed:{exc}"
    validator = str(task["validator"])
    if validator == "json_equals":
        passed = parsed == task["expected"]
        return True, passed, None if passed else "json_not_equal"
    if validator == "json_schema":
        return _validate_schema(parsed, task["schema"], task.get("expected"))
    if validator == "python_expr":
        if not isinstance(parsed, dict) or "expression" not in parsed:
            return True, False, "missing_expression"
        return _validate_expr(str(parsed["expression"]), task["expected_value"])
    return True, False, f"unknown_validator:{validator}"


def _extract_json(output: str) -> str:
    stripped = output.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object found")
    return stripped[start : end + 1]


def _validate_schema(
    parsed: Any,
    schema: dict[str, str],
    expected: dict[str, Any] | None,
) -> tuple[bool, bool, str | None]:
    if not isinstance(parsed, dict):
        return True, False, "not_object"
    for key, type_name in schema.items():
        if key not in parsed:
            return True, False, f"missing_key:{key}"
        if type_name == "string" and not isinstance(parsed[key], str):
            return True, False, f"type_mismatch:{key}"
        if type_name == "integer" and not isinstance(parsed[key], int):
            return True, False, f"type_mismatch:{key}"
        if type_name == "boolean" and not isinstance(parsed[key], bool):
            return True, False, f"type_mismatch:{key}"
    if expected is not None and parsed != expected:
        return True, False, "schema_values_mismatch"
    return True, True, None


def _validate_expr(expression: str, expected_value: Any) -> tuple[bool, bool, str | None]:
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        return True, False, f"expr_syntax:{exc.msg}"
    allowed = (
        ast.Expression,
        ast.BinOp,
        ast.UnaryOp,
        ast.Constant,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.FloorDiv,
        ast.Mod,
        ast.Pow,
        ast.USub,
        ast.UAdd,
        ast.Load,
    )
    for node in ast.walk(tree):
        if not isinstance(node, allowed):
            return True, False, f"expr_disallowed_node:{type(node).__name__}"
    try:
        value = eval(compile(tree, "<oasg-longrun-expr>", "eval"), {"__builtins__": {}}, {})
    except Exception as exc:  # noqa: BLE001
        return True, False, f"expr_eval_failed:{exc}"
    return True, value == expected_value, None if value == expected_value else "expr_wrong_value"


def _initial_event(condition: str) -> dict[str, Any]:
    return event_record(
        event_id=f"evt_{condition}_initial",
        workflow_id=condition,
        component_id="experiment",
        event_type="observation",
        payload=observation_payload(
            dimensions={dimension: "acceptable" for dimension in REQUIRED_DIMENSIONS},
            action_grades={action: "acceptable" for action in ACTION_CLASSES},
            protected_debt={dimension: "acceptable" for dimension in REQUIRED_DIMENSIONS},
        ),
    )


def _result_event(result: AttemptResult) -> dict[str, Any]:
    dimensions = {dimension: "acceptable" for dimension in REQUIRED_DIMENSIONS}
    protected = {dimension: "acceptable" for dimension in REQUIRED_DIMENSIONS}
    if not result.validation_passed:
        dimensions["evidence"] = "degraded"
        protected["evidence"] = "degraded"
    if not result.closed:
        dimensions["queue"] = "critical"
        protected["queue"] = "critical"
    if result.retries > 0:
        dimensions["budget"] = "degraded"
    action_grades = {action: "acceptable" for action in ACTION_CLASSES}
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
            protected_debt=protected,
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


def _write_epoch_metrics(
    path: Path,
    rows: list[dict[str, Any]],
    condition: str,
    epoch: int,
) -> None:
    errors: dict[str, int] = {}
    bursts: dict[str, int] = {}
    failed_by_error: dict[str, list[str]] = {}
    failed_task_ids: list[str] = []
    for row in rows:
        errors[str(row["validator_error_class"])] = errors.get(str(row["validator_error_class"]), 0) + 1
        bursts[str(row["burst"])] = bursts.get(str(row["burst"]), 0) + 1
        if row["closed"] is not True:
            error_class = str(row["validator_error_class"])
            task_id = str(row["task_id"])
            failed_task_ids.append(task_id)
            failed_by_error.setdefault(error_class, []).append(task_id)
    validation_failures = sum(1 for row in rows if row["validation_passed"] is not True)
    parse_failures = sum(1 for row in rows if row["parsed"] is not True)
    unresolved = sum(int(row["unresolved_obligations"]) for row in rows)
    write_json(
        path,
        {
            "condition": condition,
            "epoch": epoch,
            "task_count": len(rows),
            "dominant_burst": max(bursts, key=bursts.get) if bursts else "unknown",
            "dominant_failure_class": _dominant_failure_class(errors),
            "validation_failures": validation_failures,
            "parse_failures": parse_failures,
            "unresolved_obligations": unresolved,
            "retry_count": sum(int(row["retries"]) for row in rows),
            "error_classes": errors,
            "failed_task_ids": failed_task_ids,
            "failed_task_ids_by_error": failed_by_error,
            "mean_latency_ms": int(
                sum(int(row["latency_ms"]) for row in rows) / max(1, len(rows))
            ),
            "source_hash": receipt_hash({"epoch_results": rows}),
        },
    )


def _active_policy_state(path: Path) -> WorkflowPolicyState | None:
    if not path.exists():
        return None
    raw = read_json(path)
    if not isinstance(raw, dict):
        return None
    state = raw.get("policy_state", raw.get("active_policy_state"))
    return WorkflowPolicyState.from_dict(state)


def _optimizer_iterations_for_epoch(config: dict[str, Any], epoch: int) -> int:
    warmup_epochs = int(config.get("warmup_epochs", 3))
    if epoch <= warmup_epochs:
        return int(config.get("warmup_optimizer_max_iterations", config["optimizer_max_iterations"]))
    return int(config["optimizer_max_iterations"])


def _adaptive_readiness(
    *,
    library: Path,
    run_dir: Path,
    epoch: int,
    warmup_epochs: int,
) -> dict[str, Any]:
    policy_state = _active_policy_state(library)
    mutation_ids = _active_mutation_ids(policy_state)
    active = bool(mutation_ids)
    return {
        "receipt_type": "adaptive_readiness_receipt",
        "status": "active_policy_ready" if active else "no_active_policy",
        "epoch": epoch,
        "warmup_epochs": warmup_epochs,
        "active_mutation_ids": list(mutation_ids),
        "active_policy_hash": receipt_hash(policy_state.to_dict())
        if policy_state is not None
        else None,
        "ready_for_evaluation": active and epoch >= warmup_epochs,
        "promotion_diagnostic": _promotion_diagnostic(run_dir),
    }


def _should_stop_for_no_active_policy(
    config: dict[str, Any],
    readiness: dict[str, Any],
) -> bool:
    required_epoch = int(config.get("require_active_promotion_by_epoch", 0))
    if required_epoch <= 0:
        return False
    if str(readiness["status"]) != "no_active_policy":
        return False
    return int(readiness["epoch"]) >= required_epoch


def _active_mutation_ids(policy_state: WorkflowPolicyState | None) -> tuple[str, ...]:
    if policy_state is None or policy_state.state_id == "default":
        return ()
    return tuple(part for part in policy_state.state_id.split(":") if part.startswith("mut_"))


def _max_attempts(
    config: dict[str, Any],
    policy_state: WorkflowPolicyState | None,
    condition: str,
) -> int:
    if condition != "oasg_adaptive":
        return int(config["baseline_max_attempts"])
    has_policy = policy_state is not None and (
        bool(policy_state.retry_policy)
        or bool(policy_state.validator_policy)
        or bool(policy_state.context_policy)
    )
    return int(
        config["adaptive_promoted_max_attempts"]
        if has_policy
        else config["adaptive_initial_max_attempts"]
    )


def _runner_timeout_seconds(config: dict[str, Any]) -> int:
    canary_count = int(
        config.get(
            "canary_task_count_warmup",
            config.get("canary_task_count", 1),
        )
    )
    baseline_attempts = int(config.get("baseline_max_attempts", 1))
    candidate_attempts = int(config.get("adaptive_promoted_max_attempts", 2))
    ollama_timeout = int(config.get("ollama_timeout_seconds", config.get("timeout_seconds", 60)))
    required = canary_count * (baseline_attempts + candidate_attempts) * ollama_timeout + 30
    configured = int(config.get("trial_runner_timeout_seconds", required))
    return max(configured, required)


def _dominant_failure_class(errors: dict[str, int]) -> str:
    actionable = {key: value for key, value in errors.items() if key != "none"}
    if not actionable:
        return "none"
    return max(actionable, key=actionable.get)


def _promotion_diagnostic(run_dir: Path) -> dict[str, Any]:
    counts = {
        "trial_timeout_count": 0,
        "lease_cap_failure_count": 0,
        "workload_mismatch_count": 0,
        "viability_regression_count": 0,
    }
    first: dict[str, Any] | None = None
    for path in sorted((run_dir / "oasg_supervisor").rglob("*.json")):
        try:
            data = read_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        status = str(data.get("status", ""))
        receipt_type = str(data.get("receipt_type", ""))
        if data.get("timeout_status") == "timed_out":
            counts["trial_timeout_count"] += 1
        if status == "lease_rejected_cap_exceeded":
            counts["lease_cap_failure_count"] += 1
        if status == "workload_rejected" or data.get("rejection_reason") == "workload_mismatch":
            counts["workload_mismatch_count"] += 1
        if status == "rejected_viability_regression":
            counts["viability_regression_count"] += 1
        if first is None and (
            status.startswith("rejected")
            or status.endswith("rejected")
            or status.startswith("inconclusive")
            or status == "no_valid_candidate"
        ):
            first = {
                "path": str(path),
                "receipt_type": receipt_type or None,
                "status": status,
                "rejected_reasons": data.get("rejected_reasons", []),
                "timeout_status": data.get("timeout_status"),
            }
    return {
        "receipt_type": "promotion_diagnostic_receipt",
        "status": "diagnostic_available" if first is not None else "no_rejection_observed",
        "first_failed_artifact": first,
        **counts,
    }


def _write_history(path: Path, raw_events: list[dict[str, Any]]) -> None:
    write_jsonl(path, seal_records(raw_events))


def _task_manifest(tasks: list[dict[str, Any]], *, seed: int | None = None) -> dict[str, Any]:
    phases: dict[str, int] = {}
    bursts: dict[str, int] = {}
    families: dict[str, int] = {}
    for task in tasks:
        phases[str(task["phase"])] = phases.get(str(task["phase"]), 0) + 1
        bursts[str(task["burst"])] = bursts.get(str(task["burst"]), 0) + 1
        families[str(task["family"])] = families.get(str(task["family"]), 0) + 1
    return {
        "task_count": len(tasks),
        "task_ids": [task["task_id"] for task in tasks],
        "phase_counts": phases,
        "burst_counts": bursts,
        "family_counts": families,
        "task_list_hash": receipt_hash({"tasks": tasks}),
        "task_generator_seed": seed,
    }


def _new_run_dir(runs_dir: Path) -> Path:
    runs_dir.mkdir(parents=True, exist_ok=True)
    name = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = runs_dir / name
    suffix = 0
    while path.exists():
        suffix += 1
        path = runs_dir / f"{name}_{suffix:02d}"
    path.mkdir(parents=True)
    return path


def _write_latest_pointer(runs_dir: Path, run_dir: Path) -> None:
    latest = runs_dir / "latest"
    if latest.exists() or latest.is_symlink():
        if latest.is_dir() and not latest.is_symlink():
            shutil.rmtree(latest)
        else:
            latest.unlink()
    shutil.copytree(run_dir, latest)
    write_json(runs_dir / "latest_pointer.json", {"latest": run_dir.name})


def _family_rule(family: str) -> str:
    rules = {
        "safe_python_expression": "Use only literals and arithmetic operators.",
        "json_schema_repair": "Include every required key with exact values.",
        "validator_receipt": "Use booleans and integers as JSON primitives.",
        "code_transform": "Compute the requested identifier exactly.",
        "obligation_closure": "Close the obligation and set remaining to 0.",
        "replay_rollback_receipt": "Include replay and rollback receipts exactly.",
    }
    return rules.get(family, "Return the requested value exactly.")


def _error_class(reason: str | None) -> str:
    if reason is None:
        return "none"
    return reason.split(":", 1)[0]


if __name__ == "__main__":
    raise SystemExit(main())
