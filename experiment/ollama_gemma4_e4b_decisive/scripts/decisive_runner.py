"""Task execution and ledger helpers for the decisive experiment."""

from __future__ import annotations

import ast
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from oasg.canonical import receipt_hash
from oasg.constants import ACTION_CLASSES, REQUIRED_DIMENSIONS
from oasg.events import event_record, observation_payload
from oasg.io import write_jsonl
from oasg.ledger import seal_records


@dataclass(frozen=True)
class AttemptResult:
    task_id: str
    condition: str
    epoch: int
    phase: str
    burst: str
    family: str
    policy_id: str | None
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
            "policy_id": self.policy_id,
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
            "active_mutation_ids": list(self.active_mutation_ids),
            "attempt_records": list(self.attempt_records),
        }


def run_task(
    *,
    task: dict[str, Any],
    condition: str,
    config: dict[str, Any],
    policy_id: str | None,
    active_mutation_id: str | None = None,
    mock_model: bool = False,
) -> AttemptResult:
    max_attempts = _max_attempts(policy_id, config)
    prompt_ids: list[str] = []
    attempt_records: list[dict[str, Any]] = []
    prompt_chars = 0
    output_chars = 0
    parsed = False
    valid = False
    last_error: str | None = None
    started = time.perf_counter()
    for attempt in range(1, max_attempts + 1):
        prompt_id = _prompt_template_id(task, policy_id, attempt)
        prompt = _prompt_for(task, prompt_id=prompt_id, last_error=last_error)
        prompt_ids.append(prompt_id)
        prompt_chars += len(prompt)
        if mock_model:
            output, call_error = _mock_output(task, policy_id, attempt)
        else:
            output, call_error = _call_ollama(config, prompt)
        output_chars += len(output)
        if call_error:
            last_error = call_error
        else:
            parsed, valid, last_error = validate_output(task, output)
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
    active_ids = (active_mutation_id,) if active_mutation_id else ()
    policy_hash = receipt_hash({"policy_id": policy_id}) if active_ids else None
    return AttemptResult(
        task_id=str(task["task_id"]),
        condition=condition,
        epoch=int(task["epoch"]),
        phase=str(task["phase"]),
        burst=str(task["burst"]),
        family=str(task["family"]),
        policy_id=policy_id,
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
        active_policy_hash=policy_hash,
        active_mutation_ids=active_ids,
        attempt_records=tuple(attempt_records),
    )


def write_history(path: Path, condition: str, rows: list[dict[str, Any]]) -> None:
    raw_events = [initial_event(condition)]
    for row in rows:
        raw_events.append(result_event(row))
    write_jsonl(path, seal_records(raw_events))


def initial_event(condition: str) -> dict[str, Any]:
    return event_record(
        event_id=f"evt_{condition}_initial",
        workflow_id=condition,
        component_id="decisive_experiment",
        event_type="observation",
        payload=observation_payload(
            dimensions={dimension: "acceptable" for dimension in REQUIRED_DIMENSIONS},
            action_grades={action: "acceptable" for action in ACTION_CLASSES},
            protected_debt={dimension: "acceptable" for dimension in REQUIRED_DIMENSIONS},
        ),
    )


def result_event(row: dict[str, Any]) -> dict[str, Any]:
    dimensions = {dimension: "acceptable" for dimension in REQUIRED_DIMENSIONS}
    protected = {dimension: "acceptable" for dimension in REQUIRED_DIMENSIONS}
    if row.get("validation_passed") is not True:
        dimensions["evidence"] = "degraded"
        protected["evidence"] = "degraded"
    if row.get("closed") is not True:
        dimensions["queue"] = "critical"
        protected["queue"] = "critical"
    if int(row.get("retries", 0)) > 0:
        dimensions["budget"] = "degraded"
    action_grades = {action: "acceptable" for action in ACTION_CLASSES}
    action_grades["validate_artifact"] = "surplus" if row.get("validation_passed") else "degraded"
    action_grades["close_obligation"] = "surplus" if row.get("closed") else "critical"
    return event_record(
        event_id=f"evt_{row['condition']}_{row['task_id']}",
        workflow_id=str(row["condition"]),
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
            model_event=row,
        ),
    )


def validate_output(task: dict[str, Any], output: str) -> tuple[bool, bool, str | None]:
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


def _max_attempts(policy_id: str | None, config: dict[str, Any]) -> int:
    if policy_id == "single_repair_retry":
        return int(config.get("forced_policy_max_attempts", 2))
    if policy_id is not None and str(policy_id).startswith("active:single_repair_retry"):
        return int(config.get("adaptive_promoted_max_attempts", 2))
    return int(config.get("baseline_max_attempts", 1))


def _prompt_template_id(task: dict[str, Any], policy_id: str | None, attempt: int) -> str:
    if policy_id == "single_repair_retry" and attempt == 1:
        return "decisive_fixed_weak"
    if policy_id is None:
        return "decisive_fixed_weak"
    return f"decisive_{policy_id}_{task['family']}_attempt_{attempt}"


def _prompt_for(task: dict[str, Any], *, prompt_id: str, last_error: str | None) -> str:
    if prompt_id == "decisive_fixed_weak":
        return f"Answer concisely.\nRequest: {task['instruction']}\n"
    repair = f"\nPrevious validator error: {last_error}\n" if last_error else ""
    if "schema_keys_only" in prompt_id:
        return (
            "Return one minified JSON object. Include exactly these keys and primitive types: "
            f"{json.dumps(task.get('schema', {}), sort_keys=True)}.\n"
            f"Task: {task['instruction']}\n"
        )
    if "family_safe_expr_prompt" in prompt_id:
        return (
            "Return exactly one JSON object with key expression. The expression must use only "
            "numbers and arithmetic operators. No prose.\n"
            f"Task: {task['instruction']}\n"
        )
    if "receipt_template_only" in prompt_id:
        return (
            "Return exactly one JSON receipt object matching the requested operational fields. "
            "Use JSON primitives only. No prose.\n"
            f"Task: {task['instruction']}\n"
        )
    return (
        "Return exactly one minified JSON object. No Markdown or prose.\n"
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
            timeout=int(config.get("ollama_timeout_seconds", config.get("timeout_seconds", 60))),
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError) as exc:
        return "", f"ollama_call_failed:{exc}"
    return str(payload.get("response", "")), None


def _mock_output(task: dict[str, Any], policy_id: str | None, attempt: int) -> tuple[str, str | None]:
    if policy_id in {
        "strict_json_minimal",
        "schema_keys_only",
        "family_safe_expr_prompt",
        "receipt_template_only",
    } or (policy_id == "single_repair_retry" and attempt == 2):
        return _expected_output(task), None
    if task["family"] in {"validator_receipt", "safe_python_expression"}:
        return json.dumps({"wrong": True}), None
    if task["burst"] in {"validator_failure_burst", "stale_format_drift", "warmup_format_drift"}:
        return "not-json", None
    return _expected_output(task), None


def _expected_output(task: dict[str, Any]) -> str:
    if task["validator"] == "python_expr":
        return json.dumps({"expression": str(task["expected_value"])}, sort_keys=True)
    if "expected" in task:
        return json.dumps(task["expected"], sort_keys=True)
    return json.dumps({"status": "ok"}, sort_keys=True)


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
        value = eval(compile(tree, "<oasg-decisive-expr>", "eval"), {"__builtins__": {}}, {})
    except Exception as exc:  # noqa: BLE001
        return True, False, f"expr_eval_failed:{exc}"
    return True, value == expected_value, None if value == expected_value else "expr_wrong_value"


def _error_class(reason: str | None) -> str:
    if reason is None:
        return "none"
    return reason.split(":", 1)[0]
